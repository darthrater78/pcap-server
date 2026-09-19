"""Captures of a router, built by hand, where the right answer is known.

A client on the LAN side (ifindex 2) fetches from a server on the WAN side
(ifindex 3) through a Linux box captured on "any" -- or on both interfaces at
once, which is the same file. Every packet the box forwards is seen twice:
in on one interface, out on the other. Each builder returns the pcap and
what is true about it, so a test can check the app against the wire rather
than against tshark:

    copies    frame number -> the frame it is a second sighting of
    translated  the copies NAT rewrote
    retrans   first sightings of genuine retransmissions
    dupacks   first sightings of genuine duplicate ACKs
    lost_downstream  copies whose own link shows the box's drop

Run as a script to write the scenarios out as files (for uploading to a
running pcap-server):  python tests/routed_capture.py OUTDIR
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from tests.packet_builders import ip4, ip6, ipv4, ipv6, mac, pcap, sll2, tcp
except ImportError:  # run as a script from the repo root
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tests.packet_builders import ip4, ip6, ipv4, ipv6, mac, pcap, sll2, tcp

LAN, WAN = 2, 3
IN, OUT = 0, 4
LINUX_SLL2 = 276
INTERFACE_NAMES = {LAN: "eth0", WAN: "eth1"}
ROUTER_MAC = mac("02:00:00:00:00:01")


@dataclass
class Scenario:
    frames: list[bytes] = field(default_factory=list)
    times: list[float] = field(default_factory=list)
    copies: dict[int, int] = field(default_factory=dict)
    retrans: set[int] = field(default_factory=set)
    dupacks: set[int] = field(default_factory=set)
    translated: set[int] = field(default_factory=set)
    # Copies whose own link shows the loss: C leaving after B was dropped.
    lost_downstream: set[int] = field(default_factory=set)
    clock: float = 1_700_000_000.0

    def add(self, frame: bytes, gap: float) -> int:
        self.clock += gap
        self.frames.append(frame)
        self.times.append(self.clock)
        return len(self.frames)

    def pcap(self) -> bytes:
        return pcap(self.frames, linktype=LINUX_SLL2, times=self.times)


def _routed(*, v6: bool, nat: bool, drop: bool, bridge: bool = False) -> Scenario:
    """One TCP exchange through the box. `drop`: the box loses one data
    segment, so the server sends two duplicate ACKs and the client
    retransmits -- real problems that must survive. `nat`: the WAN side
    carries the box's own address instead of the client's. `bridge`: the
    box bridges instead of routing, so the second sighting is not even a
    hop older (same TTL) -- still the same packet."""
    s = Scenario()
    if v6:
        client, server, public = ip6("2001:db8:1::10"), ip6("2001:db8:2::5"), ip6("2001:db8:ff::1")
        ethertype = 0x86DD
    else:
        client, server, public = ip4("192.168.1.10"), ip4("203.0.113.5"), ip4("198.51.100.2")
        ethertype = 0x0800
    ids = {"c": 100, "s": 900}

    def packet(src, dst, sport, dport, seq, ack, flags, payload, sender, hops):
        segment = tcp(src, dst, sport, dport, payload, seq=seq, flags=flags, ack=ack)
        if v6:
            return ipv6(src, dst, 6, segment, hop_limit=64 - hops)
        return ipv4(src, dst, 6, segment, ident=ids[sender], ttl=64 - hops)

    def send(sender, seq, ack, flags, payload=b"", *, lost=False, gap=0.01):
        """Returns the frame number of the first sighting."""
        ids[sender] += 1
        hop = 0 if bridge else 1
        if sender == "c":
            wan_src = public if nat else client
            first = s.add(sll2(ROUTER_MAC, ethertype,
                               packet(client, server, 40000, 80, seq, ack, flags, payload, "c", 0),
                               ifindex=LAN, pkttype=IN), gap)
            if lost:
                return first
            second = s.add(sll2(ROUTER_MAC, ethertype,
                                packet(wan_src, server, 40000, 80, seq, ack, flags, payload, "c", hop),
                                ifindex=WAN, pkttype=OUT), 0.00005)
        else:
            wan_dst = public if nat else client
            first = s.add(sll2(ROUTER_MAC, ethertype,
                               packet(server, wan_dst, 80, 40000, seq, ack, flags, payload, "s", 0),
                               ifindex=WAN, pkttype=IN), gap)
            second = s.add(sll2(ROUTER_MAC, ethertype,
                                packet(server, client, 80, 40000, seq, ack, flags, payload, "s", hop),
                                ifindex=LAN, pkttype=OUT), 0.00005)
        s.copies[second] = first
        if nat:
            s.translated.add(second)
        return first

    syn, ack_, psh = 0x02, 0x10, 0x18
    c, sv = 1000, 5000
    data = b"x" * 100
    send("c", c, 0, syn)
    send("s", sv, c + 1, syn | ack_)
    send("c", c + 1, sv + 1, ack_)
    send("c", c + 1, sv + 1, psh, data)                      # A
    send("s", sv + 1, c + 101, ack_)
    send("c", c + 101, sv + 1, psh, data, lost=drop)         # B
    after_gap = send("c", c + 201, sv + 1, psh, data)       # C
    if drop:
        s.lost_downstream.add(after_gap + 1)
        # The server got C without B: two duplicate ACKs, then B again.
        s.dupacks.add(send("s", sv + 1, c + 101, ack_))
        s.dupacks.add(send("s", sv + 1, c + 101, ack_))
        s.retrans.add(send("c", c + 101, sv + 1, psh, data, gap=0.2))
    send("s", sv + 1, c + 301, ack_)
    # The same ACK again a second and a half later -- over IPv6 the same
    # bytes, since there is no IP ID. A new packet (tshark: a duplicate ACK,
    # which it is), never a copy of the first.
    s.dupacks.add(send("s", sv + 1, c + 301, ack_, gap=1.5))
    return s


SCENARIOS = {
    "routed-v4": lambda: _routed(v6=False, nat=False, drop=False),
    "routed-v4-loss": lambda: _routed(v6=False, nat=False, drop=True),
    "routed-v6-loss": lambda: _routed(v6=True, nat=False, drop=True),
    "nat-v4-loss": lambda: _routed(v6=False, nat=True, drop=True),
    "bridged-v4-loss": lambda: _routed(v6=False, nat=False, drop=True, bridge=True),
}


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for name, build in SCENARIOS.items():
        (out / f"{name}.pcap").write_bytes(build().pcap())
        print(out / f"{name}.pcap")
