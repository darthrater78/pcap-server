# Dev Skills gate state

## SHIPPED: v1.1.0-beta.4 (2026-09-18) + README bump now that it's live
Track: release-track docs fix, on docs/beta4-live (from origin/main efdfc08).
Model: Sonnet 5. Shell: Linux bash.

🚀 SHIP CLOSED for v1.1.0-beta.4. All four post-ship checks:
 * tag v1.1.0-beta.4 -> efdfc08 on the remote (main tip, PR #19 + PR #20 both
   merged), confirmed by the user running the presented tag block.
 * PR #19 and PR #20 both MERGED. Merge commit 87754cb (PR #19) had a Check
   failure on first run -- tests/browser/test_capture_ui.py::test_closing_a_
   background_tab_leaves_the_open_one_alone, a Playwright click timeout,
   unrelated to this diff (docs/version-only) and not reproduced in the local
   full-suite run moments earlier (1672/1672). Reran via `gh run rerun
   --failed`; run 35353175653 succeeded on retry. efdfc08 (PR #20, README-only)
   got no Check run by design (README.md is in check.yml's paths-ignore) --
   the ancestor-fallback case release.yml's gate exists for, exercised live
   for the first time.
 * Release run 35355487897 success (Release workflow, triggered by the tag).
 * GitHub release "v1.1.0-beta.4 (Pre-release)", prerelease: true,
   2026-09-18T14:20:57Z.
 * Image ghcr :1.1.0-beta.4 -> sha256:bc2a1756458ae208cb9ec50871559b147ce73842
   eefbe016dae057dff26c04c9 (a real digest), pulled and verified locally, then
   removed.

Now closing the loop the process note itself asks for: the image is
confirmed live, so README's beta line moves from 1.1.0-beta.3 to
1.1.0-beta.4, in its own commit, per the note added in PR #20.

🔢 VERSION    ➖ N/A -- README pointer only, not a version declaration.
🔨 BUILD      ➖ N/A -- README.md only.
🔒 SECURITY   ➖ N/A -- no code.
📄 DOCS       ✅ this commit IS the doc update -- bumps the beta line now that
              `docker pull ghcr.io/darthrater78/pcap-server:1.1.0-beta.4`
              is verified working (see SHIP above).
📦 RELEASE    ✅ PR #21 open: docs/beta4-live -> main.
🚀 SHIP       ➖ N/A -- no version bump, no tag, no artifact from this change.

## Fix: README beta line reverted to the deployed tag (2026-09-18, local)
Track: release-track fix, on fix/beta-readme-premature-tag (from origin/main
87754cb, the just-merged 1.1.0-beta.4 PR). Model: Sonnet 5. Shell: Linux bash.

User caught it: the beta.4 PR (#19) bumped README's beta announcement to
1.1.0-beta.4 in the same commit as the version bump -- before the tag was
pushed or the image published. Anyone on main right now gets a 404 pulling
that tag. This is the exact dev.40 mistake, repeated. Fix: the README line
reverts to 1.1.0-beta.3 (still the actually-deployed image) and gains a
process note in the surrounding HTML comment -- bump that one line only after
`docker pull` of the new tag works, in its own commit, never bundled with the
version-bump PR. Also switched the announcement to a GitHub `[!IMPORTANT]`
alert for real visual weight (was a plain blockquote).

🔢 VERSION    ➖ N/A -- reverts a value forward of what's deployed; carries no
              version of its own. backend/main.py APP_VERSION and
              docker-compose.yml correctly stay at 1.1.0-beta.4 (that's what
              main's code now is, pending its own tag/ship) -- only the
              README pointer, which this project treats as "what's live on
              ghcr" rather than "what's on main", moves back.
🔨 BUILD      ➖ N/A -- README.md only, no app/test code touched.
🔒 SECURITY   ➖ N/A -- no code; a Markdown/HTML-comment edit, no new sinks.
📄 DOCS       ✅ this commit IS the docs fix -- see summary above.
📦 RELEASE    ✅ PR #20 open: fix/beta-readme-premature-tag -> main.
🚀 SHIP       ➖ N/A -- no version bump, no tag, no artifact from this change.

## HANDOFF: Traffic Diagram overhaul + preview container -> 1.1.0-beta.4 release (2026-09-18, local)
Track: release sequence, on claude/dev-skills-beta-workflow-cwzvx5 (from
origin/main 65bf7d4, tip c8dc667). Model: Sonnet 5 (user switched down,
"no more coding if possible" -- docs/version-only work from here). Shell:
Linux bash. Previous version v1.1.0-beta.3 confirmed tagged on remote
(ls-remote, points at 65bf7d4).

🔢 VERSION    ✅ bumped 1.1.0-beta.3 -> 1.1.0-beta.4 in backend/main.py
              (APP_VERSION), docker-compose.yml (image tag), README.md (beta
              badge). docs/security.md's "Before 1.1.0-beta.3" is a historical
              note, correctly left alone. No other hardcoded refs found (grep).
              repo/release-notes links unchanged (REPO_URL-derived, already
              correct pattern). Previous tag v1.1.0-beta.3 verified on remote.
🔨 BUILD      ✅ handoff offered and verified by hand. full suite via
              scripts/check.sh on the tagged tree (75ee7f7): 1672 passed,
              0 failed, 0 skipped, 366.86s, real tshark/capinfos/chromium/
              docker. The prior sanitizer flake did not reproduce this run.
              docker build localhost/pcap-server:1.1.0-beta.4, run with a
              throwaway MASTER_KEY_FILE, / 200, /api/auth/status 200,
              in-image APP_VERSION == 1.1.0-beta.4, encryption enabled, no
              traceback in the log. Image and smoke key removed after.
🔒 SECURITY   ✅ carried over -- 0 Critical/High on the code diff (prior
              entry); this commit adds no code, only strings/docs.
📄 DOCS       ✅ docs/viewer.md Traffic/Sequence Diagram section rewritten:
              protocol picker, 15 marks (3 hue x 5 shape, was 8), Problems
              chip/badges/stats, host search, stats pane incl. per-host
              interfaces, Fit/Spacing/full screen/New window, click-to-filter
              stays open, rewind-at-end, most-used-protocol badge, window
              titles. CHANGELOG 1.1.0-beta.4 entry added (Added: picker, 15
              marks, Problems, search, stats pane, toolbar controls, playback
              polish; Changed: diagram button is now the lead tool). No
              removed features to scrub. scripts/preview.sh is a dev-only
              throwaway tool, not shipped in the image -- intentionally not
              user-doc'd or changelog'd.
📦 RELEASE    ✅ PR #19 open: claude/dev-skills-beta-workflow-cwzvx5 -> main.
              Branch was synced with origin before every push (no divergence).
              Release notes shown to the user in chat; approved ("yes").
🚀 SHIP       ⬜ next: merge PR #19, confirm merge + CI on that commit, then
              hand the tag block to the user.

What shipped in this commit (frontend + scripts only; no backend change):
- Traffic Diagram: end-of-play most-used-protocol badge per host; legend =
  multi-select protocol picker (applies to the next play; unrelated hosts and
  links hide); every protocol gets its own chip; 15 colored marks (3
  validated hues x 5 shapes -- adding a 4th hue fails the dataviz validator,
  measured); "Problems" chip + red link badges + stats rows + red ring during
  play (resets, retransmissions, window, IP fragments, ICMP errors,
  malformed); host search box (Enter steps through matches, Esc clears);
  collapsible stats pane (protocols shown before any play); click a host or
  link = filter the packet list, diagram stays open, link lists all its
  protocols; zoom/pan/Fit, Spacing, full screen, New window (diagram-only
  page; clicks relay to the main tab over BroadcastChannel); Resolve names
  toggle; per-host interfaces on "any" captures; speed usable before play;
  play rewinds at end with the picture kept; capture + view name in both
  diagram titles; readable labels; node glyphs keep screen size when zoomed
  out; automatic view never zooms below the separation floor.
- Viewer: Traffic Diagram button is the lead tool (accent + icon, after Apply).
- scripts/preview.sh + scripts/preview_pcap.py: throwaway preview on :8099.
  See memory preview-container.md for the user's requirements.

Next steps, in order:
1. Run scripts/check.sh on this commit; expect only the sanitizer flake.
   Decide whether to fix that flake (seed the random payload).
2. Open items the user raised but did not decide: stats Top talkers/Busiest
   links do not follow the protocol pick; problem badges can sit on a host
   label on short links; a 4-hue palette option was offered, not chosen.
3. Release prep for the next beta: VERSION bump, docs/viewer.md, CHANGELOG.

## IN PROGRESS: next beta -- upload tests, locked-vault fix, upload fly-out (2026-09-18, local)
Track: work commit on claude/dev-skills-beta-workflow-cwzvx5 (resumed from the
upload-diagrams handoff below). dev-skills v2.24.0. Environment: LOCAL (same
clone as the user's terminal) -- git is presented, not run; the cloud
session's "remote container" notes below no longer describe where this runs.
Model: Opus 5 (session switched mid-way); user continued without objection.

Done this session, uncommitted:
 * tests/test_capture_upload.py -- 25 tests (sealed on disk, 0600, uuid name,
   round-trip download, packets route, record fields, odd labels, other-user
   404, 4 refusals, oversize with and without Content-Length, locked 503,
   plain HTTP 403, rate limit, 401, origin migration backfill). Mutation-
   checked: chunked-cap and locked-vault tests fail with their guard removed.
 * HIGH, the pre-existing twin, REPRODUCED then FIXED. With the vault locked
   (every passphrase-mode restart until unlock): a pasted/uploaded SSH key was
   written as plaintext and NEVER re-sealed (migrate_plaintext_keys only runs
   at a startup that has a key -- passphrase mode never does); a collected
   capture landed as plaintext <id>.pcap until the next unlock. Now
   CaptureManager._refuse_while_locked (shared with import_upload) guards
   start() and _collect(); _store_ssh_key refuses 503; start route maps
   CryptoError -> 503. 4 new tests, all fail against the old code. The
   existing test_uploaded_key_is_plaintext_when_no_cryptor encoded the bug
   (it modelled "no key" as a LOCKED vault) -- split into encryption-disabled
   (plaintext, correct) and locked (503).
 * UI BUG found by the new browser test: onUploadCaptureClick's finally reset
   #upload-msg, so "Uploaded N packets" / "Upload failed: ..." were never
   shown. Fixed (syncUploadButton re-enables without touching the message).
 * Upload moved into a fly-out off the Captures heading (user: "the capture
   screen is getting kind of cramped"). Non-modal; Escape (focus back to the
   toggle), outside click and the toggle close it; stays open after an upload.
   Screenshotted light/dark/390px.
 * Browser tests: 3 upload + 4 fly-out in test_capture_ui.py, 8-slot legend in
   test_diagrams_ui.py.

FOUND, NOT FIXED (asked): .stats-dialog {display:flex} overrides the UA
dialog:not([open]){display:none}, so every closed stats/host-key dialog is
rendered below the 100vh app shell -- invisible, but its buttons are likely
still in the tab order. Pre-existing.

Later the same session, on the user's direction:
 * Fly-out moved from the Captures heading to the capture card footer beside
   Start capture, opening upward over the form (user: "looks kind of clumsy";
   chose the footer via AskUserQuestion). Anchored to the footer, width
   against the footer, full-width button under 480px.
 * Sequence Diagram lane labels fitted to their room (gap to neighbours and
   2x distance to either edge), middle-ellipsised, full name in <title>. The
   leftmost resolved hostname was clipped off the left edge.
 * Legend swatches 18x14 -> 26x20 (shape is the channel past three hues).
 * dialog:not([open]) { display:none } -- the closed-dialog bug above, FIXED
   (user: "Yes fix it"). Also removed a 108px horizontal overflow at 390px.
 * 3 more browser tests (label fit, short labels whole, closed dialogs + page
   width); the two regression ones fail against the pre-fix frontend.

🔢 VERSION    ⬜ not owed yet (next beta will bump to 1.1.0-beta.3)
🔨 BUILD      ✅ full suite on the FINAL tree: check.sh EXIT=0, 1647 passed,
              0 failed, 0 skipped, 336s, real tshark/capinfos/chromium. Looked
              at in a real browser: upload fly-out (desktop dark, 390px light),
              both diagrams on a real uploaded 83-packet pcap with name
              resolution. Handoff offered: screenshots sent to the user; no
              image built (work commit, not a release).
🔒 SECURITY   ✅ 0 Critical, 0 High on the final diff. One High (locked-vault
              plaintext writes: SSH keys + captures) fixed in this diff.
              pip-audit requirements.txt: no known vulnerabilities; no
              dependency or Dockerfile change. No new innerHTML/eval sinks --
              lane labels and titles via textContent. Quality: fitLaneLabel /
              laneLabelRoom small and pure; _refuse_while_locked shared by the
              three write paths instead of three copies.
📄 DOCS       ⬜
📦 RELEASE    ⬜
🚀 SHIP       ⬜

## (previous) pcap upload + traffic-diagram fixes (2026-09-18)
Track: work commit (branch only). No version bump, no tag, no artifact, nothing
published. Flagged to the user; they can call it a release instead.
Branch: claude/dev-skills-beta-workflow-cwzvx5, restarted from origin/main.
Environment: remote container. Claude executes git; tag pushes go to the user.
User asked for: upload a pcap to view it, sealed and encrypted exactly as a
capture is and marked as an upload; DNS resolution fixed in the traffic
diagram; more protocols shown there.

🔢 VERSION    ⬜ not owed on a work commit. APP_VERSION stays 1.1.0-beta.2,
              which is what ghcr actually holds.
🔨 BUILD      ✅ handoff n/a -- remote container. Precisely: /usr/bin/docker
              EXISTS here (check.sh's tool line lists it, and earlier gate
              records saying "no docker" read as if it did not), but there is
              no daemon -- `docker info` fails on a missing
              /var/run/docker.sock -- so no image can be built or started, and
              there is no artifact for the user to try by hand.
              Full suite via scripts/check.sh on the committed tree: 1604
              passed, 3 skipped, exit 0, 553.78s, with real
              tshark/tcpdump/capinfos and chromium. 1607 collected against
              1594 at beta.2. The 3 skips are test_entrypoint.py's
              pre-existing root-writes-0500 cases.
              Run three times this session; only this run counts. The first
              two were invalidated by edits landing mid-run (pip-audit
              installed into .venv, then the quality refactor of
              _write_sealed_upload) and neither was recorded as a result.
              Targeted re-run of the two highest-risk browser files
              (test_diagrams_ui.py, test_capture_ui.py) before the commit: 68
              passed.
              NOT required on this track; run and recorded because the change
              is code.
🔒 SECURITY   ✅ 0 Critical, 0 High. One High found and fixed in this session's
              own new code; one pre-existing twin raised and left open. Detail
              below.
📄 DOCS       ⬜ no CHANGELOG entry, correct for a work commit (dev.33/34
              precedent). A release owes one.
📦 RELEASE    ⬜ no PR opened.
🚀 SHIP       ⬜ nothing tagged, nothing published.

STOPPED MID-TASK on the user's instruction: "Stop the work for now, commit
what's done and write a handoff to the repo." The features work and are
verified by hand; the tests that would guard the UPLOAD are NOT written (the
DNS fix does have 5 of its own). Full state in
.claude/upload-diagrams-handoff.md, which is the file to start from.

COMMITTED AND PUSHED: ca937c5 (the DNS fix and its tests, kept as its own
commit so the bugfix is reviewable alone) and 19be0ef (uploads, the eight
protocol slots, this record and the handoff), on
claude/dev-skills-beta-workflow-cwzvx5, confirmed on the remote at 19be0ef.
No PR. This gate-record update is a third commit on top of those two.

SECURITY GATE, in full.

Code: 0 Critical, 0 High.
 * ONE HIGH, FOUND BY THIS GATE AND FIXED, in code written this session. A
   locked vault presents cryptor=None, indistinguishable from "encryption is
   disabled", so an upload arriving while the vault waited for its passphrase
   was written IN THE CLEAR -- stored as <uuid>.pcap with no .enc suffix, on an
   installation whose whole premise is encryption at rest. This is the
   fail-open vault.py refuses to start up into, reached by another door.
   Reproduced before fixing: the pcap magic was the first four bytes on disk.
   Now refused fail-closed before anything is written, as a 503, because the
   remedy is an admin unlocking and the same request then working.
 * Path handling: the client-supplied filename NEVER becomes a path. The stored
   file is named by a server-generated uuid4 via vault.stored_path(); the
   filename is only a display label, allowlisted, and dropped rather than
   rewritten if it does not match. Traversal is structurally impossible here
   rather than filtered.
 * Resource bound: the upload cap is counted off the request stream, so a
   chunked body with no Content-Length cannot bypass it -- verified live (400
   from the route, with nothing left on disk). This CLOSES the residual the
   _body_limit comment used to state, for the one route where it mattered.
   The middleware's Content-Length check remains as the cheap early refusal.
   Own rate limiter as well, lower than capture starts, because unlike a
   capture start nothing else bounds how fast one user can fill the volume.
 * File mode: os.open(..., O_CREAT|O_EXCL, 0o600), so there is no window
   between creation and a chmod, and no reuse of an existing path.
 * Partial writes: sealed into <name>.partial and moved into place only after
   the whole body has arrived and capinfos has read it back; removed on every
   failure path. Verified no .partial survives any of the six refusals.
 * XSS: the one new innerHTML attribute interpolation (the legend swatch's
   fill/stroke/stroke-dasharray) takes values only from the module-level
   PROTOCOL_SLOTS constant, never from server or user data. The protocol name
   beside it is escHtml'd as before. Every new upload message is written with
   textContent; the filename reaches the URL through encodeURIComponent.
 * Transport: HTTPS enforced twice -- the read-only-over-HTTP middleware and an
   explicit _require_secure_transport, kept deliberately rather than trimmed,
   because this body is packet data.
 * No new dependency, no new subprocess, no new shell, no eval, no pickle, no
   new permission. capinfos runs through the existing vault source, as the
   capture path already does.

Dependencies: pip-audit 2.10.1 (installed into the throwaway .venv for this,
which is gitignored). backend/requirements.txt and requirements-dev.txt both
"No known vulnerabilities found". 0 Critical, 0 High. .github/dependabot.yml
already exists, so nothing to recommend there.

OPEN, RAISED, NOT FIXED -- the pre-existing twin of the High above. Nothing
anywhere refuses a WRITE while vault.locked is true: the only `locked` checks
in main.py are the status field and the unlock route's own guard. _collect
passes `self._vault.cryptor if self._vault else None` to fetch_file, and
_store_ssh_key does the same for keys, so a capture completing -- or an SSH key
uploaded -- while the vault is locked looks like it lands unencrypted too. NOT
verified, only reasoned from the code; only the upload path was actually
reproduced. Left out because it is a vault-wide change across three write
paths, wants its own tests, and the session was stopped. Verify it the same way
before fixing. If it reproduces it is a High.

Quality review of the changed code:
 * FIXED: _write_sealed_upload nested 5 deep, over the 3-level limit. Split
   into _check_upload_size, _header_looks_like_a_capture, _write_upload_chunk
   and _check_upload_finished; now 33 non-comment lines at depth 3, and each
   piece has a name saying what it decides.
 * FIXED: import_upload ran long. The record construction moved to
   _upload_record. Now 54 non-comment lines at depth 2 -- still longer than the
   ~40 guideline, ACCEPTED rather than split further: what remains is three
   named phases plus two try/except blocks whose only job is removing a partial
   file, and separating those from what they clean up would make the failure
   handling harder to follow, not easier.
 * No N+1, no blocking I/O added on the event loop beyond what
   SSHManager._download already does inline for the same work and for the
   reason stated there, no unbounded cache, no listener without teardown, no
   new index needed (the new column is never queried on).
 * No new import, so no dependency-file drift and nothing owed in the
   Dockerfile.

Verified by hand, not by committed tests -- THIS IS THE GAP:
 * upload sealed on disk, download byte-identical round trip, packets route
   reads it, appears in the capture list
 * refusals: not a pcap, empty, under four bytes, pcap header on garbage,
   oversize declared (413), oversize chunked (400), plain HTTP (403),
   rate limited (429), locked vault (503)
 * DNS: both routes return host.example.com with resolution on, addresses with
   it off, and every playback lookup resolves
 * 5 new parser tests, confirmed to discriminate: 3 fail against the pre-fix
   parser, and the agreement test fails against a deliberately half-fixed tree
   (flags fixed, conversations not) -- which is the trap the fix walks into.

Findings so far, all checked against real tshark 4.2.2 output in this
container rather than inferred from the code:

Finding 1. backend/packet_parser.py's _RESOLVE_ON passes `-N mnt`. Those
letters are the complete set of resolutions tshark will perform, so leaving
`d` out actively disables the one source that works on a stored pcap: names
learned from the capture's own DNS answers. External reverse-DNS is asked for
and, in a container behind no resolver, answers nothing. Proven on a two-frame
pcap built from tests/packet_builders.py -- a DNS A answer for
host.example.com plus a TCP frame to that address. Under `-N mnt` the
destination column reads 10.0.0.9; under `-N mntd` it reads host.example.com.
This affects the packet list too, not only the diagrams.

Finding 2. get_conversations reads `-e ip.src` / `-e ip.dst`, which never
resolve, whatever the flags say. Its docstring claims otherwise. The resolved
values live in the separate `ip.src_host` / `ip.dst_host` fields, confirmed on
the same pcap: `ip.dst` gives 10.0.0.9 while `ip.dst_host` gives
host.example.com, matching _ws.col.Destination exactly.

Finding 3, corrected after measuring rather than reasoning. The first write-up
of this said playback already drew nothing. It does not. Because finding 1
means NOTHING resolved anywhere, both routes returned addresses and agreed with
each other, so playback worked and simply never showed a name -- which is the
symptom as reported, no more. The mismatch is a trap the fix walks into: fixing
the flags alone gives /packets names while /conversations keeps addresses, and
then drawTopologyFrame's `byId.get(p.source)` misses on every packet, hits
`if (!a || !b) continue`, and the animation goes blank. So the two fixes are
one change and neither ships without the other.
Verified on the two-frame pcap through the real routes: with both fixes and
resolution on, /conversations returns host.example.com and /packets returns
host.example.com, and every playback lookup resolves.

Finding 4. The diagram palette caps at three protocols, in style.css and in
diagrams.js rankProtocols. Everything past the third shares one grey "Other"
swatch. This is the "more protocols" ask.

## SHIPPED: v1.1.0-beta.2 (2026-09-18) -- the interrupted ship, finished

🚀 SHIP ✅ CLOSED AND SHIPPED. All four post-ship checks:
 * tag v1.1.0-beta.2 -> 8c2e1bf on the remote (the PR #16 merge commit), moved
   off 0038140 by the user running the presented block. Both halves of the
   re-push (delete, then create) went through; never executed here.
 * Release run 35299208966 success. All three gate steps green. The Check step
   waited 9 minutes for the merge commit's own run and logged "Check passed for
   8c2e1bf..." -- the PRIMARY lookup. The ancestor fallback added in this
   release was NOT exercised; it ships proven by tests, not by a live release.
   The first release to actually use it will be a docs-only one.
 * GitHub release "v1.1.0-beta.2 (Pre-release)", prerelease: true, 02:35:01Z.
 * Image ghcr :1.1.0-beta.2 -> sha256:2d5a4ad900550cc688c52794f66662666fc7450a
   f33ab4b1cd89ae54670b7ba9 (a real digest, not e3b0c442). Floating tags
   correctly did NOT move: :dev still 2c094523 (dev.40), :latest still c686ea5a
   (1.0.0), both matching what earlier sessions recorded.

## Work commit: CI trigger waste (2026-09-18)
Track: work commit -- CI plumbing, no version bump, no artifact, no publish.
Not added to CHANGELOG, matching the dev.33/34 CI commits' precedent.
It WILL merge to main via PR, which current SKILL.md S2 reads as a release
sequence; this repo's own recorded decision (dev-skills 2.23.0, in the dev.40
section below) says intent to publish is what makes a release, and there is
none here. Flagged to the user rather than settled unilaterally.

Branch restarted from origin/main (8c2e1bf) because PR #16 is merged -- follow-up
work is a fresh change, not commits stacked on merged history.

User: "Are we doing the right tests for the right use case? We seem to be doing
the same long test for every action to github" -> then "do all three".

Three findings, all verified against real run data, not inferred:
 1. check.yml's `pull_request:` had NO paths-ignore while `push:` had a
    carefully reasoned one. A .claude/-only commit was skipped on push and ran
    the full ~10min suite on the PR. Runs 139 (1b406da) and 140 (4791c7e) on
    2026-09-18 are exactly this, twice, in one session.
 2. No concurrency group on check.yml or lint-workflows.yml -- three quick
    commits ran three full suites to completion.
 3. push ['**'] + bare pull_request double-fired on one SHA. PR #14's branch:
    runs 134 (push) and 135 (pull_request), same commit 3157794.

Browser-suite timing, relevant to the original question: 186 browser tests
took 8m48s measured alone (contended with another run, so inflated), against
1597 tests in ~9m for the whole suite. The ~12% of tests driving a real
chromium are essentially the entire wall clock. If more time needs cutting, the
lever is pytest-xdist or sharding those, which skips no tests -- not
path-based selection.

Fixes: pull_request gains the same paths-ignore (written out again -- GitHub
Actions has no YAML anchors); concurrency on both workflows, cancel-in-progress
everywhere EXCEPT main (a cancelled run is not a passing one, and release.yml's
gate would then refuse to tag that merge commit); push narrowed to [main],
which is the only branch the gate needs a push run on.
release.yml's pattern reader gains `sort -u`, because check.yml now carries the
list twice and sed reads both ranges.

FOURTH ITEM, added on the user's "add the image smoke test too": release.yml
built the image and pushed it in ONE step, so `docker build` exiting 0 was the
only thing between a broken image and GHCR. Nothing ever started the container.
Every artifact check in the release records below -- "boots, / 200, 0
tracebacks, APP_VERSION correct in-image" -- was done BY HAND, locally, before
tagging. CI never did it. This session could not either (no docker in the
container), so :1.1.0-beta.2 was published without anyone here starting it (the
code was unchanged from beta.2's own smoke run, so that was sound -- but by
luck of the diff, not by design).

Now: build with load: true, prove it runs, then a cache-hit rebuild that
pushes. Six assertions -- / 200 within 60s, /api/auth/status 200, /api/servers
401, in-image APP_VERSION == the tag, no Traceback in the log, "encryption
enabled" present. The version check is the independent half of the gate job's:
that one reads the repo at the tagged SHA, this reads the code INSIDE the
artifact, and only the second catches a Dockerfile that copied the wrong tree.
The v1.0.0 incident (:1.0.0 published holding 0.1.0-dev.40) is that shape one
layer down.
Uses a real throwaway key, not ALLOW_UNENCRYPTED_CAPTURES (encryption is what
docker-compose.yml ships). No bind mounts for data/captures/ssh-keys -- the
Dockerfile already creates them owned by appuser, and mounting host dirs is
exactly how the dev.34 by-hand smoke run failed for reasons unrelated to the
image.

NOT RUN. Docker is not usable in this container, so the smoke test is verified
only by actionlint+shellcheck, `bash -n`, YAML parse, and the in-image sed
checked against the real backend/main.py (returns 1.1.0-beta.2). One real bug
was found and fixed during that check: `curl -fsS` exits non-zero on a 4xx, so
under `set -e` a wrong status code would have aborted the step with curl's
error instead of the message naming the code. THE FIRST RELEASE AFTER THIS
MERGES IS THE PROOF. If the smoke step is itself broken the release fails at
that step rather than publishing something bad -- the safe direction, but not a
substitute for having run it.

DELIBERATELY NOT DONE: splitting the suite by path (run browser tests only when
frontend/ changes). scripts/check.sh is one entrypoint shared by CI and local
dev, with a comment saying it exists so the two cannot drift; path-based
selection breaks that property, and the run you skip is the one that catches it.
The waste was never that the suite is thorough -- it is that it ran on commits
containing no code.

RISK RAISED AND RESOLVED: if Check were a required status check on main, a PR
whose every file is in paths-ignore would report no run and sit on "Expected --
waiting for status" forever. No tool in this session could read branch
protection, so it was flagged rather than assumed. The user checked and sent
the settings page: "Classic branch protections have not been configured", no
rulesets either. Check is NOT required, so the filter is safe and the skip-job
remedy is not needed. check.yml keeps the note inline against the day
protection is added.

Consequence worth recording: with no protection on main, release.yml's gate is
the ONLY thing standing between a commit and a published image -- nothing
requires a PR, a review, or a green check to reach main. The design still
holds (a direct push to main gets a Check run, since that trigger survived the
narrowing, and the gate requires it to pass), but it holds alone.

VERIFIED LIVE on the push of 38181b8: that commit changed workflows AND tests/,
which under the old triggers would have run the full suite on a branch push.
Only Lint workflows ran (run 25, 8s). No Check run. Fix 3 confirmed.
The waste is now measured, not estimated: runs 139 and 140 -- the two
.claude/-only PR runs -- took 12m02s and 11m36s. ~24 minutes of CI in one
session on commits containing no code.

🔢 VERSION    ➖ N/A -- structural: this change ships no artifact and publishes
              nothing, so there is no version for it to carry. APP_VERSION
              stays 1.1.0-beta.2, which is what ghcr actually holds; bumping it
              here would leave the declared version disagreeing with the
              published image and assert a release that is not happening. This
              is the repo's own recorded convention (dev-skills 2.23.0, in the
              dev.40 section below, adopted on the user's direction): intent to
              publish -- a bump, a tag or an artifact -- is what makes a
              release, and a merge to main without one is a work commit.
              Reached because the gate-preflight hook refused the PR with
              VERSION ⬜; the track question had been flagged to the user twice
              and left open, so it was settled here on that recorded convention
              and surfaced to them to overrule rather than decided silently.
              NOT a "we'll do it later" skip: there is no later bump owed for
              this change at all. The next real release bumps from
              1.1.0-beta.2 as if this had never happened.
🔨 BUILD      ✅ handoff n/a (remote container; docker is not usable here at
              all, which is also why the smoke test itself could not be run).
              Full suite via scripts/check.sh: 1594 passed, 3 skipped, exit 0,
              556.99s. actionlint 1.7.12 + shellcheck clean over all three
              workflows. The 4 new workflow-shape tests were checked against
              8c2e1bf's check.yml and 3 of them fail there, so they
              discriminate.
              FIFTH ITEM, on the user's "do the first-parent fix": the ancestor
              search walked /commits?sha=, which follows EVERY parent in date
              order. That was harmless while check.yml ran on all branches --
              a merged PR's own commits had push runs of their own. Narrowing
              the push trigger to main (item 3, same session) made it a defect:
              those commits stopped having push runs, so a long enough PR could
              fill the 50-commit window with commits that can never match, and
              the release would refuse for want of looking one step further
              back along main. Self-inflicted, caught before it shipped.
              Now walks parents[0] one commit at a time, bounded at 20 -- and
              20 first-parent steps is 20 of main's OWN commits, where the
              realistic depth is one. `// empty` so a root commit ends the walk
              rather than becoming the string "null".
              3 new tests (first-parent not a flat list, the bound, the root
              commit). 29 pass. shellcheck caught a stale `local ancestors` on
              the way through.
              Scope: grepped -- tests/test_release_workflow.py is the only test
              that reads release.yml, so those 29 are the complete affected set
              on this tree. The full suite (1594 passed) ran on the tree before
              this fix; the PR's own Check run covers it after, since tests/ is
              deliberately NOT in the new paths-ignore.

🔒 SECURITY   ✅ 0 Critical, 0 High. Triggers and concurrency add no execution
              surface -- they only narrow which pushes start a run; no new
              action, no new SHA, no permissions change anywhere.

              The one item with real content is the smoke step: the release
              job holds contents: write and packages: write, and it now RUNS
              this repo's code rather than only building it. Checked rather
              than waved through: `docker run` passes no host environment into
              the container, so GITHUB_TOKEN is not reachable from inside it;
              only MASTER_KEY_FILE and one read-only bind of a /dev/urandom
              key that never leaves the runner. The two values read back out
              of the container (in-image APP_VERSION, the log text) are
              compared and grepped, never eval'd. A hung container is bounded
              twice, by the step's own 60s poll deadline and the job's 30min
              timeout.

              Quality: the step fails closed everywhere -- a container that
              exits during the poll is detected rather than waited out, and
              cleanup() dumps the container log on every exit path so a smoke
              failure never needs a re-run to find out what happened.
📄 DOCS       ➖ N/A -- CI plumbing, not app CHANGELOG material (repo precedent:
              the dev.33/34 CI commits). The reasoning is in the workflows' own
              comments, as the rest of this repo's CI decisions are.
📦 RELEASE    ✅ PR #17 MERGED -> main (merge commit 1040454). Opened as:
              Opened on the user's "commit the record, do the first-parent fix,
              then open the PR". First attempt refused by the gate-preflight
              hook on VERSION ⬜ (see that gate above); settled as N/A with the
              reason stated, then retried. The block was not worked around.
🚀 SHIP       ➖ N/A -- work commit: no tag, no artifact, nothing published.

CLOSED. On the merge, main's new triggers went live and behaved: Lint workflows
run 29 (9s) and Check run 144 both fired on 1040454, Check because the merge
touched tests/ which is deliberately NOT in paths-ignore. Run 144 is also the
first FULL-suite run of the first-parent fix -- only the 29 targeted tests were
run on that tree locally, since tests/test_release_workflow.py is the only test
that reads release.yml.

STILL UNPROVEN, carried forward: the release.yml smoke step has never executed
(no docker in this container). The NEXT TAG is what proves both it and the
ancestor fallback from PR #16 -- neither has run in anger. A broken smoke step
fails the release rather than publishing something bad, so it fails safe, but
that is not the same as having run.

FOR THE NEXT SESSION: if more CI time needs cutting, the lever is pytest-xdist
or sharding the 186 browser tests, which are very nearly the entire wall clock
of a 1594-test run. NOT path-based test selection -- scripts/check.sh is one
entrypoint shared by CI and local dev so the two cannot drift, and splitting by
path breaks exactly that.

## Release sequence: release.yml gate fallback -> finish v1.1.0-beta.2 (2026-09-18)
Track: started as a work commit; became a release sequence when the user
asked to move the tag and unblock beta.2, which needs the fix on main.
Branch: claude/dev-skills-beta-workflow-cwzvx5.
Environment: remote container (Claude executes git; tag pushes go to the user).
User: "fix the issue with the .2 beta release workflow".

Diagnosis: release run 35296493378 (tag v1.1.0-beta.2 on 0038140, the PR #15
handoff merge) failed its gate in 8s -- "Check has never run for 0038140".
check.yml's paths-ignore skips .claude/**, so the docs-only merge that became
main's head got no Check run, and the gate had no fallback. Nothing was
published; :1.1.0-beta.2 does not exist on ghcr.io.

🔢 VERSION    ✅ 1.1.0-beta.2, unchanged -- this completes the ship that
              PR #14 started rather than bumping past it. All refs agree:
              backend/main.py APP_VERSION, docker-compose.yml image tag,
              README beta block, CHANGELOG heading. Prior version
              v1.1.0-beta.1 confirmed tagged on remote (ed4ba63). The tag
              being moved keeps naming the version the commit declares, so
              release.yml's own APP_VERSION check still matches.
🔨 BUILD      ✅ handoff n/a (remote container -- this session's clone is in an
              ephemeral container the user's terminal never sees, so there is
              no artifact here for them to try). Recorded as n/a rather than
              "offered": the accurate reason is structural, not a decline.
              Worth stating alongside it, though it is not what makes the gate
              pass: this diff touches release.yml, tests/, CHANGELOG.md and
              this file only. No app code, and the Dockerfile copies none of
              those paths, so the image built from this tree is byte-identical
              to the one beta.2's suite already tested at 88b4b59. The user was
              given the local `docker build` + smoke command anyway, to run on
              their own box if they want it.

              actionlint 1.7.12
              (repo's pinned version + checksum) with shellcheck on PATH, exit
              0 over all three workflows; lint-workflows.yml run 35298127820
              green on the pushed commit.

              The first pass on this verified the step with a throwaway
              harness in a scratch dir, having missed that
              tests/test_release_workflow.py already does exactly this for the
              APP_VERSION step -- lifts the `run:` body out of release.yml as
              text and runs it against a stub gh. The 13 new cases now live
              there in that same style: own run passing, own run failed
              (refuse, and asserts the ancestor lookup is never reached), the
              real beta.2 shape against the real check.yml, identical tree,
              code file differing from the ancestor, nearest-ancestor
              selection, ancestor tested only by a pull_request run, no tested
              ancestor, unreadable paths-ignore, a glob the step will not
              guess at, an unreadable compare, and a guard on check.yml's
              paths-ignore keeping the shape the step's sed expects.
              23 passed. Checked against HEAD~1's release.yml that 8 of the
              new cases fail without the fix, so they discriminate.

              Full suite via scripts/check.sh: 1591 passed, 3 skipped, exit 0,
              542.91s, with real tshark/tcpdump/capinfos and chromium. 1594
              collected = the 1581 at beta.2 plus these 13. The 3 skips are
              test_entrypoint.py's pre-existing root-writes-0500 cases.
🔒 SECURITY   ✅ 0 Critical, 0 High. Reviewed as a gate-weakening question,
              not a code-injection one. The fallback publishes only when the
              diff from a tested ancestor is confined to check.yml's own
              paths-ignore list, and none of those paths enter the image
              (Dockerfile copies backend/, frontend/, entrypoint.sh,
              requirements.txt, backend/tls/fetch_lego.py -- nothing else), so
              the published artifact is the tested one. Fails closed on every
              branch it cannot establish. Ancestor search restricted to push
              runs, because a pull_request run tests the merge ref, not the
              commit. No new permissions (actions: read, contents: read cover
              the added contents/commits/compare calls); external strings are
              compared, never eval'd; a filename containing a newline splits
              into entries that match no pattern and so refuse.
📄 DOCS       ✅ CHANGELOG 1.1.0-beta.2 entry gains a "Releases" bullet; the
              reasoning is in release.yml's own comments, as the rest of that
              file's decisions are.
📦 RELEASE    ✅ PR #16 open: claude/dev-skills-beta-workflow-cwzvx5 -> main,
              3 commits (e3f6961 fix, 24f233f tests, 1b406da gate record).
              Opened on the user's "yes open the PR". First attempt was
              REFUSED by the gate-preflight hook -- BUILD was ✅ with no
              artifact-handoff annotation and this repo has a Dockerfile. The
              annotation was added (n/a, remote container) and the PR retried;
              the block was not worked around.
🚀 SHIP       ✅ -- SEE THE SHIPPED SECTION AT THE TOP OF THIS FILE. What
              follows was written before the tag moved and is kept as the
              record of the decision, not as current state.
              At the time: v1.1.0-beta.2 was tagged on 0038140 and was never
              published; run 35296493378 refused it. Once the PR merges, the
              tag moves onto the new main head, which carries the fix (a tag
              push runs release.yml as of the TAGGED ref, so re-running
              35296493378 could never have picked it up).

              Note the merge commit will touch tests/, which is not in
              paths-ignore -- so Check runs on it normally and this release
              will satisfy the gate's PRIMARY lookup. The fallback added here
              is not exercised by it; the first release that really leans on
              it will be a future docs-only one.

              The tag re-push is the user's block to run (SKILL.md 5.8:
              delete + create, never Claude's, in any environment). SHIP stays
              ⏳ until git ls-remote --tags origin confirms the tag on the
              merge commit AND the release run publishes the image.

## Carry forward — the only part of the history that is still load-bearing

Everything below the 2026-09-18 sections above was pruned on 2026-09-18, at
2967 lines. The file is read WHOLE by .claude/hooks/gate-preflight.sh on every
git write, so its length is a per-operation cost.

This follows the file's own precedent, stated when dev.26 opened: "the
long-form notes for dev.21-dev.25 were dropped from this file; the CHANGELOG
carries the user-facing record and git carries the rest." Same here -- every
pruned section was CLOSED AND SHIPPED, and `git log -- .claude/dev-skills-gates.md`
has all of it.

What follows is what a new session actually needs. It was checked against the
live tree rather than copied forward, because several entries had gone stale.

### Still open

- **M5 / L1 / M1-code**, deferred by design at dev.37, never revisited:
  TOTP secrets are plaintext at rest; no chunked-body cap; the rate limiter's
  re-key. Deferred deliberately, not forgotten.
- **httpx2** -- starlette 1.6's test client asks for it in a deprecation
  warning. It is a NEW package; vet it before adopting.
- **Python 3.14** -- pydantic-core ships cp314 wheels now, so scripts/check.sh's
  3.13 ceiling could rise once the suite has actually run on 3.14. It never has.
- **The gate's ancestor fallback has never fired** (beta.3 used the primary
  lookup). The release.yml smoke step is PROVEN: run locally against the beta.3
  image and then in CI on the v1.1.0-beta.3 release, both passing.
- **If CI time needs cutting**: 186 browser tests are very nearly the entire
  wall clock of a 1594-test run. The lever is pytest-xdist or sharding THOSE.
  NOT path-based test selection -- scripts/check.sh is one entrypoint shared by
  CI and local dev, with a comment saying it exists so the two cannot drift.

### Constraints that are still true

- **backend/bpf.py and frontend/js/app.js (bpfCheckExpression) are one model in
  two copies**, kept honest by a parity browser test. Change both or neither.
- **page.wait_for_function needs "() => ..." here, never a bare expression.**
  This app's CSP blocks the bare form.
- **Custom filter entries are private per user. The server dropdown is closed** --
  do not touch it.
- **pyproject.toml is pytest config only** -- no [project] table, so the
  repo-link requirement lands on backend/main.py REPO_URL + release_notes_url.
- **Version refs differ by release KIND, so count them, do not recite a number.**
  A beta touches backend/main.py APP_VERSION, docker-compose.yml, README's beta
  block and CHANGELOG -- and deliberately NOT README's Quick start link or
  docs/reverse-proxy.md, which stay pinned to the last STABLE release so a beta
  never becomes the default path. A stable release touches those too. Earlier
  copies of this file asserted "FIVE places" and then "SEVEN"; both were true
  once and neither is a rule. Grep for the outgoing version.
- **This file is tracked in git, not gitignored** -- contrary to SKILL.md's
  local-session default, and left that way deliberately across many sessions.
- **The gate-preflight hook parses this file line by line.** A wrapped prose
  line can be misread as a gate line and reported as a phantom blocker; that
  happened on 2026-09-18. Keep free text clear of anything shaped like a
  tracker row.

### SUPERSEDED -- do not act on the old text if you find it in git history

Each of these was a standing instruction that is now FALSE. They are listed
because acting on them would mean re-declining work that is already shipped.

- ~~"CI fires three runs per release ... one-line fix OFFERED, not accepted.
  Do not re-raise unprompted."~~ FIXED 2026-09-18. check.yml's push trigger is
  branches: [main], pull_request carries the same paths-ignore, and both it and
  lint-workflows.yml have concurrency groups.
- ~~"DECLINED by the user 2026-09-13, do not raise again: rewiring CI so
  release.yml is gated on check.yml, and narrowing check.yml's triggers."~~
  BOTH DONE. The gate job landed in dev.36 (the user superseded the decline
  explicitly); the triggers were narrowed 2026-09-18.
- ~~"Live streaming has still never run against a real remote host."~~ The
  whole feature was REMOVED in dev.33. The only trace left is a DROP COLUMN
  migration in backend/database.py.
- ~~The dev.39 workflow-audit findings: no tag-on-default-branch check, no
  concurrency, no timeouts, no persist-credentials, floating action tags.~~
  ALL CLOSED -- verified against the live files 2026-09-18: every workflow has
  persist-credentials: false, timeout-minutes, SHA-pinned actions, and a
  concurrency group.
- ~~"Queued for dev.28: ACME integration; a DATA_DIR world-readable warning."~~
  Both shipped in dev.28.
- ~~"PENDING WORK: packet sanitizer not started; security audit prepared but
  not run."~~ The sanitizer shipped in dev.31; the audit ran and produced
  dev.37's H1/H2/L7/L2/L6 fixes.
- ~~"Queued UI batch" (filter badges, capture name required, confirm dialog,
  custom filters, live BPF display).~~ All five shipped in dev.26.
