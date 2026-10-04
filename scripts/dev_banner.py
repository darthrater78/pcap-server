"""Render the README's dev-build banner from the repository's GitHub releases.

The README on main embeds banner.svg from the unprotected `readme-banner`
branch, which .github/workflows/dev-banner.yml rewrites after every Release
run. When a pre-release is newer than the newest stable release, the banner
names it, gives the first entry of its release notes and the image to pull;
otherwise it is an empty 1x1 image, so the README shows nothing.

Usage:
  gh api repos/OWNER/REPO/releases --paginate \
    | python scripts/dev_banner.py ghcr.io/OWNER/REPO > banner.svg
"""
from __future__ import annotations

import json
import re
import sys
import textwrap
from html import escape

VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(dev|alpha|beta|rc)\.(\d+))?$")
PRE_RANK = {"dev": 0, "alpha": 1, "beta": 2, "rc": 3}
EMPTY = '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>\n'

# DESIGN.md's dark palette: surface-dark, surface-sunken-dark, on-surface-dark,
# muted-dark, rule-dark, warn-dark. Square corners, and status is a shape plus
# a word, as everywhere else in the app. An <img> cannot load a web font, so
# Plex is named first and the system stack is what most readers will see.
SURFACE, SUNKEN, TEXT, DIM, RULE, WARN = "#121512", "#1a1e1a", "#e3e8e1", "#9ba69d", "#2d332d", "#e0b04a"
MONO = "'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
SANS = "'IBM Plex Sans',system-ui,-apple-system,'Segoe UI',sans-serif"
WIDTH, WRAP = 820, 96


def version_key(tag: str) -> tuple[int, ...] | None:
    """Sort key where 2.0.0-dev.6 < 2.0.0-rc.1 < 2.0.0; None for tags we don't recognise."""
    m = VERSION_RE.match(tag)
    if not m:
        return None
    major, minor, patch, pre, num = m.groups()
    if pre is None:
        return (int(major), int(minor), int(patch), 1, 0, 0)
    return (int(major), int(minor), int(patch), 0, PRE_RANK[pre], int(num))


def pick_dev(releases: list[dict]) -> dict | None:
    """The newest published pre-release, if it is newer than every stable release."""
    best_pre = best_stable = None
    for rel in releases:
        if rel.get("draft"):
            continue
        key = version_key(rel.get("tag_name", ""))
        if key is None:
            continue
        if rel.get("prerelease"):
            if best_pre is None or key > best_pre[0]:
                best_pre = (key, rel)
        elif best_stable is None or key > best_stable[0]:
            best_stable = (key, rel)
    if best_pre is None or (best_stable is not None and best_stable[0] > best_pre[0]):
        return None
    return best_pre[1]


def summary(body: str) -> str:
    """The release notes' first entry as plain text.

    A release body here is that version's CHANGELOG.md section: `### Changed`
    style headings over bullets. So this skips headings and takes the first
    bullet (or paragraph) alone, with its continuation lines.
    """
    entry: list[str] = []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not entry:
            if stripped and not stripped.startswith("#"):
                entry.append(re.sub(r"^[-*]\s+", "", stripped))
        elif not stripped or stripped.startswith("#") or re.match(r"[-*]\s", stripped):
            break
        else:
            entry.append(stripped)
    text = re.sub(r"\*\*|__|`", "", " ".join(entry))
    return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).strip()


def image(release: dict, image_repo: str | None) -> str | None:
    """The image to pull: one the notes name, else this version's tag in the registry."""
    m = re.search(r"docker pull (\S+)", release.get("body") or "")
    if m:
        return m.group(1)
    if image_repo:
        return f"{image_repo}:{release['tag_name'].removeprefix('v')}"
    return None


def render(release: dict | None, image_repo: str | None = None) -> str:
    if release is None:
        return EMPTY
    tag = release["tag_name"]
    lines = textwrap.wrap(summary(release.get("body") or ""), WRAP)
    if len(lines) > 3:
        lines = lines[:3]
        lines[2] = lines[2][: WRAP - 1].rstrip() + "…"
    pull = image(release, image_repo)

    y = 34
    parts = [
        f'<text x="30" y="{y}" font-family="{MONO}" font-size="13" font-weight="600" '
        f'fill="{WARN}">▲ Dev build available · {escape(tag)} · not for production</text>'
    ]
    for line in lines:
        y += 24
        parts.append(f'<text x="30" y="{y}" font-family="{SANS}" font-size="16" fill="{TEXT}">{escape(line)}</text>')
    if pull:
        y += 16
        parts.append(f'<rect x="30" y="{y}" width="{WIDTH - 60}" height="30" fill="{SUNKEN}"/>')
        parts.append(
            f'<text x="44" y="{y + 20}" font-family="{MONO}" font-size="13" fill="{DIM}">$ '
            f'<tspan fill="{TEXT}">docker pull {escape(pull)}</tspan></text>'
        )
        y += 30
    height = y + 22
    label = escape(f"Dev build {tag} available" + (f": docker pull {pull}" if pull else ""))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img" aria-label="{label}">\n'
        f"<title>{label}</title>\n"
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{height - 1}" fill="{SURFACE}" stroke="{RULE}"/>'
        f'<rect width="6" height="{height}" fill="{WARN}"/>\n'
        + "\n".join(parts)
        + "\n</svg>\n"
    )


def parse_pages(data: str) -> list[dict]:
    """`gh api --paginate` prints one JSON array per page, back to back."""
    releases: list[dict] = []
    decoder, pos = json.JSONDecoder(), 0
    while pos < len(data):
        if data[pos].isspace():
            pos += 1
            continue
        page, pos = decoder.raw_decode(data, pos)
        releases.extend(page)
    return releases


def main(argv: list[str]) -> int:
    image_repo = argv[1] if len(argv) > 1 else None
    sys.stdout.write(render(pick_dev(parse_pages(sys.stdin.read())), image_repo))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
