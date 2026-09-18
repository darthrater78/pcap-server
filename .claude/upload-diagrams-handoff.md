# Handoff: pcap upload + traffic-diagram DNS/protocols

Written 2026-09-18. Start a fresh session from this file, then read
`.claude/dev-skills-gates.md` (the section at the TOP of that file — the hook
reads the first match for each gate name, so the newest section must stay
first). Re-check `git status` and `git log`: other sessions edit this repo.

**Goal:** three things the user asked for in one session — upload a pcap to
view it, sealed and encrypted exactly as a capture is and marked as an upload;
fix DNS resolution in the traffic diagram; show more protocols there.

**Stopped mid-task on the user's instruction** ("stop the work for now, commit
what's done and write a handoff"). Everything below is committed and pushed to
`claude/dev-skills-beta-workflow-cwzvx5`. No PR. Nothing is tagged, nothing
published, and `APP_VERSION` is untouched at 1.1.0-beta.2.

## What is DONE and verified

**1. DNS resolution — two bugs, one change.** Both were measured against real
tshark 4.2.2 in the container, not inferred.

- `_RESOLVE_ON` passed `-N mnt`. `-N`'s letters are the COMPLETE set of
  resolutions tshark performs, so omitting `d` switched OFF resolution from the
  capture's own DNS answers — the only source that works with no resolver and
  no hosts file, i.e. the only one that works on a server reading someone
  else's traffic. Now `-N mntd`, plus an explicit
  `nameres.dns_pkt_addr_resolution:TRUE`.
- `get_conversations` read `-e ip.src` / `ip.dst`, which NEVER resolve. The
  resolved values are in `ip.src_host` / `ip.dst_host` (and the ipv6 pair). Its
  docstring claimed otherwise; both are corrected.

These are ONE change and neither ships alone. Pre-fix, nothing resolved
anywhere, so both routes returned addresses and agreed — playback worked and
simply showed no names. Fixing only the flags gives `/packets` names while
`/conversations` keeps addresses, and `drawTopologyFrame`'s
`byId.get(p.source)` then misses on every packet, hits `if (!a || !b)
continue`, and the animation goes blank. `test_conversations_and_packet_list_
agree_on_every_host_name` is the guard against exactly that; it was confirmed
to fail against a deliberately half-fixed tree.

**2. More protocols in the diagrams — 8 slots, 3 hues.** Eight hues is not
available and this was measured, not assumed: the dataviz skill's validator on
its full eight-slot palette, all-pairs (which a node-link diagram needs, since
any two colours can be adjacent), hard-FAILS both modes — light CVD 3.2 /
normal-vision 7.1, dark CVD 1.6 / normal-vision 7.1. A normal-vision pair below
15 is a gate no secondary encoding excuses. Enumerating every subset of those
eight hues, FOUR is the most that clears all-pairs in both modes, and only two
orderings manage it, both in the 6–8 CVD warn band. The three already shipped
clear at 9.2 light / 9.4 dark.

So the eight slots are composite encoding — 3 validated hues × 3 shapes, in
`diagrams.js PROTOCOL_SLOTS`. Any two slots differ in hue (≥9.2, measured) or
share a hue and differ in shape. **Zero hex values changed**, so a capture whose
traffic is three protocols looks exactly as it did. Topology marks vary shape;
sequence arrows vary stroke dash (a line has no shape); the legend swatch draws
the real mark rather than a coloured square. The grid holds 9 combinations and
the cap is 8 — that cap is a legend-width choice, not a colour-safety limit.

**3. Upload.** `POST /api/captures/upload?filename=<label>`, raw pcap as the
body, **not** a multipart form. That is the design, for two reasons worth not
re-litigating:

- Starlette spools an `UploadFile` to a temp file while parsing the multipart,
  which would write the plaintext pcap to disk before anything sealed it. This
  repo has held the opposite invariant since captures were first encrypted.
- A multipart file part has no size cap before parsing, and a chunked request
  carries no Content-Length — so the existing middleware could not bound it.
  `import_upload` counts bytes off the stream instead.

An uploaded pcap is stored under the same vault key, the same `stored_path()`
name, and read by the same `source_for()` reader, so listing, viewing,
filtering, saved views, sanitizing, downloading and deleting all work with no
new code. The only difference is `CaptureInfo.origin` (new `CaptureOrigin`
enum, new `captures.origin` column backfilled to `'capture'` — a fact, not a
guess, since every pre-existing row IS a capture).

Verified end to end in the container: sealed on disk (file starts with the
crypto MAGIC, not the pcap magic), download round-trips byte-identical, the
packets route reads it, it appears in the list. Refusals all correct: not a
pcap 400, empty 400, under four bytes 400, pcap header on garbage 400 (capinfos
is the real gate), oversize with Content-Length 413 from the middleware,
**oversize chunked with no Content-Length 400 from the route** — the bypass is
closed — plain HTTP 403, rate limit 429. No `.partial` files left behind by any
refusal.

