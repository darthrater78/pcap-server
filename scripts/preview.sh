#!/usr/bin/env bash
# A throwaway pcap-server to click around in: builds the image from this tree,
# runs it on two scratch Docker volumes (removed by `down`), creates a login
# and loads a made-up capture (scripts/preview_pcap.py), so the viewer and its
# diagrams have something to show straight away.
#
# The capture is then dressed up as one taken on "any", with names for its
# interface indexes (eth0, wlan0, wan, cni0). An upload never has those -- the file
# does not carry them -- so they are written into the preview's database
# directly and the container restarted to load them. Fine for a fake capture
# in a disposable container; never something the app itself does.
#
#   scripts/preview.sh          build and (re)start it; prints the URL and login
#   scripts/preview.sh code     the current 6-digit sign-in code
#   scripts/preview.sh down     stop it and delete its data, key and all
#
# Staying signed in. The app signs everyone out whenever it restarts (on
# purpose -- backend/main.py), so this restarts it as rarely as it can:
#   * frontend/ is mounted read-only from this tree, so a JS/CSS/HTML change
#     is live on a browser refresh, with no restart at all;
#   * the container is only rebuilt and replaced when the backend changed
#     (a hash of backend/, the Dockerfile and entrypoint.sh, kept as a label);
#   * when it is replaced, the volumes and the vault key (under
#     ~/.local/state/pcap-preview) carry over: same account, same TOTP key,
#     and a device ticked "trust this device" signs in on the password alone.
#   * a changed sample capture (preview_pcap.py, or the packet builders it
#     uses) is swapped in place, account kept; that one needs a restart.
#
# PREVIEW_PORT (default 8099) picks the host port. It listens on every
# interface so it can be opened from another device on the LAN; over plain
# HTTP from there the app is read-only, which is all a look at the UI needs.
# The capture is loaded from inside the container over loopback, the one
# place plain HTTP is allowed to write.
#
# The login is fixed and printed below, and sessions never time out (no idle
# timeout, a year-long session). That is only acceptable because the
# container holds nothing but the fake capture and is meant to be torn down;
# never point this at real data.
set -euo pipefail

NAME=pcap-preview
IMAGE=localhost/pcap-server:preview
PORT="${PREVIEW_PORT:-8099}"
USERNAME=preview
PASSWORD=preview-pass
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/pcap-preview"
KEY_FILE="$STATE/master.key"

code() {
    # The current code, and the next one when this one is about to expire.
    docker exec -u appuser "$NAME" python -c "
import pyotp, time
t, now = pyotp.TOTP(open('/app/data/preview-totp').read().strip()), time.time()
left = int(30 - now % 30)
print(t.at(now), f'({left}s left)' + (f', next {t.at(now + 30)}' if left < 10 else ''))"
}

# Preview-only settings, applied on every run -- a kept database and a kept
# container included: no idle timeout, year-long sessions, and a device
# trusted for ten years, so each browser enters a TOTP code once, ticks
# "Trust this device", and from then on signs in with the password alone.
# The app's rule that TOTP is required is untouched; this only stretches its
# own remember-me. The app reads settings per request, so no restart.
apply_settings() {
    docker exec -u appuser "$NAME" python -c "
import sqlite3
with sqlite3.connect('/app/data/pcap-server.db') as conn:
    conn.executemany('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', [
        ('session_idle_timeout_minutes', '0'),
        ('session_duration_hours', '8760'),
        ('device_trust_days', '3650'),
    ])"
}

case "${1:-up}" in
    code) code; exit 0 ;;
    down)
        docker rm -f "$NAME" >/dev/null 2>&1 && echo "stopped $NAME" || echo "$NAME was not running"
        docker volume rm "$NAME-data" "$NAME-captures" >/dev/null 2>&1 || true
        rm -f "$KEY_FILE"
        exit 0 ;;
    up) ;;
    *) echo "usage: $0 [up|code|down]" >&2; exit 2 ;;
esac

SRC_HASH=$(cd "$ROOT" && find backend Dockerfile entrypoint.sh -type f -not -path '*/__pycache__/*' -print0 \
    | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16)
# The sample capture's own fingerprint: when its generator changes, the
# running preview swaps in the new capture rather than keeping the old one.
SAMPLE_HASH=$(cd "$ROOT" && cat scripts/preview_pcap.py tests/packet_builders.py | sha256sum | cut -c1-16)
RUNNING_HASH=$(docker inspect -f '{{index .Config.Labels "preview.src"}}' "$NAME" 2>/dev/null || true)
KEPT=""
if [ "$RUNNING_HASH" = "$SRC_HASH" ] && [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = "true" ]; then
    KEPT=1
