# Design note: Windows targets

*Status: proposal, not built. Written 2026-09-19 against 1.1.0-beta.9. Expands
the one-paragraph roadmap entry in
[architecture.md](../architecture.md#roadmap) into something buildable.*

Everything below is derived from reading this repository. Nothing in it has
been tried against a real Windows host from this session, and the claims that
need a real host to settle are collected under
[Open questions](#open-questions) rather than stated as fact in the body.

## The short version

The SSH half carries over almost unchanged. The target half does not, and the
reason is not that Windows is awkward — it is that **three of the security
controls this app relies on are POSIX-shaped, and each one fails quietly
rather than loudly when pointed at Windows.** Argument quoting, remote path
validation, and "is that really the binary I think it is" are all written for
a POSIX target today, and all three would still *appear* to work on Windows
while protecting nothing.

So the build order below puts those three first, before any capture runs at
all.

## What already carries over

- **The transport.** asyncssh connects to the Windows OpenSSH server like any
  other host, and its SFTP client fetches from it. Host key pinning, the key
  store and the sealed-on-arrival download path
  (`ssh_manager.py:_download`) are all platform-blind.
- **Everything after the file lands.** `dumpcap` writes pcapng, and pcapng is
  already a first-class input: the upload path recognises its magic
  (`capture.py:_CAPTURE_MAGIC`), tshark reads it, capinfos counts it. The
  parser, the viewer, the diagrams, sanitising and anonymising never learn
  where the file came from.
- **Encryption at rest, retention, and the permission model.** Untouched.

## What does not carry over

Each of these is a POSIX assumption sitting in a specific place:

| Assumption | Where | What Windows needs |
| --- | --- | --- |
| Interfaces are `ls /sys/class/net` | `ssh_manager.py:list_interfaces` | `dumpcap -D`, or `Get-NetAdapter` |
| Interface index → name from sysfs | `ssh_manager.py:_IFINDEX_SCRIPT` | Not needed — see [Multiple interfaces](#multiple-interfaces-are-easier-not-harder) |
| The probe is a `sh` script | `ssh_manager.py:_PREREQ_SCRIPT` | A PowerShell counterpart |
| Staging is `/tmp/pcap_<uuid>.pcap` | `capture.py:398` | `%TEMP%`, and a path validator that understands Windows paths |
| The capture is `tcpdump -v -w` | `capture.py:build_command_args` | `dumpcap -w -i -f -c -a` |
| Progress is `Got N` on stderr | `capture.py:_GOT_PACKETS` | Different, and possibly absent |
| Stop is `SIGINT` | `ssh_manager.py:stop_tcpdump` | Windows has no signals |
| Elevation is `sudo -n` | `ssh_manager.py:run_tcpdump` | No equivalent; see [Privilege](#privilege-there-is-no-sudo) |
| Cleanup is `rm` in a sticky `/tmp` | `ssh_manager.py:_remove_capture_file` | `del`, and per-user `%TEMP%` ACLs |
| Self-capture is caught by `boot_id` | `localnet.py` | Structurally moot; see [Self-capture](#self-capture-gets-simpler-with-one-residual-gap) |

## The capture tool: dumpcap, not pktmon

**`dumpcap.exe`**, shipped with Wireshark over the Npcap driver. It takes an
interface, a BPF capture filter, a packet count, a duration and a snap length,
and writes pcapng — which is close enough to the tcpdump argument set that
`build_command_args` keeps its shape.

`pktmon` is built in and needs nothing installed, which is genuinely
attractive, but it has **no BPF filter** and writes ETL that must be converted
with `pktmon etl2pcap` before tshark can open it. Losing the capture filter is
not a cosmetic loss here: the filter is how an operator keeps a capture from
recording credentials it did not need, and it is what
[docs/filters.md](../filters.md) is built around. Dropping it on Windows would
make Windows captures categorically broader than Linux ones.

**Never tshark on the target, only dumpcap.** tshark has `-z` and a Lua
engine; dumpcap has neither. The existing
`models.py:assert_no_forbidden_flags` exists precisely to keep a `-z` away
from a privileged tcpdump, and choosing dumpcap means the Windows counterpart
of that list is short by construction rather than by vigilance. That is a real
security argument for dumpcap and it should be written down as one.

### Npcap is a prerequisite with strings

- It is a separate install from Wireshark's bundle in some configurations, and
  the prereq check must report its absence the way the Linux check reports a
  missing tcpdump.
- Its installer has a **"restrict Npcap driver's access to Administrators
  only"** option. That single checkbox is the Windows equivalent of the
  `setcap` / `sudo` choice in [target-hosts.md](../target-hosts.md), and the
  prereq check should read and report it, because it decides whether an
  unprivileged SSH account can capture at all.
- Npcap's licence is free for personal use and has conditions on commercial
  redistribution. pcap-server would not redistribute it — the operator
  installs it — but the docs should say so plainly so nobody assumes we ship
  it.

## Privilege: there is no sudo

[target-hosts.md](../target-hosts.md) offers two routes on Linux: a file
capability (preferred), or passwordless sudo scoped to one binary. Neither
exists on Windows.

What exists instead:

1. **Install Npcap without the administrators-only restriction**, and capture
   as an ordinary account. This is the closest analogue to `setcap`, and it
   should be the documented preference for the same reason: the privilege sits
   on the capture driver, not on the SSH account.
2. **Use an SSH account that is already a local administrator.** Simpler, and
   much larger blast radius — an administrator SSH account on Windows is
   administrative for everything, not just capture. This should be documented
   as the fallback, with that cost stated.

There is no third option worth building. `runas` wants an interactive password
prompt, and the newer `sudo` on Windows 11 / Server 2025 is not a
`sudo -n`-shaped thing. **`use_sudo` should be inert for a Windows server,
and the UI should say so** rather than offering a checkbox that does nothing.

## Multiple interfaces are easier, not harder

On Linux, capturing several interfaces at once is a workaround: capture on
`any` and narrow by `ifindex` in the BPF program, which is why
`MULTI_INTERFACE_LIBPCAP` and `capture.py:ifindex_clause` exist and why
libpcap 1.10 is a prerequisite for it.

**dumpcap takes `-i` more than once natively**, writing one pcapng with an
interface description block per source. That is strictly better: no ifindex
clause, no libpcap floor, and `frame.interface_name` is populated from the
file itself rather than from a table we recorded separately and hope is still
accurate.

The other side of that coin: **there is no `any` device on Windows.**
`ANY_INTERFACE` is the default in `CaptureRequest`, so a Windows server needs
a different default — most likely "every interface dumpcap reports", expressed
as repeated `-i`, or a required explicit choice. This is a UI decision as much
as a backend one and it should be made deliberately, not defaulted into.

## The three controls that need rewriting, not porting

This is the part that matters most, and the part most likely to be got wrong
by treating Windows as "Linux with different commands".

### 1. Shell quoting

`ssh_manager.py:_shell_quote` is POSIX single-quote escaping. Windows OpenSSH
runs an SSH exec request through its configured default shell, which is
`cmd.exe` unless the administrator changed it to PowerShell. **POSIX quoting
does not neutralise `cmd.exe`** — `&`, `|`, `^` and `%VAR%` all survive it, and
PowerShell adds its own set. Reusing `_shell_quote` against a Windows target
would look correct in the code and be an injection surface in practice.

The right answer is not a better Windows quoter. It is to **keep operator
input off the command line entirely**:

- The BPF filter is the one genuinely free-form operator value, and it is the
  one that must not be interpolated into a shell string. `dumpcap -f` can read
  a filter from a file; write the filter to a file over SFTP and pass the
  path. Failing that, `-EncodedCommand` with a base64 payload built in Python
  sidesteps shell parsing rather than trying to survive it.
- Everything else (interface, counts, durations, snap length) is already
  validated to an integer or an allowlist and should stay that way.
- `models.py:BPF_FORBIDDEN_CHARS` (`;$\`\\`) is a POSIX-shaped denylist. Note
  that **`\` is already forbidden**, which is convenient here, but the list
  needs a Windows review on its own terms — a denylist tuned for `sh` is not
  evidence about `cmd.exe`.

### 2. Remote path validation

`_SAFE_PATH` requires a leading `/` and `PurePosixPath(...).name` checks the
binary. Against a Windows path both are simply wrong, and a naive relaxation
opens genuinely new categories:

- **UNC paths** (`\\attacker\share\...`) — a staging path that resolves off
  the machine entirely. This is the one to reject hardest: it turns "where do
  we stage the pcap" into "where do we send the pcap".
- **Alternate data streams** (`file.pcap:hidden`).
- **Reserved device names** (`CON`, `NUL`, `COM1`, `LPT1`), which are reserved
  in every directory, not just the root.
- **Trailing dots and spaces**, silently stripped by the filesystem, so the
  path validated is not the path opened.
- **8.3 short names** and case-insensitivity, which defeat exact-string
  comparison against an allowlist.

The staging path should be **constructed by pcap-server, never accepted from
the host or the operator**, and validated as "a plain filename under a
directory we chose". The Linux code already effectively does this
(`capture.py:398` builds the path from a UUID); the point is that the Windows
validator must be written to that standard deliberately, because the
consequences of drifting from it are worse.

### 3. Identifying the binary

On Linux, `_is_safe_tcpdump_path` requires an absolute path with no
metacharacters whose basename is exactly `tcpdump`. The equivalent check on a
case-insensitive filesystem with short names is weaker on its own.

Windows offers something Linux does not, though: **`Get-AuthenticodeSignature`
can confirm the binary is signed by the Wireshark Foundation.** Combined with
an allowlist of expected install paths and a `--version` check, that is a
stronger identification than the Linux side manages. Worth doing, and worth
treating a valid signature as a reportable `ok` in the prereq checklist rather
than a silent pass.

## Self-capture gets simpler, with one residual gap

`localnet.py` explains that the strong self-capture check is `boot_id`:
pcap-server runs in a Linux container, so a target reporting the same kernel
boot id *is* this machine. A Windows target can never share a kernel with a
Linux container, so **the check it replaces cannot fire, and the risk it
guards against structurally cannot exist** in that form. The module already
handles this correctly — a host that reports no boot id has proved nothing
either way, and the address checks still apply. No change needed; it just
needs saying so the absence is understood as designed rather than missed.

**The residual gap**, which exists today and is not created by Windows
support: if pcap-server runs under Docker Desktop on Windows, the container's
boot id belongs to the WSL2 Linux VM, not to Windows. A capture aimed at that
Windows host would record pcap-server's own traffic and the kernel check would
not catch it. Only the address checks would, and only when the host is
reachable by a name they recognise. Worth a note in
[security.md](../security.md) regardless of whether Windows targets get built.

## Stopping a capture

There is no SIGINT. `stop_tcpdump`'s whole escalation ladder — SSH signal,
then a signal command on the target, then kill — has no direct Windows
equivalent, and a hard `taskkill` risks a truncated final pcapng block.

The plan that does not depend on resolving that:

- **Always set an autostop.** `dumpcap -a duration:N` (and `-c N`) means every
  capture ends cleanly by itself even if Stop never works. On Linux the
  duration is optional and enforced by `timeout(1)`; on Windows it should be
  the primary mechanism, not the backstop.
- **For an explicit Stop**, `taskkill /PID` is the floor. Whether that leaves
  a readable file, and whether dumpcap's Windows clean-stop mechanism can be
  driven over SSH, are [open questions](#open-questions) — but the autostop
  means the answer changes how well Stop works, not whether captures are
  safe.

## The shape of the change

**A target-platform adapter, chosen per server, never guessed.** The
architecture note already says "chosen per server rather than guessed" and
that is the right call — a probe that guesses wrong picks the wrong quoting
rules, and quoting is exactly where guessing wrong is dangerous.

The adapter's surface is small, and it is the set of things the table above
listed:

    list_interfaces()      probe_script() / parse_probe()
    build_command_args()   stage_path()
    stop()                 remove_file()
    quote() / no_shell_path()

`SSHManager` keeps the transport and calls into the adapter for anything that
touches the target's OS. The existing Linux behaviour moves behind the adapter
**unchanged** — this refactor must not be the commit that also changes what
Linux captures do.

### Data model

- `ServerAuth` gains a platform field, set by the operator when adding the
  server, defaulting to Linux. Existing rows migrate to Linux.
- `tcpdump_path` is Linux-shaped in both name and validator
  (`models.py:482` requires the basename be `tcpdump`). It needs generalising
  to a capture-binary path whose validation is delegated to the adapter.
- `libpcap_version` has no meaning on Windows; the multi-interface check it
  feeds is a libpcap-1.10 question that does not apply. The prereq checklist
  needs to render per platform, not show a blank row.

## Testing

Real Windows coverage in CI is the hard part, and it should be treated as hard
rather than assumed away: Npcap's silent-install path is not freely available,
so a `windows-latest` job that actually captures packets may not be buildable.

The plan that works regardless:

1. **Unit tests on the parsers and builders**, against recorded fixtures of
   real `dumpcap -D`, `dumpcap --version` and probe output. This is where the
   Linux side already gets most of its value, and it needs no Windows host.
2. **Adversarial tests on the three controls above** — UNC paths, device
   names, trailing dots, ADS, `cmd.exe` metacharacters in a filter — as
   explicit refusal tests. These are the tests that justify the whole
   ordering of this plan.
3. **A documented manual verification checklist** for a real host, kept in the
   repo, because some of this genuinely cannot be automated and pretending
   otherwise is worse than admitting it.

## Build order

1. **The adapter seam**, with Linux behind it and behaviour identical. No
   Windows code. This should be provably a no-op.
2. **The three controls**: Windows path validation, no-shell argument passing,
   and binary identification — with their refusal tests, before anything can
   run a capture.
3. **Connect and probe.** Add a Windows server, run the prereq check, see a
   checklist. No capture yet. Useful on its own, and it is what surfaces the
   Npcap and privilege questions to the operator.
4. **List interfaces and capture**, single interface, mandatory autostop.
5. **Multiple interfaces** (repeated `-i`), Stop, and progress reporting —
   each of which is an improvement on a working capture rather than a
   prerequisite for one.

## Open questions

These need a real Windows host. They are listed so that nobody mistakes them
for settled:

- **Does `dumpcap` report a running packet count on stderr** in a form worth
  parsing, and is it parseable line-by-line the way `Got N` is? If not, the
  fallback is polling the staged file's size, or accepting no live count.
- **Can dumpcap be stopped cleanly over SSH?** Wireshark drives a clean stop
  on Windows by a mechanism that may not be available to a remote exec. If
  not: does a `taskkill`ed pcapng still open in tshark, and with what loss?
- **Is an administrator's SSH session actually elevated?** Network logon token
  filtering (`LocalAccountTokenFilterPolicy`) affects this, and the answer
  decides whether route 2 under [Privilege](#privilege-there-is-no-sudo) works
  at all for local accounts.
- **What is the default shell** on the hosts we care about, and can the probe
  detect it reliably before it needs to quote anything? If it cannot, the
  no-shell approach is not an optimisation — it is the only safe option.
- **Output encoding.** PowerShell emits CRLF and may emit UTF-16 or a BOM;
  `cmd.exe` has a code page. The probe should force UTF-8 and emit plain
  `KEY=VALUE` lines, and `-NoProfile -NonInteractive` is mandatory so a user's
  profile script cannot pollute what we parse.
- **Npcap install detection**, including the administrators-only setting, in a
  form the prereq check can read without elevation.
