# Freezerbot — Session Memory

Last updated: 2026-04-12

---

## What This Is

Freezerbot is a voice-controlled freezer inventory system running on:
- **Hardware**: Raspberry Pi 4, 10.1" 1024×600 landscape touchscreen, USB microphone, HDMI audio output to TV/monitor
- **OS**: Raspberry Pi OS Lite (Bookworm), X11 kiosk via startx
- **Stack**: PyQt6, Python 3.13.5, openWakeWord, Groq Whisper (STT), Groq llama-3.3-70b-versatile (intent), gTTS (TTS), PulseAudio

---

## Architecture

```
AppController (orchestrator)
├── WakeWordDetector (QThread, always-on, openWakeWord "hey_jarvis")
├── Recorder (QThread, one-shot per utterance, VAD silence detection)
├── STTThread (QThread, Groq Whisper)
├── IntentParserThread (QThread, Groq llama-3.3-70b-versatile)
├── TTSEngine (QThread, gTTS → pygame → PulseAudio HDMI)
├── DatabaseManager (SQLite)
├── FuzzySearch (similarity matching for REMOVE)
└── StateMachine (SETUP → SLEEP ↔ LISTENING → CONFIRMING → SLEEP)
                                    ↓
                                INVENTORY → SLEEP
```

**States**:
- `SLEEP` — idle; shows inventory screen (default)
- `LISTENING` — wake word fired; recording; snowflake visible bottom-left
- `CONFIRMING` — ADD/REMOVE pending user yes/no; confirmation screen with countdown
- `INVENTORY` — list/query result shown (also maps to inventory screen)

---

## Key Design Decisions

### Inventory as Default Screen
`SLEEP` and `LISTENING` both map to the inventory screen (`_IDX_INVENTORY`) in MainWindow.
There is no separate "sleep" screen in normal operation. The inventory auto-refreshes whenever
state transitions to `SLEEP`. The `SleepScreen` and `ListeningScreen` widgets are kept in
the codebase but are not shown.

