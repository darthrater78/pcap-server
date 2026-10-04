---
version: alpha
name: pcap-server Field Manual
description: Printed-manual look for a self-hosted packet capture tool. Colour belongs to the data; the interface is ink on survey paper.
colors:
  primary: "#172019"
  on-primary: "#ffffff"
  surface: "#e8ece6"
  surface-sunken: "#dde3db"
  on-surface: "#172019"
  muted: "#4f5953"
  rule: "#c3cbc2"
  highlight: "#f2dc5d"
  on-highlight: "#172019"
  ok: "#1e6b3a"
  warn: "#7a4f00"
  danger: "#a4161a"
  on-danger: "#ffffff"
  primary-hover: "#2e3b31"
  danger-hover: "#86110f"
  primary-dark: "#e3e8e1"
  on-primary-dark: "#121512"
  surface-dark: "#121512"
  surface-sunken-dark: "#1a1e1a"
  on-surface-dark: "#e3e8e1"
  muted-dark: "#9ba69d"
  rule-dark: "#2d332d"
  highlight-row-dark: "#4a4416"
  ok-dark: "#6fcf8e"
  warn-dark: "#e0b04a"
  danger-dark: "#f08a7e"
  on-danger-dark: "#121512"
  primary-hover-dark: "#c9d0c6"
  danger-hover-dark: "#f5a79d"
typography:
  display:
    fontFamily: IBM Plex Sans Condensed
    fontSize: 120px
    fontWeight: 600
    lineHeight: 0.9
    letterSpacing: -0.035em
  headline-lg:
    fontFamily: IBM Plex Sans Condensed
    fontSize: 32px
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: -0.01em
  headline-md:
    fontFamily: IBM Plex Sans
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.25
  body-md:
    fontFamily: IBM Plex Sans
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.55
  body-sm:
    fontFamily: IBM Plex Sans
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.45
  label-md:
    fontFamily: IBM Plex Sans
    fontSize: 13px
    fontWeight: 500
    lineHeight: 1.3
  data-md:
    fontFamily: IBM Plex Mono
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: '"tnum" 1'
  column-head:
    fontFamily: IBM Plex Mono
    fontSize: 11px
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: 0.08em
rounded:
  none: 0px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 40px
  gutter: 16px
  row: 26px
  target: 44px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.label-md}"
    rounded: "{rounded.none}"
    padding: 12px
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.on-primary}"
  button-primary-disabled:
    backgroundColor: "{colors.rule}"
    textColor: "{colors.on-surface}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.none}"
  button-danger:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.on-danger}"
  button-danger-hover:
    backgroundColor: "{colors.danger-hover}"
    textColor: "{colors.on-danger}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    typography: "{typography.data-md}"
  input-placeholder:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.muted}"
  input-disabled:
    backgroundColor: "{colors.surface-sunken}"
    textColor: "{colors.muted}"
  tab-active:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
  list-item-selected:
    backgroundColor: "{colors.surface-sunken}"
    textColor: "{colors.on-surface}"
  row-selected:
    backgroundColor: "{colors.highlight}"
    textColor: "{colors.on-highlight}"
  status-ok:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ok}"
  status-warn:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.warn}"
  status-danger:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.danger}"
  detail-pane:
    backgroundColor: "{colors.surface-sunken}"
    textColor: "{colors.on-surface}"
  detail-pane-muted:
    backgroundColor: "{colors.surface-sunken}"
    textColor: "{colors.muted}"
  button-primary-dark:
    backgroundColor: "{colors.primary-dark}"
    textColor: "{colors.on-primary-dark}"
  button-primary-hover-dark:
    backgroundColor: "{colors.primary-hover-dark}"
    textColor: "{colors.on-primary-dark}"
  button-danger-dark:
    backgroundColor: "{colors.danger-dark}"
    textColor: "{colors.on-danger-dark}"
  button-danger-hover-dark:
    backgroundColor: "{colors.danger-hover-dark}"
    textColor: "{colors.on-danger-dark}"
  input-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.on-surface-dark}"
  input-placeholder-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.muted-dark}"
  input-disabled-dark:
    backgroundColor: "{colors.surface-sunken-dark}"
    textColor: "{colors.muted-dark}"
  button-primary-disabled-dark:
    backgroundColor: "{colors.rule-dark}"
    textColor: "{colors.on-surface-dark}"
  tab-active-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.on-surface-dark}"
  list-item-selected-dark:
    backgroundColor: "{colors.surface-sunken-dark}"
    textColor: "{colors.on-surface-dark}"
  row-selected-dark:
    backgroundColor: "{colors.highlight-row-dark}"
    textColor: "{colors.on-surface-dark}"
  status-ok-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.ok-dark}"
  status-warn-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.warn-dark}"
  status-danger-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.danger-dark}"
  detail-pane-muted-dark:
    backgroundColor: "{colors.surface-sunken-dark}"
    textColor: "{colors.muted-dark}"
---

# pcap-server Field Manual

## Overview

pcap-server is used by one admin or a small ops team, on a desktop browser at work or at home, to start tcpdump on hosts over SSH and read the captures. The interface reads like a printed field manual that someone has marked up: ink on grey-green survey paper, hairline rules between sections, and a yellow highlighter on the packet you are reading. Colour belongs to the data. Protocol hues (`--pkt-*`, `--diagram-cat-*`) and status are the only colour on a screen; the chrome is ink.

## Colors

