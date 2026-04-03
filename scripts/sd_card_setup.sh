#!/usr/bin/env bash
# =============================================================================
# sd_card_setup.sh
#
# Run ONCE on a freshly flashed Raspberry Pi OS Lite (64-bit, Bookworm) SD card
# to prepare it as a Freezerbot base image.
#
# What it does:
#   1.  System update
#   2.  Install all apt dependencies (audio, Qt6, Python build tools, X11)
#   3.  Install all Python pip packages
#   4.  Configure portrait display rotation
#   5.  Configure audio output
#   6.  Install udev rule for USB auto-mount trigger
#   7.  Install systemd service skeleton
#   8.  Configure console auto-login for user pi
#   9.  Disable screen blanking
#  10.  Set hostname to freezerbot
#
# Usage (run as root or with sudo):
#   sudo bash sd_card_setup.sh
#
# After completion:
#   - Power off, remove SD card
#   - Create a compressed image backup (dd | gzip)
#   - Clone that image to any number of SD cards
# =============================================================================

set -euo pipefail

# Must run as root
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root: sudo bash $0"
    exit 1
fi

LOGFILE="/home/pi/sd_card_setup.log"
log()     { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOGFILE"; }
log_err() { echo "[$(date '+%H:%M:%S')] ERROR: $*" | tee -a "$LOGFILE" >&2; }
section() { echo "" | tee -a "$LOGFILE"; echo "=== $* ===" | tee -a "$LOGFILE"; }

log "Freezerbot SD card setup started."

# ---------------------------------------------------------------------------
# 1. System update
# ---------------------------------------------------------------------------
section "System Update"
apt-get update -qq
apt-get upgrade -y -qq
log "System updated."

# ---------------------------------------------------------------------------
# 2. Apt dependencies
# ---------------------------------------------------------------------------
section "Installing system packages"

APT_PACKAGES=(
    # Audio
    portaudio19-dev libportaudio2 alsa-utils mpg123 pulseaudio
    # Qt6 / display
    libgl1 libegl1 libxkbcommon-x11-0
    # X11 (for PyQt6 xcb backend)
    xorg xinit x11-xserver-utils xserver-xorg-input-evdev matchbox-window-manager
    # Python build tools
    python3-dev python3-pip build-essential libssl-dev libffi-dev
    # Utilities
    sqlite3 git openssl rsync
)

for pkg in "${APT_PACKAGES[@]}"; do
    if dpkg -s "$pkg" &>/dev/null; then
        log "  [skip] $pkg already installed"
    else
        log "  Installing $pkg ..."
        apt-get install -y -qq "$pkg"
    fi
done

# ---------------------------------------------------------------------------
# 3. Python pip packages
# ---------------------------------------------------------------------------
section "Installing Python packages"

PIP_PACKAGES=(
    "pvporcupine==3.0.2"
    "pyaudio==0.2.14"
    "groq==0.9.0"
    "google-generativeai==0.7.0"
    "gTTS==2.5.1"
    "pyttsx3==2.90"
    "pygame==2.6.0"
    "PyQt6==6.7.0"
    "rapidfuzz==3.9.0"
    "requests==2.32.0"
)

for pkg in "${PIP_PACKAGES[@]}"; do
    log "  Installing $pkg ..."
    pip3 install --break-system-packages -q "$pkg" 2>>"$LOGFILE" || \
        log_err "  Failed to install $pkg (non-fatal)"
done

# ---------------------------------------------------------------------------
# 4. Display: portrait rotation
# ---------------------------------------------------------------------------
section "Display configuration"

CONFIG_TXT="/boot/firmware/config.txt"
# Older Pi OS uses /boot/config.txt
[[ -f "$CONFIG_TXT" ]] || CONFIG_TXT="/boot/config.txt"

# Append display settings if not already present
if ! grep -q "display_rotate" "$CONFIG_TXT"; then
    cat >> "$CONFIG_TXT" <<'EOF'

# Freezerbot: portrait display (rotate 90 degrees clockwise)
display_rotate=1
dtoverlay=vc4-kms-v3d
# Prevent console blanking at boot
consoleblank=0
EOF
    log "Display rotation added to $CONFIG_TXT"
else
    log "Display rotation already configured."
fi

# Qt platform environment for framebuffer / X11
ENV_FILE="/etc/environment"
if ! grep -q "QT_QPA_PLATFORM" "$ENV_FILE"; then
    cat >> "$ENV_FILE" <<'EOF'

# Freezerbot Qt display settings
QT_QPA_PLATFORM=xcb
QT_QPA_EVDEV_TOUCHSCREEN_PARAMETERS=/dev/input/touchscreen0:rotate=90
EOF
    log "Qt environment variables added to $ENV_FILE"
fi

# ---------------------------------------------------------------------------
# 5. Audio: default output
# ---------------------------------------------------------------------------
section "Audio configuration"

ASOUND_CONF="/etc/asound.conf"
if [[ ! -f "$ASOUND_CONF" ]]; then
    cat > "$ASOUND_CONF" <<'EOF'
# Freezerbot audio: default to card 0 (3.5mm jack or USB audio)
defaults.pcm.card 0
defaults.ctl.card 0
EOF
    log "Created $ASOUND_CONF"
else
    log "asound.conf already exists — not overwritten."
fi

# ---------------------------------------------------------------------------
# 6. Udev rule for USB auto-trigger
# ---------------------------------------------------------------------------
section "Udev rule"

UDEV_RULE="/etc/udev/rules.d/99-freezerbot.rules"
cat > "$UDEV_RULE" <<'EOF'
# Start Freezerbot service when FREEZERBOT USB stick is detected
ACTION=="add", KERNEL=="sd[b-z]1", ENV{ID_FS_LABEL}=="FREEZERBOT", \
    RUN+="/bin/systemctl start freezerbot.service"
EOF
udevadm control --reload-rules
log "Udev rule installed: $UDEV_RULE"

# ---------------------------------------------------------------------------
# 7. Systemd service skeleton
# ---------------------------------------------------------------------------
section "Systemd service"

SERVICE_FILE="/etc/systemd/system/freezerbot.service"
cat > "$SERVICE_FILE" <<'EOF'
[Unit]
Description=Freezerbot Voice Inventory System
After=network-online.target sound.target graphical.target
Wants=network-online.target
ConditionPathExists=/media/pi/FREEZERBOT/bootstrap.sh

[Service]
User=pi
Group=pi
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/pi/.Xauthority
Environment=FREEZERBOT_ROOT=/media/pi/FREEZERBOT
Environment=QT_QPA_PLATFORM=xcb
WorkingDirectory=/media/pi/FREEZERBOT
ExecStart=/bin/bash /media/pi/FREEZERBOT/bootstrap.sh
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
log "Systemd service installed: $SERVICE_FILE"

# ---------------------------------------------------------------------------
# 8. Console auto-login for user pi
# ---------------------------------------------------------------------------
section "Auto-login"

AUTOLOGIN_DIR="/etc/systemd/system/getty@tty1.service.d"
mkdir -p "$AUTOLOGIN_DIR"
cat > "$AUTOLOGIN_DIR/autologin.conf" <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin pi --noclear %I $TERM
EOF
log "Auto-login configured for user pi."

# After login, start X server automatically if not running
BASH_PROFILE="/home/pi/.bash_profile"
if ! grep -q "startx" "$BASH_PROFILE" 2>/dev/null; then
    cat >> "$BASH_PROFILE" <<'EOF'

# Freezerbot: start X server on tty1
if [[ -z "$DISPLAY" ]] && [[ $(tty) == /dev/tty1 ]]; then
    startx -- -nocursor 2>/home/pi/xorg.log &
fi
EOF
    chown pi:pi "$BASH_PROFILE"
    log "startx added to $BASH_PROFILE"
fi

# Minimal xinitrc that just waits for the USB service to start
XINITRC="/home/pi/.xinitrc"
if [[ ! -f "$XINITRC" ]]; then
    cat > "$XINITRC" <<'EOF'
#!/bin/sh
# Freezerbot xinitrc: start matchbox window manager then idle
# The Freezerbot app is launched via systemd when USB is detected
matchbox-window-manager -use_titlebar no &
# Keep X alive
exec /bin/bash -c 'while true; do sleep 60; done'
EOF
    chown pi:pi "$XINITRC"
    chmod +x "$XINITRC"
    log "Created $XINITRC"
fi

# ---------------------------------------------------------------------------
# 9. Disable screen blanking in X
# ---------------------------------------------------------------------------
section "Screen blanking"

XORG_CONF_DIR="/etc/X11/xorg.conf.d"
mkdir -p "$XORG_CONF_DIR"
cat > "$XORG_CONF_DIR/10-freezerbot.conf" <<'EOF'
Section "ServerFlags"
    Option "BlankTime"  "0"
    Option "StandbyTime" "0"
    Option "SuspendTime" "0"
    Option "OffTime"    "0"
EndSection
EOF
log "Screen blanking disabled in Xorg."

# ---------------------------------------------------------------------------
# 10. Hostname
# ---------------------------------------------------------------------------
section "Hostname"
hostnamectl set-hostname freezerbot
log "Hostname set to freezerbot."

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
section "Setup complete"
log ""
log "SD card preparation complete!"
log ""
log "Next steps:"
log "  1. Power off the Pi"
log "  2. On another computer, create a compressed image backup:"
log "       sudo dd if=/dev/mmcblk0 bs=4M status=progress | gzip > freezerbot_sd_v1.img.gz"
log "  3. Flash that image to additional SD cards as needed"
log "  4. Prepare the FREEZERBOT USB stick with: scripts/prepare_usb.sh"
log "  5. Insert USB stick, power on — bootstrap.sh handles the rest"
log ""
log "Full log: $LOGFILE"