else
    docker build -q -t "$IMAGE" "$ROOT" >/dev/null
    # One preview at a time: the old container always goes before the new one
    # starts. Its volumes and key stay, so the new one picks up where it left off.
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    mkdir -p "$STATE"
    if [ ! -s "$KEY_FILE" ]; then
        # A new key means new, empty volumes: data sealed with a lost key is
        # unreadable, so never pair a fresh key with old data.
        docker volume rm "$NAME-data" "$NAME-captures" >/dev/null 2>&1 || true
        (umask 077 && openssl rand -base64 32 > "$KEY_FILE")
    fi
    docker run -d --name "$NAME" -p "$PORT:8080" --label "preview.src=$SRC_HASH" \
        -e PCAP_MASTER_KEY="$(cat "$KEY_FILE")" \
        -e COOKIE_SECURE=false \
        -v "$NAME-data:/app/data" -v "$NAME-captures:/app/captures" \
        -v "$ROOT/frontend:/app/frontend:ro" \
        --tmpfs /app/ssh-keys --tmpfs /tmp \
        --cap-drop ALL --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
        --cap-add SETUID --cap-add SETGID --security-opt no-new-privileges:true \
        --read-only "$IMAGE" >/dev/null
fi

# Seed through the public API from inside the container, over loopback. A new
# database gets the admin registered and TOTP enrolled; a kept one is signed
# into with the stored login. Either way, if the sample capture is missing or
# its generator changed, every capture is replaced with a fresh one. Prints
# "restart" when the app has to reload (a new capture's interface names are
# written to its database directly -- see the header).
SEED=$(cat <<'PY'
import http.cookiejar, json, os, sqlite3, sys, time, urllib.request
import pyotp

base = "http://127.0.0.1:8080"
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

def call(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/octet-stream" if raw is not None else "application/json")
    with opener.open(req, timeout=60) as resp:
        return json.loads(resp.read() or b"{}")

for _ in range(60):
    try:
        status = call("GET", "/api/auth/status")
        break
    except Exception:
        time.sleep(1)
else:
    sys.exit("pcap-server did not come up")

user, password, sample_hash = sys.argv[1], sys.argv[2], sys.argv[3]
secret_file, hash_file = "/app/data/preview-totp", "/app/data/preview-sample-hash"
if not status.get("has_users"):
    call("POST", "/api/auth/register", {"username": user, "password": password})
    secret = call("GET", "/api/auth/totp/setup")["secret"]
    call("POST", "/api/auth/totp/confirm", {"code": pyotp.TOTP(secret).now()})
    with open(secret_file, "w") as fh:
        fh.write(secret)
else:
    secret = open(secret_file).read().strip()
    call("POST", "/api/auth/login", {"username": user, "password": password,
                                     "totp_code": pyotp.TOTP(secret).now(), "trust_device": False})

stored = open(hash_file).read().strip() if os.path.exists(hash_file) else ""
if stored == sample_hash:
    print("unchanged")
    sys.exit(0)
for capture in call("GET", "/api/captures"):
    call("DELETE", f"/api/captures/{capture['id']}")
capture = call("POST", "/api/captures/upload?filename=preview-home-network.pcap", raw=sys.stdin.buffer.read())
# Make it read as a capture on "any" with named interfaces (see the header).
names = {"2": "eth0", "3": "wlan0", "4": "wan", "5": "cni0"}
with sqlite3.connect("/app/data/pcap-server.db") as conn:
    conn.execute("UPDATE captures SET interface = 'any', interface_names = ? WHERE id = ?",
                 (json.dumps(names), capture["id"]))
with open(hash_file, "w") as fh:
    fh.write(sample_hash)
print("restart")
PY
)
wait_up() {
    for _ in $(seq 60); do
        docker exec "$NAME" python -c \
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/auth/status', timeout=2)" \
            >/dev/null 2>&1 && return 0
        sleep 1
    done
    echo "pcap-server preview did not come up" >&2
    return 1
}
SEEDED=$(python3 "$ROOT/scripts/preview_pcap.py" /dev/stdout \
    | docker exec -i -u appuser "$NAME" python -c "$SEED" "$USERNAME" "$PASSWORD" "$SAMPLE_HASH")
if [ "$SEEDED" = "restart" ]; then
    # Restart so the app reloads the capture with its interface names.
    docker restart "$NAME" >/dev/null
fi
wait_up
apply_settings
SECRET=$(docker exec -u appuser "$NAME" cat /app/data/preview-totp)

if [ -n "$KEPT" ] && [ "$SEEDED" = "unchanged" ]; then
    echo "Backend and sample capture unchanged: the running preview is kept (and you stay signed in)."
    echo "Frontend changes are already live -- refresh the browser."
    echo "Sign-in code if needed: $(code)"
    exit 0
fi
if [ "$SEEDED" = "restart" ]; then
    NOTE=" -- new sample capture loaded; the restart signed everyone out (a trusted browser needs only the password)"
elif [ -z "$KEPT" ]; then
    NOTE=" -- rebuilt for a backend change; the restart signed everyone out (a trusted browser needs only the password)"
fi

HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
cat <<EOF

pcap-server preview is up, with a sample capture loaded${NOTE:-}.

  URL        http://${HOST_IP:-localhost}:$PORT   (or http://localhost:$PORT on this machine)
  Username   $USERNAME
  Password   $PASSWORD
  Code       $(code)   <- changes every 30s; get a fresh one with: scripts/preview.sh code
             Tick "Trust this device" and this browser never needs a code again.
  TOTP key   $SECRET   (add it to an authenticator app instead, if you prefer)

Stop it with: scripts/preview.sh down
EOF
