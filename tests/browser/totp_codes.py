"""TOTP codes for the browser suites, each for a step the server has not used.

A module of its own, not part of conftest.py, because conftest is loaded twice
-- once by pytest as `conftest`, once by the suites as `tests.browser.conftest`
-- and each copy would keep its own record. Both import this one by the same
name, so there is exactly one.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pyotp

# The last TOTP step handed out per secret. The server accepts each step once
# per account (RFC 6238 section 5.2), and this suite signs in several times a
# minute with the same secret -- so "the current code" is not good enough twice.
_last_totp_step: dict[str, int] = {}


def totp_now(secret: str) -> str:
    """A code for a step the server has not accepted yet.

    The current step if it is unused, else the next one (the server accepts
    one step of drift either way), and only when both are spent does this wait
    for the clock to move on.
    """
    totp = pyotp.TOTP(secret)
    while True:
        now_step = totp.timecode(datetime.now(timezone.utc))
        step = max(now_step, _last_totp_step.get(secret, -1) + 1)
        if step <= now_step + 1:
            break
        time.sleep(max(0.05, (now_step + 1) * totp.interval - time.time() + 0.05))
    _last_totp_step[secret] = step
    return totp.generate_otp(step)
