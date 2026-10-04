"""The README's dev-build banner (scripts/dev_banner.py)."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import dev_banner  # noqa: E402

IMAGE_REPO = "ghcr.io/darthrater78/pcap-server"

# The shape release.yml publishes: this version's CHANGELOG.md section.
DEV1_BODY = (
    "\n### Changed\n\n"
    "- **The whole interface is redrawn as a field manual**: survey-paper ground,\n"
    "  ink rules and [square controls](DESIGN.md), login included.\n"
    "- **Fonts are self-hosted.**\n\n"
    "### Fixed\n\n- something else\n"
)


def rel(tag, prerelease=False, body="", draft=False):
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft, "body": body}


def _texts(svg, size=None):
    nodes = ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}text")
    return [t for t in nodes if size is None or t.get("font-size") == size]


def test_versions_sort_dev_before_rc_before_final():
    tags = ["v2.0.0", "v2.0.0-rc.1", "v2.0.0-dev.10", "v2.0.0-dev.9", "v1.1.1", "v2.0.0-beta.1"]
    assert sorted(tags, key=dev_banner.version_key) == [
        "v1.1.1", "v2.0.0-dev.9", "v2.0.0-dev.10", "v2.0.0-beta.1", "v2.0.0-rc.1", "v2.0.0"]
    assert dev_banner.version_key("nightly") is None


def test_newest_pre_release_ahead_of_stable_is_picked():
    releases = [rel("v1.1.1"), rel("v2.0.0-dev.5", True), rel("v2.0.0-dev.6", True), rel("v1.1.0")]
    assert dev_banner.pick_dev(releases)["tag_name"] == "v2.0.0-dev.6"


def test_no_banner_once_the_stable_release_ships_or_without_a_pre_release():
    assert dev_banner.pick_dev([rel("v2.0.0-dev.6", True), rel("v2.0.0")]) is None
    assert dev_banner.pick_dev([rel("v1.1.1")]) is None
    assert dev_banner.pick_dev([rel("v2.0.0-dev.7", True, draft=True), rel("v1.1.1")]) is None
    # Every pre-release this repo has already published is behind 1.1.1.
    assert dev_banner.pick_dev([rel("v1.1.0-beta.9", True), rel("v0.1.0-dev.40", True), rel("v1.1.1")]) is None
    assert dev_banner.render(None) == dev_banner.EMPTY


def test_banner_shows_tag_first_changelog_entry_and_image():
    svg = dev_banner.render(rel("v2.0.0-dev.1", True, DEV1_BODY), IMAGE_REPO)
    assert "v2.0.0-dev.1" in svg
    # The notes name no image, so it is this version's tag in the registry.
    assert "docker pull ghcr.io/darthrater78/pcap-server:2.0.0-dev.1" in svg
    text = " ".join(t.text or "" for t in _texts(svg, "16"))
    assert text == (
        "The whole interface is redrawn as a field manual: survey-paper ground, "
        "ink rules and square controls, login included."
    )
    assert "**" not in svg and "Changed" not in svg and "Fonts are self-hosted" not in svg


def test_an_image_named_in_the_notes_wins_and_none_is_shown_without_either():
    body = "First paragraph.\r\n\r\n```bash\r\ndocker pull ghcr.io/other/image:1\r\n```\r\n"
    assert "docker pull ghcr.io/other/image:1" in dev_banner.render(rel("v2.0.0-rc.1", True, body), IMAGE_REPO)
    assert "docker pull" not in dev_banner.render(rel("v2.0.0-rc.1", True, "First paragraph."))


def test_banner_escapes_markup_and_caps_long_summaries():
    body = "Fixes <script> & " + "very long words " * 40
    svg = dev_banner.render(rel("v3.0.0-rc.1", True, body))
    assert "<script>" not in svg
    lines = _texts(svg, "16")
    assert len(lines) == 3 and lines[-1].text.endswith("…")


def test_empty_notes_still_draw_a_well_formed_banner():
    svg = dev_banner.render(rel("v2.0.0-dev.2", True, None), IMAGE_REPO)
    assert _texts(svg, "16") == []
    assert "v2.0.0-dev.2" in svg


def test_paginated_gh_output_is_read_page_by_page():
    pages = json.dumps([rel("v1.1.1")]) + "\n" + json.dumps([rel("v2.0.0-dev.1", True)])
    assert [r["tag_name"] for r in dev_banner.parse_pages(pages)] == ["v1.1.1", "v2.0.0-dev.1"]
