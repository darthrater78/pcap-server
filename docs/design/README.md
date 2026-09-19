# Design notes

Proposals and investigations, written before anything is built. A note here
describes a thing that does **not** exist yet — read
[architecture.md](../architecture.md) for what does.

Each note says up front what it is, when it was written and against which
version, and separates what follows from the code as it stands from what still
needs verifying on real hardware. A note is a record of thinking, not a
commitment to build, and one that gets built is replaced by the real
documentation rather than quietly left to go stale.

| Note | What it covers |
| --- | --- |
| [compare-captures.md](compare-captures.md) | Opening two captures side by side to see what happened between two points |
| [windows-targets.md](windows-targets.md) | Capturing from Windows hosts: `dumpcap` over Npcap, and the three POSIX-shaped security controls that need rewriting rather than porting |
| [proxmox-targets.md](proxmox-targets.md) | Capturing on a Proxmox VE node: which interface answers which question, and the three ways a correct capture can still harm the environment |
