# Reading a capture

*Part of the [pcap-server](../README.md) documentation.*

**View** on a finished capture opens it in the packet viewer: a Wireshark-style
list on top, the decoded protocol tree and hex dump below, and a display-filter
box across the top. Display filters themselves — both languages, and building
one by right-clicking — are in [filters.md](filters.md).

## Captures open as tabs

Each capture you open gets its own tab on the bar at the top, next to Servers,
Capture and Admin. Open two and you can click between them — comparing a
capture taken before a change with one taken after is what the packet list is
usually for, and it should not mean going back to the list each time. Close a
tab with the **×** on it; the capture itself is untouched, and it opens again
from the Capture tab.

There is no standing **Viewer** tab. It led to an empty panel for most of a
session, and a tab that is usually empty is one people learn not to press. The
Viewer exists while something is open in it and not otherwise.

Each tab says which capture it holds. Inside the panel, the line above the
filter box names the **server, the interface and the capture filter** the
packets are coming from — which is the question a packet table cannot answer,
and matters most when a filter narrower than you remember looks exactly like a
quiet network.

## Opening a pcap from somewhere else

**Upload a pcap**, beside **Start capture** on the Capture tab, opens a small
panel for a `.pcap` or `.pcapng` recorded elsewhere — Wireshark on a laptop, a
tcpdump on a box this server cannot reach. Choose the file and press
**Upload**; the result (the packet count, or why it was refused) stays in the
panel, and the capture appears in the list below.

