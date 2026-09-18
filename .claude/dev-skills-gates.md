# Dev Skills gate state

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
- **The release.yml smoke step has never executed**, and the gate's ancestor
  fallback has never fired. Both shipped 2026-09-18 proven by tests only; the
  next tag is what proves them. Both fail closed.
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
