#!/usr/bin/env bash
# =============================================================================
# setup_check.sh
#
# Run by bootstrap.sh before every app launch (via ExecStartPre in systemd).
# Verifies dependencies are present and re-installs any that are missing.
# Idempotent — fast when everything is already installed.
#
# Arguments:
#   $1 — USB_ROOT: path to FREEZERBOT USB stick mount (optional, auto-detected)
# =============================================================================

set -euo pipefail

USB_ROOT="${1:-}"
if [[ -z "$USB_ROOT" ]]; then
    # Auto-detect: walk up from this script's location
    USB_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fi

LOG_FILE="$USB_ROOT/logs/setup_check.log"
mkdir -p "$USB_ROOT/logs"

log()     { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [setup_check] $*" | tee -a "$LOG_FILE"; }
log_err() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [setup_check] ERROR: $*" | tee -a "$LOG_FILE" >&2; }
ok()      { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [setup_check]   OK  $*" | tee -a "$LOG_FILE"; }

log "Running setup_check. USB root: $USB_ROOT"

# ---------------------------------------------------------------------------
# Python version
# ---------------------------------------------------------------------------
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
PY_MAJ=$(echo "$PY_VER" | cut -d. -f1)
PY_MIN=$(echo "$PY_VER" | cut -d. -f2)

if [[ "$PY_MAJ" -lt 3 || ( "$PY_MAJ" -eq 3 && "$PY_MIN" -lt 11 ) ]]; then
    log_err "Python 3.11+ required. Found: $PY_VER"
    exit 1
fi
ok "Python $PY_VER"

# ---------------------------------------------------------------------------
# Python packages — check and install missing
# ---------------------------------------------------------------------------
declare -A PY_PACKAGES=(
    ["pvporcupine"]="pvporcupine==3.0.2"
    ["pyaudio"]="pyaudio==0.2.14"
    ["groq"]="groq==0.9.0"
    ["google.generativeai"]="google-generativeai==0.7.0"
    ["gtts"]="gTTS==2.5.1"
    ["pyttsx3"]="pyttsx3==2.90"
    ["pygame"]="pygame==2.6.0"
    ["PyQt6"]="PyQt6==6.7.0"
    ["rapidfuzz"]="rapidfuzz==3.9.0"
    ["requests"]="requests==2.32.0"
)

for import_name in "${!PY_PACKAGES[@]}"; do
    pkg_spec="${PY_PACKAGES[$import_name]}"
    if python3 -c "import $import_name" 2>/dev/null; then
        ok "$import_name"
    else
        log "Missing: $import_name — installing $pkg_spec ..."
        pip3 install --break-system-packages -q "$pkg_spec" 2>>"$LOG_FILE" && \
            ok "$import_name (installed)" || \
            log_err "Failed to install $pkg_spec"
    fi
done

# ---------------------------------------------------------------------------
# USB stick directories
# ---------------------------------------------------------------------------
for dir in app config data logs wake_words; do
    full="$USB_ROOT/$dir"
    if [[ -d "$full" ]]; then
        ok "Directory: $dir/"
    else
        log "Creating missing directory: $dir/"
        mkdir -p "$full"
    fi
done

# ---------------------------------------------------------------------------
# config.json presence
# ---------------------------------------------------------------------------
CONFIG_FILE="$USB_ROOT/config/config.json"
if [[ -f "$CONFIG_FILE" ]]; then
    ok "config.json present"
else
    log_err "config.json missing at $CONFIG_FILE"
    exit 1
fi

# ---------------------------------------------------------------------------
# Audio device check (informational — does not block startup)
# ---------------------------------------------------------------------------
AUDIO_DEVICES=$(python3 -c "
import pyaudio
p = pyaudio.PyAudio()
devices = []
for i in range(p.get_device_count()):
    d = p.get_device_info_by_index(i)
    if d['maxInputChannels'] > 0:
        devices.append(f\"  [{i}] {d['name']}\")
p.terminate()
print('\n'.join(devices) if devices else '  (none found)')
" 2>/dev/null || echo "  pyaudio not available")

log "Available audio input devices:"
echo "$AUDIO_DEVICES" | tee -a "$LOG_FILE"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
log "setup_check complete."
exit 0
