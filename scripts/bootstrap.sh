#!/usr/bin/env bash
# =============================================================================
# bootstrap.sh
#
# Lives on the USB stick root. Triggered on first boot by the Pi's udev/systemd
# rule when the FREEZERBOT USB stick is mounted.
#
# Responsibilities:
#   1. Verify WiFi / internet connectivity (retry loop)
#   2. Detect if app is already installed on USB stick
#   3. If not installed: git clone repo + run install.sh
#   4. Decrypt API keys from keys.enc and write to config.json
#   5. Run setup_check.sh (dependency verification)
#   6. Launch the application
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — edit GITHUB_REPO_URL before first use
# ---------------------------------------------------------------------------
GITHUB_REPO_URL="https://github.com/Killerspec833/FreezerBot.git"
GITHUB_REPO_BRANCH="main"

# ---------------------------------------------------------------------------
# Path detection: find where this USB stick is mounted
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
USB_ROOT="$SCRIPT_DIR"
export FREEZERBOT_ROOT="$USB_ROOT"

LOG_FILE="$USB_ROOT/logs/bootstrap.log"
mkdir -p "$USB_ROOT/logs"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
log_err() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" | tee -a "$LOG_FILE" >&2; }

log "bootstrap.sh started. USB root: $USB_ROOT"

# ---------------------------------------------------------------------------
# 1. Wait for internet connectivity (retry up to 5 minutes)
# ---------------------------------------------------------------------------
log "Checking internet connectivity..."
MAX_WAIT=300
WAITED=0
INTERVAL=10

until python3 -c "import socket; socket.setdefaulttimeout(3); socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(('8.8.8.8', 53))" 2>/dev/null; do
    if [[ $WAITED -ge $MAX_WAIT ]]; then
        log_err "No internet connection after ${MAX_WAIT}s. Cannot proceed."
        log_err "Ensure WiFi is configured in Raspberry Pi OS before first boot."
        exit 1
    fi
    log "No internet yet. Retrying in ${INTERVAL}s... (${WAITED}/${MAX_WAIT}s elapsed)"
    sleep "$INTERVAL"
    WAITED=$((WAITED + INTERVAL))
done

log "Internet connectivity confirmed."

# ---------------------------------------------------------------------------
# 2. Check if app is already installed on USB stick
# ---------------------------------------------------------------------------
APP_MAIN="$USB_ROOT/app/main.py"
INSTALL_MARKER="$USB_ROOT/.install_complete"

if [[ -f "$INSTALL_MARKER" && -f "$APP_MAIN" ]]; then
    log "App already installed. Skipping clone and install."
else
    log "App not installed. Starting installation from GitHub..."

    # -----------------------------------------------------------------------
    # 3. Clone the repository to a temp location and run install.sh
    # -----------------------------------------------------------------------
    CLONE_DIR="$(mktemp -d /tmp/freezerbot_install.XXXXXX)"
    log "Cloning $GITHUB_REPO_URL (branch: $GITHUB_REPO_BRANCH) to $CLONE_DIR ..."

    if ! git clone --depth 1 --branch "$GITHUB_REPO_BRANCH" "$GITHUB_REPO_URL" "$CLONE_DIR"; then
        log_err "git clone failed. Check GITHUB_REPO_URL in bootstrap.sh."
        rm -rf "$CLONE_DIR"
        exit 1
    fi

    log "Clone complete. Running install.sh..."
    bash "$CLONE_DIR/scripts/install.sh" "$USB_ROOT" "$CLONE_DIR"

    # install.sh copies app code to USB_ROOT and sets the marker
    rm -rf "$CLONE_DIR"
    log "Installation complete."
fi

# ---------------------------------------------------------------------------
# 4. Decrypt API keys and write to config.json (if keys.enc exists and
#    config.json still has empty keys)
# ---------------------------------------------------------------------------
KEYS_ENC="$USB_ROOT/keys.enc"
PASSPHRASE_FILE="$USB_ROOT/config/.install_passphrase"
CONFIG_FILE="$USB_ROOT/config/config.json"

if [[ -f "$KEYS_ENC" && -f "$PASSPHRASE_FILE" ]]; then
    KEYS_ALREADY_SET=$(python3 -c "
import json, sys
try:
    cfg = json.load(open(sys.argv[1]))
    keys = cfg.get('api_keys', {})
    all_set = all([
        keys.get('picovoice_access_key'),
        keys.get('groq_api_key'),
        keys.get('gemini_api_key'),
    ])
    print('yes' if all_set else 'no')
except Exception:
    print('no')
" "$CONFIG_FILE" 2>/dev/null || echo "no")

    if [[ "$KEYS_ALREADY_SET" == "no" ]]; then
        log "Decrypting API keys..."
        PASSPHRASE="$(cat "$PASSPHRASE_FILE")"
        DECRYPTED_JSON="$(mktemp /tmp/freezerbot_keys.XXXXXX.json)"

        if openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -d \
            -pass "pass:$PASSPHRASE" \
            -in "$KEYS_ENC" \
            -out "$DECRYPTED_JSON" 2>>"$LOG_FILE"; then

            python3 - "$CONFIG_FILE" "$DECRYPTED_JSON" <<'PYEOF'
import json, sys

config_path = sys.argv[1]
keys_path   = sys.argv[2]

with open(config_path, 'r') as f:
    config = json.load(f)

with open(keys_path, 'r') as f:
    keys = json.load(f)

config['api_keys']['picovoice_access_key'] = keys.get('picovoice_access_key', '')
config['api_keys']['groq_api_key']         = keys.get('groq_api_key', '')
config['api_keys']['gemini_api_key']       = keys.get('gemini_api_key', '')

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)
PYEOF

            log "API keys written to config.json."
        else
            log_err "Failed to decrypt keys.enc. Check passphrase file and keys.enc integrity."
        fi

        # Securely delete the temp decrypted file regardless of outcome
        python3 -c "
import os, sys
path = sys.argv[1]
try:
    size = os.path.getsize(path)
    with open(path, 'r+b') as f:
        f.write(b'0' * size)
    os.remove(path)
except Exception:
    pass
" "$DECRYPTED_JSON" 2>/dev/null || rm -f "$DECRYPTED_JSON"

    else
        log "API keys already set in config.json. Skipping decryption."
    fi
else
    log "keys.enc or passphrase file not found — skipping key decryption."
fi

# ---------------------------------------------------------------------------
# 5. Run setup_check.sh (verify/install any missing dependencies)
# ---------------------------------------------------------------------------
SETUP_CHECK="$USB_ROOT/scripts/setup_check.sh"
if [[ -f "$SETUP_CHECK" ]]; then
    log "Running setup_check.sh..."
    bash "$SETUP_CHECK" "$USB_ROOT" 2>&1 | tee -a "$LOG_FILE"
else
    log "setup_check.sh not found — skipping dependency check."
fi

# ---------------------------------------------------------------------------
# 6. Launch the application
# ---------------------------------------------------------------------------
log "Launching Freezerbot application..."
exec python3 "$USB_ROOT/app/main.py" >> "$LOG_FILE" 2>&1