**4. One real security finding, in this session's own new code, found by the
gate and fixed.** A locked vault presents `cryptor=None`, which is
indistinguishable from "encryption disabled". An upload arriving while the
vault waited for its passphrase was therefore written **in the clear**, as
`<uuid>.pcap` with no `.enc` suffix, on an installation whose whole premise is
encryption at rest. Reproduced (the pcap magic was the first four bytes on
disk), then fixed fail-closed before anything is written; now 503, because the
remedy is an admin unlocking and the same request then working.

## OPEN — the pre-existing twin of that finding, NOT fixed

⚠️ **The same fail-open almost certainly exists on the capture path, and it
predates this work.** `_collect` does `cryptor = self._vault.cryptor if
self._vault else None` and hands that to `fetch_file`; `_store_ssh_key` has the
same shape (`vault.cryptor.seal_bytes(...) if vault.cryptor else content`). No
route anywhere refuses a write while `vault.locked` is true — grep shows the
only `locked` checks in `main.py` are the status field and the unlock route's
own guard. So a capture that completes, or an SSH key that is uploaded, while
the vault is locked looks like it lands unencrypted.

This was NOT fixed here, deliberately: it is a vault-wide change touching three
write paths, it wants tests of its own, and the session was told to stop. It was
not verified either — only the upload path was actually reproduced. **Verify it
before fixing it**, the same way: force `vault._cryptor = None`, drive the path,
and look at the first four bytes on disk. If it reproduces it is a High.

## Still TODO on the three features

- **Upload tests are NOT written.** This is the biggest gap. Everything in
  "verified" above was proven with throwaway scripts, not committed tests —
  so none of it is guarded. `tests/test_capture_upload.py` was about to be
  written when the session stopped; write it in the style of
  `tests/test_capture_views.py` (a `secure_client` + `enrolled` fixture pair).
  Cover at least: the sealed-on-disk assertion, the download round trip, all
  five refusals, the chunked-oversize case (the important one — use a generator
  body so httpx omits Content-Length), the locked-vault 503, that another user
  cannot see or download the upload, that the record leaves server/interface/
  filter/command empty, and that the `origin` migration backfills `'capture'`.
- **No browser test for the upload UI or the 8-slot legend.**
  `tests/browser/test_diagrams_ui.py` is the place for the legend (assert 8
  legend items and distinct shapes, not 3); `tests/browser/test_capture_ui.py`
  for the upload row.
- **Nothing was driven in a real browser.** The upload row, the `upload` badge,
  the new legend swatches and the shaped canvas marks have never been looked at
  on screen — only the JS syntax and the unit-level behaviour are checked. Run
  the app and look before this goes near a release.
- **No CHANGELOG entry**, correctly: work commit, no publish. A release owes
  one, and it should mention the DNS fix as a fix to the packet list too, not
  just the diagrams.
- **`docs/viewer.md` and `README.md` say nothing about uploads.** Owed at
  release time.

## Key files

- `backend/packet_parser.py:~250` — `_RESOLVE_ON`, the `-N mntd` fix and why.
- `backend/packet_parser.py` `get_conversations` — the `_host` field switch.
- `backend/capture.py` — `UploadRejected`, `import_upload` and its helpers
  (`_upload_record`, `_write_sealed_upload`, `_header_looks_like_a_capture`,
  `_check_upload_size`, `_check_upload_finished`, `_write_upload_chunk`).
- `backend/main.py` — `/api/captures/upload`, `_upload_label`, `_body_limit`'s
  third cap, `upload_rate_limiter`.
- `frontend/js/diagrams.js:~15-130` — the palette reasoning, `PROTOCOL_SLOTS`,
  `slotSwatch`, `drawPacketMark`.
- `frontend/js/app.js` — `onUploadCaptureClick`, the `upload` badge in
  `renderCaptures`, the origin line in `setViewerLabel`.

## Decisions the next session must respect

- **The upload body is raw, never multipart.** Both reasons are above and both
  are load-bearing.
- **The client filename is a LABEL and never a path.** The stored file is named
  by a server-generated UUID. `_upload_label` drops a name that does not match
  its allowlist rather than rewriting it, so an odd name shows the capture id —
  honest — instead of something that looks like the chosen file and is not.
- **Do not add a fourth diagram hue.** Four is the measured ceiling and only two
  orderings reach it, both in the warn band, and getting there means repainting
  the three that already clear the target. The shape channel is the way to more
  protocols.
- **`origin` has no third "unknown" state.** The migration backfills `'capture'`
  because that is what every pre-existing row is.
- Everything in `.claude/dev-skills-gates.md` under "Constraints that are still
  true" still applies — in particular the bpf.py/app.js parity rule and the
  `page.wait_for_function` CSP quirk.

## Shell environment
Remote container; Claude runs git here. Tag pushes and ref deletions still go
to the user as a block to run (none owed — nothing is tagged).

## Next step
Write `tests/test_capture_upload.py`. The behaviour is already proven to work;
it is simply unguarded, and that is the one thing standing between this branch
and being reviewable.
