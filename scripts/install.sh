#!/usr/bin/env bash
# =============================================================================
# install.sh
#
# Called by bootstrap.sh after git clone.
# Installs all system and Python dependencies, then copies app code to the
# USB stick. Idempotent — safe to run again to update the installation.
#
# Arguments:
#   $1 — USB_ROOT: path to FREEZERBOT USB stick mount
#   $2 — CLONE_DIR: path to the git-cloned repository
# =============================================================================

set -euo pipefail

USB_ROOT="${1:?USB_ROOT argument required}"
CLONE_DIR="${2:?CLONE_DIR argument required}"

LOG_FILE="$USB_ROOT/logs/install.log"
mkdir -p "$USB_ROOT/logs"

log()     { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
log_err() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" | tee -a "$LOG_FILE" >&2; }

log "install.sh started."
log "  USB root : $USB_ROOT"
log "  Clone dir: $CLONE_DIR"

# ---------------------------------------------------------------------------
# Python version check
# ---------------------------------------------------------------------------
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
REQUIRED_MAJOR=3
REQUIRED_MINOR=11

PY_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [[ "$PY_MAJOR" -lt "$REQUIRED_MAJOR" || ( "$PY_MAJOR" -eq "$REQUIRED_MAJOR" && "$PY_MINOR" -lt "$REQUIRED_MINOR" ) ]]; then
    log_err "Python $REQUIRED_MAJOR.$REQUIRED_MINOR+ required. Found: $PYTHON_VERSION"
    exit 1
fi
log "Python version OK: $PYTHON_VERSION"

# ---------------------------------------------------------------------------
# System package dependencies
# ---------------------------------------------------------------------------
log "Installing system packages..."
sudo apt-get update -qq 2>&1 | tail -1

SYSTEM_PACKAGES=(
    # Audio
    portaudio19-dev
    libportaudio2
    alsa-utils
    mpg123
    pulseaudio
    # Qt6 / display
    libgl1
    libegl1
    libxkbcommon-x11-0
    # X11 (needed for PyQt6 xcb platform plugin)
    xorg
    xinit
    x11-xserver-utils
    x11-apps
    xinput
    xserver-xorg-input-evdev
    matchbox-window-manager
    # Python build tools
    python3-dev
    python3-pip
    build-essential
    libssl-dev
    libffi-dev
    # Utilities
    sqlite3
    git
    openssl
    rsync
)

for pkg in "${SYSTEM_PACKAGES[@]}"; do
    if dpkg -s "$pkg" &>/dev/null; then
        log "  [OK] $pkg already installed"
    else
        log "  Installing $pkg ..."
        sudo apt-get install -y -qq "$pkg" 2>&1 | tail -1 || log_err "Failed to install $pkg (continuing)"
    fi
done

# ---------------------------------------------------------------------------
# Python package dependencies
# ---------------------------------------------------------------------------
log "Installing Python packages..."

# Single source of truth for package versions is requirements.txt in the repo.
REQUIREMENTS="$CLONE_DIR/requirements.txt"
if [[ ! -f "$REQUIREMENTS" ]]; then
    log_err "requirements.txt not found at $REQUIREMENTS"
    exit 1
fi

# Map from pip distribution name (lower-case, normalised) to Python import name.
# Only entries that differ between the two need to be listed here.
declare -A IMPORT_OVERRIDE=(
    ["google-generativeai"]="google.generativeai"
    ["gtts"]="gtts"
    ["pyqt6"]="PyQt6"
)

_import_name_for() {
    # $1 = distribution name (e.g. "google-generativeai")
    local dist_lower
    dist_lower=$(echo "$1" | tr '[:upper:]' '[:lower:]' | tr '-' '_')
    if [[ -v "IMPORT_OVERRIDE[$(echo "$1" | tr '[:upper:]' '[:lower:]')]" ]]; then
        echo "${IMPORT_OVERRIDE[$(echo "$1" | tr '[:upper:]' '[:lower:]')]}"
    else
        echo "$dist_lower"
    fi
}

while IFS= read -r line || [[ -n "$line" ]]; do
    # Skip blank lines and comments
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue

    pkg_spec="$line"
    # Strip version specifier to get the distribution name
    dist_name="${pkg_spec%%[=><!\[]*}"
    import_name=$(_import_name_for "$dist_name")

    if python3 -c "import $import_name" 2>/dev/null; then
        log "  [OK] $import_name already installed"
    else
        log "  Installing $pkg_spec ..."
        pip3 install --break-system-packages -q "$pkg_spec" 2>&1 | tail -1 || \
            log_err "Failed to install $pkg_spec (continuing)"
    fi
done < "$REQUIREMENTS"

# ---------------------------------------------------------------------------
# Copy application code from clone to USB stick
# ---------------------------------------------------------------------------
log "Copying application code to USB stick..."

# Preserve config/, data/, logs/, wake_words/ — only update runtime code/assets.
rsync -a --delete \
    "$CLONE_DIR/app/"       "$USB_ROOT/app/"       2>>"$LOG_FILE"
rsync -a --delete \
    "$CLONE_DIR/scripts/"   "$USB_ROOT/scripts/"   2>>"$LOG_FILE"
cp "$CLONE_DIR/requirements.txt" "$USB_ROOT/requirements.txt"

# Copy keys.enc if present in the repo (it may not be on fresh clones)
if [[ -f "$CLONE_DIR/keys.enc" ]]; then
    cp "$CLONE_DIR/keys.enc" "$USB_ROOT/keys.enc"
    log "  keys.enc copied."
fi

# Ensure required directories exist
mkdir -p "$USB_ROOT/data" "$USB_ROOT/logs"
chmod +x "$USB_ROOT/scripts/"*.sh 2>/dev/null || true
chmod +x "$USB_ROOT/bootstrap.sh"  2>/dev/null || true

log "Application code installed."

# ---------------------------------------------------------------------------
# Configure auto-login (console, user pi)
# ---------------------------------------------------------------------------
AUTOLOGIN_CONF="/etc/systemd/system/getty@tty1.service.d/autologin.conf"
if [[ ! -f "$AUTOLOGIN_CONF" ]]; then
    log "Configuring console auto-login for user pi..."
    sudo mkdir -p "$(dirname "$AUTOLOGIN_CONF")"
    sudo tee "$AUTOLOGIN_CONF" > /dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin pi --noclear %I $TERM
EOF
    log "  Auto-login configured."
fi

# ---------------------------------------------------------------------------
# Configure kiosk X auto-start via .bash_profile and .xinitrc
# ---------------------------------------------------------------------------
BASH_PROFILE="/home/pi/.bash_profile"
if ! grep -q "startx" "$BASH_PROFILE" 2>/dev/null; then
    log "Configuring X auto-start in .bash_profile..."
    cat >> "$BASH_PROFILE" <<'EOF'

# Freezerbot: start X automatically on tty1
if [[ -z "$DISPLAY" && "$(tty)" == "/dev/tty1" ]]; then
    exec startx 2>/home/pi/startx.log
fi
EOF
    log "  .bash_profile updated."
fi

XINITRC="/home/pi/.xinitrc"
if [[ ! -f "$XINITRC" ]]; then
    log "Creating .xinitrc..."
    cat > "$XINITRC" <<'EOF'
#!/bin/bash
export FREEZERBOT_ROOT=/media/pi/FREEZERBOT
export QT_QPA_PLATFORM=xcb
xsetroot -cursor_name blank
exec /bin/bash /media/pi/FREEZERBOT/bootstrap.sh
EOF
    chmod +x "$XINITRC"
    log "  .xinitrc created."
fi

# Allow X to start from non-console sessions (safety net for future use)
XWRAPPER="/etc/X11/Xwrapper.config"
if ! grep -q "allowed_users=anybody" "$XWRAPPER" 2>/dev/null; then
    sudo sh -c 'printf "allowed_users=anybody\nneeds_root_rights=yes\n" > /etc/X11/Xwrapper.config'
    log "  Xwrapper.config configured."
fi

# ---------------------------------------------------------------------------
# Auto-mount USB stick via /etc/fstab
# ---------------------------------------------------------------------------
FSTAB="/etc/fstab"
if ! grep -q "FREEZERBOT" "$FSTAB" 2>/dev/null; then
    log "Adding FREEZERBOT USB auto-mount to /etc/fstab..."
    sudo mkdir -p /media/pi/FREEZERBOT
    echo "LABEL=FREEZERBOT /media/pi/FREEZERBOT vfat defaults,nofail,uid=1000,gid=1000 0 0" | sudo tee -a "$FSTAB" > /dev/null
    log "  fstab entry added."
fi

# ---------------------------------------------------------------------------
# Mark installation complete
# ---------------------------------------------------------------------------
date > "$USB_ROOT/.install_complete"
log "Install complete. Marker written to .install_complete"
