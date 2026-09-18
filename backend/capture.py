from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from backend.crypto import CHUNK_SIZE, CryptoError
from backend.models import (
    ANY_INTERFACE,
    assert_no_forbidden_flags,
    CaptureInfo,
    CaptureOrigin,
    CaptureRequest,
    CaptureStatus,
    ServerInfo,
)
from backend.packet_parser import get_packet_count
from backend.ssh_manager import MAX_INTERFACE_INDEXES, SSHManager

logger = logging.getLogger(__name__)

# tcpdump always announces itself on stderr; only the rest is a diagnosis.
_STDERR_NOISE = ("listening on", "packets captured", "packets received", "packets dropped", "Got ")

# Allowance on top of a capture's own duration before the monitor gives up and
# releases the connection.
_MONITOR_GRACE_SECONDS = 60

# tcpdump -v, when writing with -w, reports its running total on stderr once a
# second as "Got 1234\r". It is the only progress signal that exists while a
# capture runs: the pcap is on the remote host until the transfer, so there is
# nothing local to count.
# Bounded on purpose. This parses stderr from the host being captured on --
# frequently a machine under investigation -- so the digit run is attacker
# influenced, and int() on a multi-megabyte digit string is quadratic. Twelve
# digits is more packets than any capture this tool can take.
_GOT_PACKETS = re.compile(r"Got (\d{1,12})")

# The same stderr accumulates for the whole capture, so it cannot be allowed to
# grow without limit either. The tail is what diagnoses an exit; a flood that
# pushes the opening lines out has already told us all it is going to.
_STDERR_KEEP_CHARS = 64 * 1024
_STDERR_COLLAPSE_PARTS = 32

# The live count is read from memory by the status endpoint. Writing the row on
# every tick would be a database write per second per capture to persist a
# number that is superseded a second later, so the row lags deliberately.
_LIVE_COUNT_PERSIST_SECONDS = 2.0

# How long to keep reading stderr after tcpdump exits. Its last words -- the
# summary counts, and any diagnosis of a failure -- all arrive in that moment.
_STDERR_DRAIN_SECONDS = 5

# Captures that are still consuming a resource -- an SSH connection to the
# target, a local file being written, a monitor task -- as opposed to ones
# that have finished one way or another and are just sitting in history.
_ACTIVE_STATUSES = (CaptureStatus.RUNNING, CaptureStatus.STOPPING, CaptureStatus.TRANSFERRING)

class _LiveCount:
    """Applies tcpdump's running total to a capture record as it is reported.

    Held in memory immediately, which is what the status endpoint serves, and
    written to the database at most once every _LIVE_COUNT_PERSIST_SECONDS: a
    row rewrite per second per capture buys nothing to persist a number that is
    superseded a second later.
    """

    __slots__ = ("_info", "_persist", "_last_write")

    def __init__(self, info: CaptureInfo, persist: Callable[[CaptureInfo], None]) -> None:
        self._info = info
        self._persist = persist
        self._last_write = 0.0

    def __call__(self, count: int) -> None:
        if count == self._info.packet_count:
            return
        self._info.packet_count = count
        now = time.monotonic()
        if now - self._last_write >= _LIVE_COUNT_PERSIST_SECONDS:
            self._last_write = now
            self._persist(self._info)


class UploadRejected(Exception):
    """An uploaded file is not something this server will store as a capture."""


class CaptureLimitExceeded(Exception):
    """Raised when starting a capture would exceed max_concurrent_captures."""


class InterfaceAlreadyCapturing(Exception):
    """Raised when this server's interface already has a capture running.

    Separate from CaptureLimitExceeded because it is a different kind of no:
    the limit is a quota on this container's resources and clears by waiting,
    while this is a conflict over one specific link that clears only by
    stopping the capture that holds it -- or by choosing another interface.
    """


def server_label(server: ServerInfo) -> str:
    """A human-readable stamp of where a capture ran, frozen at start time."""
    endpoint = f"{server.username}@{server.hostname}"
    if server.port != 22:
        endpoint += f":{server.port}"
    return f"{server.name} ({endpoint})" if server.name else endpoint