### Snowflake Indicator
- Widget: `app/ui/widgets/snowflake_widget.py` — 6-arm snowflake, 48×48 canvas
- Color pulses blue (#1565C0) → white → blue via sine wave at ~33fps
- Positioned bottom-left (8px margin) on both `InventoryScreen` and `ConfirmationScreen`
- Floats over content using `raise_()` and `WA_TranslucentBackground`
- Inventory snowflake: shown during `LISTENING` state (main_window controls)
- Confirmation snowflake: shown when the CONFIRMING recorder is actually open
- Both screens have `show_snowflake(status)` / `hide_snowflake()` / `resizeEvent` for dynamic positioning

### Intent Engine: Groq (not Gemini)
Gemini was replaced with Groq `llama-3.3-70b-versatile` for intent parsing because:
- Gemini free-tier quota exhausted (429 errors)
- Groq is faster and free-tier is more generous
- Same JSON response format, temperature=0.1, max_tokens=256
- `app/intent/intent_parser.py` contains the system prompt and parser

### Wake Word: openWakeWord (not Picovoice/Porcupine)
Replaced because Picovoice requires a console account (Gmail not accepted).
openWakeWord is open-source, no API key, models auto-download from HuggingFace.
Model in use: `hey_jarvis`. Config key: `wake_word_model`.

### Audio Device: PulseAudio "default" (not direct hw:)
- USB mic device index must NOT be set to direct `hw:` paths — PulseAudio owns them
- `config.json` has `audio.input_device_index: null` to use PulseAudio default
- Both `WakeWordDetector` and `Recorder` fall back to system default if configured index has no input channels
- HDMI audio is the output: `alsa_output.platform-fef00700.hdmi.hdmi-stereo`
- Made permanent via `~/.config/pulse/default.pa` on the Pi

---

## Echo & Re-listen Logic (critical, hard-won)

### The Problem
TTS plays through HDMI → TV speakers → USB mic picks up the echo.
`speaking_finished` fires when pygame's internal buffer empties, but PulseAudio still has
~300–500ms buffered, so the *actual* audio finishes 300–500ms after the signal.

### Solutions Applied

**1. Post-TTS grace period** (`app_controller.py: on_wake_word_detected`)
```python
elapsed = time.monotonic() - self._tts_finished_at
if elapsed < 2.0:
    return  # discard — stale detection
```
`_tts_finished_at` is set at the start of `_on_tts_finished`.

**2. Stale buffer drain in WakeWordDetector** (`wake_word_detector.py`)
After resuming from pause, reads and discards ~2 seconds of accumulated PulseAudio
buffer frames before evaluating predictions. Then calls `oww.reset()` to clear model state.
```python
drain_chunks = int(2.0 * native_rate / native_frames)
for _ in range(drain_chunks):
    stream.read(native_frames, exception_on_overflow=False)
oww.reset()
```

**3. Short-transcript filter** (`app_controller.py: on_transcript_ready`)
Transcripts with < 3 words are treated as TTS echo and re-listen starts after 1200ms.
After 2 consecutive short transcripts: give up, return to SLEEP.
Exception: CONFIRMING state is excluded (legitimate 1-word answers: "yes", "no").

**4. UNKNOWN → SLEEP (not re-listen)**
Unknown intents send the app to SLEEP, not back to LISTENING.
This breaks the "Sorry, I didn't understand" infinite loop.

**5. CONFIRMING: 3-second delay with countdown**
The confirmation recorder opens 3 seconds after TTS finishes to ensure echo clears.
A countdown is shown in the confirmation screen hint: "Mic opens in 3s… 2s… 1s… Say YES or NO now".
The snowflake appears on the confirmation screen when the recorder is actually open.

**6. Detector pause: stream stays open**
WakeWordDetector does NOT close the PyAudio stream on pause (PulseAudio supports
multiple simultaneous clients). It just blocks on `_resume_event.wait()`. This avoids
`-9985 Device unavailable` errors.

---

## Audio Pipeline State Machine

```
Wake word detected
  → _recording_active = True
  → blockSignals(True) on detector
  → detector.pause()
  → Recorder starts

Recording complete
  → STT (Groq Whisper)
  → Intent (Groq llama-3.3-70b)

Intent = ADD/REMOVE (needs confirm)
  → TTS speaks "Adding X to Y. Is that correct?"
  → State = CONFIRMING
  → TTS finishes → _tts_finished_at set → 3s countdown → Recorder opens
  → User says "yes/no" (or taps button)
  → _on_confirmed/_on_denied → State = SLEEP
  → _on_tts_finished (SLEEP) → 500ms → _resume_detector
  → detector.resume() → drain buffer → oww.reset()

Intent = LIST/QUERY/UNKNOWN
  → TTS speaks response
  → State = SLEEP (or INVENTORY for LIST/QUERY)
  → _on_tts_finished → 500ms → _resume_detector
  → detector.resume() → drain buffer → oww.reset()
```

---

## File Map (key files only)

| File | Purpose |
|------|---------|
| `app/core/app_controller.py` | Central orchestrator, all state logic, echo mitigations |
| `app/core/state_machine.py` | State enum + legal transitions |
| `app/core/config_manager.py` | Config load/save, `wake_word_model` field |
| `app/audio/wake_word_detector.py` | openWakeWord, buffer drain on resume |
| `app/audio/recorder.py` | VAD-based utterance capture |
| `app/audio/tts_engine.py` | gTTS + pygame; `speaking_finished` fires on pygame buffer empty |
| `app/intent/intent_parser.py` | Groq LLM intent parsing, JSON→ParsedIntent |
| `app/ui/main_window.py` | QStackedWidget; SLEEP/LISTENING/INVENTORY → inventory screen |
| `app/ui/inventory_screen.py` | Default/idle screen; hosts snowflake overlay |
| `app/ui/confirmation_screen.py` | ADD/REMOVE confirm; hosts snowflake + countdown hint |
| `app/ui/widgets/snowflake_widget.py` | Animated snowflake indicator |
| `config/config.json` | Runtime config; `audio.input_device_index: null` |

---

## Pi SSH & Deployment

```bash
# SSH access (key auth)
ssh pi@192.168.0.155

# App location on Pi
/media/pi/FREEZERBOT/

# Run app
cd /media/pi/FREEZERBOT && DISPLAY=:0 nohup python3 app/main.py > /tmp/freezerbot.log 2>&1 &

# Watch logs (filter ALSA noise)
ssh pi@192.168.0.155 "cat /tmp/freezerbot.log | grep -v ALSA | grep -v Jack | grep -v Cannot | grep -v JackShm | grep -v onnx | grep -v UserWarning | grep -v warnings"

# Kill app
ssh pi@192.168.0.155 "pkill -9 -f 'python3.*main'"

# Deploy single file
rsync -av <local_file> pi@192.168.0.155:/media/pi/FREEZERBOT/<path>
```

**PulseAudio HDMI fix** (persistent across reboots):
```
~/.config/pulse/default.pa on Pi:
  .include /etc/pulse/default.pa
  set-default-sink alsa_output.platform-fef00700.hdmi.hdmi-stereo
```

---

## Known Issues / Remaining Work

- **Physical room echo**: if TV volume is high and room is reflective, the mic still
  captures TTS audio even after the drain. Mitigated but not eliminated. Consider
  reducing TV volume or adding acoustic treatment near the mic.
- **8-second max recordings**: if `silence_threshold_rms` (500 RMS) is below the ambient
  noise floor, silence detection never triggers and recordings hit max length. May need
  tuning per environment.
- **Two recorders on burst detection**: `blockSignals` doesn't block already-queued signals.
  A second recorder can start; mitigated by `sender()` check in `_on_recording_complete`
  which drops results from stale recorders.
- **CONFIRMING voice timeout**: user must wait 3 seconds after TTS before speaking yes/no.
  Countdown shown on screen to guide timing.
