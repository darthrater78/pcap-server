# Handoff: ship v1.1.0-beta.2

**Goal:** Publish `ghcr.io/darthrater78/pcap-server:1.1.0-beta.2` — the
traffic-diagram follow-ups (trace playback, DNS resolution, directional
filters, Sequence Diagram lane guard) as the next beta.

## Current state

- PR #13 (the follow-up feature work) merged to `main` — `74b5902`.
- PR #14 (the version bump to 1.1.0-beta.2) merged to `main` — `88b4b59`.
  `git ls-remote --heads origin` confirms `main` is at `88b4b59`.
- **Tag `v1.1.0-beta.2` was pushed by the user AHEAD of Check confirming
  green**, at their explicit instruction after being told the risk. At push
  time, `Check` on `88b4b59` was still `in_progress`
  (https://github.com/darthrater78/pcap-server/actions/runs/35265384428).
  This is a deliberate, acknowledged deviation from the normal order (Gate 6
  wants the passing Check run confirmed *before* the tag goes out) — not a
  mistake to silently correct, but the next session must pick up here and
  verify what actually happened rather than assume it shipped clean.

## What to check first, next session (or later this one)

1. **Did `Check` on `88b4b59` pass?**
   ```
   gh api "repos/darthrater78/pcap-server/actions/workflows/check.yml/runs?head_sha=88b4b59d3259ec04f10f333ab8d69bc9f01ea9b4&per_page=5" --jq '.workflow_runs[0] | "\(.status) \(.conclusion)"'
   ```
2. **Did the tag actually push, and to the right commit?**
   ```
   git ls-remote --tags origin v1.1.0-beta.2
   git rev-parse v1.1.0-beta.2^{}   # after a fetch — must read 88b4b59...
   ```
3. **Did `release.yml` run, and what did it decide?**
   ```
   gh run list --workflow=release.yml --limit 3
   ```
   `release.yml`'s own `gate` job independently re-checks that the tagged
   commit is on `main` *and* has a passing Check run — so if Check actually
   failed, this job should have refused to build, and the release run's
   conclusion will say so. **If it refused:** nothing was published, the tag
   just points at a commit whose tests didn't pass — fix the failure, then
   follow "Recovery: a tag landed on the wrong commit" isn't quite right here
   (the tag is on the *intended* commit) — instead: delete the tag
   (`git push origin :refs/tags/v1.1.0-beta.2` — ref deletion, always the
   user's to run), fix whatever Check found, merge the fix, re-tag.
   **If it built anyway** (i.e., Check actually passed by the time the gate
   job ran, even though it was `in_progress` when the tag was pushed): proceed
   to post-ship verification as normal.
4. **Post-ship verification (once the release run shows success):**
   - `git ls-remote --tags origin v1.1.0-beta.2` — tag on remote
   - `gh release view v1.1.0-beta.2` — GitHub release exists
   - Image published: check the release run's own build-push log for the
     exact tags it pushed (same technique used for v1.1.0-beta.1 — the run's
     "Derive release metadata from tag" + "Build and push image" steps state
     the image name directly, no `read:packages` scope needed)
   - PR #14 state == "MERGED" (already confirmed above)
5. **Add release notes** if `release.yml`'s auto-generated ones need replacing
   with the CHANGELOG 1.1.0-beta.2 entry (`gh release edit v1.1.0-beta.2
   --notes "..."`) — same pattern as every prior release in this repo.

## Gate tracker (as of this handoff)

See `.claude/dev-skills-gates.md`, section "Release sequence: 1.1.0-beta.2":
VERSION / BUILD / SECURITY / DOCS all ✅. RELEASE was ⏳ (PR #14 merged, not
yet updated to ✅ as of this file). SHIP is unverified — this handoff exists
because that verification didn't happen before the tag went out.

## Key files

- `backend/main.py:116` — `APP_VERSION = "1.1.0-beta.2"`, source of truth
- `docker-compose.yml` — image tag, also `1.1.0-beta.2`
- `README.md` — beta-announcement block, already updated to `1.1.0-beta.2`
- `CHANGELOG.md` — `## 1.1.0-beta.2` entry already written

## Environment

Local session (Linux Terminal, bash/zsh), same clone the user's terminal
uses. Git write operations are presented for the user to run, never executed
directly here, except where they explicitly asked otherwise. Tag pushes and
ref deletions always go to the user, in every environment.

## Next step

Run the four checks above, in order. If Check passed and the release
published clean, this handoff can be deleted once its content is folded into
`.claude/dev-skills-gates.md`'s SHIP line (matching how every other
`*-handoff.md` in this repo's history got swept into the next commit). If
Check failed, the recovery steps in section 3 above are the next action, not
this file.
