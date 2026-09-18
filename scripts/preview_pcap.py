"""Write a small, made-up home-network capture for scripts/preview.sh.

A home network's worth of hosts and a real mix of protocols -- DNS, mDNS,
SSDP, DHCP, TLS, HTTP, SSH, SMB, NTP, SNMP, syslog, ICMP, ARP -- plus the
trouble the diagrams flag: refused connections (resets), a retransmission,
fragmented datagrams and ICMP port-unreachables. All of it interleaved
the way traffic is rather than one protocol at a time, and with each device
leaning towards its own (the TV streams, the phone announces itself, the
printer answers SNMP), so the Traffic Diagram's most-used-protocol badges
differ from host to host. Every address is private, multicast or a
documentation range; nothing here was ever captured anywhere.

It is Linux cooked v2, the format of a capture on "any", so every packet
carries the index of the interface it crossed: 2 wired LAN, 3 Wi-Fi, 4 WAN.
A file has no table naming those indexes (a real capture on "any" records one
from the target), so on its own the viewer shows "#2", "#3" and "#4";
scripts/preview.sh gives them the names eth0, wlan0 and wan.

Packets are built by hand with tests/packet_builders.py, the same helpers the
sanitizer tests use, so this adds no dependency.

    python3 scripts/preview_pcap.py out.pcap
"""

from __future__ import annotations

import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.packet_builders import (  # noqa: E402
    dns_query, dns_response_a, icmp, ip4, ipv4, mac, ones_complement_checksum, snmp_get, tcp,
    tls_client_hello, udp,
)

ROUTER = "192.168.1.1"
LAPTOP = "192.168.1.10"
PHONE = "192.168.1.11"
NAS = "192.168.1.20"
PRINTER = "192.168.1.30"
TV = "192.168.1.40"
WEB = "203.0.113.10"      # TEST-NET-3
CDN = "198.51.100.25"     # TEST-NET-2
NTP_SERVER = "198.51.100.123"
# Enough destinations that the Traffic Diagram has a crowd to lay out.
SITES = [
    ("shop.example.com", WEB), ("cdn.example.net", CDN),
    ("mail.example.org", "203.0.113.25"), ("video.example.com", "203.0.113.80"),
    ("api.example.net", "198.51.100.40"), ("news.example.org", "198.51.100.77"),
    ("maps.example.com", "203.0.113.141"), ("social.example.net", "198.51.100.200"),
]

MACS = {
    ROUTER: "02:00:00:00:00:01", LAPTOP: "02:00:00:00:00:10", PHONE: "02:00:00:00:00:11",
    NAS: "02:00:00:00:00:20", PRINTER: "02:00:00:00:00:30", TV: "02:00:00:00:00:40",
}


# Interface indexes, as a capture on the router's "any" would record them.
WIRED, WIFI, WAN = 2, 3, 4
# 0.0.0.0 is the phone asking DHCP for an address, on Wi-Fi.
IFINDEX = {LAPTOP: WIFI, PHONE: WIFI, NAS: WIRED, PRINTER: WIRED, TV: WIRED, "0.0.0.0": WIFI}


def _mac_for(address: str) -> bytes:
    # Off-LAN addresses sit behind the router, so their frames carry its MAC.
    return mac(MACS.get(address, MACS[ROUTER]))


def _ifindex(src: str, dst: str) -> int:
    """The interface the packet crossed: the LAN side of whichever end is on
    the LAN, else the WAN (the router's own traffic out)."""
    return IFINDEX.get(src) or IFINDEX.get(dst) or WAN


def _sll2(src: str, dst: str, ethertype: int, payload: bytes) -> bytes:
    # protocol, reserved, ifindex, ARPHRD_ETHER, packet type (0 = to us),
    # address length, address padded to 8.
    header = struct.pack("!HHiHBB8s", ethertype, 0, _ifindex(src, dst), 1, 0, 6, _mac_for(src) + b"\0\0")
    return header + payload


def _ip_frame(src: str, dst: str, proto: int, payload: bytes) -> bytes:
    return _sll2(src, dst, 0x0800, ipv4(ip4(src), ip4(dst), proto, payload))


def _udp(src: str, dst: str, sport: int, dport: int, payload: bytes) -> bytes:
    return _ip_frame(src, dst, 17, udp(ip4(src), ip4(dst), sport, dport, payload))


# Next sequence number per direction of each flow. Without it every segment
# repeats seq 1 and tshark reads the stream as retransmissions, not TLS/HTTP.
_SEQ: dict[tuple[str, str, int, int], int] = {}


