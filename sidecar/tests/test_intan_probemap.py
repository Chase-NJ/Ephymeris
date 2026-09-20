"""Intan's probe-map XML."""

from __future__ import annotations

from pathlib import Path

import pytest

from ephymeris_sidecar.intan import probemap

MAP = """<?xml version="1.0"?>
<IntanRHX version="3.0.0" type="ControllerRecordUSB3" sampleRate="30 kHz">
 <ProbeMapSettings backgroundColor="Black" siteOutlineColor="White" siteWidth="9">
  <Page name="Shank">
   <Line x1="40" x2="40" y1="20" y2="220"/>
   <Text x="50" y="225" text="A" fontHeight="12" textAlignment="CenterBottom"/>
   <Port name="A" siteShape="Ellipse" siteHeight="7">
    <ElectrodeSite channelNumber="16" x="0" y="775"/>
    <ElectrodeSite channelNumber="3" x="43.3" y="750" siteOutlineColor="Red" siteWidth="4"/>
   </Port>
   <Port name="b">
    <ElectrodeSite channelNumber="0" x="10" y="10"/>
   </Port>
  </Page>
 </ProbeMapSettings>
</IntanRHX>
"""


def test_the_cascade_is_resolved_so_the_window_never_re_implements_it():
    """settings -> page -> port -> site. Each site comes out fully specified."""
    parsed = probemap.parse(MAP)
    page = parsed["pages"][0]
    first, second = page["ports"][0]["sites"]

    assert first == {
        "channel": "A-016", "x": 0.0, "y": 775.0, "shape": "ellipse",
        "width": 9.0,        # from ProbeMapSettings
        "height": 7.0,       # from the Port
        "outline": "White",  # from ProbeMapSettings
    }
    assert (second["width"], second["outline"]) == (4.0, "Red")  # the site's own
    # Port B inherits nothing from port A.
    assert page["ports"][1]["sites"][0]["shape"] == "rectangle"
    assert page["ports"][1]["port"] == "B"
    assert parsed["siteCount"] == 3


def test_coordinates_pass_through_unflipped():
    """Intan's y points up. Flipping is the renderer's job: a parser that
    flipped would make this JSON disagree with the file someone is debugging."""
    page = probemap.parse(MAP)["pages"][0]
    assert page["lines"][0] == {"x1": 40.0, "y1": 20.0, "x2": 40.0, "y2": 220.0, "color": "White"}
    assert page["texts"][0]["alignment"] == "CenterBottom"
    assert page["texts"][0]["height"] == 12.0


def test_channels_are_native_names_by_port():
    parsed = probemap.parse(MAP)
    assert probemap.channels_of(parsed) == ["A-003", "A-016", "B-000"]
    assert probemap.channels_of(parsed, "a") == ["A-003", "A-016"]


@pytest.mark.parametrize(
    ("text", "says"),
    [
        ("<not xml", "well-formed"),
        ("<Settings/>", "ProbeMapSettings"),
        ("<ProbeMapSettings/>", "no <Page>"),
        ("<ProbeMapSettings><Page/></ProbeMapSettings>", "no electrode sites"),
        (MAP.replace('channelNumber="16"', 'channelNumber="200"'), "0–127"),
        (MAP.replace('name="A"', 'name="Q"'), "A–H"),
        (MAP.replace('x="0" y="775"', 'y="775"'), "has no `x`"),
    ],
)
def test_a_file_that_is_not_a_probe_map_says_why(text, says):
    with pytest.raises(probemap.ProbeMapError, match=says):
        probemap.parse(text, name="picked.xml")


LAB_MAPS = Path(r"K:\Documents\Hart Lab\00_Resources\01_Intan\Probe Mapping")


@pytest.mark.skipif(not LAB_MAPS.exists(), reason="the lab's probe maps are not on this machine")
def test_the_lab_s_own_maps_and_intan_s_examples_all_parse():
    files = [p for p in LAB_MAPS.rglob("*.xml") if not p.name.startswith("._")]
    assert files
    for path in files:
        parsed = probemap.parse_file(path)
        assert parsed["siteCount"] > 0, path.name
    poly2 = probemap.parse_file(LAB_MAPS / "NeuroNexus" / "A1x32_POLY2.xml")
    assert poly2["siteCount"] == 32
    assert len(probemap.channels_of(poly2, "A")) == 32