def _row(info: CaptureInfo) -> dict:
    row = info.model_dump()
    row["status"] = info.status.value
    row["origin"] = info.origin.value
    for key in ("started_at", "stopped_at"):
        row[key] = row[key].isoformat() if row[key] else None
    return row


async def _pump_stderr(process: object, buf: list[str], on_count) -> None:
    """Drain stderr as it arrives, reporting each running packet count seen.

    Draining continuously rather than once at exit does two things: it surfaces
    the count while the capture is still running, and it keeps a chatty tcpdump
    from stalling on a full channel window with nobody reading.

    Appends to a caller-owned buffer so a cancelled or timed-out pump still
    leaves behind whatever it read for the failure message.
    """
    stream = getattr(process, "stderr", None)
    if stream is None:
        return
    try:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            buf.append(chunk)
            if len(buf) > _STDERR_COLLAPSE_PARTS:
                buf[:] = ["".join(buf)[-_STDERR_KEEP_CHARS:]]
            # "Got 12\rGot 34\r" can arrive in one read; only the last is current.
            found = _GOT_PACKETS.findall(chunk)
            if found:
                on_count(int(found[-1]))
    except asyncio.CancelledError:
        raise
    except Exception:
        # A progress counter is not worth failing a capture over. The
        # authoritative count still comes from capinfos after the transfer.
        logger.warning("stopped reading capture stderr", exc_info=True)


def _discard_partial(local_path: Path) -> None:
    try:
        if local_path.exists():
            local_path.unlink()
    except OSError:
        logger.warning("could not remove partial capture %s", local_path)


def _describe_failure(exc: Exception, stderr_text: str) -> str:
    lines = [
        line.strip()
        for line in stderr_text.splitlines()
        if line.strip() and not any(noise in line for noise in _STDERR_NOISE)
    ]
    if lines:
        return " | ".join(lines)[:300]
    return str(exc)[:300] or "capture failed"


