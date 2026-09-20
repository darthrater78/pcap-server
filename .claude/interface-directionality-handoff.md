# Handoff: interface identity and directionality on uploads

Written 2026-09-20. Start a fresh session from this file. Branch cut clean from
`main` (`0c99359`, 1.1.0-beta.9) — it carries **no code changes**, only this
document.

**Replaces** the branch `claude/wireshark-multi-interface-directionality-i8rm8e`,
which is being deleted. That branch held a code fix that was **not** ready (see
"The blocked decision") and a handoff with a factual error. Nothing of value is
lost: everything still needed is below.

**Nothing here is shipped or committed as code.** beta.9 behavior is unchanged
and is currently the safer default.

---

## 1. Settled facts — measured, do not re-derive

Verified in a Linux container, Wireshark/tshark 4.2.2, tcpdump 4.99.4,
libpcap 1.10.4. Each cell is per-packet.

| Capture path | Encapsulation | Direction | Interface identity |
| --- | --- | --- | --- |
| **Native, `any`** (tcpdump) | Linux cooked **v2** | **real** — kernel `sll.pkttype`, 38 in / 22 out | **real** — kernel `sll.ifindex` → sysfs name |
| Native, single named interface | Ethernet | none (0/40) | none per-packet; known from the request |
| **Upload, Wireshark multi-interface** | pcapng, N IDBs | none (0/341) | **real** — IDB `if_name`, 341/341 |
| **Upload, Wireshark `any`** (Linux) | Linux cooked **v1** | **real** — `sll.pkttype`, 203 in / 185 out | only the pseudo-name `"any"` — useless |
| Upload, legacy `.pcap` | Ethernet | none | none (IDBs collapse to 1) |

Key consequences:

- **Wireshark genuinely captures multiple interfaces.** One pcapng, one IDB per
  interface, correct name on every packet. Survives *Save As* and *File > Merge*.
  Saving as legacy **`.pcap` destroys it** — the format cannot hold interfaces.
  That is a real operator footgun.
- **Direction is not always inferred on an upload.** It is real whenever the file
  is a Linux cooked capture, because direction rides *inside the SLL header*, not
  in `epb_flags`. (An earlier handoff claimed uploads can never carry real
  direction. That was wrong and is the error this document corrects.)
- **Direction is never recorded on an ordinary Ethernet capture**, on any
  platform, because libpcap's per-packet header has no direction field for
  dumpcap to write. Only cooked captures and non-libpcap sources carry it.
- `dumpcap -i any` writes cooked **v1** (no ifindex); `tcpdump -i any` writes
  cooked **v2** (with ifindex). Same libpcap — it is a tool choice. So
  `ssh_manager.py`'s "a capture on `any` is Linux cooked v2" holds for the native
  path but **not** for an uploaded Wireshark `any` capture.

### Method note — why this is about Wireshark, not tshark
Captures were taken with `dumpcap`, which ships in `wireshark-common`; the GUI
has no capture path of its own and forks dumpcap. So `dumpcap -i a -i b` is the
same writer as ticking two interfaces in the GUI. tshark appears only as the
instrument for reading files back — correct, because tshark is also how
pcap-server reads them.

---

## 2. The blocked decision

The rule *"a recorded interface name outranks the operator's subnet mapping"* is
correct in spirit but **under-specified**, and shipping it unguarded is a net
regression. Two known counterexamples, one measured and one expected:

1. **Measured.** A Wireshark `any` capture records its IDB name as the literal
   string `"any"`. Preferring it yields `interface: {'any': 388}` and discards
   the operator's mapping entirely — worse than beta.9.
2. **Expected, unverified.** On Windows, Wireshark conventionally puts
   `\Device\NPF_{GUID}` in `if_name` and the friendly name in `if_description`
   (the field `frame.interface_description` exists; it is empty on Linux, where
   our IDBs carry no `if_description`). If so, preferring `if_name` shows
   operators a raw GUID instead of their readable mapping.

Both are the same flaw: *"the file records a name"* is not *"the file records
which interface."* The rule needs to be **"prefer a recorded name that identifies
a specific, readable interface; otherwise fall back to the mapping"** — and
probably to read `if_description` in preference to a GUID-shaped `if_name`.

