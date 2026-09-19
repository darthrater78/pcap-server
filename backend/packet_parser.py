from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
from array import array
from pathlib import Path
from xml.etree import ElementTree

from backend.models import (
    Conversation,
    ConversationEndpoint,
    DisplayFilterError,
    FILTER_FORBIDDEN,
    FILTER_MAX_LEN,
    FollowStreamResult,
    FollowStreamSegment,
    PACKET_FIELD_RE,
    PacketDetail,
    PacketSummary,
    ProtocolHierarchyNode,
    validate_display_filter,
)
from backend.pcapsource import PcapSource

logger = logging.getLogger(__name__)




async def _run_tool(cmd: list[str], source: PcapSource) -> tuple[bytes, bytes, int]:
    """Run a pcap tool with the capture on stdin.

    Every tool used here (tshark, capinfos) reads "-" as stdin, which is what
    keeps a decrypted capture out of the filesystem entirely -- it exists only
    as chunks in flight between this process and the tool.

    stdin is an explicit os.pipe(), never stdin=PIPE. Wiretap -- the library
    behind both tools -- accepts a regular file or a FIFO and rejects anything
    else outright:

        tshark: The standard input is a "special file" or socket or other
        non-regular file.

    asyncio's PIPE is a real pipe, so that check passes. uvloop's is a Unix
    socketpair, so it does not, and uvloop is what the container runs. Every
    tshark call returned nothing and every capinfos call returned no count,
    which is why a capture that downloaded and opened perfectly well showed an
    empty packet list and a packet count of zero.

    The pipe is fed by a separate task while stdout is drained, because a
    capture larger than the pipe buffer would otherwise deadlock: the writer
    blocks on a full stdin pipe while the reader waits for output that cannot
    come.
    """
    read_fd, write_fd = os.pipe()
    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=read_fd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        finally:
            # The child holds its own duplicate. Leaving this end open in the
            # parent means the tool never sees EOF and waits for input forever.
            os.close(read_fd)
    except BaseException:
        os.close(write_fd)
        raise

    async def feed() -> None:
        try:
            async for chunk in source.chunks():
                # A blocking write on a full pipe parks a worker thread, not the
                # event loop. os.write is not guaranteed to take the whole chunk.
                await asyncio.to_thread(_write_all, write_fd, chunk)
        except (BrokenPipeError, ConnectionResetError):
            # Normal when the tool stops early, e.g. tshark with -c.
            pass
        finally:
            try:
                os.close(write_fd)
            except OSError:
                pass

    feeder = asyncio.create_task(feed())
    stdout, stderr = await proc.communicate()
    feed_error = None
    try:
        await feeder
    except Exception as exc:  # noqa: BLE001 - re-raised below with context
        feed_error = exc

    if feed_error is not None:
        # The tool saw truncated input or none at all, so whatever it printed is
        # not trustworthy. Failing loudly beats returning a plausible empty result.
        logger.error("failed while feeding %s: %s", cmd[0], feed_error)
        raise RuntimeError(f"could not supply capture data to {cmd[0]}") from feed_error

    return stdout, stderr, proc.returncode or 0