- **Survey paper (`surface` #e8ece6):** page ground. Dark: `surface-dark` #121512, a green-black, not true black.
- **Ink (`primary` / `on-surface` #172019):** text, rules under inputs, primary buttons, the wordmark. There is no brand hue: the accent is ink.
- **Highlighter (`highlight` #f2dc5d):** a fill, never a text colour, and only for the selected packet row (in the packet list and its sequence-diagram row) and search matches inside packet data. Never on tabs, menus, nav or list selection. Text on it is always ink. Dark: `highlight-row-dark`.
- **Sunken (`surface-sunken`):** the packet detail and hex panes, disabled inputs.
- **Status:** `ok`, `warn`, `danger` (and `-dark`). Never reused for anything decorative. `warn` is amber, not orange, so it never reads as the diagrams' DNS orange.
- **Data colours:** `--pkt-*` and `--diagram-cat-*` in `frontend/css/style.css` keep their validated hues in both themes. Do not retune them to match the chrome.

## Typography

- **IBM Plex Sans** for body, labels and buttons. **IBM Plex Sans Condensed** 600 only for the login wordmark (`display`) and page titles (`headline-lg`). **IBM Plex Mono** for anything a machine produced: addresses, ports, filters, packet rows, hex, sizes, counts, timestamps.
- Self-hosted woff2 under `frontend/fonts/`, Latin subset, weights 400/500/600 for Sans, 600 for Condensed, 400/500 for Mono. No Google Fonts: the CSP is `font-src 'self'`.
- Field labels are sentence case `label-md` above the input. Only table column headers use `column-head` (mono, caps, 0.08em tracking).
- Digits that line up use tabular figures (`data-md`). Smallest text anywhere is 11px, and only for column headers.

## Layout

- Spacing scale 4/8/16/24/40px. Sibling groups use flex or grid with `gap`.
- Top bar: wordmark, tabs (Servers, Capture, one tab per open capture with ×), then right-aligned links: Admin, GitHub, version (links to release notes), Theme, user, Log out. Same bar on every signed-in screen.
- Capture views (Packets, Traffic diagram, Sequence diagram, Protocol hierarchy, Conversations) sit in their own sub-row under the capture header. Actions on the capture (Columns, Save view, Sanitize, Download) sit right-aligned on that row, styled as buttons, not links.
- Packet table rows 26px, no zebra; protocol tint at `--pkt-tint`.
- Below 720px: tabs scroll horizontally in their own strip, two-column forms stack, the packet detail and hex panes stack under the table, the login drops its left column to the wordmark only. Side gutter 16px at every width.
- Numbering only where order is real: "Step 1 of 2" on first-run setup. No numbered tabs, section numbers or FIG. labels.

## Elevation & Depth

Flat. No shadows. Hierarchy comes from rules and tone: a 2px ink rule under the top bar, 1px `rule` hairlines between list items and sections, and `surface-sunken` for panes that hold detail. One filled block per screen at most, for something that needs action now (e.g. Admin's "No HTTPS certificate"), filled with a 12% tint of its status colour, with no side stripe.

## Shapes

Square everything: `rounded.none` on buttons, inputs, panes, dialogs and checkboxes. Inputs are an underline (1px ink), not a box. Status is a shape plus a word: ■ ok, ▲ warn, ✕ danger. Interface names and similar sets are bordered 1px squares, not pills.

## Components

- **Buttons:** primary is ink fill with white text; secondary is a 1px ink outline; danger is a `danger` fill, used only inside a confirm step. Minimum height 44px for anything you tap (`spacing.target`). Disabled buttons use `rule` fill and say why nearby. Disabled inputs use the sunken fill with muted text, still 4.5:1.
- **Links:** ink, underlined, used for navigation only. Actions are buttons.
- **Inputs:** underline at rest; on focus the underline becomes 2px ink plus the focus outline below; on error the underline and message turn `danger` and the message says what to change.
- **Focus:** every focusable element gets a 2px ink outline (light ink in dark) at 2px offset. The highlighter is never the only focus cue: yellow on grey-green is under 3:1.
- **Tabs and menus:** the active tab, view or nav item is semibold ink with a 3px ink underline (2px for links in the top bar), no fill.
- **Selected list item** (server list, Admin side nav): `surface-sunken` fill and semibold name.
- **Packet rows:** protocol tint by default; selected row gets the highlighter fill and a 2px ink rule above and below; retransmissions and errors keep `--pkt-bad`.
- **Status lines:** shape + word in the status colour, e.g. "■ ready", "▲ check sudo", "✕ no tcpdump".
- **Callout:** `surface-sunken` block with no border, body-sm text. Used for hints such as where the tcpdump flags went.
- **Empty states:** one sentence on what will appear, and the one button that makes it appear.
- **Delete:** the Delete button opens an inline confirm that names what will be removed, with a `button-danger` to confirm and a secondary Cancel.

## Do's and Don'ts

- Do keep every colour on a screen meaningful: a protocol, a status, or the highlighter.
- Do keep the login's GitHub and Release notes links and "Trust this device for 30 days".
- Do show the version, not installation state, before sign-in.
- Don't use cream or warm paper with a terracotta or orange accent.
- Don't put a brand hue on text, tabs or buttons; the accent is ink.
- Don't use gradients, shadows, glass, rounded corners, pills or emoji.
- Don't put a coloured stripe on the side of any block.
- Don't number tabs or sections, or add FIG. labels as decoration.
- Don't set field labels in all-caps mono; caps mono is for table column headers only.
- Don't use the highlighter as text colour, on navigation, or as the only focus cue.
- Don't use em-dash asides in UI copy; write two short sentences.
- Don't retune `--pkt-*` or `--diagram-cat-*` to match the chrome.