class CaptureManager:
    def __init__(self, ssh: SSHManager, captures_dir: Path, get_setting: Callable[[str], int], db, vault=None) -> None:
        self._ssh = ssh
        self._captures_dir = captures_dir
        self._captures_dir.mkdir(parents=True, exist_ok=True)
        self._get_setting = get_setting
        self._db = db
        self._vault = vault
        self._captures: dict[str, CaptureInfo] = {}
        # RemoteCapture objects: the tcpdump process bound to its SSH connection,
        # so closing one closes both.
        self._processes: dict[str, object] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._restore()

    def _restore(self) -> None:
        for row in self._db.list_captures():
            info = CaptureInfo(**row)
            # The process died with the previous container; nothing can resume it.
            if info.status in (CaptureStatus.RUNNING, CaptureStatus.STOPPING, CaptureStatus.TRANSFERRING):
                info.status = CaptureStatus.FAILED
                info.error = "interrupted by a server restart"
                self._db.upsert_capture(_row(info))
            self._captures[info.id] = info

    def _pcap_source(self, path: Path):
        if self._vault:
            return self._vault.source_for(path)
        from backend.pcapsource import PlaintextSource
        return PlaintextSource(path)

    def _persist(self, info: CaptureInfo) -> None:
        self._db.upsert_capture(_row(info))

    @property
    def captures(self) -> dict[str, CaptureInfo]:
        return dict(self._captures)

    def get(self, capture_id: str) -> CaptureInfo | None:
        return self._captures.get(capture_id)

    def list_for_user(self, user_id: str) -> list[CaptureInfo]:
        return [c for c in self._captures.values() if c.user_id == user_id]

    def active_count(self) -> int:
        return sum(1 for c in self._captures.values() if c.status in _ACTIVE_STATUSES)

    def build_command_args(self, req: CaptureRequest) -> list[str]:
        """The complete set of things that change what a -w capture contains.

        -n used to be appended here as well. Under -w tcpdump prints nothing, so
        it only made the command string shown to the user look like it did
        something.
        """
        max_packets = self._get_setting("max_capture_packets")
        # -v is what makes tcpdump report its running packet count on stderr.
        # Under -w it prints no packets, so it changes the progress reporting
        # and nothing about the capture file.
        args: list[str] = ["-v"]
        args += ["-i", req.interface]
        if req.count:
            count = min(req.count, max_packets)
            args += ["-c", str(count)]
        if req.snap_len is not None:
            args += ["-s", str(req.snap_len)]
        if req.bpf_filter:
            # After --, so a filter starting with a dash is read as an expression
            # rather than as an option.
            args.append("--")
            args.append(req.bpf_filter)
        assert_no_forbidden_flags(args)
        return args

    def _refuse_while_locked(self, what: str) -> None:
        """Raise CryptoError if the vault is waiting for its passphrase.

        FAIL CLOSED BEFORE ANYTHING IS WRITTEN. A locked vault presents
        cryptor=None, which every write path reads as "encryption is disabled"
        -- so without this, a pcap arriving while the vault waits for its
        passphrase is written in the clear, under a name with no .enc suffix,
        on an installation whose whole premise is encryption at rest. That is
        the fail-open vault.py refuses to start up into, by another door.
        Routes map this to 503: an admin unlocking is the remedy, after which
        the same request works.
        """
        if self._vault and self._vault.locked:
            raise CryptoError(
                f"the vault is locked, so {what} cannot be encrypted -- unlock "
                "encryption first rather than storing it in the clear"
            )

    async def start(self, req: CaptureRequest, server: ServerInfo, user_id: str) -> CaptureInfo:
        # Before anything else, and in particular before tcpdump runs on the
        # target: refusing at collection time would throw away a capture the
        # user already waited for.
        self._refuse_while_locked("a new capture")

        # Checked first, before any connection is opened or file created: each
        # running capture holds an SSH connection to a target host plus a local
        # file handle, and neither this container's descriptor table nor the
        # remote host's tolerance for simultaneous sessions is unlimited.
        max_concurrent = self._get_setting("max_concurrent_captures")
        if self.active_count() >= max_concurrent:
            raise CaptureLimitExceeded(
                f"{max_concurrent} capture(s) already running or finishing up -- "
                "stop or wait for one to finish before starting another"
            )

        # One capture per interface per server. Two tcpdumps reading the same
        # link record the same packets twice, doubling load on the target host
        # for a second copy of a capture you already have -- and leave two
        # captures nothing in the UI distinguishes. Different interfaces on one
        # host stay allowed: reading eth0 and eth1 at once is a real thing to
        # want, and they do not overlap.
        #
        # Deliberately in the same synchronous stretch as the limit check above
        # and the _captures insert below. Nothing awaits between them, so two
        # simultaneous requests cannot both pass this and then both register;
        # an await anywhere in here would open exactly that window.
        busy = next(
            (
                c for c in self._captures.values()
                if c.status in _ACTIVE_STATUSES
                and c.server_id == server.id
                and c.interface == req.interface
            ),
            None,
        )
        if busy:
            held = busy.name or busy.id
            raise InterfaceAlreadyCapturing(
                f"a capture is already running on {req.interface} on this server "
                f"({held}) -- stop it first, or capture a different interface"
            )

        max_seconds = self._get_setting("max_capture_seconds")
        capture_id = str(uuid.uuid4())
        remote_path = f"/tmp/pcap_{capture_id}.pcap"
        # The vault decides the on-disk name, so an encrypted capture is never
        # mistaken for a readable pcap by anything that scans the directory.
        local_path = (
            self._vault.stored_path(capture_id) if self._vault
            else self._captures_dir / f"{capture_id}.pcap"
        )

        args = self.build_command_args(req)
        duration = req.duration_seconds
        if duration:
            duration = min(duration, max_seconds)
        else:
            duration = max_seconds
        # Grace for tcpdump to flush and exit after timeout(1) fires. Carried
        # to this capture's own monitor rather than held on the manager: with
        # max_concurrent_captures above 1, a second start() overwrote the
        # shared value before the first monitor had read it, so a 10-minute
        # capture started alongside a 5-second one was abandoned after 65s.
        monitor_timeout = duration + _MONITOR_GRACE_SECONDS

        binary = server.tcpdump_path or "tcpdump"
        full_cmd = [binary, "-w", remote_path] + args
        if server.use_sudo:
            full_cmd = ["sudo", "-n"] + full_cmd
        assert_no_forbidden_flags(full_cmd)
        cmd_str = " ".join(full_cmd)

        info = CaptureInfo(
            id=capture_id,
            name=req.name,
            server_id=server.id,
            server_label=server_label(server),
            interface=req.interface,
            user_id=user_id,
            bpf_filter=req.bpf_filter,
            status=CaptureStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            command=cmd_str,
            remote_path=remote_path,
            local_path=str(local_path),
        )
        self._captures[capture_id] = info
        self._persist(info)

        # From here the capture counts against max_concurrent_captures. Only
        # _monitor ever ends a RUNNING capture, and it does not exist yet, so a
        # failure to launch has to close the record itself -- otherwise every
        # unreachable host leaks a slot permanently, and after
        # max_concurrent_captures of them nothing can start again until the
        # container restarts and _restore() sweeps them.
        try:
            process = await self._ssh.run_tcpdump(
                server,
                args,
                remote_path,
                duration=duration,
            )
        except BaseException as exc:
            info.status = CaptureStatus.FAILED
            info.stopped_at = datetime.now(timezone.utc)
            info.error = _describe_failure(exc, "")
            self._persist(info)
            raise

        self._processes[capture_id] = process

        task = asyncio.create_task(
            self._monitor(
                capture_id, server, process, remote_path, local_path,
                monitor_timeout=monitor_timeout,
            )
        )
        self._tasks[capture_id] = task

        return info

    # --- uploads ---------------------------------------------------------
    #
    # A pcap recorded elsewhere, stored under exactly the protections a capture
    # taken here gets: sealed with the same vault key, named by the same
    # stored_path() rule, opened by the same source_for() reader, listed,
    # viewed, filtered, sanitized, downloaded and deleted by the same code. The
    # only thing that differs is the record's origin field, which says this
    # server did not watch it happen.
    #
    # Read off the raw request body, NOT a multipart form. That is the whole
    # design, for two reasons:
    #
    #   1. Starlette spools an UploadFile's bytes to a temp file as it parses
    #      the multipart, which for a pcap would mean writing the plaintext
    #      capture to disk unencrypted and only sealing it afterwards. This
    #      repo has held the opposite invariant since captures were first
    #      encrypted -- a plaintext pcap never becomes a file (see
    #      SSHManager._download, which seals over SFTP for the same reason) --
    #      and an upload route is no place to break it.
    #   2. A multipart file part has no size cap at all before it is parsed, so
    #      the existing Content-Length middleware is the only thing in front of
    #      it, and a chunked request carries no Content-Length. Counting bytes
    #      off the stream here closes that for this route by construction
    #      instead of trusting a header.

    # pcap (both byte orders, microsecond and nanosecond) and pcapng's Section
    # Header Block. Checked because tshark will be pointed at whatever is
    # stored, and a file that is not a capture at all should be refused while
    # it is still four bytes rather than after a subprocess has chewed on it.
    # NOT a substitute for the capinfos check below, which is what actually
    # establishes that the file is readable -- this only rejects the obvious.
    _PCAP_MAGICS = (
        b"\xa1\xb2\xc3\xd4",  # pcap, microseconds, big-endian
        b"\xd4\xc3\xb2\xa1",  # pcap, microseconds, little-endian
        b"\xa1\xb2\x3c\x4d",  # pcap, nanoseconds, big-endian
        b"\x4d\x3c\xb2\xa1",  # pcap, nanoseconds, little-endian
        b"\x0a\x0d\x0d\x0a",  # pcapng Section Header Block
    )

    async def import_upload(
        self,
        user_id: str,
        filename: str,
        chunks,
        max_bytes: int,
    ) -> CaptureInfo:
        """Seal an uploaded pcap into the captures volume and record it.

        `chunks` is an async iterator of raw body bytes. Nothing is trusted
        about its length: the cap is enforced as the bytes arrive, and the
        moment it is passed the partial file is removed and the request
        refused, so a client that lies about Content-Length -- or sends no
        Content-Length at all -- cannot fill the volume.
        """
        # Reproduced before it was fixed: the file landed as <uuid>.pcap with
        # the pcap magic as its first four bytes.
        self._refuse_while_locked("an uploaded capture")

        capture_id = str(uuid.uuid4())
        target = (
            self._vault.stored_path(capture_id) if self._vault
            else self._captures_dir / f"{capture_id}.pcap"
        )
        # Written beside the real name and moved into place only once the whole
        # body has arrived and sealed cleanly. A half-written upload is never a
        # file the vault's startup scan or the capture list can find -- the same
        # reason CaptureVault.migrate_plaintext works this way.
        partial = target.with_name(target.name + ".partial")
        started = datetime.now(timezone.utc)

        try:
            total = await self._write_sealed_upload(partial, chunks, max_bytes)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise

        try:
            partial.replace(target)
            # capinfos is the real gate: it is the same tool the capture path
            # counts packets with, reading through the same vault source, so a
            # file that survives it is one the viewer can actually open. A pcap
            # header on 40 bytes of noise gets this far and fails here.
            try:
                packet_count = await get_packet_count(self._pcap_source(target))
            except Exception as exc:
                raise UploadRejected(
                    "this file has a capture file header but could not be read as one "
                    f"({str(exc)[:200]})"
                ) from exc
        except BaseException:
            partial.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise

        info = self._upload_record(
            capture_id, user_id, filename, target, started, packet_count,
        )
        self._captures[capture_id] = info
        self._persist(info)
        logger.info(
            "stored uploaded capture %s (%d bytes on the wire, %d packets) for user %s",
            capture_id, total, packet_count, user_id,
        )
        return info

    @staticmethod
    def _upload_record(
        capture_id: str,
        user_id: str,
        filename: str,
        target: Path,
        started: datetime,
        packet_count: int,
    ) -> CaptureInfo:
        """The record for a stored upload, and what it deliberately leaves empty."""
        return CaptureInfo(
            id=capture_id,
            # The filename is the only thing known about where this came from,
            # so it becomes the label rather than leaving a list of UUIDs.
            # Renaming afterwards works exactly as it does for a capture.
            name=filename,
            user_id=user_id,
            origin=CaptureOrigin.UPLOAD,
            # Deliberately blank, all of them. There was no server, no
            # interface, no command and no capture filter -- and writing a
            # plausible-looking value into any of them would be this record
            # claiming to know something about the file that it does not.
            server_id="",
            server_label="",
            interface="",
            bpf_filter="",
            command="",
            remote_path="",
            status=CaptureStatus.COMPLETED,
            # Both timestamps are when the upload happened, not when the
            # traffic was captured -- which is inside the file and is not this
            # record's to report. The viewer's own relative timestamps come
            # from the pcap itself, so nothing here misdates a packet.
            started_at=started,
            stopped_at=datetime.now(timezone.utc),
            local_path=str(target),
            file_size=target.stat().st_size,
            packet_count=packet_count,
        )

    async def _write_sealed_upload(self, partial: Path, chunks, max_bytes: int) -> int:
        """Seal the body into `partial` as it arrives. Returns plaintext bytes.

        Sealed and written inline, chunk by chunk, exactly as
        SSHManager._download does for a capture arriving over SFTP -- the same
        shape of work, and the reason given there holds here: AES-GCM over a
        64 KiB chunk is microseconds with AES-NI, so it does not meaningfully
        occupy the event loop, and the writes interleave with awaits on the
        socket anyway.
        """
        cryptor = self._vault.cryptor if self._vault else None
        sealer = cryptor.sealer() if cryptor else None
        total = 0
        head = b""
        checked = False
        # 0600 from the moment it exists, not chmod'd afterwards: between
        # creation and the chmod there is a window where the file is readable
        # by anything sharing the volume, and a capture is exactly the file
        # that must not have one.
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with open(fd, "wb") as out:
            if sealer:
                out.write(sealer.header())
            async for chunk in chunks:
                if not chunk:
                    continue
                total += len(chunk)
                self._check_upload_size(total, max_bytes)
                if not checked:
                    head += chunk
                    checked = self._header_looks_like_a_capture(head)
                self._write_upload_chunk(out, sealer, chunk)
            self._check_upload_finished(total, checked)
            if sealer:
                out.write(sealer.finish())
            out.flush()
            os.fsync(out.fileno())
        return total

    @staticmethod
    def _check_upload_size(total: int, max_bytes: int) -> None:
        if total > max_bytes:
            raise UploadRejected(
                f"upload is larger than the {max_bytes // (1024 * 1024)} MB limit "
                "(see max_upload_mb in admin settings)"
            )

    @classmethod
    def _header_looks_like_a_capture(cls, head: bytes) -> bool:
        """True once these opening bytes are a known capture header.

        False means "not yet, keep accumulating" -- the magic can straddle a
        chunk boundary, so the decision waits for four bytes rather than
        reading past the end of a one-byte first chunk. A file that ends while
        this is still False is caught by _check_upload_finished.
        """
        if len(head) < 4:
            return False
        if not head.startswith(cls._PCAP_MAGICS):
            raise UploadRejected(
                "this is not a pcap or pcapng file -- it does not start with a "
                "capture file header. Export from Wireshark or tcpdump as "
                ".pcap or .pcapng."
            )
        return True

    @staticmethod
    def _write_upload_chunk(out, sealer, chunk: bytes) -> None:
        """One body read, split to the crypto module's chunk size.

        Cryptor.open_stream refuses any chunk declaring more than CHUNK_SIZE
        bytes, so a sealed chunk built from a larger body read would write a
        file that nothing -- including this server -- could ever open.
        """
        for i in range(0, len(chunk), CHUNK_SIZE):
            part = chunk[i:i + CHUNK_SIZE]
            out.write(sealer.seal(part) if sealer else part)

    @staticmethod
    def _check_upload_finished(total: int, checked: bool) -> None:
        """The two things only the end of the body can tell us."""
        if not total:
            raise UploadRejected("no file was uploaded (the request body was empty)")
        if not checked:
            raise UploadRejected(
                "this file is too short to be a capture -- it is under four bytes"
            )

    async def stop(self, capture_id: str) -> CaptureInfo:
        info = self._captures.get(capture_id)
        if not info:
            raise KeyError(f"capture {capture_id} not found")

        if info.status != CaptureStatus.RUNNING:
            return info

        info.status = CaptureStatus.STOPPING
        self._persist(info)
        process = self._processes.get(capture_id)
        if process:
            await self._ssh.stop_tcpdump(process)

        return info

    def rename(self, capture_id: str, name: str) -> CaptureInfo:
        info = self._captures.get(capture_id)
        if not info:
            raise KeyError(f"capture {capture_id} not found")
        info.name = name
        self._persist(info)
        return info

    async def delete(self, capture_id: str) -> dict:
        """Remove a capture, terminating it first if it is still running.

        Deleting a running capture is a stop that keeps nothing, and it has to
        do everything a stop does: interrupt tcpdump the same way, take the
        file it was writing off the target host, release the SSH session, and
        only then drop the record and the local copy.

        Delete used to diverge from stop on all three counts. It signalled the
        process but cancelled the monitor without awaiting it, so the monitor's
        finally -- which ends in _persist() -- ran after the row had been
        deleted and wrote it straight back, as a FAILED capture whose file was
        already gone. And because the monitor never reached _collect, nothing
        removed the remote pcap: the capture an operator deleted stayed on the
        target, complete.

        Returns what actually happened, so the caller can say so rather than
        having the capture disappear with no account of what was done.
        """
        info = self._captures.get(capture_id)
        remote_path = info.remote_path if info else ""
        result = {"terminated": False, "remote_file_removed": False}

        # Out of the monitor's reach before it is cancelled: terminating the
        # capture is this method's job, done deliberately, rather than a side
        # effect of the connection being torn down underneath it.
        process = self._processes.pop(capture_id, None)

        task = self._tasks.pop(capture_id, None)
        if task:
            task.cancel()
            # A cancelled task has not run its finally until it is awaited.
            # Waiting here is what keeps the delete final.
            await asyncio.gather(task, return_exceptions=True)

        if process:
            # Live in this process, so it gets exactly the interrupt-then-kill a
            # Stop performs. Signalling a process that has already exited raises
            # instead, which is not a reason to fail the delete: closing the
            # session below ends it either way, and refusing here would leave
            # the record behind for a capture that is already over.
            try:
                await self._ssh.stop_tcpdump(process)
            except Exception:
                logger.warning("could not interrupt capture %s cleanly; closing its session", capture_id)
            result["terminated"] = True
            if remote_path:
                try:
                    await process.remove_remote_file(remote_path)
                    result["remote_file_removed"] = True
                except Exception:
                    # The record and the local copy still go. A file left in
                    # the target's /tmp is worth a warning and a word to the
                    # caller, not a refusal to delete.
                    logger.warning(
                        "failed to remove remote file %s for deleted capture %s",
                        remote_path, capture_id,
                    )
            await process.close()

        self._db.delete_capture(capture_id)
        info = self._captures.pop(capture_id, None)
        if info and info.local_path:
            path = Path(info.local_path)
            if path.exists():
                path.unlink()
        return result

    async def shutdown(self) -> None:
        for capture_id in list(self._processes.keys()):
            process = self._processes.pop(capture_id, None)
            if process:
                try:
                    await self._ssh.stop_tcpdump(process)
                except Exception:
                    logger.warning("failed to stop capture %s during shutdown", capture_id)
                finally:
                    # Stopping tcpdump is not the same as releasing its
                    # connection; shutdown must do both.
                    try:
                        await process.close()
                    except Exception:
                        logger.warning("failed to close connection for %s", capture_id)
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            # Awaiting is the point, not politeness: a cancelled task has not
            # run its finally until it is awaited, and the monitor's finally is
            # what releases the connection and writes the closing row. Without
            # this the coroutine is finalised by the garbage collector after the
            # loop has already closed.
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def _monitor(
        self,
        capture_id: str,
        server: ServerInfo,
        process: object,
        remote_path: str,
        local_path: Path,
        *,
        monitor_timeout: float,
    ) -> None:
        """Own a running capture from launch to a terminal status.

        Split three ways deliberately: waiting for the process, bringing the
        pcap back, and deciding what a failure means are separate concerns, and
        the middle one is the only part that touches the remote host twice.
        """
        info = self._captures[capture_id]
        stderr: list[str] = []
        pump = asyncio.create_task(
            _pump_stderr(process, stderr, _LiveCount(info, self._persist))
        )
        # Alongside the capture rather than before it: a start that waited on
        # one more SSH round trip would be slower for a table that is only
        # needed once someone reads the packets.
        names = (
            asyncio.create_task(self._record_interface_names(info, server))
            if info.interface == ANY_INTERFACE else None
        )
        try:
            await self._await_exit(process, pump, monitor_timeout)

            info.stopped_at = datetime.now(timezone.utc)
            info.status = CaptureStatus.TRANSFERRING
            self._persist(info)

            await self._collect(capture_id, server, remote_path, local_path, info)
            info.status = CaptureStatus.COMPLETED

        except asyncio.CancelledError:
            info.status = CaptureStatus.FAILED
            info.error = "cancelled"
            raise
        except asyncio.TimeoutError:
            info.status = CaptureStatus.FAILED
            info.error = "capture did not finish in time and was abandoned"
        except Exception as exc:
            logger.exception("capture %s failed", capture_id)
            info.status = CaptureStatus.FAILED
            info.error = _describe_failure(exc, "".join(stderr))
            # A transfer interrupted partway leaves a truncated pcap. It is
            # unreachable -- downloads require COMPLETED -- but leaving half a
            # capture on the volume is misleading.
            _discard_partial(local_path)
        finally:
            pump.cancel()
            if names is not None:
                names.cancel()
            # The SSH connection is released here, on every path -- success,
            # failure, timeout and cancellation alike.
            capture = self._processes.pop(capture_id, None)
            if capture is not None:
                await capture.close()
            self._persist(info)
            self._tasks.pop(capture_id, None)

    async def _record_interface_names(self, info: CaptureInfo, server: ServerInfo) -> None:
        """Merge the host's current interface table into the capture's.

        Never fails the capture: without the table the packets are all still
        there, and the viewer shows interface indexes instead of names. Where
        an index was reused by a different interface, the later reading wins.
        """
        try:
            table = await self._ssh.interface_indexes(server)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("could not read interface names for capture %s: %s", info.id, exc)
            return
        if not isinstance(table, dict) or not table:
            return
        merged = {**info.interface_names, **table}
        # Two readings can each be at the cap; the latest one alone is then
        # the better table to keep.
        info.interface_names = merged if len(merged) <= MAX_INTERFACE_INDEXES else table
        self._persist(info)

    async def _await_exit(self, process: object, pump: asyncio.Task, timeout: float) -> None:
        """Wait for tcpdump to finish, then let the rest of its stderr land."""
        # The remote command is wrapped in timeout(1), but that only helps if
        # timeout(1) is present and behaves. This is the backstop: without it a
        # process that never exits holds its SSH connection open forever.
        await asyncio.wait_for(process.wait(), timeout=timeout)
        try:
            await asyncio.wait_for(pump, timeout=_STDERR_DRAIN_SECONDS)
        except Exception:
            # Failing to read the epilogue is not a failed capture. Whatever the
            # pump did manage to read is still in the buffer for diagnosis.
            pass
        # timeout(1) exits 124 and SIGINT exits 130 -- both are how a capture ends normally.
        if process.exit_status not in (0, 124, 130, None):
            raise RuntimeError(f"tcpdump exited {process.exit_status}")

    async def _collect(
        self,
        capture_id: str,
        server: ServerInfo,
        remote_path: str,
        local_path: Path,
        info: CaptureInfo,
    ) -> None:
        """Bring the pcap back, tidy the remote host, and record size and count."""
        # start() already refused while locked; this is the backstop for the
        # write itself. Raising here leaves the remote file in place, since its
        # deletion below only runs after a successful fetch.
        self._refuse_while_locked("this capture")
        cryptor = self._vault.cryptor if self._vault else None
        await self._ssh.fetch_file(server, remote_path, local_path, cryptor=cryptor)

        if info.interface == ANY_INTERFACE:
            # Again at the end: anything created during the capture -- a
            # container's veth, a VPN tunnel -- only exists in this reading.
            await self._record_interface_names(info, server)

        try:
            await self._ssh.delete_remote_file(server, remote_path)
        except Exception:
            # The capture is already here. A file left in the target's /tmp is
            # worth a warning, not a failed capture.
            logger.warning("failed to clean up remote file %s", remote_path)

        if local_path.exists():
            info.file_size = local_path.stat().st_size

        try:
            info.packet_count = await get_packet_count(self._pcap_source(local_path))
        except Exception:
            # The capture itself is intact and downloadable. Failing it over a
            # count tcpdump already reported would throw away a good pcap to
            # report a number twice.
            logger.warning(
                "could not count packets in %s; keeping tcpdump's own total of %d",
                capture_id, info.packet_count,
            )
