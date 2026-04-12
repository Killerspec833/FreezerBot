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

# Single source of truth for package versions is requirements.txt, located
# two directories up from this script (repo root / USB root).
REQUIREMENTS="$USB_ROOT/requirements.txt"
# Fall back to the scripts/ sibling location if running from the repo directly
[[ -f "$REQUIREMENTS" ]] || REQUIREMENTS="$(cd "$(dirname "$0")/.." && pwd)/requirements.txt"

if [[ ! -f "$REQUIREMENTS" ]]; then
    log_err "requirements.txt not found (expected at $REQUIREMENTS)"
    exit 1
fi

# Map from pip distribution name (lower-case) to Python import name for
# packages where the two differ.
declare -A IMPORT_OVERRIDE=(
    ["google-generativeai"]="google.generativeai"
    ["gtts"]="gtts"
    ["pyqt6"]="PyQt6"
)

_import_name_for() {
    local dist_lower
    dist_lower=$(echo "$1" | tr '[:upper:]' '[:lower:]' | tr '-' '_')
    if [[ -v "IMPORT_OVERRIDE[$(echo "$1" | tr '[:upper:]' '[:lower:]')]" ]]; then
        echo "${IMPORT_OVERRIDE[$(echo "$1" | tr '[:upper:]' '[:lower:]')]}"
    else
        echo "$dist_lower"
    fi
}

log "Checking Python packages against $REQUIREMENTS ..."

while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue

    pkg_spec="$line"
    dist_name="${pkg_spec%%[=><!\[]*}"
    import_name=$(_import_name_for "$dist_name")

    if python3 -c "import $import_name" 2>/dev/null; then
        ok "$import_name"
    else
        log "Missing: $import_name — installing $pkg_spec ..."
        pip3 install --break-system-packages -q "$pkg_spec" 2>>"$LOG_FILE" && \
            ok "$import_name (installed)" || \
            log_err "Failed to install $pkg_spec"
    fi
done < "$REQUIREMENTS"

# ---------------------------------------------------------------------------
# USB stick directories
# ---------------------------------------------------------------------------
for dir in app config data logs; do
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