def _tcp(src: str, dst: str, sport: int, dport: int, payload: bytes = b"", flags: int = 0x18) -> bytes:
    key = (src, dst, sport, dport)
    seq = _SEQ.get(key, 1000)
    _SEQ[key] = seq + len(payload) + (1 if flags & 0x02 else 0)
    # Acknowledge what the other side has sent so far. packet_builders.tcp
    # always sends ack 1, which tshark flags as a duplicate ACK on every row.
    ack = _SEQ.get((dst, src, dport, sport), 0) if flags & 0x10 else 0
    segment = bytearray(tcp(ip4(src), ip4(dst), sport, dport, payload, seq=seq, flags=flags))
    segment[8:12] = struct.pack("!I", ack)
    segment[16:18] = b"\0\0"
    pseudo = ip4(src) + ip4(dst) + struct.pack("!BBH", 0, 6, len(segment))
    segment[16:18] = struct.pack("!H", ones_complement_checksum(pseudo + bytes(segment)))
    return _ip_frame(src, dst, 6, bytes(segment))


def _arp(sender: str, target: str) -> bytes:
    body = struct.pack("!HHBBH6s4s6s4s", 1, 0x0800, 6, 4, 1,
                       _mac_for(sender), ip4(sender), b"\x00" * 6, ip4(target))
    return _sll2(sender, target, 0x0806, body)


def _dhcp_discover(client_mac: bytes) -> bytes:
    fixed = struct.pack("!BBBBIHH4s4s4s4s16s64s128s", 1, 1, 6, 0, 0x3903F326, 0, 0x8000,
                        b"\0" * 4, b"\0" * 4, b"\0" * 4, b"\0" * 4, client_mac, b"", b"")
    return fixed + b"\x63\x82\x53\x63" + b"\x35\x01\x01" + b"\xff"


SSDP_SEARCH = (b"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
               b'MAN: "ssdp:discover"\r\nMX: 1\r\nST: ssdp:all\r\n\r\n')
MDNS = "224.0.0.251"
SSDP = "239.255.255.250"


def _ntp_request() -> bytes:
    return b"\x23" + b"\x00" * 47  # LI 0, version 4, client mode


def _handshake(client: str, server: str, sport: int, dport: int) -> list[bytes]:
    return [
        _tcp(client, server, sport, dport, flags=0x02),
        _tcp(server, client, dport, sport, flags=0x12),
        _tcp(client, server, sport, dport, flags=0x10),
    ]


def _web(rng: random.Random, client: str, sport: int) -> list[bytes]:
    name, server = rng.choice(SITES)
    frames = [_udp(client, ROUTER, sport, 53, dns_query(name)),
              _udp(ROUTER, client, 53, sport, dns_response_a(name, server))]
    frames += _handshake(client, server, sport + 1, 443)
    frames.append(_tcp(client, server, sport + 1, 443, tls_client_hello(name)))
    # Several records per ACK, as a download looks -- not one ACK per record,
    # which would make bare TCP the most common "protocol" in the capture.
    for i in range(rng.randint(4, 12)):
        frames.append(_tcp(server, client, 443, sport + 1, b"\x17\x03\x03\x00\x40" + b"\x00" * 64))
        if i % 4 == 3:
            frames.append(_tcp(client, server, sport + 1, 443, flags=0x10))
    return frames


KINDS = ["web", "stream", "http", "ssh", "smb", "mdns", "ssdp", "dhcp", "ping", "ntp", "snmp", "syslog", "arp",
         "refused", "retransmit", "fragments", "unreachable"]
WEIGHTS = [5, 4, 2, 2, 3, 3, 2, 1, 2, 1, 3, 2, 2, 3, 2, 1, 1]