An upload is stored exactly as a capture taken here is: encrypted with the same
key, under a name the server generates (the file's own name is only its label),
and read by the same viewer — filters, saved views, sanitizing, download and
delete all work on it unchanged. It is marked **upload** in the list, and the
line above the filter box reads *uploaded pcap* instead of naming a server,
interface and capture filter, because this server recorded none of those.

A file is refused if it is not a pcap or pcapng, if tshark cannot read it, or
if it is larger than **Max uploaded capture size (MB)** in Admin → Settings
(512 by default). Uploads need HTTPS, like every other change, and are refused
while encryption is locked in passphrase mode — unlock first.

## Choosing the columns

The packet list starts on the columns Wireshark opens with — number, time,
source, destination, protocol, length and the Info summary — and none of them
are fixed. **Drag a heading** to move it, or **right-click one** to hide it,
nudge it left or right, or open the **Columns** dialog (also on the toolbar).

Adding a column is the useful half. Any field tshark knows can be one, which is
most of what Wireshark dissects: `tcp.window_size` beside every packet while
chasing a stall, `dns.qry.name` while reading a resolver's traffic,
`http.host`, `ip.ttl`, `vlan.id`. Two ways in:

- **Right-click a field in the packet detail** below the list and choose
  **Apply as Column** — the same gesture as in Wireshark, and the quickest,
  because the field is already in front of you.
- **The Columns dialog**, which lists common fields by name and takes any other
  as typed. A name this server's tshark does not recognise is refused there and
  then, rather than becoming a column that is silently empty on every packet.

**Drag a heading's right edge** to make that column wider or narrower. The
width is kept in this browser, and a double-click on the edge puts it back.
Past the window's width the list scrolls sideways.

**Go to #** on the toolbar (or **Ctrl+G**, as in Wireshark) jumps to a packet
by number. It scrolls the list to that packet and opens it. A packet the list
does not hold, because it is filtered out or past the rows loaded, still opens
below, with a note saying why it is not highlighted.

Columns can be renamed, and the arrangement is **saved to your account** — not
to the browser — so it is the same list on every capture and on whatever you
sign in from next. **Reset to default columns** in the dialog puts it back.

An added column is fetched on the same pass that draws the list, so it costs no
extra round trip, and right-clicking one filters on the field it came from
rather than on a guess made from the value.

Timestamps can be relative, epoch, delta, the server's UTC, or your own time
zone.

## Which interface a packet crossed

A capture on `any` has an **Interface** column: the interface each packet went
through and which way — `eth0 out`, `docker0 in`, `bcast` for broadcast. The
file itself only numbers interfaces, so pcap-server reads the host's names when
the capture starts and again when it ends. Right-click a cell for **Apply as
filter** on `sll.ifindex`, the same menu every other column offers. An
interface that existed only in the middle of a capture shows as `#3`, and an
older tcpdump that writes the first cooked format records no interface at all,
so the column shows just the direction. Captures on a named interface have no
such column.

**Several interfaces at once.** On the Capture tab, **Pick several** under
Interface lists the server's interfaces as checkboxes. Tick two or more and
the capture runs on `any`, limited to those interfaces by index: one tcpdump
and one file, with the Interface column above. The names are looked up on the
server as the capture starts. The capture list, the viewer's header and the
diagrams show the interfaces by name (`eth0, wlan0`), with the capture filter
shown without the index clause in front of it. This uses tcpdump's `ifindex`
filter, which needs libpcap 1.10 or later on the server. **Check
prerequisites** reads the version (see
[Target hosts](target-hosts.md#checking-a-server-before-you-capture)). On a
server that has not been checked, or has an older libpcap, the list is
disabled and says why. Ticking just one is the same as picking it from the
list.

`any` cannot put an interface into promiscuous mode, so a capture on several
interfaces (or on `any`) sees only what the host itself sends, receives,
routes or bridges. For a mirror (SPAN) port, capture that one interface on its
own.

**The same packet on two interfaces.** On a box that routes or bridges, a
capture of both sides sees each forwarded packet twice: in on one interface,
out on the other. tshark's TCP analysis knows nothing of interfaces, so it
calls the second sighting a retransmission (data) or a duplicate ACK (a bare
ACK). pcap-server finds these repeat sightings — same addresses, IP ID,
length, ports, TCP sequence, ack, flags and checksum, on a different
interface within a second — and marks them in the packet list (**again: #N**,
muted unless its own link shows a problem, below). Through NAT the addresses
change, so it matches on IP ID, length and TCP sequence and ack with the
untranslated address the same (**NAT of #N**; IPv4 only, and outside TCP only
with a non-zero IP ID). NAT copies keep tshark's flags, which hold for that
side, because tshark treats each side as its own conversation.

Each link that carries unchanged copies is also read on its own, the way a
capture of just that link would be, and a copy's Info is what tshark says there.
On the link a packet leaves by, that is the only place a segment the box
dropped shows up: the next one reads *previous segment not captured*.

The Traffic and Sequence Diagrams draw and count each packet once. Problems
count distinct events. A duplicate ACK seen arriving and leaving is one; a
drop only the outgoing link shows is one of its own. Conversations count an
unchanged copy once, and a NATed copy under its own pair of addresses. Pick an
interface in the Traffic Diagram to see everything that crossed it, as that
link saw it. The *Seen on 2+ interfaces* row in the stats pane says how many
repeats there were. Up to 8 links are read on their own; past that, a copy
takes its first sighting's verdict.

**The name does not survive a download.** The mapping lives only in
pcap-server's own database; the `.pcap` file itself — classic pcap, the same
format tcpdump always wrote — has nowhere to carry it. Opened elsewhere, a
downloaded capture still shows the raw interface **index** (`sll.ifindex`,
under *Linux cooked capture v2* in any real Wireshark's own packet detail —
no plugin needed), just not the name that went with it here. If you need a
specific interface's traffic to stay identifiable after download, filter to
it first — right-click the column, **Apply as filter**, then download that —
rather than downloading the whole `any` capture and losing the mapping.

## Field and byte selection

The detail tree and the hex pane are two views of the same frame. Click a field
and its bytes light up in both the hex and ASCII columns; click a byte and the
innermost field covering it is selected, with every parent opened so the row is
on screen. This works because the dissection comes from tshark's PDML output,
which reports each field's byte offset and length — the JSON output does not.

**Export bytes**, in the detail toolbar once a packet is selected, saves that
packet's raw bytes as a `.bin` file — built client-side from the same hex the
detail pane already holds, so it costs no extra request.

## Follow a stream

Right-click a TCP or UDP packet — its row in the list, or anywhere in its
detail pane — for **Follow TCP Stream** / **Follow UDP Stream**: the whole
conversation, reassembled in the order it was sent, one colour per direction.
**Set as display filter** narrows the packet list to the same stream
(`tcp.stream eq N` / `udp.stream eq N`).

## Protocol Hierarchy and Conversations

Two toolbar buttons give the shape of a capture without reading it packet by
packet. **Protocol Hierarchy** breaks it down by layer — `eth` → `ip` → `tcp`
→ `http`, each with a frame count, a byte count and a share of the whole —
nested the way the protocols themselves nest. **Conversations** lists every
address pair's traffic, split by direction, and every address's own total;
either table's rows offer a one-click filter onto them. Both read the current
display filter's slice of the capture when one is set, and the whole thing
otherwise.

## Traffic Diagram and Sequence Diagram

Two more toolbar buttons, for when a table is the wrong shape to see it in.

**Traffic Diagram** draws Conversations as a graph instead of a table: a node
per host, sized by bytes, and an edge per pair, weighted by how much they
exchanged. Drag a node to untangle a busy layout; click a node or an edge to
filter onto it, same as a Conversations row — the diagram stays open, and a
link's filter covers every protocol it carried — a confirmation dialog checks
you mean it first, since a node click also closes the diagram. The legend
doubles as a **protocol picker**: click a chip to show only that protocol on
the next play, hiding unrelated hosts and links; click again to bring
everything back. **Play** fetches the capture's actual packet order and
animates it — a dot per packet, moving from source to destination, colored by
protocol — so the diagram shows not just who talked to whom but the order and
rhythm of it, and leaves each host wearing a badge for its most-used protocol
when play ends. Slow it right down (the speed control works before play
starts too, and goes to 0.02x) to trace one packet at a time, and watch a link
get visibly brighter and thicker the more traffic crosses it as playback
passes that point — capped, so one very busy link cannot swallow the rest of
the graph. Playback rewinds at the end and keeps the finished picture on
screen rather than clearing it.

**Links are colored by where the traffic goes.** Amber: a public address, the
internet — those hosts are always drawn at the top. Grey: another machine on
the LAN (RFC 1918, ULA, link-local). Violet and dashed: traffic that never left
the capturing box — containers, Kubernetes pods, bridges and loopback. A host's
ring wears the same color. The box's own address, the one its outbound traffic
leaves through, is drawn in **bold**: on an "any" capture, the address that only
ever sends packets *out* of a physical interface and never has them forwarded
*in* (the kernel records each packet's direction); on other captures, the
address in at least half the IP packets. The diagram calls it "likely". Inside
versus outside the box is read from the interface a host was seen on when the
capture was taken on "any" (a host only ever seen on `cni0`, `docker0` or a
`veth` is inside), and otherwise from container-default ranges (Docker's
172.17/16, k3s' 10.42/16 and 10.43/16, kubeadm's 10.244/16 and 10.96/12).

Each key in the color legend has a color picker: change a zone's color and
every link and ring follows, kept in this browser; **Reset colors** puts the
defaults back.

**Clicking a host** filters the packet list to it and lights up every host it
talks to: its peers and the links to them are drawn on top at full strength,
and everything else fades back. **Clear filter**, beside the filter the diagram
applied, puts the packet list back to the filter the diagram was drawn with and
clears the highlight. So does clicking the same host or link again. If the
packet list's filter changes some other way, such as being cleared, a view
picked or something typed (including in a **New window** diagram's main tab),
the highlight goes too. While a play runs with a host selected, a faded host
that a packet is travelling to or from lights up again, label and all, for as
long as the packet's trail is on it.

**Moving several hosts at once:** Shift-click hosts (or Ctrl/Cmd-click), or
Shift-drag a box around them on empty space. The picked hosts get a dashed
ring, and dragging any one of them moves them all. Click empty space to let go.

**Interface**, on the toolbar, appears when the packets name more than one
interface (an "any" capture, or an upload with mapped subnets). Pick one and
the whole diagram narrows to it. Hosts and links that never crossed it leave
the drawing, the chips count only its packets, the stats pane totals it, and
Play plays only it. A saved layout remembers the choice.

On an "any" capture (or an upload with mapped subnets) each host's label has a
grey line under its address listing the **interfaces it was seen on**:
`cni0 · ens18 +1` means the host crossed `cni0` and `ens18` and one more
interface (hover the host for the full list). With names resolved, a host
shows its name, then its address, then its interfaces, one line each.

The chips are grouped by what the traffic is for — **Problems**, Name
resolution, Directory & auth (AD), Web & APIs, File sharing, Remote access,
Discovery & broadcast, Network services, Mail, Databases, Transport only,
Other — and clicking a group's name picks the whole group; the ▾ beside it
folds the group away (remembered per browser, with a count of what it holds
and how much of it is picked). **Problems** is broken out by kind (resets,
retransmissions, duplicate ACKs, window problems, IP fragments, ICMP errors,
malformed), each a chip of its own. With anything picked, the
unpicked chips step back (faded and dashed), and problem badges and red rings
show only for the problem kinds that are picked — a play of just DNS shows
none. A **JSON** chip is HTTP bodies carrying JSON, usually API calls: tshark
names a packet by its innermost layer. A **search box** finds a host by name
or address — Enter steps through matches, Esc clears. The **Protocols** column (left) and the **stats pane** (right) each fold
to a narrow strip, remembered per browser, and scroll when they hold more
than fits. Each stats section folds on its heading. The stats pane (shown before any
play) lists per-protocol totals, problems by
kind, and how many hosts sit in each zone. Toolbar controls: zoom/pan and
**Fit**, **Spacing** (fans out a dense layout), full screen, and **New
window** — a diagram-only page useful on a second monitor, whose clicks relay
back to the main tab.

Both diagram windows can be **resized** by dragging their bottom-right
corner; the drawing refits, and the size is remembered per browser.

**Saved layouts.** The header under a diagram's title names the capture it
draws: server, interface, capture filter, when it started, how long it ran,
packets and size. **Save layout** keeps the Traffic Diagram as you arranged it
— every host's position, the picked chips, zoom, spacing, and the filter and
names setting it was drawn with — against that capture, on the server, so it
follows your account. Pick it from **Saved layout** to get it back; **Save
as…** keeps another. A capture's layouts are deleted with the capture.

**Sequence Diagram** is closer to Wireshark's own Flow Graph: one lane per
host, and every packet drawn as a time-ordered arrow between two lanes,
colored by protocol, with the packet written under it: its number, protocol
and Info line, cut only at the diagram's edge (the full line is on hover).
Click an arrow, or its label, to jump straight to that packet's detail.
Rows are spaced evenly rather than by real elapsed time, since a burst of
packets a millisecond apart would otherwise collapse into an unreadable stack.
A host name too long for its lane is shortened in the middle; hover it for the
full name. With names resolved, each lane shows the name with its address
under it.

Both color the 15 most common protocols in view and group the rest as
**Other**. Fifteen is more than can be told apart by colour alone, so three
validated colours are combined with five shapes, and, in the Sequence
Diagram, line styles: any two protocols differ in colour or in shape. The
legend draws each protocol's actual mark, so match the shape as well as the
colour.

Both read the current display filter the same way Conversations does, and both
cap how much they will draw at once — 200 hosts for the Traffic Diagram and 40
lanes for the Sequence Diagram; 10,000 packets for the Sequence Diagram (a row
each), and for the Traffic Diagram as many as one capture can hold (**Max
capture packets** in Settings, 100,000 by default). Above a cap they ask for a
narrower filter rather than drawing a misleading or unusably dense picture, and
the count they judge is what the filter matched, so narrowing it works. The two
packet caps always apply; the **Optimize for diagrams** checkboxes on the
**Capture** tab fit a capture to one of them before it is taken (see
[Filters](filters.md#optimize-for-diagrams)). A long
capture plays faster: at 1x the Traffic Diagram plays 40 packets a second, or
whatever finishes the play in about two minutes, whichever is quicker.

**Resolve hostnames** (the same toggle the packet list uses, under the view
flags) applies to both: turn it on *before* opening either diagram, since it
changes what gets fetched rather than how an already-loaded one is drawn, and
flipping it mid-view does nothing until you reopen. Hosts stay keyed by
address either way — clicking a named host filters on `ip.addr == <address>`
— and the packet list gains **Source IP** and **Destination IP** columns
beside Source and Destination while names are on. Names come from the DNS
answers inside the capture itself, which works even when this server cannot
look the addresses up, and for addresses those do not cover, from a reverse-DNS
query — same tradeoff as everywhere else it appears in this app.

### Interfaces on an uploaded capture

A capture from somewhere else — a Wireshark pcapng taken on several
interfaces, say — does not carry the Linux cooked header an "any" capture
here has, so its packets have no interface of their own to show. Tell it which
subnet sits behind which: tick **Captured on more than one interface** in
the upload fly-out, and the **Interfaces** dialog opens right away — enter
each subnet and the interface it was captured on (e.g. `192.168.1.0/24`
`eth0`, `10.42.0.0/16` `cni0`), and the mapping goes up with the file.
**Interfaces** on the capture opens the same dialog later, with the private
subnets it found in the capture listed to name.
Each packet then shows that interface and a direction, as a capture on "any"
would: to a mapped subnet is **out** on its interface, from one is **in**, and
a packet routed between two mapped subnets shows where it leaves (out on the
destination's). Where the pcapng recorded a packet's direction, that wins, and
the subnets only say which interface. The Traffic Diagram reads the same
interfaces for its zones, so mapping a pod range to `cni0` puts those hosts
inside the box.

## Saved views

A display filter you will want again is worth keeping. **Save view** turns
whatever is in the filter box into a named tab on that capture — "auth
traffic", "the retransmissions", "everything to the DC" — and the tabs are
still there the next time you open it, on any machine you sign in from.

| | |
| --- | --- |
| Switching | click a tab; its filter goes into the box and the list redraws |
| **All packets** | always first, always present. It is the unfiltered capture, not a saved row, so it cannot be renamed or deleted |
| Editing | the selected tab offers rename, and will take the filter currently in the box if you have refined it |
| Downloading | **↓** on the selected tab downloads *that view* as its own pcap, containing only the packets its filter selects |
| Leaving a view | typing over the filter deselects the tab, rather than leaving it claiming to show something it no longer does |

Views are stored server-side against your account and that capture, not in the
browser, and they go when the capture does. Two things follow from that: they
survive a different browser, and another user's views are not yours to see.

**A filtered download is still packet data**, and frequently the most sensitive
slice of a capture rather than a less sensitive one — so it is refused over
plain HTTP for the same reason the full download is.

## Related

- [sanitizing.md](sanitizing.md) — downloading a capture, or one saved view,
  with credentials and identifiers replaced.
- [architecture.md](architecture.md#statistics-protocol-hierarchy-conversations-follow-stream)
  — how the statistics views are computed.
