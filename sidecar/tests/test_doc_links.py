"""Every documentation reference in the repo resolves.

Code comments cite the docs as `FILE.md#anchor` — never by section number,
because numbers move whenever a document is reorganised and a stale citation
reads exactly like a correct one. This test is what makes that convention
hold: it finds every `README.md#…`, `ARCHITECTURE.md#…` (etc.) reference and
every relative Markdown link in the docs, and fails on any whose file or
heading does not exist.

Anchors follow GitHub's slugging (lowercase, punctuation dropped, spaces to
hyphens, `-1`/`-2` for repeats) plus explicit `<a id="…">` targets, which is
how the generated `PROTOCOL.md` labels its commands, events and shapes.
"""

from __future__ import annotations

import re
import subprocess
from functools import cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"

#: Where each citable document lives.
DOC_FILES = {
    **{p.name: p for p in DOCS.glob("*.md")},
    **{p.name: p for p in (DOCS / "adr").glob("*.md")},
    "README.md": REPO_ROOT / "README.md",
    "GLOSSARY.md": REPO_ROOT / "GLOSSARY.md",
}

#: Documents that no longer exist; a reference to one is a stale citation.
RETIRED = (
    "getting-started.md",
    "dashboard.md",
    "cohorts.md",
    "settings.md",
    "websocket-protocol.md",
    "tasks.md",
    "data.md",
    "recording.md",
)

#: A dot inside an anchor is part of it (`cmd-sessions.end`); a trailing one ends the sentence.
CITATION = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in DOC_FILES) + r")#([A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*)"
)
MD_LINK = re.compile(r"\]\(([^)\s]+?\.md)(?:#([^)\s]+))?\)")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)|<img[^>]+src=\"([^\"]+)\"")
RETIRED_REF = re.compile(r"(?<![A-Za-z/_-])(" + "|".join(re.escape(n) for n in RETIRED) + r")\b")
SECTION_SIGN = "§"

#: Generated or vendored files whose text this repo does not author.
SKIP = ("sidecar/ephymeris_sidecar/boards/rpc/", "package-lock.json")


@cache
def tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    files = []
    for rel in out:
        if rel.startswith(SKIP):
            continue
        path = REPO_ROOT / rel
        if path.suffix in {".png", ".ico", ".icns", ".woff", ".woff2", ".bin", ".pyc"}:
            continue
        if path.is_file():
            files.append(path)
    return files


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def slugify(heading: str) -> str:
    text = re.sub(r"<[^>]+>", "", heading)
    text = text.replace("`", "").strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


@cache
def anchors(doc: Path) -> frozenset[str]:
    text = doc.read_text(encoding="utf-8")
    found: set[str] = set(re.findall(r'<a id="([^"]+)"', text))
    seen: dict[str, int] = {}
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        match = None if in_fence else re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if not match:
            continue
        slug = slugify(match.group(1))
        count = seen.get(slug, 0)
        found.add(slug if count == 0 else f"{slug}-{count}")
        seen[slug] = count + 1
    return frozenset(found)


def _references() -> list[tuple[str, str, str]]:
    refs = []
    for path in tracked_text_files():
        text = _read(path)
        if text is None:
            continue
        rel = str(path.relative_to(REPO_ROOT))
        for match in CITATION.finditer(text):
            refs.append((rel, match.group(1), match.group(2)))
        if path.suffix == ".md":
            for match in MD_LINK.finditer(text):
                target = match.group(1)
                if "://" in target:
                    continue
                resolved = (path.parent / target).resolve()
                refs.append((rel, str(resolved.relative_to(REPO_ROOT)), match.group(2) or ""))
    return refs


def test_every_cited_anchor_exists() -> None:
    broken = []
    for source, target, anchor in _references():
        doc = DOC_FILES.get(target) or REPO_ROOT / target
        if not doc.exists():
            broken.append(f"{source}: {target} does not exist")
        elif anchor and anchor.lower() not in anchors(doc):
            broken.append(f"{source}: {target}#{anchor} — no such heading")
    assert not broken, "broken documentation references:\n  " + "\n  ".join(sorted(set(broken)))


def test_every_doc_image_exists() -> None:
    """A screenshot or figure referenced from a doc must be committed beside it."""
    missing = []
    for path in tracked_text_files():
        if path.suffix != ".md":
            continue
        for match in IMAGE.finditer(path.read_text(encoding="utf-8")):
            target = match.group(1) or match.group(2)
            if "://" in target:
                continue
            if not (path.parent / target).resolve().exists():
                missing.append(f"{path.relative_to(REPO_ROOT)}: {target}")
    assert not missing, "missing doc images:\n  " + "\n  ".join(missing)


def test_no_reference_to_a_retired_doc() -> None:
    stale = []
    for path in tracked_text_files():
        text = _read(path)
        if text is None or path.name == Path(__file__).name:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if RETIRED_REF.search(line):
                stale.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()[:100]}")
    assert not stale, "references to retired docs:\n  " + "\n  ".join(stale)


@pytest.mark.parametrize("root", ["src", "sidecar", "protocol", "scripts", "src-tauri", "docs"])
def test_no_section_number_citations(root: str) -> None:
    """Cite `FILE.md#anchor`, not `§N` — numbers go stale silently."""
    hits = []
    for path in tracked_text_files():
        rel = str(path.relative_to(REPO_ROOT))
        if not rel.startswith(root + "/") or path.name == Path(__file__).name:
            continue
        text = _read(path)
        if text and SECTION_SIGN in text:
            for number, line in enumerate(text.splitlines(), 1):
                if SECTION_SIGN in line:
                    hits.append(f"{rel}:{number}: {line.strip()[:100]}")
    assert not hits, f"{len(hits)} section-number citations:\n  " + "\n  ".join(hits[:40])
