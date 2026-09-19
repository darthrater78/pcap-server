# Design note: capturing on a Proxmox VE node

*Status: investigation and proposal, not built. Written 2026-09-19 against
1.1.0-beta.9, in answer to "even though it's Debian, is there nuance that
would prevent capturing without risking the VMs or the environment".*

Nothing here has been run against a real Proxmox node from this session.
Claims are separated accordingly: the body states what follows from how
Proxmox is built and from this repository's own code, and
[What still needs a real node](#what-still-needs-a-real-node) lists what must
be confirmed on hardware before any of it is documented as fact for operators.

## The short answer

**Proxmox works today, and the Debian part is not the problem.** tcpdump,
`/sys/class/net`, `/tmp`, `sudo`, SIGINT and `/proc/sys/kernel/random/boot_id`
are all exactly as this app expects. A PVE node is a target it already
understands.

The nuance is not in the platform. It is that **a hypervisor is the one kind
of target where an ordinary, correct capture can damage the environment
around it** — and it does so through three routes that have nothing to do with
Debian:

1. **Filling the node's root filesystem**, which is where `/tmp` lives and
   where the cluster configuration database lives with it. This is the most
   likely way to cause real harm, and it is entirely mundane.
2. **Disturbing the cluster network**, where the failure mode is not a dropped
   packet but HA fencing rebooting the node and every VM on it.
3. **Capturing far more than was intended** — on a hypervisor, the wrong
   interface choice is not noise, it is every other tenant's traffic.

None of the three is a reason not to capture on Proxmox. All three are reasons
the *defaults* matter more here than on an ordinary host.

## Why a PVE node is not just a Debian box

The interface list is the whole difference, and it is worth being concrete,
because "capture on `vmbr0`" and "capture on `tap101i0`" answer different
questions and carry different risk.

| Interface | What it is | What a capture there sees |
| --- | --- | --- |
| `enp1s0`, `eno1` | Physical NIC | Everything leaving the node, post-bridge |
| `bond0` | LACP / active-backup bond | As above, across members |
| `vmbr0` | Linux bridge | Traffic crossing the bridge — all guests on it, plus the node's own |
| `vmbr0.100` | VLAN interface on a bridge | One VLAN's traffic |
| `tap<VMID>i<N>` | One QEMU VM's virtual NIC | **Exactly one VM, and nothing else** |
| `veth<CTID>i<N>` | One LXC container's NIC | Exactly one container |
| `fwbr<VMID>i<N>`, `fwpr…`, `fwln…` | Firewall bridge pair, present when the PVE firewall is enabled for that guest | Traffic at a specific point in the firewall chain |
| `vxlan…`, OVS bridges | SDN / Open vSwitch | See [Where a capture silently sees nothing](#where-a-capture-silently-sees-nothing) |

Two consequences follow directly:

**`tap<VMID>i<N>` is almost always the right answer.** One VM, no other
tenant's traffic, no duplication, and no promiscuous mode on anything that
carries the cluster. If an operator wants "this VM's traffic", the tap is both
the narrowest and the safest choice. The UI knowing this — labelling a tap with
its VMID — would be the single most useful Proxmox-specific feature.

**The firewall bridges determine whether you see pre- or post-firewall
traffic.** With the PVE firewall enabled, the guest's packets traverse
`tap → fwbr → fwln/fwpr → vmbr`. Capturing on the tap shows what the guest
sent, *before* the firewall had its say; capturing further along shows what
survived. "The packet isn't there" and "the packet was dropped by the
firewall" are different findings, and which interface you chose decides which
one you can tell.

### `any` is a bad default on a hypervisor

On an ordinary host, `any` is the sensible default and this app uses it. On a
PVE node it is actively poor:

- **Every packet is recorded several times.** A guest packet to the outside
  world appears on the tap, the firewall bridge pair, the bridge, the bond and
  the physical NIC. beta.8 taught this app to recognise repeat sightings
  rather than call them retransmissions, so the *analysis* now survives it —
  but the capture is still several times the size it needed to be, which feeds
  straight into risk 1 below.
- **It captures every guest.** On a node hosting unrelated workloads, `any` is
  a capture of all of them. That is a disclosure decision, and it should be
  made on purpose rather than inherited from a default.
- **It loses the Ethernet header.** `any` is LINUX_SLL2 cooked capture, which
  is exactly the layer that matters when the question is "which bridge port
  did this come in on". `capture.py` already works around this for filters;
  the information loss remains.

## The three ways a capture can hurt the environment

### 1. Filling the root filesystem — the likely one

The capture is staged on the target at `/tmp/pcap_<uuid>.pcap`
(`capture.py:398`) and fetched afterwards. On a PVE node `/tmp` is on the root
LVM volume, which is typically modest and is **shared with things that matter
a great deal**:

- **`/var/lib/pve-cluster`**, the SQLite database behind `pmxcfs` — the FUSE
  filesystem mounted at `/etc/pve` that holds every VM's configuration. A full
  root filesystem is how cluster configuration writes start failing.
- Guest logs, task logs, and on many installs the ISO and backup directories.

A busy 10GbE bridge can produce gigabytes in seconds, and an unbounded
capture on `vmbr0` is a straightforward way to fill a root volume. **This is
the single most likely way for a capture to damage a Proxmox environment, and
it involves nothing exotic at all.**

What this app already does about it: `max_capture_packets` caps the packet
count (250,000 by default as of beta.9), and `snap_len` bounds per-packet size.
Those together bound the file — but only if the operator sets a count, and the
bound is in packets, not bytes.

What is missing is a check the operator does not have to think about:
**read the free space on the staging filesystem during the prereq check, and
refuse or warn when the worst-case capture size does not comfortably fit.**
The prereq probe already reads `/tmp` writability (`TMPWRITE`); free space is
the same probe, one command further, and it turns the most likely failure into
a message before the capture instead of an incident after it.

> If `/tmp` is on tmpfs — not the PVE default, but a change some operators
> make — the same capture consumes RAM instead of disk, and on a node whose
> memory is committed to guests the consequence is the OOM killer choosing
> among them. Both branches are bad; the check above covers both, because it
> asks the filesystem rather than assuming which one it is.

### 2. Disturbing the cluster network — the severe one

libpcap puts an interface into promiscuous mode by default. On a PVE node this
deserves thought rather than alarm:

- On a **tap or veth**, promiscuous mode is uneventful and does not affect the
  guest.
- On a **physical NIC or bond member**, enabling promiscuous mode is usually
  harmless, but with some drivers and some SR-IOV configurations it can
  provoke a brief driver reinitialisation or link flap.

On a standalone node, a momentary link flap is a nuisance. On a **cluster
node**, it is not: **corosync** is latency-sensitive, and a node that loses
quorum while **HA** is configured will self-fence — a watchdog reboot, taking
every VM on it down and triggering HA recovery elsewhere. That is the worst
realistic outcome in this note, and the chain from "captured on the wrong
interface" to it is short.

Three things follow:

- **`-p` (no promiscuous mode) should be available**, and should be the
  default for any capture whose purpose is the node's own traffic. tcpdump
  supports it; this app does not currently offer it.
- **Capturing the corosync ring interface should warn.** Not refuse — a
  corosync problem is a legitimate thing to capture — but say what the risk is,
  once, where the operator will see it.
- **The physical/bond interfaces should be visibly distinguished from the
  taps** in the interface list, so the safe choice is also the obvious one.

Sustained load is the quieter version of the same risk: a capture writing
hundreds of megabytes a second competes for CPU and disk with the guests, and
on a converged setup with **Ceph** it competes with the storage network the
guests are running from. A capture filter is the mitigation, and
[filters.md](../filters.md) already argues for one on its own merits.

### 3. Interface churn, and a capture that mislabels a tenant

`tap` and `veth` interfaces are created when a guest starts and destroyed when
it stops or migrates. Two consequences:

- **A stored interface list goes stale immediately.** A capture on `tap101i0`
  fails once VM 101 has migrated, and the failure is at capture start, which is
  the good case.
- **Interface indexes are reused.** This app records the index → name table at
  capture time (`ssh_manager.py:interface_indexes`) because an `any` capture
  identifies interfaces by index only. On a node with guest churn, an index
  recorded for one guest's tap can belong to a **different guest's tap** by the
  time the table is read — so the viewer would label another tenant's traffic
  with the wrong guest. This is a correctness bug and a disclosure bug at once,
  and it is specific to hosts with ephemeral interfaces, which is to say
  hypervisors and container hosts.

The mitigation is to re-read the table at the *end* of the capture as well as
the start, and to treat a mismatch as "do not label these by name" rather than
picking one. Cheap, and it fails toward honesty.

## Where a capture silently sees nothing

The worst kind of nuance: the capture succeeds, the file is valid, and the
traffic being looked for was never capturable. Each of these should produce a
warning at capture start, because an operator who does not know will conclude
the traffic does not exist.

- **PCI passthrough and SR-IOV VFs.** The guest owns the device; its traffic
  never crosses the host's network stack. **It cannot be captured from the host
  at all** — the capture has to happen inside the guest, or on the switch.
- **Open vSwitch bridges.** An OVS bridge is not an ordinary Linux bridge, and
  attaching to its interface with tcpdump does not reliably see the traffic
  crossing it; that is what `ovs-tcpdump` and its mirror port exist for. A
  capture on an OVS bridge may return almost nothing.
- **SDN and VXLAN.** A capture on the underlay sees encapsulated frames — real
  traffic, but not the guest's packets as the guest sees them. tshark decodes
  VXLAN, so this is interpretable rather than lost, but it surprises people.
- **A VLAN-aware bridge** shows tagged frames while the tap shows untagged
  ones. The same traffic, two different-looking captures, and a filter written
  for one does not match the other.

## Security

A Proxmox node changes the security calculus in ways that are about scope, not
mechanism.

**The blast radius of the capture.** On an ordinary host, a capture exposes
that host's traffic. On a hypervisor, a capture on `vmbr0` or `any` exposes
**every guest's traffic**, including guests belonging to workloads the operator
running the capture may have no business reading. This app already encrypts
captures at rest and gates downloads behind HTTPS, so the handling is sound —
the issue is that the *scope* of what gets handled is far larger than the
operator may realise. The remedy is the default, not the crypto: a tap, not a
bridge.

**The blast radius of the SSH account.** Proxmox pushes operators toward
`root@pam`, and SSH-ing to a PVE node as root is normal practice. But root on a
PVE node is control of every VM on it, and pcap-server holds that key
persistently. [target-hosts.md](../target-hosts.md) already argues for a
capability over sudo and for scoping sudo to one binary; **on a hypervisor that
argument is much stronger**, and the Proxmox guidance should make the
recommendation explicit:

- A dedicated unprivileged SSH user, and
- `setcap cap_net_raw,cap_net_admin=eip` on tcpdump — which works on Debian and
  so on PVE — so no sudo at all, and
- **not** `root@pam`, and **not** an unscoped `NOPASSWD: ALL`.

**Self-capture, which the boot id check gets partly right.** This matters
whenever pcap-server runs *on* the node it is pointed at:

- pcap-server in an **LXC container or Docker on the PVE node itself** shares
  the node's kernel, so `/proc/sys/kernel/random/boot_id` matches and
  `localnet.py:describe_if_same_kernel` catches it. Correct today, whatever
  address was used.
- pcap-server in a **VM on that same node** has its own kernel. The boot id
  differs, so the kernel check cannot fire, and a capture on `vmbr0` would
  record pcap-server's own web session — which over plain HTTP is the exact
  credential-disclosure scenario `localnet.py` was written to prevent. Only the
  address checks stand here, and they cannot see a LAN address they were never
  told about.

That second case is a genuine residual gap, it is more likely on Proxmox than
anywhere else (a management VM on the hypervisor it manages is a common
arrangement), and it should be documented in
[security.md](../security.md) even though nothing about it is a defect in the
existing check.

**Debian's tcpdump drops privileges to a `tcpdump` user** via `-Z`, which is
why `_remove_capture_file` handles a file the login user does not own. That is
already correct on PVE. Debian also ships an **AppArmor profile for tcpdump**,
and whether it constrains writes to the staging path on a PVE node is one of
the things below that needs a real node to settle — if it does, it would
present as a capture that fails at start with a permission error on a host
where every other check passed.

## What would actually be built

None of this is required to capture on Proxmox today. It is what would make
Proxmox captures safe by default rather than safe by operator diligence, and
it is ordered by how much harm it prevents per unit of work:

1. **Free-space check on the staging filesystem**, in the prereq check and
   again at capture start. Addresses risk 1, which is the likely one. Not
   Proxmox-specific — every target benefits — which is an argument for doing it
   first.
2. **Recognise a PVE node and label its interfaces.** `vmbr0` as a bridge,
   `tap101i0` as "VM 101", `veth200i0` as "CT 200", `fwbr…` as a firewall
   bridge, physical and bond members marked as such. Reading guest names needs
   `/etc/pve` access, so the first version should label from the interface name
   alone, which needs no privilege and cannot be wrong about what it does not
   read.
3. **Offer `-p`**, and prefer it wherever promiscuous mode is not needed.
4. **Warn on the choices that carry real risk**: a physical or bond interface
   on a cluster node, `any` on a hypervisor, and the cases under
   [Where a capture silently sees nothing](#where-a-capture-silently-sees-nothing).
5. **Re-read the ifindex table at capture end** and decline to label by name
   when it has changed.
6. **A Proxmox section in [target-hosts.md](../target-hosts.md)**: the
   unprivileged-user-plus-setcap recipe, the interface map, the tap-not-bridge
   default, and the self-capture case above.

## An operator checklist, until then

Everything here works with the app as it stands:

- **Capture the guest's tap**, not `vmbr0` and not `any`, whenever the question
  is about one guest.
- **Always set a packet count or a duration**, and a snap length when only
  headers are wanted. This is what keeps the node's root filesystem safe.
- **Check free space on `/` before capturing**, and remember the staged file
  lives there for the length of the capture plus the transfer.
- **Use a capture filter.** It bounds the file and it bounds what gets
  recorded, which on a hypervisor means what gets disclosed.
- **On a cluster node with HA**, treat a capture on a physical NIC or bond
  member as a change worth scheduling, not a diagnostic to run casually.
- **Do not point pcap-server at a node it is running on**, in a VM or
  otherwise. The kernel check catches the container case; it cannot catch the
  VM case.
- **Prefer an unprivileged user with `setcap` over `root@pam`.**

## What still needs a real node

- **`/tmp` size and layout** on a default PVE install, and whether the default
  is ever tmpfs on current releases.
- **Whether Debian's AppArmor profile for tcpdump** constrains writing the
  staged pcap to `/tmp` on a PVE node, and if so, what the failure looks like.
- **Whether `tcpdump -D` or `/sys/class/net`** reports OVS internal ports and
  SDN interfaces in a form worth listing, and what a capture on an OVS bridge
  actually returns.
- **Promiscuous-mode behaviour on the physical NICs that matter** — how real
  the link-flap risk is per driver, since the severity of risk 2 is high but
  its likelihood is the part that is unclear.
- **Whether guest names can be read** without privilege, for the interface
  labels, or whether the VMID alone is the honest limit.
- **The ifindex-reuse window in practice** on a node with guest churn, to
  confirm the mislabelling above is reachable rather than theoretical.
