"""Infrastructure for the browser suites: a real server, a real browser.

The Python suites call the API directly and cover it thoroughly. That is not
the same thing as covering the app, and the gap is not theoretical -- every one
of these shipped while the API suite was green:

  * Enter did nothing in the server form. There is no <form> on the page, so
    the browser's own submit behaviour never applied, and the keydown handler
    named five element ids that did not include any field of that form. The
    API was fine; the form had no way to submit it.
  * The inline theme script is pinned in the CSP by content hash. Editing the
    script without recomputing the hash makes the browser drop it silently --
    no error, no failed request, just the wrong theme on first paint.
  * The filter library was a tab; choosing a filter filled a field on a
    different tab.

None of those produce a bad HTTP response, so none of them can be seen from a
test that only speaks HTTP. These suites drive the page the way a person does.

These suites use playwright's async API, not its sync one. The sync API drives
the driver through an event loop it installs on the main thread and keeps for
as long as it is open; the rest of this repo's tests are async and run under
pytest-asyncio, which then finds a loop it did not make and cannot tear down.
Each suite passes on its own either way -- the two only collide in a full run,
which is the run that matters.

Skipping: if playwright or a chromium binary is missing the tests report as
SKIPPED with the remedy in the reason, the same way the tshark-dependent tests
do -- scripts/check.sh runs pytest with -r s so a skipped browser suite is
printed, not silently dropped.
"""

from __future__ import annotations

import base64
import importlib.util
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import asyncssh
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio

from tests.browser.browser_binary import launch_kwargs

REPO_ROOT = Path(__file__).resolve().parents[2]

HAS_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None

needs_browser = pytest.mark.skipif(
    not HAS_PLAYWRIGHT,
    reason="playwright is not installed -- pip install -r backend/requirements-dev.txt",
)

# Every browser test runs on the session's event loop, the one the shared
# chromium lives on (see the browser fixture for why it has to be the same).
BROWSER_LOOP = pytest.mark.asyncio(loop_scope="session")

# The admin account every suite signs in as. Created through the real
# registration and TOTP-enrolment endpoints, not by writing rows. These are not
# credentials to anything: the account exists inside a throwaway database, on a
# server bound to loopback, for the length of one test run.
ADMIN_USERNAME = "browser-admin"
ADMIN_PASSWORD = "browser-admin-passphrase"

_STARTUP_TIMEOUT = 60.0


@dataclass(frozen=True)
class LiveServer:
    """A uvicorn process serving the real app out of throwaway directories."""

    url: str
    root: Path
    totp_secret: str = ""

    @property
    def ssh_keys_dir(self) -> Path:
        return self.root / "ssh-keys"


