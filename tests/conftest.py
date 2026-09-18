"""backend.main runs Database(), CaptureVault() and delete_all_sessions() at
module scope, and SystemExit(1)s on a refused vault. So the environment it
reads has to exist before backend.main is ever imported -- which means before
pytest imports any test module that imports it, not inside a fixture (a
fixture, even session-scoped, only runs after collection has already imported
the test modules). Plain module-level code in conftest.py runs at collection
time, ahead of that import, which is why it lives here instead of in a
fixture."""

from __future__ import annotations

import atexit
import base64
import os
import secrets
import shutil
import tempfile

_tmp_root = tempfile.mkdtemp(prefix="pcap-server-tests-")
# One per process, so one per xdist worker too; left behind they pile up in /tmp.
atexit.register(shutil.rmtree, _tmp_root, True)

# Under pytest-xdist this file runs first in the controller process, and every
# worker inherits the controller's environment. A plain setdefault then kept
# the controller's directories, so all the workers opened one database: they
# raced on it at import ("database is locked" while one switched it to WAL)
# and shared each other's rows. So each name set here is recorded, and a
# worker replaces the ones the controller set with its own. A value from the
# real environment, which is never recorded, is still honoured everywhere.
_OWNED = "PCAP_TESTS_CONFTEST_SET"
_inherited = set(filter(None, os.environ.get(_OWNED, "").split(",")))
_owned: set[str] = set()


def _default(name: str, value: str) -> None:
    if name in _inherited or name not in os.environ:
        os.environ[name] = value
        _owned.add(name)


_default("DATA_DIR", os.path.join(_tmp_root, "data"))
_default("CAPTURES_DIR", os.path.join(_tmp_root, "captures"))
_default("SSH_KEYS_DIR", os.path.join(_tmp_root, "ssh-keys"))
_default("PCAP_MASTER_KEY", base64.b64encode(secrets.token_bytes(32)).decode())
_default("COOKIE_SECURE", "false")
os.environ[_OWNED] = ",".join(sorted(_owned | _inherited))

os.makedirs(os.environ["DATA_DIR"], exist_ok=True)
os.makedirs(os.environ["CAPTURES_DIR"], exist_ok=True)
os.makedirs(os.environ["SSH_KEYS_DIR"], exist_ok=True)
