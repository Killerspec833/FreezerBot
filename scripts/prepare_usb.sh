#!/usr/bin/env bash
# =============================================================================
# prepare_usb.sh
#
# Run this ONCE on your computer (Linux/macOS) to prepare a blank USB stick
# before first use on the Pi. It will:
#   1. Prompt for your three API keys
#   2. Generate a random passphrase
#   3. Encrypt the keys with AES-256-CBC (openssl)
#   4. Write keys.enc to the repo root (to be committed to GitHub)
#   5. Write the passphrase to the USB stick at config/.install_passphrase
#   6. Copy config/config.json template to the USB stick
#
# Usage:
#   ./scripts/prepare_usb.sh /path/to/USB_mount_point
#
# Example (macOS):
#   ./scripts/prepare_usb.sh /Volumes/FREEZERBOT
#
# Example (Linux):
#   ./scripts/prepare_usb.sh /media/$USER/FREEZERBOT
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
red()   { echo -e "\033[0;31m$*\033[0m"; }
green() { echo -e "\033[0;32m$*\033[0m"; }
bold()  { echo -e "\033[1m$*\033[0m"; }

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || { red "Required command not found: $1"; exit 1; }
}

# ---------------------------------------------------------------------------
# Argument check
# ---------------------------------------------------------------------------
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <USB_mount_path>"
    echo "Example: $0 /Volumes/FREEZERBOT"
    exit 1
fi

USB="$1"

if [[ ! -d "$USB" ]]; then
    red "Mount point not found: $USB"
    exit 1
fi

require_cmd openssl
require_cmd python3

# Locate repo root (parent of this script's directory)
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ---------------------------------------------------------------------------
# Collect API keys
# ---------------------------------------------------------------------------
bold "\n=== Freezerbot USB Preparation ==="
echo ""
echo "You will be prompted for your three API keys."
echo "Keys are never stored in plain text — they are encrypted before leaving this terminal."
echo ""

read -rsp "Picovoice Access Key: " PICO_KEY; echo
read -rsp "Groq API Key:         " GROQ_KEY; echo
read -rsp "Gemini API Key:       " GEMINI_KEY; echo

if [[ -z "$PICO_KEY" || -z "$GROQ_KEY" || -z "$GEMINI_KEY" ]]; then
    red "All three API keys are required."
    exit 1
fi

# ---------------------------------------------------------------------------
# Generate passphrase
# ---------------------------------------------------------------------------
PASSPHRASE="$(python3 -c "import secrets, string; \
    chars = string.ascii_letters + string.digits; \
    print(''.join(secrets.choice(chars) for _ in range(48)))")"

# ---------------------------------------------------------------------------
# Build keys JSON and encrypt it
# ---------------------------------------------------------------------------
KEYS_JSON=$(python3 -c "
import json, sys
keys = {
    'picovoice_access_key': sys.argv[1],
    'groq_api_key':         sys.argv[2],
    'gemini_api_key':       sys.argv[3],
}
print(json.dumps(keys))
" "$PICO_KEY" "$GROQ_KEY" "$GEMINI_KEY")

ENC_OUT="$REPO_ROOT/keys.enc"

echo "$KEYS_JSON" | openssl enc -aes-256-cbc -pbkdf2 -iter 100000 \
    -pass "pass:$PASSPHRASE" \
    -out "$ENC_OUT"

green "  keys.enc written to: $ENC_OUT"

# ---------------------------------------------------------------------------
# Write passphrase to USB stick
# ---------------------------------------------------------------------------
mkdir -p "$USB/config"
PASSPHRASE_FILE="$USB/config/.install_passphrase"
printf '%s' "$PASSPHRASE" > "$PASSPHRASE_FILE"
chmod 600 "$PASSPHRASE_FILE"

green "  Passphrase written to: $PASSPHRASE_FILE"

# ---------------------------------------------------------------------------
# Copy config.json template to USB stick (only if not already present)
# ---------------------------------------------------------------------------
CONFIG_DEST="$USB/config/config.json"
if [[ ! -f "$CONFIG_DEST" ]]; then
    cp "$REPO_ROOT/config/config.json" "$CONFIG_DEST"
    green "  config.json template copied to USB stick."
else
    echo "  config/config.json already exists on USB stick — not overwritten."
fi

# ---------------------------------------------------------------------------
# Create required USB directories
# ---------------------------------------------------------------------------
mkdir -p "$USB/data" "$USB/logs" "$USB/wake_words"
green "  USB directories created: data/, logs/, wake_words/"

# ---------------------------------------------------------------------------
# Remind user to copy bootstrap.sh and wake word files
# ---------------------------------------------------------------------------
BOOTSTRAP_SRC="$REPO_ROOT/scripts/bootstrap.sh"
BOOTSTRAP_DEST="$USB/bootstrap.sh"
cp "$BOOTSTRAP_SRC" "$BOOTSTRAP_DEST"
chmod +x "$BOOTSTRAP_DEST"
green "  bootstrap.sh copied to USB stick root."

echo ""
bold "=== Next steps ==="
echo ""
echo "1. Commit keys.enc to your GitHub repo:"
echo "     git add keys.enc && git commit -m 'Add encrypted API keys'"
echo ""
echo "2. Copy wake word .ppn files to:"
echo "     $USB/wake_words/"
echo "   (Download from console.picovoice.ai for Raspberry Pi ARM platform)"
echo ""
echo "3. Insert the USB stick into your Pi and power on."
echo "   bootstrap.sh will run automatically on first boot."
echo ""
green "USB preparation complete."