def _session(rng: random.Random, kind: str) -> list[bytes]:
    """One burst of activity, from whichever device that kind of traffic is
    typical of."""
    sport = rng.randint(40000, 60000)
    if kind == "web":
        return _web(rng, rng.choice([LAPTOP, PHONE]), sport)
    if kind == "stream":
        return _web(rng, TV, sport)
    if kind == "http":
        frames = _handshake(LAPTOP, WEB, sport, 80)
        frames.append(_tcp(LAPTOP, WEB, sport, 80, b"GET / HTTP/1.1\r\nHost: shop.example.com\r\n\r\n"))
        frames.append(_tcp(WEB, LAPTOP, 80, sport, b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"))
        return frames
    if kind == "ssh":
        frames = _handshake(LAPTOP, NAS, sport, 22)
        frames.append(_tcp(NAS, LAPTOP, 22, sport, b"SSH-2.0-OpenSSH_9.6\r\n"))
        frames.append(_tcp(LAPTOP, NAS, sport, 22, b"SSH-2.0-OpenSSH_9.6\r\n"))
        return frames
    if kind == "smb":
        frames = _handshake(LAPTOP, NAS, sport, 445)
        for _ in range(rng.randint(3, 6)):
            frames.append(_tcp(LAPTOP, NAS, sport, 445, b"\x00\x00\x00\x78" + b"\x00" * 120))
            frames.append(_tcp(NAS, LAPTOP, 445, sport, b"\x00\x00\x01\x90" + b"\x00" * 400))
        return frames
    if kind == "mdns":
        who = rng.choice([PHONE, TV, PHONE])
        return [_udp(who, MDNS, 5353, 5353, dns_query(rng.choice(
            ["_googlecast._tcp.local", "_airplay._tcp.local", "_ipp._tcp.local"]), qtype=12))]
    if kind == "ssdp":
        return [_udp(rng.choice([TV, PHONE]), SSDP, sport, 1900, SSDP_SEARCH)]
    if kind == "dhcp":
        return [_udp("0.0.0.0", "255.255.255.255", 68, 67, _dhcp_discover(_mac_for(PHONE)))]
    if kind == "ping":
        client, target = rng.choice([(LAPTOP, ROUTER), (LAPTOP, PRINTER), (PHONE, ROUTER)])
        return [_ip_frame(client, target, 1, icmp(8, 0, b"\x00\x01\x00\x01" + b"ping" * 8)),
                _ip_frame(target, client, 1, icmp(0, 0, b"\x00\x01\x00\x01" + b"ping" * 8))]
    if kind == "ntp":
        return [_udp(ROUTER, NTP_SERVER, 123, 123, _ntp_request()),
                _udp(NTP_SERVER, ROUTER, 123, 123, b"\x24" + b"\x00" * 47)]
    if kind == "snmp":
        return [_udp(NAS, PRINTER, sport, 161, snmp_get("public")),
                _udp(PRINTER, NAS, 161, sport, snmp_get("public"))]
    if kind == "syslog":
        line = f"<30>Sep 18 12:{rng.randint(0, 59):02d}:00 router dnsmasq[811]: query[A] {rng.choice(SITES)[0]}"
        return [_udp(ROUTER, NAS, 514, 514, line.encode())]
    if kind == "refused":
        # A connection to a closed port: SYN, then RST/ACK straight back.
        client, server, port = rng.choice([(LAPTOP, NAS, 8080), (PHONE, PRINTER, 9100), (TV, NAS, 32400)])
        return [_tcp(client, server, sport, port, flags=0x02), _tcp(server, client, port, sport, flags=0x14)]
    if kind == "retransmit":
        # The same TLS record sent twice: tshark flags the second a retransmission.
        name, server = rng.choice(SITES)
        frames = _handshake(LAPTOP, server, sport, 443)
        record = b"\x17\x03\x03\x00\x40" + b"\x00" * 64
        frames.append(_tcp(server, LAPTOP, 443, sport, record))
        _SEQ[(server, LAPTOP, 443, sport)] -= len(record)
        frames.append(_tcp(server, LAPTOP, 443, sport, record))
        return frames
    if kind == "fragments":
        # One UDP datagram too big for the link, split into two IP fragments.
        payload = udp(ip4(NAS), ip4(TV), 5004, 5004, bytes(rng.randrange(256) for _ in range(2000)))
        ident = rng.randint(1, 65535)
        first, rest = payload[:1480], payload[1480:]
        return [
            _sll2(NAS, TV, 0x0800, ipv4(ip4(NAS), ip4(TV), 17, first, frag=0x2000, ident=ident)),
            _sll2(NAS, TV, 0x0800, ipv4(ip4(NAS), ip4(TV), 17, rest, frag=1480 // 8, ident=ident)),
        ]
    if kind == "unreachable":
        # A DNS query to a host with nothing listening, answered by ICMP port unreachable.
        query = _udp(PHONE, PRINTER, sport, 53, dns_query("printer.local"))[20:]  # the IP packet
        return [_udp(PHONE, PRINTER, sport, 53, dns_query("printer.local")),
                _ip_frame(PRINTER, PHONE, 1, icmp(3, 3, b"\0\0\0\0" + query[:28]))]
    return [_arp(rng.choice([LAPTOP, PHONE, TV]), ROUTER)]


def build(seed: int = 7, sessions: int = 110) -> bytes:
    rng = random.Random(seed)
    _SEQ.clear()
    # Every kind at least once, so no protocol is missing by chance, then the
    # rest drawn by weight and the lot shuffled together.
    kinds = KINDS + rng.choices(KINDS, weights=WEIGHTS, k=max(0, sessions - len(KINDS)))
    rng.shuffle(kinds)
    frames: list[bytes] = []
    for kind in kinds:
        frames += _session(rng, kind)
    # pcap with real sub-second spacing: packets_builders.pcap stamps one
    # packet per second, which makes a 300-packet capture last five minutes.
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 276)  # LINUX_SLL2
    t = 1_758_000_000.0
    for frame in frames:
        t += rng.uniform(0.001, 0.12)
        sec, usec = int(t), int((t % 1) * 1_000_000)
        out += struct.pack("<IIII", sec, usec, len(frame), len(frame)) + frame
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: preview_pcap.py OUT.pcap")
    Path(sys.argv[1]).write_bytes(build())