**This is what the incoming Windows captures are for.** Do not finalize the
precedence rule until they land.

---

## 3. Incoming: three Windows captures

Expected: multiple interfaces, a single interface, and an "any" equivalent.

### There is no `any` on Windows
`any` is a Linux pseudo-device (it is what produces cooked capture). Npcap does
not provide one, which is why there is no GUI option — it is not a missing
checkbox, it is absent from the platform. **No Windows file can give both real
interface and real direction the way `tcpdump -i any` does.** Three substitutes,
in order of usefulness:

**(a) All interfaces at once — the Wireshark-native equivalent.** Gives real
interface identity, no direction. This is the file that settles the GUID question
in §2.

```powershell
# enumerate, then pass every interface as its own -i
$ids = (dumpcap -D) | ForEach-Object { if ($_ -match '^(\d+)\.') { $matches[1] } }
$argl = $ids | ForEach-Object { '-i', $_ }
& dumpcap @argl -w all-interfaces.pcapng -a duration:30
```
Drop any pseudo-interface that refuses to open and re-run. The GUI equivalent is
ctrl-clicking several interfaces in the capture dialog.

**(b) `pktmon` — built in, Windows 10 1809+ / Server 2019+.** Captures across all
adapters *and* records direction, so this is the closest thing in spirit to
`any`.
```
pktmon start --capture --pkt-size 0 --file-name all.etl
pktmon stop
pktmon etl2pcap all.etl --out all.pcapng
```
Syntax moved across builds; if the above is rejected try `pktmon start -c
--pkt-size 0 -f all.etl` and `pktmon pcapng all.etl -o all.pcapng`.

**(c) `netsh trace` + `etl2pcapng` — the one most likely to carry `epb_flags`.**
```
netsh trace start capture=yes report=no tracefile=C:\trace.etl maxsize=512
netsh trace stop
etl2pcapng.exe C:\trace.etl C:\trace.pcapng
```
`etl2pcapng` is a separate Microsoft tool (github.com/microsoft/etl2pcapng); it
is expected to write per-packet direction into `epb_flags`. **Unverified** —
confirm on arrival. If it does, this is the first real-world file that exercises
the direction path at all, and it validates defect 1 in §5.

### Single interface (for the third file)
```powershell
dumpcap -i 1 -w single.pcapng -a duration:30      # number from: dumpcap -D
```

---

## 4. What to run when the files arrive

Classify each file before drawing any conclusion:

```sh
capinfos FILE | grep -E 'encapsulation|Number of interfaces|Strict time order'
capinfos FILE | grep -A3 'Interface #'          # does if_description exist?

# per-packet evidence, in one pass
tshark -r FILE -T fields -e frame.number -e frame.interface_id \
  -e frame.interface_name -e frame.interface_description \
  -e frame.packet_flags_direction -e sll.ifindex -e sll.pkttype \
  -E separator='|' | head -10

# how many packets carry each thing (substitute each field)
tshark -r FILE -T fields -e frame.packet_flags_direction | grep -c .
```

The three questions to answer per file:
1. Is `if_name` a readable name, or a `\Device\NPF_{GUID}`?
2. Is `if_description` populated, and is it the friendly name?
3. Does `frame.packet_flags_direction` appear on any packet? Note the **exact
   string** — tshark prints hex (`0x00000002`), which is the whole of defect 1.

---

## 5. The two defects (unfixed; beta.9 carries both)

Both are upload-path only. PR #29 was native-capture work and touched neither.

**Defect 1 — a recorded direction is silently dropped.**
`backend/packet_parser.py`: `_PCAPNG_DIRECTION = {"1": "in", "2": "out"}`, looked
up in `_place_packet` with `.get(flag)` where `flag` is
`frame.packet_flags_direction`. tshark prints that field in **hex**, so the
lookup never matches and the "a recorded direction wins" path documented in
`docs/viewer.md` has **never once executed**. Fix: parse it — base 16 when
prefixed `0x`, mask the low two bits, 1 → in, 2 → out, 0 and empty → none.
Low practical impact today (nothing Wireshark writes carries the flags), but
it is small and unambiguously correct — and file (c) above may be the first
real file that needs it.

