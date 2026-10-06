"""Write a small, made-up home-network capture for scripts/preview.sh.

A home network's worth of hosts and a real mix of protocols -- DNS, mDNS,
SSDP, DHCP, TLS, HTTP, SSH, SMB, NTP, SNMP, syslog, ICMP, ARP -- plus the
name-service traffic a display filter is usually written to find: every DHCP
message type (a full discover/offer/request/ack, renewals, an inform, a NAK,
a release), DNS queries with their answers across record types (A, AAAA, PTR,
TXT, MX, SOA, SRV, a name that does not exist), and dynamic DNS updates the
way a Windows client does them (SOA lookup, an update that is refused, a TKEY
negotiation, the update again). Then the
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
scripts/preview.sh gives them the names eth0, wlan0, wan and cni0 (the pod bridge).

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
    dns_name, dns_query, icmp, ip4, ip6, ipv4, mac, ones_complement_checksum, snmp_get, tcp,
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
# A small Kubernetes node on the NAS: two pods and the cluster DNS service,
# on the pod bridge (cni0), so the diagram has traffic inside the box.
POD_WEB = "10.42.0.12"
POD_API = "10.42.0.15"
CLUSTER_DNS = "10.43.0.10"
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
WIRED, WIFI, WAN, CNI = 2, 3, 4, 5
# 0.0.0.0 is the phone asking DHCP for an address, on Wi-Fi.
IFINDEX = {LAPTOP: WIFI, PHONE: WIFI, NAS: WIRED, PRINTER: WIRED, TV: WIRED, "0.0.0.0": WIFI,
           POD_WEB: CNI, POD_API: CNI, CLUSTER_DNS: CNI}


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
    # The router's own packets are outgoing (4); everything else arrives (0).
    # That is how the Traffic Diagram tells the capturing box's own address.
    pkttype = 4 if src == ROUTER else 0
    header = struct.pack("!HHiHBB8s", ethertype, 0, _ifindex(src, dst), 1, pkttype, 6, _mac_for(src) + b"\0\0")
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


# --- DNS, built a section at a time -------------------------------------------
#
# A message is a header and four lists of records. Queries and their answers
# share an id, so tshark pairs them (dns.response_to, dns.time).

A, PTR, SOA, MX, TXT, AAAA, SRV, TKEY = 1, 12, 6, 15, 16, 28, 33, 249
QUERY, RESPONSE, AUTHORITATIVE = 0x0100, 0x8180, 0x8580
UPDATE, UPDATE_RESPONSE = 5 << 11, 0x8000 | (5 << 11)   # opcode 5: dynamic update
NXDOMAIN, REFUSED = 3, 5
LAN_ZONE, REVERSE_ZONE = "home.lan", "1.168.192.in-addr.arpa"
HOSTNAMES = {LAPTOP: "laptop", PHONE: "phone", NAS: "nas", PRINTER: "printer", TV: "tv"}


def _dns(ident: int, flags: int, questions=(), answers=(), authority=(), additional=()) -> bytes:
    header = struct.pack("!HHHHHH", ident, flags, len(questions), len(answers), len(authority), len(additional))
    return header + b"".join(questions) + b"".join(answers) + b"".join(authority) + b"".join(additional)


def _q(name: str, qtype: int, qclass: int = 1) -> bytes:
    return dns_name(name) + struct.pack("!HH", qtype, qclass)


def _rr(name: str, rtype: int, rdata: bytes, ttl: int = 300, rclass: int = 1) -> bytes:
    return dns_name(name) + struct.pack("!HHIH", rtype, rclass, ttl, len(rdata)) + rdata


def _soa_rdata(zone: str) -> bytes:
    return (dns_name(f"ns1.{zone}") + dns_name(f"hostmaster.{zone}")
            + struct.pack("!IIIII", 2025091801, 3600, 600, 86400, 300))


def _srv_rdata(priority: int, weight: int, port: int, target: str) -> bytes:
    return struct.pack("!HHH", priority, weight, port) + dns_name(target)


def _tkey_rdata(key: bytes) -> bytes:
    # algorithm, inception, expiration, mode, error, key, other data. Mode 2
    # (Diffie-Hellman) rather than a Windows client's 3 (GSS-API): tshark
    # parses a mode 3 key as a GSS token, and made-up bytes are not one.
    return (dns_name("gss-tsig") + struct.pack("!IIHHH", 1_758_000_000, 1_758_086_400, 2, 0, len(key))
            + key + struct.pack("!H", 0))


def _ask(rng: random.Random, client: str, server: str, question: bytes,
         flags: int = RESPONSE, answers=(), authority=(), additional=(), sent_with=()) -> list[bytes]:
    """A query and the response to it, on one port and one id. `sent_with` is
    what the query itself carries in its additional section."""
    ident, sport = rng.randrange(1, 65536), rng.randint(40000, 60000)
    return [
        _udp(client, server, sport, 53, _dns(ident, QUERY, [question], additional=sent_with)),
        _udp(server, client, 53, sport, _dns(ident, flags, [question], answers, authority, additional)),
    ]


def _lookup(rng: random.Random, client: str) -> list[bytes]:
    """One ordinary lookup, of whichever record type comes up."""
    kind = rng.choice(["a", "a", "aaaa", "ptr", "txt", "mx", "nxdomain"])
    name, address = rng.choice(SITES)
    if kind == "a":
        return _ask(rng, client, ROUTER, _q(name, A), answers=[_rr(name, A, ip4(address))])
    if kind == "aaaa":
        return _ask(rng, client, ROUTER, _q(name, AAAA),
                    answers=[_rr(name, AAAA, ip6(f"2001:db8::{rng.randint(1, 0xffff):x}"))])
    if kind == "ptr":
        host = rng.choice(list(HOSTNAMES))
        reverse = ".".join(reversed(host.split("."))) + ".in-addr.arpa"
        return _ask(rng, client, ROUTER, _q(reverse, PTR), flags=AUTHORITATIVE,
                    answers=[_rr(reverse, PTR, dns_name(f"{HOSTNAMES[host]}.{LAN_ZONE}"))])
    if kind == "txt":
        zone = name.split(".", 1)[1]
        text = b"v=spf1 include:_spf.example.net -all"
        return _ask(rng, client, ROUTER, _q(zone, TXT), answers=[_rr(zone, TXT, bytes([len(text)]) + text)])
    if kind == "mx":
        zone = name.split(".", 1)[1]
        return _ask(rng, client, ROUTER, _q(zone, MX),
                    answers=[_rr(zone, MX, struct.pack("!H", 10) + dns_name(f"mail.{zone}"))],
                    additional=[_rr(f"mail.{zone}", A, ip4("203.0.113.25"))])
    missing = rng.choice([f"wpad.{LAN_ZONE}", "isatap.home.lan", "typo.example.invalid"])
    zone = missing.split(".", 1)[1]
    return _ask(rng, client, ROUTER, _q(missing, A), flags=RESPONSE | NXDOMAIN,
                authority=[_rr(zone, SOA, _soa_rdata(zone))])


# What a client asks for when it is looking for a service, not a host.
SERVICES = [
    ("_ldap._tcp.dc._msdcs", "corp.example.com", 389, "dc"),
    ("_kerberos._tcp", "corp.example.com", 88, "dc"),
    ("_kerberos._udp", "corp.example.com", 88, "dc"),
    ("_sip._udp", "example.net", 5060, "sip"),
    ("_xmpp-client._tcp", "example.org", 5222, "chat"),
    ("_imaps._tcp", "example.org", 993, "mail"),
    ("_minecraft._tcp", "example.com", 25565, "play"),
]


def _srv_lookup(rng: random.Random, client: str) -> list[bytes]:
    prefix, zone, port, host = rng.choice(SERVICES)
    service = f"{prefix}.{zone}"
    targets = [f"{host}{n}.{zone}" for n in (1, 2)]
    return _ask(
        rng, client, ROUTER, _q(service, SRV),
        answers=[_rr(service, SRV, _srv_rdata(0, 100, port, targets[0])),
                 _rr(service, SRV, _srv_rdata(10, 50, port, targets[1]))],
        additional=[_rr(targets[0], A, ip4("198.51.100.40")), _rr(targets[1], A, ip4("198.51.100.41"))],
    )


def _soa_lookup(rng: random.Random, client: str, zone: str) -> list[bytes]:
    return _ask(rng, client, ROUTER, _q(zone, SOA), flags=AUTHORITATIVE,
                answers=[_rr(zone, SOA, _soa_rdata(zone))])


def _update(rng: random.Random, client: str, zone: str, records: list[bytes], rcode: int = 0,
            signed: bytes = b"") -> list[bytes]:
    """A dynamic update and the server's verdict. The four sections mean
    zone, prerequisites, updates and additional here (RFC 2136)."""
    ident, sport = rng.randrange(1, 65536), rng.randint(40000, 60000)
    additional = [signed] if signed else []
    return [
        _udp(client, ROUTER, sport, 53, _dns(ident, UPDATE, [_q(zone, SOA)], [], records, additional)),
        _udp(ROUTER, client, 53, sport, _dns(ident, UPDATE_RESPONSE | rcode, [_q(zone, SOA)])),
    ]


def _dynamic_update(rng: random.Random, client: str) -> list[bytes]:
    """A host registering its own name. Either the plain way, which this
    server accepts for some hosts, or the Windows way: find the zone, try
    unsigned, be refused, negotiate a key (TKEY), and try again signed."""
    host = f"{HOSTNAMES[client]}.{LAN_ZONE}"
    forward = [
        # delete whatever A records the name has (class ANY, no data), then add ours
        _rr(host, A, b"", ttl=0, rclass=255),
        _rr(host, A, ip4(client), ttl=1200),
    ]
    reverse_name = ".".join(reversed(client.split("."))) + ".in-addr.arpa"
    reverse = [_rr(reverse_name, PTR, dns_name(host), ttl=1200)]
    frames = _soa_lookup(rng, client, LAN_ZONE)
    if rng.random() < 0.4:
        return frames + _update(rng, client, LAN_ZONE, forward) + _update(rng, client, REVERSE_ZONE, reverse)
    frames += _update(rng, client, LAN_ZONE, forward, rcode=REFUSED)
    key_name = f"{rng.randrange(1 << 32):08x}-ms-7.1-{rng.randrange(1 << 16):04x}.{LAN_ZONE}"
    token = bytes(rng.randrange(256) for _ in range(48))
    tkey = _rr(key_name, TKEY, _tkey_rdata(token), ttl=0, rclass=255)
    # The query carries the client's half of the negotiation; the answer the server's.
    frames += _ask(rng, client, ROUTER, _q(key_name, TKEY, qclass=255), answers=[tkey], sent_with=[tkey])
    frames += _update(rng, client, LAN_ZONE, forward, signed=tkey)
    return frames + _update(rng, client, REVERSE_ZONE, reverse, signed=tkey)


# --- DHCP ---------------------------------------------------------------------

DISCOVER, OFFER, REQUEST, DECLINE, ACK, NAK, RELEASE, INFORM = range(1, 9)
LEASE_SECONDS = 86400


def _dhcp_options(message_type: int, *options: tuple[int, bytes]) -> bytes:
    out = b"\x63\x82\x53\x63" + bytes([53, 1, message_type])
    for code, value in options:
        out += bytes([code, len(value)]) + value
    return out + b"\xff"


def _dhcp(op: int, xid: int, client_mac: bytes, options: bytes, *, ciaddr: str = "0.0.0.0",
          yiaddr: str = "0.0.0.0", siaddr: str = "0.0.0.0", broadcast: bool = False) -> bytes:
    return struct.pack("!BBBBIHH4s4s4s4s16s64s128s", op, 1, 6, 0, xid, 0, 0x8000 if broadcast else 0,
                       ip4(ciaddr), ip4(yiaddr), ip4(siaddr), b"\0" * 4, client_mac, b"", b"") + options


def _from_unconfigured(owner: str, payload: bytes) -> bytes:
    """0.0.0.0 -> 255.255.255.255 from a host with no address yet: the frame
    still carries that host's own MAC and arrives on its own interface, which
    the address-keyed helpers above cannot know."""
    packet = ipv4(ip4("0.0.0.0"), ip4("255.255.255.255"), 17,
                  udp(ip4("0.0.0.0"), ip4("255.255.255.255"), 68, 67, payload))
    header = struct.pack("!HHiHBB8s", 0x0800, 0, IFINDEX[owner], 1, 1, 6, mac(MACS[owner]) + b"\0\0")
    return header + packet


def _server_options(client: str) -> list[tuple[int, bytes]]:
    return [(54, ip4(ROUTER)), (51, struct.pack("!I", LEASE_SECONDS)), (1, ip4("255.255.255.0")),
            (3, ip4(ROUTER)), (6, ip4(ROUTER)), (15, LAN_ZONE.encode()),
            (58, struct.pack("!I", LEASE_SECONDS // 2)), (59, struct.pack("!I", LEASE_SECONDS * 7 // 8))]


def _dhcp_session(rng: random.Random) -> list[bytes]:
    """One DHCP conversation, of whichever kind comes up."""
    client = rng.choice([PHONE, PHONE, TV, PRINTER, LAPTOP, NAS])
    client_mac, xid = mac(MACS[client]), rng.randrange(1 << 32)
    name = HOSTNAMES[client].encode()
    wanted = (55, bytes([1, 3, 6, 15, 31, 33, 43, 44, 46, 47, 119, 121, 249, 252]))
    # Option 81: the client asks the server to register its name for it.
    fqdn = (81, b"\x01\x00\x00" + f"{HOSTNAMES[client]}.{LAN_ZONE}".encode())
    kind = rng.choice(["join", "join", "renew", "renew", "inform", "nak", "release"])
    if kind == "join":
        return [
            _from_unconfigured(client, _dhcp(1, xid, client_mac, _dhcp_options(
                DISCOVER, (61, b"\x01" + client_mac), (12, name), wanted))),
            _udp(ROUTER, client, 67, 68, _dhcp(2, xid, client_mac, _dhcp_options(
                OFFER, *_server_options(client)), yiaddr=client, siaddr=ROUTER)),
            _from_unconfigured(client, _dhcp(1, xid, client_mac, _dhcp_options(
                REQUEST, (61, b"\x01" + client_mac), (50, ip4(client)), (54, ip4(ROUTER)), (12, name), fqdn, wanted))),
            _udp(ROUTER, client, 67, 68, _dhcp(2, xid, client_mac, _dhcp_options(
                ACK, *_server_options(client), fqdn), yiaddr=client, siaddr=ROUTER)),
        ]
    if kind == "renew":
        return [
            _udp(client, ROUTER, 68, 67, _dhcp(1, xid, client_mac, _dhcp_options(
                REQUEST, (61, b"\x01" + client_mac), (12, name), fqdn, wanted), ciaddr=client)),
            _udp(ROUTER, client, 67, 68, _dhcp(2, xid, client_mac, _dhcp_options(
                ACK, *_server_options(client), fqdn), ciaddr=client, yiaddr=client, siaddr=ROUTER)),
        ]
    if kind == "inform":
        return [
            _udp(client, ROUTER, 68, 67, _dhcp(1, xid, client_mac, _dhcp_options(
                INFORM, (61, b"\x01" + client_mac), (12, name), (60, b"MSFT 5.0"), wanted), ciaddr=client)),
            _udp(ROUTER, client, 67, 68, _dhcp(2, xid, client_mac, _dhcp_options(
                ACK, (54, ip4(ROUTER)), (1, ip4("255.255.255.0")), (3, ip4(ROUTER)), (6, ip4(ROUTER)),
                (15, LAN_ZONE.encode())), ciaddr=client)),
        ]
    if kind == "nak":
        # Asking to keep an address from another network: refused.
        return [
            _from_unconfigured(client, _dhcp(1, xid, client_mac, _dhcp_options(
                REQUEST, (61, b"\x01" + client_mac), (50, ip4("192.168.0.57")), (12, name), wanted))),
            _udp(ROUTER, client, 67, 68, _dhcp(2, xid, client_mac, _dhcp_options(
                NAK, (54, ip4(ROUTER)), (56, b"wrong network")), broadcast=True)),
        ]
    return [_udp(client, ROUTER, 68, 67, _dhcp(1, xid, client_mac, _dhcp_options(
        RELEASE, (54, ip4(ROUTER)), (61, b"\x01" + client_mac)), ciaddr=client))]


def _web(rng: random.Random, client: str, sport: int) -> list[bytes]:
    name, server = rng.choice(SITES)
    frames = _ask(rng, client, ROUTER, _q(name, A), answers=[_rr(name, A, ip4(server))])
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
         "refused", "retransmit", "fragments", "unreachable", "k8s", "dns", "srv", "soa", "ddns"]
WEIGHTS = [5, 4, 2, 2, 3, 3, 2, 4, 2, 1, 3, 2, 2, 3, 2, 1, 1, 3, 6, 4, 2, 4]


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
        return _dhcp_session(rng)
    if kind == "dns":
        return _lookup(rng, rng.choice([LAPTOP, PHONE, TV, NAS]))
    if kind == "srv":
        return _srv_lookup(rng, rng.choice([LAPTOP, LAPTOP, PHONE]))
    if kind == "soa":
        return _soa_lookup(rng, rng.choice([LAPTOP, NAS]), rng.choice([LAN_ZONE, "example.com", "corp.example.com"]))
    if kind == "ddns":
        return _dynamic_update(rng, rng.choice([LAPTOP, LAPTOP, PRINTER, NAS, TV]))
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
    if kind == "k8s":
        # A pod resolves a service, calls another pod's JSON API, and that pod
        # calls out to the internet.
        body = b'{"status":"ok","items":[1,2,3]}'
        frames = [_udp(POD_WEB, CLUSTER_DNS, sport, 53, dns_query("api.default.svc.cluster.local"))]
        frames += _handshake(POD_WEB, POD_API, sport + 1, 8080)
        frames.append(_tcp(POD_WEB, POD_API, sport + 1, 8080,
                           b"GET /items HTTP/1.1\r\nHost: api\r\nAccept: application/json\r\n\r\n"))
        frames.append(_tcp(POD_API, POD_WEB, 8080, sport + 1,
                           b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                           + str(len(body)).encode() + b"\r\n\r\n" + body))
        name, server = rng.choice(SITES)
        frames += _handshake(POD_API, server, sport + 2, 443)
        frames.append(_tcp(POD_API, server, sport + 2, 443, tls_client_hello(name)))
        return frames
    return [_arp(rng.choice([LAPTOP, PHONE, TV]), ROUTER)]


def build(seed: int = 7, sessions: int = 190) -> bytes:
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
