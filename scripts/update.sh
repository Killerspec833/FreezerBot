#!/usr/bin/env bash
# =============================================================================
# update.sh
#
# Manual update script — pulls the latest app code from GitHub and installs
# it to the USB stick WITHOUT touching config.json, inventory.db, or wake_words/.
#
# Run this from the Pi when you want to apply new code:
#   bash /media/pi/FREEZERBOT/scripts/update.sh
#
# Or trigger it remotely via SSH.
# =============================================================================

set -euo pipefail

GITHUB_REPO_URL="https://github.com/Killerspec833/FreezerBot.git"
GITHUB_BRANCH="main"

# ---------------------------------------------------------------------------
# Locate USB root
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USB_ROOT="$SCRIPT_DIR"
export FREEZERBOT_ROOT="$USB_ROOT"

LOG_FILE="$USB_ROOT/logs/update.log"
mkdir -p "$USB_ROOT/logs"

log()     { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [update] $*" | tee -a "$LOG_FILE"; }
log_err() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [update] ERROR: $*" | tee -a "$LOG_FILE" >&2; }

log "Update started. USB root: $USB_ROOT"

# ---------------------------------------------------------------------------
# Internet check
# ---------------------------------------------------------------------------
if ! python3 -c "import socket; socket.setdefaulttimeout(3); socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(('8.8.8.8', 53))" 2>/dev/null; then
    log_err "No internet connection. Cannot update."
    exit 1
fi
log "Internet connectivity confirmed."

# ---------------------------------------------------------------------------
# Stop the running app if active
# ---------------------------------------------------------------------------
if systemctl is-active --quiet freezerbot.service 2>/dev/null; then
    log "Stopping Freezerbot service..."
    sudo systemctl stop freezerbot.service
    RESTART_AFTER=true
else
    RESTART_AFTER=false
fi

# ---------------------------------------------------------------------------
# Clone latest code to temp dir
# ---------------------------------------------------------------------------
CLONE_DIR="$(mktemp -d /tmp/freezerbot_update.XXXXXX)"
log "Cloning latest code from $GITHUB_REPO_URL ..."

if ! git clone --depth 1 --branch "$GITHUB_BRANCH" "$GITHUB_REPO_URL" "$CLONE_DIR" 2>>"$LOG_FILE"; then
    log_err "git clone failed."
    rm -rf "$CLONE_DIR"
    [[ "$RESTART_AFTER" == true ]] && sudo systemctl start freezerbot.service
    exit 1
fi
log "Clone complete."

# ---------------------------------------------------------------------------
# Get current and new version (last git commit hash)
# ---------------------------------------------------------------------------
NEW_HASH=$(git -C "$CLONE_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")
CURRENT_HASH_FILE="$USB_ROOT/.current_version"
CURRENT_HASH=$(cat "$CURRENT_HASH_FILE" 2>/dev/null || echo "none")

log "Current version: $CURRENT_HASH"
log "Available version: $NEW_HASH"

if [[ "$CURRENT_HASH" == "$NEW_HASH" ]]; then
    log "Already up to date. No changes applied."
    rm -rf "$CLONE_DIR"
    [[ "$RESTART_AFTER" == true ]] && sudo systemctl start freezerbot.service
    exit 0
fi

# ---------------------------------------------------------------------------
# Sync app code and scripts to USB stick
# Explicitly EXCLUDE config/, data/, logs/, wake_words/ to protect user data
# ---------------------------------------------------------------------------
log "Syncing app/ ..."
rsync -a --delete \
    "$CLONE_DIR/app/" \
    "$USB_ROOT/app/" \
    2>>"$LOG_FILE"

log "Syncing scripts/ ..."
rsync -a --delete \
    "$CLONE_DIR/scripts/" \
    "$USB_ROOT/scripts/" \
    2>>"$LOG_FILE"

# Update bootstrap.sh in USB root
if [[ -f "$CLONE_DIR/scripts/bootstrap.sh" ]]; then
    cp "$CLONE_DIR/scripts/bootstrap.sh" "$USB_ROOT/bootstrap.sh"
fi

# Update keys.enc if a newer one is in the repo
if [[ -f "$CLONE_DIR/keys.enc" ]]; then
    cp "$CLONE_DIR/keys.enc" "$USB_ROOT/keys.enc"
    log "keys.enc updated."
fi

chmod +x "$USB_ROOT/scripts/"*.sh 2>/dev/null || true
chmod +x "$USB_ROOT/bootstrap.sh" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Update systemd service if changed
# ---------------------------------------------------------------------------
SERVICE_SRC="$CLONE_DIR/scripts/freezerbot.service"
SERVICE_DEST="/etc/systemd/system/freezerbot.service"
if [[ -f "$SERVICE_SRC" ]] && ! diff -q "$SERVICE_SRC" "$SERVICE_DEST" &>/dev/null; then
    log "Updating systemd service..."
    sudo cp "$SERVICE_SRC" "$SERVICE_DEST"
    sudo systemctl daemon-reload
fi

# ---------------------------------------------------------------------------
# Record new version and clean up
# ---------------------------------------------------------------------------
echo "$NEW_HASH" > "$CURRENT_HASH_FILE"
rm -rf "$CLONE_DIR"

log "Update complete. Now at version: $NEW_HASH"

# ---------------------------------------------------------------------------
# Restart app if it was running
# ---------------------------------------------------------------------------
if [[ "$RESTART_AFTER" == true ]]; then
    log "Restarting Freezerbot service..."
    sudo systemctl start freezerbot.service
fi

log "Done."
