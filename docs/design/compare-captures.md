# Design note: comparing two captures

*Status: proposal, not built. Written for 1.1.0-beta.7 in response to "would
it be possible to compare two pcaps at the same time to get both sides".*

## The question it answers

Most requests like this come from one situation: the same traffic captured at
two points. The client and the server, both sides of a firewall or NAT, or a
host and the router in front of it. On their own, each capture answers "what
did this box see". Together, they answer the question that sent you
capturing: **what happened in between.** Which packets never arrived (a drop
or a filter), which arrived changed (NAT rewrote an address, an MSS was
clamped, a TTL was spent), and how long each one took to cross.

Two captures open in two tabs already works today, but it leaves the matching
to your eyes.

## What it would look like

**Compare…** on a capture in the list (or with two captures ticked) opens a
comparison view:

- **Two packet lists side by side**, A on the left and B on the right, with
  the same packet on the same row. A packet only one side saw gets a gap
  opposite it, shaded, so a drop shows as a hole in one column.
- **A summary strip:** matched, only in A, only in B, the clock offset worked
  out between the two captures, and the median one-way delay after that
  offset.
- **Per matched pair:** the delay, and what changed in transit. Address and
  port (NAT), TTL or hop limit, DSCP, and for TCP the window and MSS. These
  show as an extra column, and one click filters to "changed in transit".
- **Filters that follow the pairing.** "Only in A", "only in B" and "changed"
  work as filters, and an ordinary display filter narrows both sides at once.
- **The Traffic Diagram in compare mode (later):** hosts from both captures,
  with each link marked seen by A, by B or by both. A link only one side saw
  is the first place to look.

## How packets are matched

Timestamps cannot be used alone: the two boxes' clocks disagree, often by more
than the gaps between packets. Matching uses what the packet carries, taken
per packet with one tshark pass over each file (`-T fields`):

1. **IPv4:** source, destination, protocol and `ip.id`, plus the transport
   ports, with `tcp.seq`/`tcp.ack` or the UDP length and checksum when
   present. IP IDs repeat and can be zero, so this is a candidate key, not the
   answer on its own.
2. **IPv6 and IPv4 with a zero ID:** the 5-tuple, plus `tcp.seq` and `tcp.ack`
   and the TCP payload length, or a hash of the first 64 bytes of the
   transport payload for UDP and ICMP.
3. **NAT:** when the addresses differ between the sides, the ports and
   sequence numbers still line up. Match on those first, then learn the
   address mapping from the matches, so NAT becomes a finding rather than a
   reason nothing matched.
4. **Resolving duplicates in order:** among candidates with the same key, pair
   them in time order within a window. That window is centred on the clock
   offset, estimated as the median A-to-B difference over the matches that
   were unique.

Retransmissions stay separate packets (tshark marks them), so a segment sent
twice and seen once on the far side reads correctly as "one of these was
lost".

## Where it runs

- **Backend:** `GET /api/compare?a=<id>&b=<id>&display_filter=…` runs the
  existing packet path on both captures, with the few extra fields above, and
  joins them in Python. It returns row pairs with offsets, paged like
  `/packets`. Both captures must be readable by the caller (the same check
  `/packets` makes), and both go through the vault like any other read. It
  needs no new storage: a comparison is computed, not saved. Saving one could
  come later, the way diagram layouts did.
- **Limits:** the same cap per side as the Traffic Diagram (Max capture
  packets, 100,000 by default), and the display filter to narrow before
  matching. A pairing over two 100,000-packet captures is a hash join, which
  is seconds at most, but it is cached per (a, b, filter) for the viewer's
  paging.
- **Frontend:** a new viewer mode rather than a new tab type. It reuses the
  column layout, row colouring and detail pane. Clicking a row opens that
  side's packet, and a toggle shows both details stacked.

## Build order

1. **Side by side, time-aligned, no matching.** Two lists with scrolling
   locked on time, plus a manual clock-offset nudge. Cheap, and useful on its
   own.
2. **Matching and the summary**, including only-in-A/B and delay: the core of
   it.
3. **Changed in transit** (NAT and the header differences).
4. **Traffic Diagram compare mode.**

## Open questions for you

- Is the usual case client and server of the same conversation, or two sides
  of a NAT or firewall? That decides whether step 3 comes before step 2.
- Should a comparison be saveable, like a diagram layout?
- Is two enough, or do you have three-point captures (client, firewall,
  server)?