async def spawn_tool(
    cmd: list[str],
    source: PcapSource,
    *,
    limit: int | None = None,
) -> tuple[asyncio.subprocess.Process, asyncio.Task]:
    """Start a pcap tool reading the capture on stdin, for a caller that streams.

    _run_tool collects everything the tool prints; this hands back the running
    process for a caller that reads its output as it comes, and the task
    feeding it, which the caller must pass to reap_tool when done. Same
    os.pipe() stdin and same separate feeder as _run_tool, for the same reasons.

    `limit` raises the per-line bound on proc.stdout.readline() for tools
    whose output lines can be long.
    """
    read_fd, write_fd = os.pipe()
    try:
        try:
            kwargs = {"limit": limit} if limit else {}
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=read_fd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **kwargs,
            )
        finally:
            os.close(read_fd)
    except BaseException:
        os.close(write_fd)
        raise

    async def feed() -> None:
        try:
            async for chunk in source.chunks():
                await asyncio.to_thread(_write_all, write_fd, chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                os.close(write_fd)
            except OSError:
                pass

    return proc, asyncio.create_task(feed())


async def reap_tool(proc: asyncio.subprocess.Process, feeder: asyncio.Task) -> None:
    """Stop whatever spawn_tool started that is still running.

    A client that disconnects mid-download leaves both the tool and its feeder
    running; this is what ends them.
    """
    if not feeder.done():
        feeder.cancel()
    if proc.returncode is None:
        proc.kill()
    await asyncio.gather(feeder, proc.wait(), return_exceptions=True)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


async def get_packet_count(source: PcapSource) -> int:
    """The capture's packet count, or a raised error -- never a silent zero.

    This used to return 0 both for an empty capture and for a capinfos that
    never ran, which is indistinguishable to every caller and hid the socketpair
    failure above for an entire release.
    """
    stdout, stderr, rc = await _run_tool(["capinfos", "-c", "-M", "-"], source)
    for line in stdout.decode(errors="replace").splitlines():
        if "Number of packets" in line:
            parts = line.split(":")
            if len(parts) == 2:
                return int(parts[1].strip())
    detail = stderr.decode(errors="replace").strip()[:300] or f"exit status {rc}"
    raise RuntimeError(f"capinfos reported no packet count: {detail}")


# tcpdump-style view flags, mapped onto how tshark renders the packet list.
# Only flags that genuinely change this view are accepted.
VIEW_FLAG_TIME_FIELD = {
    "-tt": "frame.time_epoch",
    "-ttt": "frame.time_delta",
    "-tttt": "frame.time",
    # Epoch seconds, formatted into a real date and time by the browser. tshark's
    # own frame.time is the capture host's local time, and this container runs on
    # UTC with no idea what zone the operator reading the capture is in -- the
    # browser is the only place that knows, so it does the formatting.
    "-tz": "frame.time_epoch",
}
ALLOWED_VIEW_FLAGS = {"-e", "-t", *VIEW_FLAG_TIME_FIELD}

# Columns the operator has added to the packet list beyond the built-in ones:
# any tshark field, fetched as one more `-e` on the pass the list already runs.
# PACKET_FIELD_RE (models.py, where the layout models share it) is what keeps a
# name out of argv's flag space.
#
# Per request. Each one is another column tshark prints for every packet; the
# ceiling is a stop on a caller scripting the query, not a limit anyone reaches
# by adding columns to a table they have to read.
MAX_EXTRA_COLUMNS = 12

# Fields the built-in columns need, up to and including _ws.col.Info. The MAC
# fields follow when -e is set, and the operator's own columns after those.
_BASE_FIELD_COUNT = 20

# The network-layer address fields, IPv4 then IPv6. These never resolve,
# whatever -N says (the resolved value lives in the separate *_host fields), so
# with names on they are what a row's "Source IP" column and every filter built
# from a diagram read: a display filter has to compare ip.addr to an address,
# and a hostname there is a filter tshark refuses.
_ADDRESS_FIELDS = ["-e", "ip.src", "-e", "ip.dst", "-e", "ipv6.src", "-e", "ipv6.dst"]


# A pcapng file (what Wireshark saves) can say, per packet, which interface it
# was captured on and which way it went. Read beside the Linux cooked header's
# own fields: an upload has those instead of sll.ifindex/sll.pkttype.
_PCAPNG_FIELDS = ["-e", "frame.packet_flags_direction", "-e", "frame.interface_name"]
_PCAPNG_DIRECTION = {"1": "in", "2": "out"}

# Whether a packet is an IP fragment, from the header itself. Info cannot say:
# on the fragment that completes a datagram, tshark prints the reassembled
# datagram's summary ("5004 -> 5004 Len=2000"), which reads like any packet.
_FRAGMENT_FIELDS = ["-e", "ip.flags.mf", "-e", "ip.frag_offset", "-e", "ipv6.fraghdr.nxt"]


def _is_fragment(mf: str, offset: str, v6_fraghdr: str) -> bool:
    return mf in ("1", "True") or offset not in ("", "0") or bool(v6_fraghdr)


class SubnetMap:
    """The operator's subnet -> interface table for a capture (models.SubnetMapping).

    For a packet with no interface of its own, the interface is the one whose
    subnet the packet's addresses sit in, most specific subnet first, and its
    direction is what a capture on the box itself would have said: leaving
    toward a mapped subnet is "out" on that subnet's interface, arriving from
    one is "in". A packet routed between two mapped subnets is shown where it
    leaves -- out on the destination's. A direction the pcapng recorded wins
    over that guess; the subnets then only say which interface.
    """

    def __init__(self, mappings: list[dict] | None):
        nets = []
        for m in mappings or []:
            try:
                nets.append((ipaddress.ip_network(m["cidr"], strict=False), str(m["name"])))
            except (KeyError, TypeError, ValueError):
                continue
        self._nets = sorted(nets, key=lambda n: n[0].prefixlen, reverse=True)
        self._cache: dict[str, str] = {}

    def __bool__(self) -> bool:
        return bool(self._nets)

    def name_for(self, address: str) -> str:
        if not address:
            return ""
        if address in self._cache:
            return self._cache[address]
        name = ""
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            ip = None
        if ip is not None:
            for net, iface in self._nets:
                if ip.version == net.version and ip in net:
                    name = iface
                    break
        if len(self._cache) < 50000:
            self._cache[address] = name
        return name

    def place(self, src: str, dst: str, recorded: str) -> tuple[str, str]:
        """(interface, direction) for one packet, or ("", recorded) unmapped."""
        s, d = self.name_for(src), self.name_for(dst)
        if recorded == "out" and (d or s):
            return d or s, "out"
        if recorded == "in" and (s or d):
            return s or d, "in"
        if d:
            return d, "out"
        if s:
            return s, "in"
        return "", recorded


def _place_packet(
    ifindex: int, pkttype: str, names: dict[int, str], flag: str, pcapng_iface: str,
    src_addr: str, dst_addr: str, smap: SubnetMap | None,
) -> tuple[str, str]:
    """A packet's interface and direction, from the best evidence it carries:
    the Linux cooked header ("any" captures), then the subnet map, then what a
    pcapng recorded."""
    if ifindex:
        return _interface(ifindex, names), _SLL_DIRECTION.get(pkttype, "")
    # Cooked v1 records a direction but no interface; pcapng may record one.
    recorded = _SLL_DIRECTION.get(pkttype, "") or _PCAPNG_DIRECTION.get(flag, "")
    if smap:
        iface, direction = smap.place(src_addr, dst_addr, recorded)
        if iface:
            return iface, direction
    return pcapng_iface[:64], recorded


def _address_pair(v4src: str, v4dst: str, v6src: str, v6dst: str) -> tuple[str, str]:
    """A packet's source and destination address, or ("", "") without an IP layer."""
    return (v4src or v6src), (v4dst or v6dst)

# How tshark complains about a `-e` it does not recognise: "Some fields aren't
# valid: nope.nope" on current builds, "isn't a valid field" on older ones.
_NOT_A_FIELD = re.compile(r"field[s]?\b.{0,20}\b(?:aren't|isn't|not) valid|isn't a valid", re.I)


class ColumnFieldError(ValueError):
    """A requested column names a field this tshark does not dissect."""

# Name resolution is a single explicit opt-in, not a pair of tcpdump-style
# flags, because tcpdump's -n/-nn distinction cannot be expressed in this view:
#
#   * tshark's Info column prints ports numerically whatever the resolution
#     settings say -- verified against a capture on port 80, where -N mt and -n
#     produce byte-identical output. So "ports named" has nowhere to appear.
#   * Host names need nameres.network_name AND
#     nameres.use_external_name_resolver. -N mnt alone changes nothing; the
#     hosts file is only consulted when the external resolver is enabled too.
#
# So the only resolution that alters this view is host lookup, and that sends a
# reverse-DNS query for every address in the capture. On a tool used to examine
# suspicious traffic, that tells the resolver what is being investigated -- so
# it is off unless the operator asks for it, and the UI says what it does.
#
# The `d` in the -N flags is what makes resolution work on a stored pcap at all,
# and it was missing. -N's letters are the COMPLETE set of resolutions tshark
# will perform -- not additions to the defaults -- so `mnt` silently switched
# OFF the nameres.dns_pkt_addr_resolution that ships enabled, which is the one
# source that needs no network: the names in the capture's own DNS answers.
# Everything else about the flags was right and did nothing, because a pcap
# server reading someone else's traffic usually has no reverse-DNS for those
# addresses and often no resolver at all.
#
# Measured on a two-frame pcap (a DNS A answer for host.example.com, then a TCP
# frame to that address): under -N mnt the destination column reads 10.0.0.9,
# under -N mntd it reads host.example.com.
_RESOLVE_OFF = ["-n"]
_RESOLVE_ON = [
    "-N", "mntd",
    "-o", "nameres.network_name:TRUE",
    "-o", "nameres.use_external_name_resolver:TRUE",
    # Explicit rather than relying on the shipped default, so the behaviour
    # -N's `d` asks for cannot be turned off by a profile this container picks
    # up. The two settings are a pair: `d` selects the resolution, this enables
    # the source it reads from.
    "-o", "nameres.dns_pkt_addr_resolution:TRUE",
]


def _name_resolution_args(resolve_names: bool) -> list[str]:
    return list(_RESOLVE_ON if resolve_names else _RESOLVE_OFF)


# Names this tshark has confirmed it knows. Only confirmations are kept: a name
# that was wrong once is cheap to ask about again, while caching the negative
# would outlive a dissector the image gains on its next build. Bounded, because
# an authenticated caller can ask about as many distinct names as it likes.
_KNOWN_FIELDS: set[str] = set()
_KNOWN_FIELDS_LIMIT = 2000
_FIELD_REGISTRY_LOCK: asyncio.Lock | None = None


async def unknown_packet_fields(fields: list[str]) -> list[str]:
    """Which of these names tshark does not recognise, asked of tshark itself.

    `tshark -G fields` is its dissector registry -- the same list Wireshark's
    own "Custom" column type offers -- so a name checked against it is one that
    will still be a column when the pass actually runs, rather than one that
    fails at list time with a message about an invalid field.

    Called when a layout is SAVED, not when packets are listed: the registry is
    a multi-megabyte stream and the packet list must stay cheap. The list route
    re-checks the pattern above, which is the part that matters for argv.
    """
    global _FIELD_REGISTRY_LOCK
    wanted = {f for f in fields if f not in _KNOWN_FIELDS}
    if not wanted:
        return []
    if _FIELD_REGISTRY_LOCK is None:
        _FIELD_REGISTRY_LOCK = asyncio.Lock()
    async with _FIELD_REGISTRY_LOCK:
        wanted -= _KNOWN_FIELDS
        if not wanted:
            return []
        found = await _lookup_in_registry(wanted)
        if len(_KNOWN_FIELDS) + len(found) <= _KNOWN_FIELDS_LIMIT:
            _KNOWN_FIELDS.update(found)
    return sorted(wanted - found)


async def _lookup_in_registry(wanted: set[str]) -> set[str]:
    """One streamed pass over `tshark -G fields`, looking for these names."""
    found: set[str] = set()
    proc = await asyncio.create_subprocess_exec(
        "tshark", "-G", "fields",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=1024 * 1024,
    )
    try:
        async for raw_line in proc.stdout:
            parts = raw_line.decode("utf-8", "replace").rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            # F lines are fields (abbrev in column 2); P lines are protocols,
            # whose filter name is a usable column of its own -- `-e tcp` is
            # what Wireshark's own protocol columns are built from.
            if parts[0] in ("F", "P") and parts[2] in wanted:
                found.add(parts[2])
                if found == wanted:
                    break
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        raise
    finally:
        # Broken out of early on a match, so the pipe may still be full: killing
        # rather than waiting on a process nobody is reading from any more.
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
    return found


def validate_column_fields(fields: list[str]) -> list[str]:
    """The pattern check and the per-request cap, deduplicated, order kept.

    Raises ValueError rather than returning a verdict: every caller wants the
    request refused, and a silently dropped column is a column the operator
    added and never saw.
    """
    unique = list(dict.fromkeys(fields))
    if len(unique) > MAX_EXTRA_COLUMNS:
        raise ValueError(
            f"at most {MAX_EXTRA_COLUMNS} added columns, asked for {len(unique)}"
        )
    for field in unique:
        if not PACKET_FIELD_RE.match(field):
            raise ValueError(f"not a tshark field name: {field!r}")
    return unique


async def get_packet_list(
    source: PcapSource,
    offset: int = 0,
    limit: int = 200,
    display_filter: str = "",
    view_flags: list[str] | None = None,
    resolve_names: bool = False,
    interface_names: dict[int, str] | None = None,
    extra_fields: list[str] | None = None,
    subnet_map: list[dict] | None = None,
    copies: InterfaceCopies | None = None,
) -> list[PacketSummary]:
    flags = set(view_flags or [])
    extra = validate_column_fields(list(extra_fields or []))
    time_field = "frame.time_relative"
    for flag, field in VIEW_FLAG_TIME_FIELD.items():
        if flag in flags:
            time_field = field
            break
    show_time = "-t" not in flags
    show_mac = "-e" in flags

    cmd = ["tshark", "-r", "-"]
    cmd += _name_resolution_args(resolve_names)
    cmd += [
        "-T", "fields",
        "-e", "frame.number",
        "-e", time_field,
        "-e", "_ws.col.Source",
        "-e", "_ws.col.Destination",
        "-e", "frame.protocols",
        "-e", "frame.len",
        # Before Info, so the one free-text column stays last but for the MACs.
        "-e", "sll.ifindex",
        "-e", "sll.pkttype",
        # What Follow Stream needs to offer itself from a row's own right-click
        # menu, without first opening the packet's detail pane to find it --
        # empty on every packet outside a TCP or UDP conversation.
        "-e", "tcp.stream",
        "-e", "udp.stream",
        *_ADDRESS_FIELDS,
        *_PCAPNG_FIELDS,
        *_FRAGMENT_FIELDS,
        "-e", "_ws.col.Info",
    ]
    if show_mac:
        # sll.src.eth as well as eth.src: "tcpdump -i any" produces a Linux
        # cooked capture, which has no Ethernet header, so eth.src and eth.dst
        # are both empty on it. Since "any" is the default interface, -e showed
        # two blank columns for most captures. The cooked header records the
        # sender's address but no destination, so that column stays empty and
        # the flag's help says why.
        cmd += ["-e", "eth.src", "-e", "eth.dst", "-e", "sll.src.eth"]
    # Last, so a column the operator added never shifts the positions the
    # built-in ones are read from.
    for field in extra:
        cmd += ["-e", field]
    cmd += [
        "-E", "separator=\t",
        "-E", "quote=n",
        "-E", "occurrence=f",
    ]
    if display_filter:
        _validate_display_filter(display_filter)
        cmd += ["-Y", display_filter]

    stdout, stderr, rc = await _run_tool(cmd, source)
    if rc != 0:
        logger.warning("tshark stderr: %s", stderr.decode(errors="replace")[:500])
        # Checked before the filter, because a run carrying both a filter and a
        # bad field would otherwise be reported as a filter this tool cannot
        # parse -- which is a message about the wrong thing entirely.
        if extra and _NOT_A_FIELD.search(stderr.decode(errors="replace")):
            # tshark refuses the whole run over one `-e` it does not recognise.
            # A layout saved against an image whose tshark dissected a field
            # this one does not must say so: the alternative is the empty list
            # that means "nothing matched", about a column nobody can see.
            raise ColumnFieldError(_filter_rejection(stderr))
        if display_filter:
            # A valid filter that matches nothing still exits 0, so a non-zero
            # exit with a filter present means the filter is the problem.
            raise DisplayFilterError(_filter_rejection(stderr))

    expected = _BASE_FIELD_COUNT + (3 if show_mac else 0) + len(extra)
    smap = SubnetMap(subnet_map)
    packets = []
    for line in stdout.decode(errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < _BASE_FIELD_COUNT:
            continue
        # Taken from the END rather than by counting forward: the Info column is
        # free text in the middle of the row, and a tab inside it would shift
        # every position after it. The built-in columns have always read forward
        # and are left alone, but a column the operator added is new ground and
        # can be read from the side of the row nothing shifts.
        values = (
            dict(zip(extra, parts[len(parts) - len(extra):]))
            if extra and len(parts) >= expected
            else {}
        )
        num = int(parts[0])
        if num <= offset:
            continue
        if len(packets) >= limit:
            break

        protocol = parts[4].split(":")[-1] if parts[4] else "?"
        # Empty unless the capture is Linux cooked v2, which is "any".
        ifindex = int(parts[6]) if parts[6].isascii() and parts[6].isdigit() else 0
        src_addr, dst_addr = _address_pair(*parts[10:14])
        iface, direction = _place_packet(
            ifindex, parts[7], interface_names or {}, parts[14], parts[15], src_addr, dst_addr, smap,
        )
        # An unchanged copy reads as its own link would show it, not as the
        # retransmission tshark's whole-file analysis took it for.
        link_info = copies.info_on_link(num, parts[19]) if copies else None
        packets.append(PacketSummary(
            number=num,
            timestamp=parts[1] if show_time else "",
            source=parts[2] or "N/A",
            destination=parts[3] or "N/A",
            protocol=protocol.upper(),
            length=int(parts[5]) if parts[5] else 0,
            info=parts[19] if link_info is None else link_info,
            fragment=_is_fragment(*parts[16:19]),
            src_mac=_mac(parts, 20, 22) if show_mac else "",
            dst_mac=_mac(parts, 21) if show_mac else "",
            source_addr=src_addr,
            destination_addr=dst_addr,
            interface=iface,
            ifindex=ifindex,
            direction=direction,
            tcp_stream=int(parts[8]) if parts[8].isdigit() else None,
            udp_stream=int(parts[9]) if parts[9].isdigit() else None,
            copy_of=copies.original(num) if copies else 0,
            copy_nat=copies.translated(num) if copies else False,
            copy_link_view=link_info is not None,
            values=values,
        ))

    return packets


# --- one packet, seen on more than one interface ------------------------------
#
# A capture on several interfaces -- or on "any" -- sees a routed or bridged
# packet once per link it crosses: in on eth0, out on eth1. tshark's TCP
# analysis has no notion of interfaces, so it reads the second sighting as a
# retransmission (a data segment) or a duplicate ACK (a bare ACK), and a
# healthy routed conversation came out of the Traffic Diagram as half
# problems. Measured on a hand-built SLL2 capture of a forwarded HTTP fetch:
# every forwarded frame was flagged.
#
# A sighting is a copy when an IP packet identical in everything a router
# leaves alone -- addresses, IP ID, length, ports, TCP sequence, ack, flags,
# transport checksum -- was seen on a DIFFERENT interface moments before. The
# interface set is kept per instance: a sighting on an interface that already
# saw this instance starts a new one, which is what a genuine retransmission
# or repeated duplicate ACK is (IPv6 has no IP ID to tell them apart, and
# needs none this way).
#
# NAT rewrites one address (and the checksums with it), so a NATed hop is
# matched separately: IPv4 only, by IP ID (which NAT keeps), length, protocol
# and TCP sequence, ack and flags, with the untranslated address the same on
# both. tshark reads each side as a conversation of its own, so its flags on
# a translated copy are right for that side -- but the same duplicate ACK is
# not two duplicate ACKs. A zero IP ID says nothing on its own, so outside
# TCP it is never matched.
_COPY_WINDOW_SECONDS = 1.0
_COPY_PRUNE_EVERY = 50_000
_COPY_FIELDS = [
    "-e", "frame.number", "-e", "frame.time_epoch",
    "-e", "sll.ifindex", "-e", "frame.interface_id",
    *_ADDRESS_FIELDS,
    "-e", "ip.id", "-e", "ip.len", "-e", "ipv6.plen", "-e", "ip.proto", "-e", "ipv6.nxt",
    "-e", "tcp.srcport", "-e", "tcp.dstport", "-e", "tcp.seq_raw", "-e", "tcp.ack_raw",
    "-e", "tcp.flags", "-e", "tcp.checksum",
    "-e", "udp.srcport", "-e", "udp.dstport", "-e", "udp.checksum",
    "-e", "icmp.checksum", "-e", "icmpv6.checksum",
]


_TRANSLATED = 1 << 31


class InterfaceCopies:
    """Which frames of a capture are second sightings, and of which frame.

    One unsigned int per frame (0: not a copy; the top bit marks a copy whose
    addresses NAT rewrote), so a million-frame capture is 4 MB, whatever
    display filter a caller later reads it through.

    And, for an unchanged copy, what tshark says about it on its own link
    (find_interface_copies): `link_view` marks the frames that were read that
    way, `link_info` holds the Info of those it flagged.
    """

    __slots__ = ("_of", "count", "link_view", "link_info")

    def __init__(self, originals: "array", count: int) -> None:
        self._of = originals
        self.count = count
        self.link_view = bytearray()
        self.link_info: dict[int, str] = {}

    def info_on_link(self, number: int, combined: str) -> str | None:
        """An unchanged copy's Info as a capture of its own link reads it, or
        None when that was not worked out (the combined Info then stands)."""
        if number >= len(self.link_view) or not self.link_view[number]:
            return None
        return self.link_info.get(number) or _ANALYSIS_PREFIX.sub("", combined)

    def _raw(self, number: int) -> int:
        return self._of[number] if 0 <= number < len(self._of) else 0

    def original(self, number: int) -> int:
        return self._raw(number) & ~_TRANSLATED

    def translated(self, number: int) -> bool:
        return bool(self._raw(number) & _TRANSLATED)


# tshark's own analysis notes at the start of Info: "[TCP Retransmission] ".
_ANALYSIS_PREFIX = re.compile(r"^(?:\[TCP [^\]]*\] )+")

# Links read on their own for their copies' sake; past this many the copies
# fall back to their first sighting's verdict.
_LINK_VIEWS_MAX = 8


class _LinkSource(PcapSource):
    """One link's packets of a capture, as a capture of their own."""

    def __init__(self, source: PcapSource, display_filter: str) -> None:
        self._source = source
        self._filter = display_filter

    async def chunks(self):
        async for chunk in stream_filtered_pcap(self._source, self._filter):
            yield chunk

    async def size(self) -> int:
        raise NotImplementedError


async def _read_link_views(
    source: PcapSource, copies: InterfaceCopies, frames: dict[str, "array"], links: set[str],
) -> None:
    """What tshark says about each unchanged copy on its own link.

    Its analysis of the whole file is wrong about them (see above); a capture
    of just that link is what it would have had to go on, and on the
    downstream link it is the only thing that sees a segment the box dropped
    ("previous segment not captured"). One filtered pass per link that has
    copies; the link's k-th packet is the k-th frame the copy pass saw on it.
    """
    for link in sorted(links)[:_LINK_VIEWS_MAX]:
        kind, value = link[0], int(link[1:])
        link_filter = f"sll.ifindex == {value}" if kind == "i" else f"frame.interface_id == {value}"
        numbers = frames[link]
        cmd = ["tshark", "-r", "-", "-n", "-T", "fields", "-e", "_ws.col.Info",
               "-E", "separator=\t", "-E", "quote=n"]
        proc, feeder = await spawn_tool(cmd, _LinkSource(source, link_filter), limit=1024 * 1024)
        stderr_task = asyncio.create_task(proc.stderr.read())
        try:
            k = 0
            while (line := await proc.stdout.readline()) and k < len(numbers):
                number = numbers[k]
                k += 1
                raw = copies._raw(number)
                if not raw or raw & _TRANSLATED:
                    continue
                if number >= len(copies.link_view):
                    copies.link_view.extend(bytes(number + 1 - len(copies.link_view)))
                copies.link_view[number] = 1
                info = line.decode(errors="replace").rstrip("\n")
                if info.startswith("[TCP "):
                    copies.link_info[number] = info[:DIAGRAM_INFO_MAX]
            await stderr_task
            await proc.wait()
        finally:
            await reap_tool(proc, feeder)
            if not stderr_task.done():
                stderr_task.cancel()


async def find_interface_copies(source: PcapSource) -> InterfaceCopies:
    """One pass over the whole capture, never through a display filter: a
    filter that keeps the copy and drops the first sighting (`sll.ifindex ==
    3`, `tcp.analysis.retransmission`) must still see it marked a copy.

    Reassembly is off: each frame is judged by its own headers, and the pass
    costs less. Then each link that carries copies is read on its own
    (_read_link_views).
    """
    cmd = [
        "tshark", "-r", "-", "-n",
        "-o", "tcp.analyze_sequence_numbers:FALSE",
        "-o", "tcp.desegment_tcp_streams:FALSE",
        "-o", "ip.defragment:FALSE",
        "-o", "ipv6.defragment:FALSE",
        "-T", "fields", *_COPY_FIELDS,
        "-E", "separator=\t", "-E", "quote=n", "-E", "occurrence=f",
    ]
    originals = array("I", [0])
    count = 0
    # key -> [last seen, first frame of this instance, interfaces it was seen on]
    seen: dict[tuple, list] = {}
    # The same for NAT, keyed without addresses; the instance also keeps them.
    nat_seen: dict[tuple, list] = {}
    # Every frame's number, per link, in order: how a link's own capture is
    # lined up with this one afterwards.
    frames: dict[str, array] = {}
    copy_links: set[str] = set()
    lines = 0
    proc, feeder = await spawn_tool(cmd, source)
    stderr_task = asyncio.create_task(proc.stderr.read())
    try:
        while line := await proc.stdout.readline():
            parts = line.decode(errors="replace").rstrip("\n").split("\t")
            if len(parts) < len(_COPY_FIELDS) // 2 or not parts[0].isdigit():
                continue
            number = int(parts[0])
            if number >= 2**32:
                continue
            while len(originals) <= number:
                originals.append(0)
            iface = f"i{parts[2]}" if parts[2].isdigit() else f"n{parts[3] if parts[3].isdigit() else 0}"
            frames.setdefault(iface, array("I")).append(number)
            src, dst = _address_pair(*parts[4:8])
            if not src:
                continue
            try:
                when = float(parts[1])
            except ValueError:
                continue
            key = (src, dst, *parts[8:])
            state = seen.get(key)
            # ip.id, ip.len, ip.proto, then tcp seq, ack and flags. ip.src
            # set means IPv4 (occurrence=f: the outer header of a tunnel).
            # A zero IP ID (Linux sends SYN-ACKs so) is matched only on TCP,
            # whose sequence and ack numbers say enough on their own.
            nat_key = (parts[8], parts[9], parts[11], *parts[15:18]) \
                if parts[4] and parts[8] and (int(parts[8], 0) or parts[15]) else None
            nat = nat_seen.get(nat_key) if nat_key else None
            if state and when - state[0] <= _COPY_WINDOW_SECONDS and iface not in state[2]:
                originals[number] = state[1]
                count += 1
                state[0] = when
                state[2].add(iface)
                copy_links.add(iface)
            elif (nat and when - nat[0] <= _COPY_WINDOW_SECONDS and iface not in nat[2]
                  and (src, dst) != (nat[3], nat[4]) and (src == nat[3] or dst == nat[4])):
                originals[number] = nat[1] | _TRANSLATED
                count += 1
                nat[0] = when
                nat[2].add(iface)
            else:
                seen[key] = [when, number, {iface}]
                if nat_key:
                    nat_seen[nat_key] = [when, number, {iface}, src, dst]
            lines += 1
            if lines % _COPY_PRUNE_EVERY == 0:
                seen = {k: v for k, v in seen.items() if when - v[0] <= _COPY_WINDOW_SECONDS}
                nat_seen = {k: v for k, v in nat_seen.items() if when - v[0] <= _COPY_WINDOW_SECONDS}
        stderr = await stderr_task
        await proc.wait()
    finally:
        await reap_tool(proc, feeder)
        if not stderr_task.done():
            stderr_task.cancel()
    if proc.returncode not in (0, None):
        logger.warning("tshark stderr: %s", stderr.decode(errors="replace")[:500])
        raise RuntimeError("tshark failed reading the capture for repeat sightings")
    copies = InterfaceCopies(originals, count)
    if copy_links:
        try:
            await _read_link_views(source, copies, frames, copy_links)
        except Exception:
            # The marks stand without it; copies then keep their first
            # sighting's verdict.
            logger.warning("could not read links on their own for repeat sightings", exc_info=True)
            copies.link_view = bytearray()
            copies.link_info = {}
    return copies


# The Traffic and Sequence diagrams' packets. Their own route rather than the
# packet list's pages, for two reasons. One pass: the list's offset is a frame
# number, so a page costs a tshark run over the whole capture regardless, and
# a 100,000-packet diagram fetched 1,000 at a time was a hundred full passes
# (and three times the per-minute packet request budget). And a count of what
# the filter actually matched: the list reports the capture's own total, which
# made a filtered diagram's cap check measure the wrong thing.
DIAGRAM_INFO_MAX = 256


async def get_diagram_packets(
    source: PcapSource,
    cap: int,
    display_filter: str = "",
    resolve_names: bool = False,
    interface_names: dict[int, str] | None = None,
    subnet_map: list[dict] | None = None,
    copies: InterfaceCopies | None = None,
) -> tuple[list[dict], int, dict[str, str]]:
    """Up to `cap` packets matching the filter, how many matched in all, and names.

    Every match is counted, but only the first `cap` are kept, so memory is
    bounded by the cap and not by the capture. Over the cap, the caller still
    gets those first `cap` packets -- `matched` being larger than len(packets)
    is the caller's signal to draw them and say the picture is partial, rather
    than a reason to draw nothing.

    A packet with an IP layer is keyed by its ADDRESSES, with resolution on or
    off, exactly as get_conversations keys its nodes: a diagram builds display
    filters from these, and `ip.addr == "ec2-...amazonaws.com"` is a filter
    tshark refuses. What resolution found comes back beside them, as a map
    from address to name. Anything without an IP layer (ARP, STP) keeps the
    Source/Destination column's own text.
    """
    cmd = ["tshark", "-r", "-"]
    cmd += _name_resolution_args(resolve_names)
    cmd += [
        "-T", "fields",
        "-e", "frame.number",
        "-e", "_ws.col.Source",
        "-e", "_ws.col.Destination",
        "-e", "frame.protocols",
        "-e", "frame.len",
        "-e", "sll.ifindex",
        # Which way the packet went, on "any" captures: what tells the
        # diagram which addresses are the capturing box's own (see
        # diagrams.js detectEgress).
        "-e", "sll.pkttype",
        *_ADDRESS_FIELDS,
        *_PCAPNG_FIELDS,
        *_FRAGMENT_FIELDS,
        # Last: the one free-text column, so a tab inside it shifts nothing.
        "-e", "_ws.col.Info",
        "-E", "separator=\t",
        "-E", "quote=n",
        "-E", "occurrence=f",
    ]
    if display_filter:
        _validate_display_filter(display_filter)
        cmd += ["-Y", display_filter]

    ifnames = interface_names or {}
    smap = SubnetMap(subnet_map)
    packets: list[dict] = []
    names: dict[str, str] = {}
    matched = 0
    # An Info column can run long; the default 64 KiB line bound is not the
    # thing that should decide whether a diagram loads.
    proc, feeder = await spawn_tool(cmd, source, limit=1024 * 1024)
    # Drained alongside stdout so a chatty stderr can never fill its pipe and
    # stall the run.
    stderr_task = asyncio.create_task(proc.stderr.read())
    try:
        while line := await proc.stdout.readline():
            parts = line.decode(errors="replace").rstrip("\n").split("\t", 16)
            if len(parts) < 17 or not parts[0].isdigit():
                continue
            matched += 1
            if matched > cap:
                continue
            protocol = parts[3].split(":")[-1] if parts[3] else "?"
            ifindex = int(parts[5]) if parts[5].isascii() and parts[5].isdigit() else 0
            src, dst = parts[1] or "N/A", parts[2] or "N/A"
            src_addr, dst_addr = _address_pair(*parts[7:11])
            iface, direction = _place_packet(
                ifindex, parts[6], ifnames, parts[11], parts[12], src_addr, dst_addr, smap,
            )
            if resolve_names:
                _note_name(names, src_addr, src)
                _note_name(names, dst_addr, dst)
            number = int(parts[0])
            link_info = copies.info_on_link(number, parts[16]) if copies else None
            packets.append({
                "number": number,
                "source": src_addr or src,
                "destination": dst_addr or dst,
                "protocol": protocol.upper(),
                "length": int(parts[4]) if parts[4].isdigit() else 0,
                "interface": iface,
                "direction": direction,
                "fragment": _is_fragment(*parts[13:16]),
                "copy_of": copies.original(number) if copies else 0,
                "copy_nat": copies.translated(number) if copies else False,
                "copy_link_view": link_info is not None,
                "info": (parts[16] if link_info is None else link_info)[:DIAGRAM_INFO_MAX],
            })
        stderr = await stderr_task
        await proc.wait()
    finally:
        await reap_tool(proc, feeder)
        if not stderr_task.done():
            stderr_task.cancel()

    if proc.returncode not in (0, None):
        logger.warning("tshark stderr: %s", stderr.decode(errors="replace")[:500])
        if display_filter:
            raise DisplayFilterError(_filter_rejection(stderr))
        raise RuntimeError("tshark failed listing diagram packets")
    # matched > cap: the caller draws a diagram of the first `cap` packets
    # rather than refusing outright, and shows a truncation notice from the
    # gap between this count and len(packets) -- a picture of most of a
    # capture beats no picture at all.
    return packets, matched, names


# One name per address, and only a real one: a column that printed the address
# itself (nothing resolved) or nothing at all adds no entry. Bounded, like the
# diagram's own node cap, so a capture of a million distinct hosts cannot grow
# the map without limit.
_NAMES_MAX = 20000


def _note_name(names: dict[str, str], address: str, shown: str) -> None:
    if address and shown and shown != address and address not in names and len(names) < _NAMES_MAX:
        names[address] = shown


# The kernel's PACKET_* types as tshark prints sll.pkttype under -T fields.
_SLL_DIRECTION = {"0": "in", "1": "broadcast", "2": "multicast", "3": "other-host", "4": "out"}


def _interface(ifindex: int, names: dict[int, str]) -> str:
    if not ifindex:
        return ""
    return names.get(ifindex) or f"#{ifindex}"


def _mac(parts: list[str], *indexes: int) -> str:
    """First address present at any of these column positions.

    Ethernet and Linux-cooked captures record the address in different fields
    and never both, so the columns are requested together and whichever one the
    frame actually has wins.
    """
    for index in indexes:
        if len(parts) > index and parts[index]:
            return parts[index]
    return ""


async def get_protocol_hierarchy(
    source: PcapSource, display_filter: str = "",
) -> list[ProtocolHierarchyNode]:
    """Wireshark's Statistics > Protocol Hierarchy, built from the same
    per-packet fields the packet list already reads rather than by parsing
    tshark's own `-z io,phs` report.

    That report is formatted for a terminal -- indentation carries the tree
    structure, column widths are not fixed -- which makes it the wrong thing
    to screen-scrape when the same tree can be built directly from
    `frame.protocols` (the colon-separated layer list already used to derive
    a packet's protocol column) and `frame.len`, one line per packet, exactly
    like get_packet_list's own tshark call.
    """
    cmd = ["tshark", "-r", "-", "-T", "fields", "-e", "frame.protocols", "-e", "frame.len",
           "-E", "separator=\t", "-E", "occurrence=f"]
    if display_filter:
        _validate_display_filter(display_filter)
        cmd += ["-Y", display_filter]

    stdout, stderr, rc = await _run_tool(cmd, source)
    if rc != 0:
        logger.warning("tshark stderr: %s", stderr.decode(errors="replace")[:500])
        if display_filter:
            raise DisplayFilterError(_filter_rejection(stderr))

    # dict, not ProtocolHierarchyNode, while building: a packet's protocol
    # stack can branch (tcp:http vs tcp:tls under the same tcp), and mutating
    # the totals in place as each packet is folded in is far simpler against
    # a plain dict tree than rebuilding an immutable model on every packet.
    root: dict[str, dict] = {}
    for line in stdout.decode(errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0]:
            continue
        length = int(parts[1]) if parts[1] else 0
        node = root
        for layer in parts[0].split(":"):
            entry = node.setdefault(layer, {"frames": 0, "bytes": 0, "children": {}})
            entry["frames"] += 1
            entry["bytes"] += length
            node = entry["children"]

    def to_models(tree: dict[str, dict]) -> list[ProtocolHierarchyNode]:
        return [
            ProtocolHierarchyNode(
                name=name, frames=entry["frames"], bytes=entry["bytes"],
                children=to_models(entry["children"]),
            )
            for name, entry in tree.items()
        ]

    return to_models(root)


async def get_conversations(
    source: PcapSource, display_filter: str = "", resolve_names: bool = False,
    copies: InterfaceCopies | None = None,
) -> tuple[list[Conversation], list[ConversationEndpoint]]:
    """Wireshark's Conversations and Endpoints tabs, from one tshark pass.

    Network-layer only (IPv4 and IPv6 addresses, not port-qualified) -- the
    reasonable middle ground between "every packet has an address" (always
    meaningful) and a separate report per transport (tcp/udp/...), which
    would be four tshark calls for a distinction the address pairs already
    mostly make on their own via the ports carried in frame.protocols'
    Info column context. Built the same way as the protocol hierarchy above:
    aggregated in Python from one field-per-packet pass, not by parsing
    tshark's `-z conv,ip` text table, whose column widths are sized to the
    addresses actually present and so are not fixed across calls.

    resolve_names follows the same opt-in as get_packet_list: off by default,
    since turning it on sends a reverse-DNS query for every address in the
    capture.

    Pairs and endpoints are always keyed by ADDRESS (ip.src / ipv6.src,
    which never resolve). With resolution on, the resolved names come from the
    separate ip.src_host / ipv6.src_host fields and ride along on each
    endpoint as `name`. That is what lets the Traffic Diagram label a host by
    name while every filter it builds still says ip.addr == <address>: keying
    by name, as this used to, produced `ip.addr == "ec2-...amazonaws.com"`,
    which tshark refuses. get_diagram_packets keys its packets the same way,
    so the diagram's packet-to-node lookup still matches by string.

    A packet seen unchanged on two interfaces (`copies`) is one packet
    between its two hosts, so it counts once -- unless the filter dropped its
    first sighting, in which case the copy is the only one there is. A NATed
    copy is between a different pair, and counts there.
    """
    cmd = ["tshark", "-r", "-"]
    cmd += _name_resolution_args(resolve_names)
    cmd += ["-T", "fields", *_ADDRESS_FIELDS, "-e", "frame.len", "-e", "frame.number"]
    if resolve_names:
        cmd += ["-e", "ip.src_host", "-e", "ip.dst_host", "-e", "ipv6.src_host", "-e", "ipv6.dst_host"]
    cmd += ["-E", "separator=\t", "-E", "occurrence=f"]
    if display_filter:
        _validate_display_filter(display_filter)
        cmd += ["-Y", display_filter]

    stdout, stderr, rc = await _run_tool(cmd, source)
    if rc != 0:
        logger.warning("tshark stderr: %s", stderr.decode(errors="replace")[:500])
        if display_filter:
            raise DisplayFilterError(_filter_rejection(stderr))

    # Keyed by the pair sorted once, so the same two addresses always land in
    # the same bucket regardless of which one happened to be frame.src on a
    # given packet -- direction is still tracked, just per-packet rather than
    # baked into the key.
    pairs: dict[tuple[str, str], dict[str, int]] = {}
    endpoints: dict[str, dict[str, int]] = {}
    names: dict[str, str] = {}
    # Frames counted so far, one byte each -- only kept when there are
    # copies to decide about.
    counted = bytearray()
    for line in stdout.decode(errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        src, dst = _address_pair(*parts[:4])
        length = int(parts[4]) if parts[4] else 0
        if not src or not dst:
            continue
        if copies and copies.count and parts[5].isdigit():
            number = int(parts[5])
            original = copies.original(number)
            # A NATed copy is a pair of addresses of its own on the wire, and
            # stays; only an exact copy is the same packet counted twice.
            if original and not copies.translated(number) and original < len(counted) and counted[original]:
                continue
            if number >= len(counted):
                counted.extend(bytes(number + 1 - len(counted)))
            counted[number] = 1
        if resolve_names and len(parts) >= 10:
            host_src, host_dst = _address_pair(*parts[6:10])
            _note_name(names, src, host_src)
            _note_name(names, dst, host_dst)

        for addr in (src, dst):
            ep = endpoints.setdefault(addr, {"packets": 0, "bytes": 0})
            ep["packets"] += 1
            ep["bytes"] += length

        key = (src, dst) if src <= dst else (dst, src)
        conv = pairs.setdefault(key, {
            "packets_a_to_b": 0, "bytes_a_to_b": 0,
            "packets_b_to_a": 0, "bytes_b_to_a": 0,
        })
        if src == key[0]:
            conv["packets_a_to_b"] += 1
            conv["bytes_a_to_b"] += length
        else:
            conv["packets_b_to_a"] += 1
            conv["bytes_b_to_a"] += length

    conversations = [
        Conversation(a=a, b=b, **totals) for (a, b), totals in pairs.items()
    ]
    endpoint_list = [
        ConversationEndpoint(address=addr, name=names.get(addr, ""), **totals)
        for addr, totals in endpoints.items()
    ]
    return conversations, endpoint_list


# tshark's own header lines in a `follow,<proto>,raw` report -- everything
# that is not one of these, and not a pure hex line, is a data line.
_FOLLOW_NODE = re.compile(r"^Node ([01]): (.*)$")


async def get_follow_stream(
    source: PcapSource, protocol: str, stream: int,
) -> FollowStreamResult:
    """One TCP or UDP stream, reassembled in the order it was sent.

    `raw` mode, not `ascii` or `hex`: ascii mode replaces non-printable bytes
    with `.`, which is fine for Wireshark's own lossy preview but wrong for
    anything meant to round-trip; hex mode's byte offsets run continuously
    across consecutive same-direction frames, merging them, which loses frame
    boundaries verified NOT to matter for raw mode -- two consecutive
    same-direction frames come back as two separate lines, not one, checked
    against a real capture rather than assumed. Each line is a plain hex
    string, undecorated, tab-prefixed for the second endpoint -- the simplest
    of the three formats to parse exactly, which is the point: a Follow
    Stream view is only as trustworthy as its byte-for-byte fidelity to what
    was actually sent.
    """
    if protocol not in ("tcp", "udp"):
        # The route validates this before calling in; caught again here so a
        # future caller cannot smuggle an arbitrary -z mode into the argv
        # through this parameter, and so this function is safe to call
        # directly, not just from behind that one check.
        raise ValueError(f"unsupported protocol for follow stream: {protocol}")
    cmd = ["tshark", "-r", "-", "-q", "-z", f"follow,{protocol},raw,{stream}"]
    stdout, stderr, rc = await _run_tool(cmd, source)
    if rc != 0:
        logger.warning("tshark stderr: %s", stderr.decode(errors="replace")[:500])
        raise ValueError(f"could not follow {protocol} stream {stream}")

    node_a = node_b = ""
    segments: list[FollowStreamSegment] = []
    for line in stdout.decode(errors="replace").splitlines():
        match = _FOLLOW_NODE.match(line)
        if match:
            if match.group(1) == "0":
                node_a = match.group(2)
            else:
                node_b = match.group(2)
            continue
        from_b = line.startswith("\t")
        payload = line[1:] if from_b else line
        if payload and all(c in "0123456789abcdefABCDEF" for c in payload):
            segments.append(FollowStreamSegment(from_a=not from_b, hex=payload.lower()))

    # tshark exits 0 and prints "Node 0: :0" / "Node 1: :0" for a stream index
    # that does not exist, rather than an error -- checked against a real
    # capture. An empty address before the colon is the only signal that the
    # index was never real, since a genuine stream always has one.
    if not node_a.split(":", 1)[0]:
        raise ValueError(f"no such {protocol} stream: {stream}")

    return FollowStreamResult(protocol=protocol, stream=stream, a=node_a, b=node_b, segments=segments)


async def stream_filtered_pcap(
    source: PcapSource,
    display_filter: str,
) -> AsyncIterator[bytes]:
    """Yield a pcap containing only the packets a display filter selects.

    Streamed rather than buffered, unlike every other tool call here. A packet
    list is bounded by its own limit parameter and a PDML tree is one frame,
    but this is a whole capture minus whatever the filter removed -- reading it
    into memory to hand it to a response would put a multi-gigabyte object in
    the process just to copy it out again.

    `-F pcap` because tshark writes pcapng by default. A saved view downloads
    beside the full capture and should be the same kind of file, not a second
    format that some tools read and others do not.

    The filter is validated here as well as wherever it was stored: this is the
    function that turns it into an argument, and validation belongs next to
    the thing it protects.
    """
    validate_display_filter(display_filter)
    cmd = ["tshark", "-r", "-", "-Y", display_filter, "-w", "-", "-F", "pcap"]

    proc, feeder = await spawn_tool(cmd, source)
    try:
        while True:
            chunk = await proc.stdout.read(CHUNK_BYTES)
            if not chunk:
                break
            yield chunk
        stderr = await proc.stderr.read()
        await proc.wait()
    finally:
        await reap_tool(proc, feeder)

    if proc.returncode not in (0, None):
        raise DisplayFilterError(_filter_rejection(stderr))


# What to read off tshark's stdout at a time. Matches the crypto layer's chunk
# size so a filtered download moves in the same units the capture was sealed in.
CHUNK_BYTES = 64 * 1024


async def get_packet_detail(source: PcapSource, frame_number: int) -> PacketDetail:
    """The dissection tree for one frame, plus its raw bytes.

    PDML, not `-T json`. The JSON output gives a field's name and value and
    nothing else; PDML gives four more things the viewer cannot work without:

        <field name="tcp.srcport" showname="Source Port: 51234"
               size="2" pos="34" show="51234" value="c822"/>

    `name` and `show` are what a click turns into `tcp.srcport == 51234`.
    `pos` and `size` are what lets that same click highlight bytes 34-35 in the
    hex pane, and what lets a click in the hex pane find the field covering the
    byte under the cursor. `showname` is Wireshark's own label, including the
    bit diagrams for flag fields (".... ..1. = Syn: Set"), which would otherwise
    have to be reconstructed from a bitmask by hand.

    Two tool runs, the same as before: PDML carries no frame bytes, so the
    second run fetches them. It asks for `-T json -x` rather than plain `-x`
    because that reports the frame data source as one unambiguous hex string in
    `frame_raw`, where the text form has to be scraped and can carry a second
    block for reassembled data whose offsets do not match PDML's `pos`.
    """
    cmd = [
        "tshark", "-r", "-",
        "-T", "pdml",
        "-Y", f"frame.number == {int(frame_number)}",
    ]
    stdout, stderr, _ = await _run_tool(cmd, source)
    layers = _parse_pdml(stdout)
    if layers is None:
        logger.warning("tshark stderr: %s", stderr.decode(errors="replace")[:500])
        raise ValueError(f"frame {frame_number} not found")

    timestamp = ""
    for layer in layers:
        if layer["name"] == "frame":
            timestamp = _find_field_value(layer["fields"], "frame.time_relative")
            break

    frame_hex, hex_dump = await _get_frame_bytes(source, frame_number)

    return PacketDetail(
        number=frame_number,
        timestamp=timestamp,
        layers=layers,
        hex_dump=hex_dump,
        frame_hex=frame_hex,
        tcp_stream=_int_or_none(_find_field_anywhere(layers, "tcp.stream")),
        udp_stream=_int_or_none(_find_field_anywhere(layers, "udp.stream")),
    )


def _find_field_value(fields: list[dict], name: str) -> str:
    for field in fields:
        if field.get("name") == name:
            return field.get("value", "")
        found = _find_field_value(field.get("children") or [], name)
        if found:
            return found
    return ""


def _find_field_anywhere(layers: list[dict], name: str) -> str:
    """Like _find_field_value, but across every top-level layer.

    tcp.stream lives under the "tcp" layer, not "frame" -- callers that
    already know which layer a field is under use _find_field_value directly;
    this is for the ones that would otherwise have to guess.
    """
    for layer in layers:
        value = _find_field_value(layer.get("fields") or [], name)
        if value:
            return value
    return ""


def _int_or_none(value: str) -> int | None:
    return int(value) if value.lstrip("-").isdigit() else None


# tshark's PDML carries no document type declaration and no entities. Anything
# claiming to is not tshark's output, so it is refused rather than handed to a
# parser: expat resolves internal entity definitions, which is the one way a
# packet's own bytes could turn into an expansion attack against this process.
# Matched case-insensitively even though XML only permits these uppercase: the
# cost is nothing and it does not depend on the parser rejecting the lowercase
# form for us.
_XML_REFUSED = (b"<!doctype", b"<!entity")


def _parse_pdml(raw: bytes) -> list[dict] | None:
    """PDML for a single packet, as a list of protocol layers.

    Returns None when the filter matched no frame, which the caller reports as
    a missing frame -- distinct from a frame that dissects to nothing.
    """
    lowered = raw.lower()
    for marker in _XML_REFUSED:
        if marker in lowered:
            raise ValueError("refusing to parse PDML containing a document type declaration")

    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise ValueError(f"could not parse tshark PDML output: {exc}") from None

    packet = root.find("packet")
    if packet is None:
        return None

    layers = []
    for proto in packet.findall("proto"):
        name = proto.get("name", "")
        # geninfo is PDML's own synthetic summary, not a protocol in the frame.
        # Wireshark does not show it and its fields have no meaningful offsets.
        if name == "geninfo":
            continue
        layers.append({
            "name": name,
            "label": proto.get("showname") or name,
            "pos": _int_attr(proto, "pos"),
            "size": _int_attr(proto, "size"),
            "fields": [_pdml_field(child) for child in proto.findall("field")],
        })
    return layers


def _pdml_field(el) -> dict:
    """One PDML <field> and everything nested under it.

    `show` is the displayed value and the one to filter on; `value` is the raw
    hex of the same bytes. Where a field has no `show` -- some container fields
    do not -- the hex stands in so the row is not blank.
    """
    show = el.get("show")
    return {
        "name": el.get("name", ""),
        "label": el.get("showname") or el.get("name", ""),
        "value": show if show is not None else (el.get("value") or ""),
        "pos": _int_attr(el, "pos"),
        "size": _int_attr(el, "size"),
        "hidden": el.get("hide") == "yes",
        "children": [_pdml_field(child) for child in el.findall("field")],
    }


def _int_attr(el, attr: str) -> int:
    try:
        return int(el.get(attr, ""))
    except ValueError:
        return -1 if attr == "pos" else 0


async def _get_frame_bytes(source: PcapSource, frame_number: int) -> tuple[str, str]:
    """The frame's raw bytes, as a hex string and as a printable dump.

    The hex string is what the viewer renders its own panes from. The text dump
    is kept because it is what a copy-paste into a bug report wants, and because
    removing it would change the API for no gain.
    """
    stdout, _, _ = await _run_tool(
        [
            "tshark", "-r", "-",
            "-T", "json", "-x",
            "-Y", f"frame.number == {int(frame_number)}",
        ],
        source,
    )
    try:
        data = json.loads(stdout.decode())
    except json.JSONDecodeError:
        return "", ""
    if not data:
        return "", ""

    raw = data[0].get("_source", {}).get("layers", {}).get("frame_raw")
    # frame_raw is [hex, pos, size, bitmask, type]; only the hex is wanted, and
    # a tshark that ever reports it as a bare string is handled rather than
    # indexed into character by character.
    if isinstance(raw, list) and raw:
        frame_hex = str(raw[0])
    elif isinstance(raw, str):
        frame_hex = raw
    else:
        return "", ""

    frame_hex = frame_hex.strip().lower()
    if not _HEX_ONLY.fullmatch(frame_hex):
        return "", ""
    return frame_hex, _hex_dump_text(frame_hex)


_HEX_ONLY = re.compile(r"(?:[0-9a-f]{2})*")


def _hex_dump_text(frame_hex: str) -> str:
    """The classic offset / hex / ASCII dump, built from the bytes themselves."""
    data = bytes.fromhex(frame_hex)
    lines = []
    for offset in range(0, len(data), 16):
        chunk = data[offset:offset + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:04x}  {hex_part:<47}  {text}")
    return "\n".join(lines)


# The rule itself lives in backend.models, so that a filter being *saved* as a
# view and a filter being *run* right now are checked by one function rather
# than two that can drift. These names are kept because they are what this
# module's callers and tests already reach for.
_FILTER_FORBIDDEN = FILTER_FORBIDDEN
_FILTER_MAX_LEN = FILTER_MAX_LEN
_validate_display_filter = validate_display_filter


def _filter_rejection(stderr: bytes) -> str:
    """tshark's own complaint about a filter, tidied for display.

    It writes something like:

        tshark: Constant expression is invalid.
            tcp.porrt == 80
            ^~~~~~~~~~~~~~~

    The caret line is the useful part, so it is kept; the "Running as user"
    banner and the tool name prefix are not.
    """
    lines = [
        line.rstrip()
        for line in stderr.decode(errors="replace").splitlines()
        if line.strip() and "Running as user" not in line
    ]
    if not lines:
        return "tshark rejected this display filter"
    lines[0] = lines[0].removeprefix("tshark: ")
    return "\n".join(lines)[:400]
