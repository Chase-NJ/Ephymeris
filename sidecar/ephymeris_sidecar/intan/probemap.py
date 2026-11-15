"""Intan's probe-map XML -> the JSON the probe window draws.

RHX can load one of these itself, but not over TCP -- there is no command for
it -- so Ephymeris reads the same file the operator would have loaded there and
draws it. The format is `ProbeMap_XMLDocumentation.pdf`: a `ProbeMapSettings`
element holding `Page`s; a page holds `Line`s, `Text`s and `Port`s; a port
holds `ElectrodeSite`s. Five attributes INHERIT -- settings -> page -> port ->
site -- and resolving that here means the window draws what it is given and
never re-implements the cascade.

Coordinates pass through untouched, in the file's own units (micrometres, in
the lab's maps). Intan's y axis points UP; flipping it is the renderer's job,
because a parser that flipped would make the numbers in this JSON disagree
with the numbers in the file someone is debugging.

`xml.etree` on a file the operator picked from their own disk. It does not
fetch external entities, and the billion-laughs shape is refused by size long
before it matters.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

#: A real probe map is a few kilobytes. This bounds a wrong file picked by
#: mistake, not a realistic one.
MAX_BYTES = 2_000_000

_DEFAULTS = {
    "backgroundColor": "Black",
    "siteOutlineColor": "Gray",
    "lineColor": "White",
    "fontHeight": "10",
    "fontColor": "White",
    "textAlignment": "BottomLeft",
    "siteShape": "Rectangle",
    "siteWidth": "5",
    "siteHeight": "5",
}
_PORTS = "ABCDEFGH"


class ProbeMapError(ValueError):
    """The file is not a probe map this can draw. The message is for the
    operator, who picked the file."""


def parse_file(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    try:
        if target.stat().st_size > MAX_BYTES:
            raise ProbeMapError(f"{target.name} is too large to be a probe map.")
        text = target.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise ProbeMapError(f"{target.name} could not be read: {exc.strerror or exc}") from exc
    return parse(text, name=target.name)


def parse(text: str, *, name: str = "probe map") -> dict[str, Any]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ProbeMapError(f"{name} is not well-formed XML: {exc}") from exc

    settings = root if root.tag == "ProbeMapSettings" else root.find(".//ProbeMapSettings")
    if settings is None:
        raise ProbeMapError(f"{name} has no <ProbeMapSettings> element, so it is not a probe map.")

    top = _inherit(_DEFAULTS, settings)
    pages = [_page(element, top, index, name) for index, element in enumerate(settings.findall("Page"))]
    if not pages:
        raise ProbeMapError(f"{name} declares no <Page>.")
    sites = sum(len(port["sites"]) for page in pages for port in page["ports"])
    if sites == 0:
        raise ProbeMapError(f"{name} declares no electrode sites.")
    return {"name": name, "pages": pages, "siteCount": sites}


def _inherit(parent: dict[str, str], element: ET.Element) -> dict[str, str]:
    return {key: element.get(key, value) for key, value in parent.items()}


def _number(element: ET.Element, key: str, name: str, context: str) -> float:
    raw = element.get(key)
    if raw is None:
        raise ProbeMapError(f"{name}: a <{element.tag}> in {context} has no `{key}`.")
    try:
        return float(raw)
    except ValueError as exc:
        raise ProbeMapError(f"{name}: `{key}={raw}` in {context} is not a number.") from exc


def _page(element: ET.Element, top: dict[str, str], index: int, name: str) -> dict[str, Any]:
    style = _inherit(top, element)
    label = element.get("name") or str(index + 1)
    context = f"page {label!r}"

    lines = [
        {
            "x1": _number(line, "x1", name, context),
            "y1": _number(line, "y1", name, context),
            "x2": _number(line, "x2", name, context),
            "y2": _number(line, "y2", name, context),
            "color": line.get("lineColor", style["lineColor"]),
        }
        for line in element.findall("Line")
    ]
    texts = [
        {
            "x": _number(text, "x", name, context),
            "y": _number(text, "y", name, context),
            "text": text.get("text", ""),
            "height": float(text.get("fontHeight", style["fontHeight"])),
            "color": text.get("fontColor", style["fontColor"]),
            "alignment": text.get("textAlignment", style["textAlignment"]),
            "rotation": float(text.get("rotation", "0") or 0),
        }
        for text in element.findall("Text")
    ]

    ports: list[dict[str, Any]] = []
    for port in element.findall("Port"):
        letter = (port.get("name") or "").strip().upper()
        if letter not in _PORTS or len(letter) != 1:
            raise ProbeMapError(f"{name}: {context} has a <Port> named {port.get('name')!r}; ports are A–H.")
        port_style = _inherit(style, port)
        sites = []
        for site in port.findall("ElectrodeSite"):
            site_style = _inherit(port_style, site)
            number = _number(site, "channelNumber", name, f"port {letter}")
            if number != int(number) or not 0 <= number <= 127:
                raise ProbeMapError(f"{name}: port {letter} has channelNumber {number:g}; channels are 0–127.")
            sites.append(
                {
                    # The native channel name is what every other part of the
                    # recording is keyed by, so it is built once, here.
                    "channel": f"{letter}-{int(number):03d}",
                    "x": _number(site, "x", name, f"port {letter}"),
                    "y": _number(site, "y", name, f"port {letter}"),
                    "shape": "ellipse" if site_style["siteShape"].lower() == "ellipse" else "rectangle",
                    "width": float(site_style["siteWidth"]),
                    "height": float(site_style["siteHeight"]),
                    "outline": site_style["siteOutlineColor"],
                }
            )
        ports.append({"port": letter, "sites": sites})

    return {
        "name": label,
        "background": style["backgroundColor"],
        "lines": lines,
        "texts": texts,
        "ports": ports,
    }