def _free_port() -> int:
    """Ask the kernel for a port, then hand it to uvicorn.

    There is a window between closing this socket and uvicorn binding it. It is
    the standard approach and the alternative -- passing an inherited socket
    through uvicorn -- buys very little for a test fixture.
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_serving(url: str, proc: subprocess.Popen, log: Path) -> None:
    deadline = time.monotonic() + _STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"the test server exited with {proc.returncode} before serving:\n"
                f"{log.read_text(errors='replace')}"
            )
        try:
            with urllib.request.urlopen(f"{url}/api/auth/status", timeout=2) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(0.1)
    raise RuntimeError(
        f"the test server did not answer within {_STARTUP_TIMEOUT:.0f}s:\n"
        f"{log.read_text(errors='replace')}"
    )


def _start_server(root: Path) -> tuple[LiveServer, subprocess.Popen]:
    """Launch the app on loopback with its own data, captures and key dirs.

    Loopback matters beyond isolation: the app is deliberately read-only over
    plain HTTP, and it treats a loopback client as secure transport (nothing
    crosses a wire to be read). Served on 127.0.0.1 the whole UI works over
    http:// without a certificate.
    """
    for name in ("data", "captures", "ssh-keys"):
        (root / name).mkdir(parents=True, exist_ok=True)

    # An ssh-keyscan that answers the way the real one does for an address that
    # never replies -- nothing on stdout, a message on stderr, non-zero -- but
    # immediately. The real binary waits out its -T 5 timeout, and about a dozen
    # tests point the form at TEST-NET-3, so each paid five seconds (the
    # trust-host ones twice) to learn the same thing. The app's own handling of
    # a failed scan is what is under test; how long the failure took is not.
    # tests/test_ssh_manager.py and tests/test_servers.py cover the real
    # command line.
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    keyscan = bin_dir / "ssh-keyscan"
    keyscan.write_text(
        "#!/bin/sh\n"
        'echo "ssh-keyscan: connection timed out (browser-suite stand-in)" >&2\n'
        "exit 1\n"
    )
    keyscan.chmod(0o755)

    # The same reasoning for the SSH connections the app opens itself, which go
    # through asyncssh in-process, so there is no binary to stand in for.
    # TEST-NET-3 never answers, so every connect waited out the app's 15s
    # CONNECT_TIMEOUT: one test spent 15s on it, and a page that closed
    # mid-connect left uvicorn waiting on that request at shutdown until
    # _stop_server gave up and killed it. Python imports sitecustomize from the
    # path at startup, before `-m backend.serve` runs, so this lowers the
    # constant in the test server's process only; the app's source and its
    # production default are untouched.
    shim_dir = root / "pyshim"
    shim_dir.mkdir(parents=True, exist_ok=True)
    (shim_dir / "sitecustomize.py").write_text(
        "import backend.ssh_manager\n"
        "# Loudly, if the constant is ever renamed: setting a name that is not\n"
        "# there would quietly bring the fifteen-second waits back.\n"
        "assert hasattr(backend.ssh_manager, 'CONNECT_TIMEOUT')\n"
        "backend.ssh_manager.CONNECT_TIMEOUT = 1\n"
    )
    pythonpath = os.pathsep.join(
        p for p in (str(shim_dir), str(REPO_ROOT), os.environ.get("PYTHONPATH")) if p
    )

    port = _free_port()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "PYTHONPATH": pythonpath,
        "DATA_DIR": str(root / "data"),
        "CAPTURES_DIR": str(root / "captures"),
        "SSH_KEYS_DIR": str(root / "ssh-keys"),
        "PCAP_MASTER_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
        "COOKIE_SECURE": "false",
        # Same reasoning as the stand-in ssh-keyscan, for the SSH connections
        # the app makes itself: TEST-NET-3 never answers, and waiting out the
        # default fifteen seconds proves nothing a second does not. A page that
        # closed mid-connect also left uvicorn waiting on that request at
        # shutdown, until _stop_server gave up and killed it.
        "PCAP_SSH_CONNECT_TIMEOUT": "1",
    }
    log = root / "server.log"
    # To a file rather than a pipe nobody reads: a pipe fills and blocks the
    # server mid-test, and the log is what explains a startup failure.
    handle = log.open("w")
    proc = subprocess.Popen(
        [
            # The image's own entry point, so the launcher is what gets tested.
            sys.executable, "-m", "backend.serve",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_until_serving(url, proc, log)
    except Exception:
        _stop_server(proc)
        handle.close()
        raise
    handle.close()
    return LiveServer(url=url, root=root), proc


def _stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _seed_admin(url: str) -> str:
    """Register the admin and finish TOTP enrolment through the public API.

    Enrolment is compulsory -- an account that skips it cannot reach the app --
    so every suite that is not specifically testing first-run setup needs it
    done already. Returns the TOTP secret so tests can produce valid codes.
    """
    import httpx
    import pyotp

    with httpx.Client(base_url=url, timeout=30) as client:
        client.post(
            "/api/auth/register",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        ).raise_for_status()
        secret = client.get("/api/auth/totp/setup").raise_for_status().json()["secret"]
        client.post(
            "/api/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()}
        ).raise_for_status()
    return secret


@pytest.fixture(scope="session")
def live_server():
    """One server for the whole session, with the admin already enrolled.

    Shared deliberately: booting uvicorn per test would dominate the runtime.
    Tests that need a server with no users take `fresh_server` instead.
    """
    root = Path(tempfile.mkdtemp(prefix="pcap-browser-"))
    try:
        server, proc = _start_server(root)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    # A real key, not a placeholder.
    #
    # It used to be the string "# placeholder for tests; not a key", on the
    # reasoning that only the presence of the file is checked. That is true of
    # add_server and false of anything that connects: _connect loads the client
    # key BEFORE it consults the trust store, so an unparseable key turned every
    # probe into a generic "SSH connection failed" 502 -- masking the 409 that
    # says the host is not trusted, which is the answer the add form branches
    # on. A test for that branch could never see it.
    #
    # Nothing here ever completes a handshake (TEST-NET-3 answers nothing), so
    # this key authenticates against nothing. It only has to parse.
    (server.ssh_keys_dir / "browser-test-key").write_bytes(
        asyncssh.generate_private_key("ssh-ed25519").export_private_key("openssh")
    )
    try:
        yield LiveServer(url=server.url, root=root, totp_secret=_seed_admin(server.url))
    finally:
        _stop_server(proc)
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def fresh_server():
    """A server with an empty database, for the first-run screens."""
    root = Path(tempfile.mkdtemp(prefix="pcap-browser-fresh-"))
    try:
        server, proc = _start_server(root)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    try:
        yield server
    finally:
        _stop_server(proc)
        shutil.rmtree(root, ignore_errors=True)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def browser():
    """One headless chromium per test process, shared by every test in it.

    Launching one cost about half a second a test -- a playwright driver and a
    chromium started and torn down some 250 times, more than the tests
    themselves took. Isolation does not come from the browser but from the
    context: each test gets a fresh one (no cookies, no storage) from _open_page.

    An async fixture that outlives a test has to live on an event loop that
    does too, and everything that talks to it has to use that same loop:
    playwright objects are bound to the loop that created them, and awaiting
    one from another loop does not fail, it hangs. So this fixture, the page
    fixtures below and every browser test (BROWSER_LOOP in each module's
    pytestmark) all run on the session loop.
    """
    if not HAS_PLAYWRIGHT:
        pytest.skip("playwright is not installed")
    from playwright.async_api import async_playwright

    async with async_playwright() as play:
        kwargs = launch_kwargs(play)
        if kwargs is None:
            pytest.skip(
                "no chromium for playwright -- run: "
                f"{sys.executable} -m playwright install chromium"
            )
        if getattr(os, "geteuid", lambda: 1)() == 0:
            # Chromium's setuid sandbox refuses to start as root, which is how
            # CI images and dev containers usually run. The pages loaded here
            # are this repo's own, served from loopback, so the sandbox is not
            # what stands between these tests and anything.
            kwargs["args"] = ["--no-sandbox"]
        instance = await play.chromium.launch(**kwargs)
        try:
            yield instance
        finally:
            await instance.close()


async def _open_page(browser, url: str):
    """A fresh context (so: no cookies, no storage) pointed at `url`.

    Console errors and uncaught exceptions are collected onto the page as
    `console_errors`. A page that throws still renders, so without this a
    broken handler looks exactly like a working one until the assertion that
    happens to touch it.
    """
    context = await browser.new_context(base_url=url)
    page = await context.new_page()
    errors: list[str] = []
    page.console_errors = errors

    def on_console(msg) -> None:
        if msg.type != "error":
            return
        # With the URL, because the text of a failed load does not carry one:
        # "Failed to load resource: ... 404" says nothing about what failed.
        where = (msg.location or {}).get("url", "")
        errors.append(f"{msg.text} ({where})" if where else msg.text)

    page.on("console", on_console)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    return context, page


@pytest_asyncio.fixture(loop_scope="session")
async def page(browser, live_server):
    context, page = await _open_page(browser, live_server.url)
    try:
        yield page
    finally:
        await context.close()


@pytest_asyncio.fixture(loop_scope="session")
async def fresh_page(browser, fresh_server):
    context, page = await _open_page(browser, fresh_server.url)
    try:
        yield page
    finally:
        await context.close()


def totp_now(secret: str) -> str:
    import pyotp

    return pyotp.TOTP(secret).now()


async def sign_in(page, live_server) -> None:
    """Sign in through the login screen, TOTP and all, and land in the app."""
    await page.goto("/")
    await page.fill("#login-username", ADMIN_USERNAME)
    await page.fill("#login-password", ADMIN_PASSWORD)
    await page.click("#btn-login")
    await page.wait_for_selector("#totp-group:not([hidden])")
    await page.fill("#login-totp", totp_now(live_server.totp_secret))
    await page.click("#btn-login")
    await page.wait_for_selector("#app-screen:not([hidden])")


@pytest.fixture(scope="session")
def admin_session(api_client):
    """One signed-in session cookie, minted once for every app_page to reuse.

    Signing in through the login screen costs about 0.75s a test -- a scrypt
    verify at OWASP cost, two round trips and a TOTP step -- and it was paid by
    every test that only wanted to be signed in, some 200 of them. The login
    screen itself is exercised by the tests that are about it, which still go
    through sign_in(). The cookie is api_client's: the same admin, already
    signed in, so it costs no login of its own.

    The session is the admin's, and only a test that ends it (signing out) or
    an admin action on that same user can invalidate it; app_page notices and
    signs in the slow way rather than handing a test a dead session.
    """
    return {"value": api_client.cookies["session"]}


@pytest_asyncio.fixture(loop_scope="session")
async def app_page(page, live_server, admin_session):
    """A page signed in and sitting on the Servers tab."""
    await page.context.add_cookies(
        [{"name": "session", "value": admin_session["value"], "url": live_server.url}]
    )
    await page.goto("/")
    signed_in = await page.wait_for_selector(
        "#app-screen:not([hidden]), #login-form:not([hidden])"
    )
    if await signed_in.get_attribute("id") != "app-screen":
        # The shared session is gone (something signed the admin out). Sign in
        # the long way and share the new one, so one such test costs one login.
        await sign_in(page, live_server)
        cookies = await page.context.cookies(live_server.url)
        admin_session["value"] = next(c["value"] for c in cookies if c["name"] == "session")
    return page


@pytest.fixture(scope="session")
def api_client(live_server):
    """A signed-in HTTP client, for arranging and tearing down state.

    Setting up a test's preconditions through the UI would make every test a
    test of the setup as well; this does it over the same API the UI calls.
    """
    import httpx

    with httpx.Client(base_url=live_server.url, timeout=30) as client:
        client.post(
            "/api/auth/login",
            json={
                "username": ADMIN_USERNAME,
                "password": ADMIN_PASSWORD,
                "totp_code": totp_now(live_server.totp_secret),
                "trust_device": False,
            },
        ).raise_for_status()
        yield client