**Defect 2 — the mapping outranks recorded interface names.** `_place_packet`
consults `smap.place()` before the file's own `frame.interface_name`, so adding a
mapping to a real multi-interface upload replaces **341/341** recorded names with
the guess. Fix requires the guarded rule from §2 — **do not ship it unguarded.**

Useful nearby constants: `_SLL_DIRECTION` maps pkttype `0 in / 1 broadcast /
2 multicast / 3 other-host / 4 out`; `_COPY_WINDOW_SECONDS` is 1.0.

---

## 6. Proposed beta.10, smallest defensible scope

1. **Docs correction — the highest-value item.** `docs/viewer.md` currently says
   an uploaded Wireshark pcapng has "no interface of their own to show." That is
   false and operators are reading it now. Replace with the §1 matrix and the
   *Save As → pcap* footgun. Zero behavioral risk.
2. **Defect 1** (hex parse). Tiny, correct, no downside.
3. **Defect 2 — hold** until the Windows captures settle the precedence rule.

If beta.10 ends up as docs plus a one-line parse fix, decide whether it warrants
a version bump at all or folds into whatever else beta.10 carries.

**Deferred to beta.11+:** detecting IDBs on upload and telling the operator their
file already names its own interfaces (needs a new endpoint — feature work), and
the product question of whether the mapping should be relabelled as a *direction*
feature, since that is its durable value.

---

## 7. Closed — do not re-open

**Out-of-order timestamps are benign.** Multi-interface captures are not in
strict time order (`capinfos`: `Strict time order: False`; single-interface `any`
says `True`). Measured: 3 of 341 packets arrive before their predecessor,
backward jumps to **60 ms**, **100% at interface boundaries** — inherent to
separate per-interface ring buffers.

Hypothesised to break the beta.8 copy detection. **Tested and falsified.**
`_COPY_WINDOW_SECONDS` is 1.0 s against 60 ms of disorder, and every comparison
is a one-sided `when - state[0] <= window`: a backward jump makes the difference
*smaller*, so it errs toward matching, never toward missing a copy. Pruning is
one-sided the same way. No duration arithmetic exists in the copy path to go
negative.

Scope caveat: only `packet_parser.py`'s copy path was examined. Conversations
totals and the Sequence Diagram's ordering were **not** checked.

---

## 8. Reproducing the Linux baseline

No fixtures are committed. Regenerate:
```sh
python3 -m http.server 8765 --bind 127.0.0.1 &
dumpcap -i eth0 -i lo -w multi.pcapng -a duration:8 &   # = ticking two in the GUI
curl -s --noproxy '*' http://127.0.0.1:8765/ -o /dev/null
curl -s -m 5 https://api.github.com/ -o /dev/null
wait
editcap multi.pcapng saved.pcapng          # what Save As writes
editcap -F pcap multi.pcapng legacy.pcap   # the footgun: interfaces gone
tcpdump -i any -w td_any.pcap -c 60        # native path: cooked v2, both real
```
A file that *does* carry directions (nothing Wireshark produces):
`text2pcap -D -l 1 in.txt out.pcapng`, each packet prefixed `I` or `O`.

**Deterministic pcapng fixtures** need a small builder; it was written once and
is worth rebuilding. Layout, little-endian: SHB `0x0A0D0D0A` (magic
`0x1A2B3C4D`, version 1.0, section length -1); IDB `0x00000001` (linktype u16,
reserved u16, snaplen u32; option **2 = if_name**, option **3 = if_description**);
EPB `0x00000006` (interface_id, ts_high, ts_low, cap_len, orig_len, data;
option **2 = epb_flags**, direction in **bits 0–1**). Every block is padded to 4
bytes and carries its total length at both ends; options end with a zero
code/length pair. Default timestamp resolution is 1e-6 s.

---

## 9. Next step

Wait for the three Windows captures. Run §4 on each, answer the three questions,
then settle the §2 precedence rule and implement beta.10 per §6 — docs first,
since that is correct regardless of what the captures show.
