# Dev Skills gate state
Track: release sequence -- 1.1.0 stable, no more betas (user, 2026-09-20)
Mode: manual
Version: 1.1.0
Model: Opus 5 (ceiling flagged; user's standing per-task approval for this repo)
Shell: Linux bash. Env: LOCAL -- same clone as the user's terminal.
Updated: 2026-09-20

## ACTIVE: v1.1.0 -- first stable since 1.0.0, moves :latest
Branch claude/interface-directionality-findings, from main 0c99359 (beta.9).
Started from .claude/interface-directionality-handoff.md; that handoff is
closed by this work, and beta.10/beta.11 were never cut -- the user took it
straight to stable.

THE SHAPE OF THIS RELEASE CHANGED MID-SESSION, twice, on the user's call.
It began as "fix the two upload defects", grew a subnet-mapping UI and an
interface-naming feature, and ended by DELETING the subnet mapping entirely:
"the mappings dont do anything anyway... it does not work like i want it to,
and its a gap from a native pcapserver capture." Full removal was chosen from
three options (AskUserQuestion): UI, routes, parser, and the stored column.

WHY THE REMOVAL IS RIGHT, not just asked for: the mapping inferred an
interface and a direction from a packet's ADDRESSES, which cannot say which
link a packet crossed. Measured, not argued -- with both ends mapped
(172.16 -> 100.26 and back) place() always returned the DESTINATION's
interface and always "out", so the reverse direction never showed "in" at
all. A subnet is not an interface; one merely routed through is not one
either. It read like recorded fact and was a guess.

WHAT SHIPS INSTEAD: only what a capture's own file records. Settled by the
two Windows captures the user sent (see the handoff for the measurement).

🔢 VERSION    ✅ 1.1.0 -- backend/main.py APP_VERSION + docker-compose.yml
              agree; CHANGELOG heading added. STABLE, so the references a
              beta deliberately leaves alone moved too: README Quick start
              link -> v1.1.0, docs/reverse-proxy.md -> 1.1.0 (x2), and the
              README beta-notice block is GONE rather than bumped (this is
              not a beta). Previous tag v1.1.0-beta.9 confirmed on the
              remote -> 7afae37.
🔨 BUILD      ✅ handoff offered and taken; scripts/check.sh EXIT=0 on the final tree.
              1814 passed, 0 failed, 0 skipped, 36.70s, with real
              tshark/tcpdump/capinfos/chromium. The handoff was EARLIER in the
              session, on the pre-removal tree:
              preview container driven by hand on :8099 with the user's own
              Windows capture uploaded into it. That look found a real bug no
              test could (stale notice text), and the preview work is what
              led the user to the removal. The removed UI needs no re-look;
              what remains of the frontend is covered by 270 browser tests.
🔒 SECURITY   ✅ 0 open -- 0 Critical, 0 High. backend+frontend net -178 lines
              (226 added, 404 removed): one route gone
              (PUT /api/captures/{id}/subnet-map), two request models, a
              stored column and a parser class, so the attack surface only
              shrinks. Earlier copies of this row said "-879", which counted
              this file's own 1106-line prune as deleted product code -- the
              whole-tree figure is -15, and neither number means anything
              about attack surface. The one thing that GREW it is reviewed
              in full below.
📄 DOCS       ✅ docs/viewer.md rewritten: what each kind of upload records,
              the legacy-.pcap footgun, and a named section on the GAP the
              user asked to be documented -- an upload is not as good as a
              capture taken here, why, and what to do instead. CHANGELOG 1.1.0
              leads with Removed and says stored mappings are dropped.
📦 RELEASE    ✅ branch synced with origin (fetch 2026-09-20, no divergence);
              commit approved by the user; PR opened on this commit; release
              notes = the CHANGELOG 1.1.0 section, approved with it.
🚀 SHIP       ⏳ 1.1.0 is STABLE -- the tag moves :latest, unlike every beta
              this repo has shipped since 1.0.0. Plan: merge the PR, then the
              user pushes v1.1.0 from /home/serveradmin/pcap-server; then
              verify the tag SHA on the remote and the Release run only.

SECURITY, the one item with content: an interface name now originates in an
UPLOADED FILE (a pcapng's if_name/if_description), where before it came from
the operator's mapping or this server's own reading of a host it controls.
Every render site checked one by one -- the packet list cell escapes it in the
body, the title and the data attribute; the diagram writes labels and tooltips
with textContent; bounded to 64 chars at the parser. MEASURED, not reasoned: a
crafted if_description containing a TAB or NEWLINE does not shift the
tab-separated columns, because tshark backslash-escapes both. No filter is
ever built from a name (grepped: only sll.ifindex == {int} and
frame.interface_id == {int}). pip-audit clean on both requirements files.

WHAT WAS KEPT from the earlier half of the session:
 * the hex direction parse (tshark prints the pcapng flag in hex; the lookup
   was decimal, so that path had never once run);
 * recorded interface names used as they stand, description preferred over a
   GUID-shaped name, "any" and bare GUIDs treated as naming nothing;
 * recorded_interfaces read once at upload and stored on the capture;
 * the Interface column showing on an upload that records interfaces -- it was
   hidden on exactly those captures, so the names had nowhere to appear;
 * the right-click filter on that column for uploads;
 * scripts/preview.sh: COOKIE_SECURE=true + TRUST_PROXY_HEADERS=true for the
   user's proxy, preview.sh itself folded into the rebuild hash (a docker-run
   flag change used to report "unchanged" and keep the old container), and the
   seed's cookie policy fixed -- a Secure cookie is not SENT over loopback
   http by urllib, so seeding logged in 200 then 401'd on everything after.
   Verified from wiped volumes, which is the path that would have broken.

TESTS: the suite is smaller and the removed features' tests went with them.
New/kept coverage: the hex parse incl. leading zeros, what counts as an
identifying name, the two-source precedence, a built Windows-shaped pcapng
through both the list and diagram paths, get_interfaces on a file that records
names and one that records none, recorded_interfaces stored at upload, the
Interface column appearing and staying hidden, and the recorded-name
right-click filter.

NEXT: commit approval, then Gate 5.

## SHIPPED -- one line each; full records in git log and CHANGELOG.md
Pruned 2026-09-20 from 1072 lines: the file is read WHOLE by
.claude/hooks/gate-preflight.sh on every git write, so its length is a
per-operation cost, and six closed releases in full were most of it.

- **v1.1.0-beta.9** diagram packet caps + partial diagrams instead of a hard
  fail. PR #31 -> 7afae37, Release run 35443258638. Found and fixed a real CSS
  bug by looking at the rendered preview (a descendant selector over-matching
  nested radio inputs) that no test could see.
- **v1.1.0-beta.8** multi-interface reality fixes. PR #29, tag -> acb969e.
- **v1.1.0-beta.7** UI feedback batch. PR #27 -> a61203b, run 35415933306.
- **v1.1.0-beta.6** diagram zones/layouts, capture optimize, upload interfaces.
  PR #23 -> e387d10. First tag landed before the merge; the release gate
  refused it and published nothing -- working as designed.
- **v1.1.0-beta.5** large-capture diagrams + label fix. PR #22 -> a39e8a2.
- **v1.1.0-beta.4** Traffic Diagram overhaul + preview container. PR #19/#20,
  tag -> efdfc08. Its README-only commit was the first live exercise of
  release.yml's ancestor fallback.
- **v1.1.0-beta.2** the interrupted ship, finished. Tag moved onto the PR #16
  merge commit by the user; run 35299208966.
- **Work commit, 2026-09-18: CI trigger waste.** check.yml push -> [main],
  pull_request given the same paths-ignore, concurrency on both workflows, and
  release.yml gained the image smoke test. PR #17 -> 1040454. Measured: two
  .claude/-only PR runs had cost 12m02s and 11m36s on commits containing no
  code.

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
