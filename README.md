# Freezerbot

Voice-controlled freezer inventory system for Raspberry Pi 4.

Speak to add or remove food items across multiple freezer locations.
Ask questions like "Is there any chicken?" or "What's in the basement freezer?"

---

## Hardware Required

| Component | Notes |
|-----------|-------|
| Raspberry Pi 4 (2GB+ RAM) | Any revision |
| MicroSD card (16GB+) | For OS base image |
| USB stick (16GB+, FAT32) | Label must be `FREEZERBOT` |
| 10.1" touchscreen 1024×600 | Landscape orientation |
| USB microphone | Any USB mic |
| Speaker | 3.5mm jack or USB |

---

## Architecture

```
SD Card:  Raspberry Pi OS Lite 64-bit + all dependencies (base image)
USB Stick: App code + SQLite database + config + wake word files
```

The USB stick is the portable "brain" — move it between any Pi with the base SD image.

---

## One-Time Setup

### Step 1 — Create accounts (all free)

1. **Picovoice** — [console.picovoice.ai](https://console.picovoice.ai)
   - Create account → copy your **Access Key**
   - Go to Wake Words → create a custom wake word for each option you want
   - Platform: **Raspberry Pi (ARM Cortex-A72)**
   - Download each `.ppn` file

2. **Groq** — [console.groq.com](https://console.groq.com)
   - Create account → API Keys → Create API Key → copy it

3. **Google AI Studio** — [aistudio.google.com](https://aistudio.google.com)
   - Create a project → Get API key → copy it

---

### Step 2 — Flash the SD card

1. Download **Raspberry Pi OS Lite 64-bit (Bookworm)** from [raspberrypi.com/software](https://www.raspberrypi.com/software/)
2. Flash using **Raspberry Pi Imager**
   - Click the gear icon (Advanced Options) before writing:
     - Hostname: `freezerbot`
     - Username: `pi`, set a password
     - **Configure WiFi**: enter your network SSID and password
     - Enable SSH (optional but useful)
3. Insert SD card into Pi, connect display, keyboard, power on
4. SSH in or use the keyboard to run the setup script:

```bash
curl -fsSL https://raw.githubusercontent.com/Killerspec833/FreezerBot/main/scripts/sd_card_setup.sh | sudo bash
```

Or copy the script to the Pi and run `sudo bash sd_card_setup.sh`.

5. When complete, **power off the Pi**
6. Optional — create a reusable SD card image backup:
```bash
# Run this on another Linux machine with the SD card inserted as /dev/mmcblk0
sudo dd if=/dev/mmcblk0 bs=4M status=progress | gzip > freezerbot_sd_v1.img.gz
```

---

### Step 3 — Prepare the USB stick

On your computer (Linux or macOS):

1. Format the USB stick as **FAT32** with label `FREEZERBOT`

   **Linux:**
   ```bash
   sudo mkfs.vfat -n FREEZERBOT -F 32 /dev/sdX1
   ```
   **macOS:**
   ```bash
   diskutil eraseDisk FAT32 FREEZERBOT MBRFormat /dev/diskN
   ```
   **Windows:** Format dialog → FAT32, Volume Label = `FREEZERBOT`

2. Clone the repo and run the USB preparation script:
   ```bash
   git clone https://github.com/Killerspec833/FreezerBot.git
   cd FreezerBot
   bash scripts/prepare_usb.sh /path/to/FREEZERBOT/mount
   ```
   When prompted, enter your three API keys. The script encrypts them and writes all necessary files.

3. Copy your wake word `.ppn` files to the USB stick:
   ```
   /FREEZERBOT/wake_words/Computer_en_raspberry-pi_v3_0_0.ppn
   /FREEZERBOT/wake_words/Hey-Jarvis_en_raspberry-pi_v3_0_0.ppn
   ... (whichever words you downloaded)
   ```

4. Commit `keys.enc` to your GitHub repo (it is AES-256 encrypted — safe to commit):
   ```bash
   git add keys.enc
   git commit -m "Add encrypted API keys"
   git push
   ```

---

### Step 4 — First boot

1. Insert the USB stick into the Pi
2. Power on
3. The Pi boots, logs in automatically, starts X, detects the USB stick via udev, and runs `bootstrap.sh`
4. `bootstrap.sh`:
   - Waits for WiFi (up to 5 minutes)
   - Clones the GitHub repo
   - Installs any missing dependencies
   - Decrypts API keys into `config.json`
   - Launches the app
5. **Setup wizard** appears on screen:
   - Choose your wake word
   - Review storage locations
   - System check (all green = proceed)
   - Done — Freezerbot is ready

---

## Daily Use

### Wake the system
- Say your chosen wake word (e.g. **"Frost"** or **"Hey Jarvis"**)
- Or tap anywhere on the screen
- The blue circle with red ripple rings appears — you're being heard

### Add an item
> *"Add ground beef, 2 packages, basement freezer"*
> *"Add one roast to the kitchen"*

The screen shows what was heard. Say **"yes"** or tap **Confirm**.
Say **"no"** or tap **Deny** to try again.

### Remove an item
> *"Remove the chicken thighs"*
> *"Ground beef out"*
> *"Subtract pork chops"*

### Ask a question
> *"Is there any salmon?"*
> *"Find chicken breast"*
> *"Do we have any beef?"*

### List a location
> *"What's in the basement freezer?"*
> *"Show me the kitchen freezer"*
> *"List the fridge"*

---

## Storage Locations

| Say... | Means... |
|--------|----------|
| "basement" / "chest freezer" / "basement freezer" | Basement Freezer |
| "kitchen" / "tall one" / "tall freezer" | Kitchen Freezer |
| "fridge" / "fridge freezer" / "small freezer" | Fridge |

---

## Updating the App

To pull the latest code without losing your inventory data:

```bash
bash /media/pi/FREEZERBOT/scripts/update.sh
```

This syncs only `app/` and `scripts/` — `config/`, `data/`, `logs/`, and `wake_words/` are never touched.

---

## Files on USB Stick

```
FREEZERBOT/
├── app/              ← Application code (synced from GitHub)
├── config/
│   ├── config.json   ← Settings + API keys (after setup)
│   └── .install_passphrase  ← Decryption key (keep secret)
├── data/
│   └── inventory.db  ← Your inventory (SQLite)
├── logs/             ← App and install logs
├── wake_words/       ← Porcupine .ppn files
├── keys.enc          ← Encrypted API keys (from GitHub)
├── bootstrap.sh      ← Entry point (run by systemd on USB mount)
└── scripts/          ← All deployment scripts
```

---

## Troubleshooting

| Problem | Check |
|---------|-------|
| App doesn't start | `journalctl -u freezerbot.service -n 50` |
| No wake word response | `logs/freezerbot.log` — check Porcupine key and .ppn file |
| Speech not recognised | `logs/freezerbot.log` — Groq API errors |
| Wrong items added | Gemini confidence in logs; try speaking more clearly |
| Screen stays black | Check display_rotate in `/boot/firmware/config.txt` |
| Bootstrap loops | `logs/bootstrap.log` — usually a WiFi or GitHub issue |

---

## Project Structure

```
app/
├── main.py               Entry point
├── core/
│   ├── app_controller.py Central orchestrator
│   ├── config_manager.py Typed config read/write
│   ├── path_resolver.py  USB stick path detection
│   ├── state_machine.py  SLEEP/LISTENING/CONFIRMING/INVENTORY/SETUP
│   └── theme.py          UI constants (colours, sizes)
├── ui/                   PyQt6 screens
├── audio/                Wake word, recorder, STT, TTS
├── database/             SQLite CRUD + fuzzy search
├── intent/               Gemini NLU + location resolver
└── services/             Logger, connectivity checker
```
