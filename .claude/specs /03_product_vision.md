# Gary — Product Vision & Architecture Spec

> Brainstormed: 2026-06-30. Status: research / pre-implementation.
> This document covers features, hardware paths, cloud architecture, and phone app design.

---

## 1. Feature Roadmap

### Priority order (by impact)

| # | Feature | Effort | Why |
|---|---------|--------|-----|
| 1 | Persistent memory across sessions | Low | Makes Gary feel personal, not amnesiac |
| 2 | Meeting mode | Medium | Highest exhibition wow factor |
| 3 | Mac .app bundle | Medium | Required for exhibition credibility |
| 4 | Streaming TTS latency fix | Low | Makes everything feel faster |
| 5 | Menu bar icon (replaces spacebar hold) | Low | Standard Mac idiom |
| 6 | Proactive surface (calendar/notifications) | Medium | "Ambient presence" fully realized |
| 7 | Drag-to-ask (select text → Gary explains) | Medium | Laptop magic, no glasses required |
| 8 | Glasses camera → Gemini Vision | Low | Already have ESP32 stream |

### Feature details

**Persistent memory:** SQLite/JSON store of facts Gary learns ("I'm working on React", "standup at 10am"). Pairs with existing `tools/memory.py`. Survives session restarts.

**Meeting mode:** Auto-detect Zoom/Meet/Teams as active window → transcribe call → running summary in overlay → action items at hangup.

**Proactive surface:** Gary notices things without being asked. Upcoming meeting in 5 min → `show_toast`. Long Slack silence → nudge. Failing CI badge in browser → alert. Publishes `show_toast` events on a poll loop.

**Drag-to-ask:** User selects text anywhere on screen → Gary explains/translates. Implemented via macOS Accessibility API + global hotkey. No glasses required.

**Streaming TTS:** ElevenLabs and Cartesia both support chunk-streaming. LiveKit's `AgentSession` handles this. Biggest single latency win — reduces perceived response time significantly.

---

## 2. Mac App (.app Bundle)

**Approach:** PyInstaller (`--windowed --onefile`). Bundles Python + `.venv` + pywebview.

**Gotchas:**
- pywebview + LiveKit agents have complex native deps — expect iteration
- Redis must be bundled or assumed installed (Homebrew). For standalone: embed Valkey binary or move to asyncio queues
- Menu bar icon via `rumps` library — cleaner trigger than spacebar hold

**Finish line for exhibition:** signed `.app` + LaunchAgent plist (auto-start on boot). No notarization required for demo.

---

## 3. Latency Optimizations

Current pipeline: `mic → Deepgram → Gemini → ElevenLabs → speaker` (~1.5–3s)

| Lever | Impact |
|-------|--------|
| Enable streaming TTS (Cartesia/ElevenLabs chunk mode) | Largest — Gary starts speaking before full response generated |
| Switch to `gemini-2.0-flash` for tool-heavy calls | Faster for simple actions, same quality |
| Silero VAD for end-of-speech detection | Eliminates silence timeout waiting |
| Cache common TTS phrases ("Got it", "On it", "Sure") | Small, zero-effort win |

---

## 4. Cloud vs. Fine-Tuning Decision

**Don't fine-tune yet.** Reasons:
- System prompt handles personality and tool routing well
- Gemini 2.5 Flash is capable enough for current use
- No curated training data exists yet
- Wrong tool calls → fix the prompt first

**What to do instead:**
- RAG over user context (calendar, notes, preferences) injected per turn
- Audit tool call miss rate → prompt fixes before model changes

Fine-tuning revisit: when shipping to users at scale and needing consistent brand voice or specialized domain knowledge.

---

## 5. Hardware Paths

### Path 1 — XIAO + 3D printed mount (Exhibition / Now)

Don't design a custom PCB before July. Get to exhibition with what you have.

| Part | Cost |
|------|------|
| XIAO ESP32-S3 Sense ×2 | $30 |
| Cheap glasses frame | $8–15 |
| 3D printed temple mount | $5–15 |
| 150mAh LiPo + TP4056 breakout + switch | $8–12 |
| **Total** | **~$50–70** |

Timeline: 1–2 weeks.

### Path 2 — Custom ESP32-S3 PCB (Post-exhibition, v1 product)

Small 2-layer board (~50×20mm) integrating everything the XIAO does in a glasses-native form factor.

**Electronics BOM per unit:**

| Component | Part | Cost |
|-----------|------|------|
| MCU | ESP32-S3-WROOM-1 module | $3.50 |
| Camera | OV5640 wide-angle + FPC socket | $6–8 |
| Audio out | Bone conduction piezo transducer | $8–12 |
| Amp | MAX98357A I2S amp | $1.50 |
| Mics | ICS-43434 PDM MEMS ×2 | $2.00 |
| Battery charger | BQ24079 (safer than TP4056 for wearables) | $1.50 |
| Batteries | LiPo 150mAh slim ×2 | $8–12 |
| Touch | AT42QT1010 capacitive IC | $0.80 |
| IMU | MPU-6050 (head gestures, v1.1) | $0.80 |
| USB-C | Charging + UART flash | $0.30 |
| Privacy LED | RGB | $0.30 |
| FPC cables + passives | — | $4–6 |
| **Total BOM** | | **$36–58/unit** |

**PCB (JLCPCB, 10 units — 2 boards per glasses):**

| | Cost |
|-|------|
| PCB design (KiCad, your time ~30–50hrs or freelancer) | $0 or $800–2,000 |
| PCB fab + PCBA | $400–700 |
| Per-unit PCB cost | $40–70 |

**Frame options:**

| Option | Cost/unit | Quality |
|--------|-----------|---------|
| Off-shelf frame + 3D printed inserts | $20–40 | Exhibition-grade |
| SLA 3D printed custom frame | $40–80 | Good demo quality |
| Wenzhou OEM injection molded (MOQ 100–500) | $12–25 + $5K–15K tooling | Product quality |

**Total per unit (10-unit batch):** $96–208  
**Timeline:** 6–10 weeks PCB → assembled in hand

### Path 3 — Rigid-flex glasses PCB (v2 product, 6+ months)

Skip for now. Requires $500–1,200 first run, specialized KiCad rules, and knowing final frame dimensions. Only relevant when pitching investors or going to manufacturing.

### Camera recommendation

**OV5640 with wide-angle (120°) M12 lens.** 5MP, autofocus, ~8mm sensor module. Proven with ESP32. $6–8. Don't chase higher resolution — WiFi bandwidth is the bottleneck, not the sensor.

### Hardware skip list for MVP

| Feature | Verdict |
|---------|---------|
| Bone conduction audio | Use for v1 (simpler than open-ear) |
| Open-ear speakers (Meta-style) | Skip — needs tuned acoustic chambers |
| GPS / compass | Skip |
| On-device AI inference | Skip — stream to phone/cloud |
| Rigid-flex PCB | Skip — 3D printed mount achieves same result |

---

## 6. Full Cloud Architecture

### Why full cloud

Eliminates Raspberry Pi + Hailo HAT (~$250/deployment). No customer-side infrastructure. Scales to many users. Models improve without hardware updates. Enables subscription revenue.

### Architecture

```
[Glasses — ESP32-S3]
  Camera → MJPEG over WiFi (local network to phone)
  Mic → audio over WiFi/BLE
  Bone conduction ← audio from phone (BLE)
  Touch strip → BLE events

[Phone — iOS companion app]
  ├─ MediaPipe Hands: gesture detection @ 30fps (LOCAL, ~15ms)
  ├─ YOLOv8n CoreML: object detection (LOCAL, ~20ms)
  ├─ ArUco OpenCV: device markers (LOCAL, ~8ms)
  ├─ SmartHomeManager: HA + HomeKit + Hue (LOCAL network)
  ├─ ContextProvider: calendar, location, contacts (LOCAL)
  ├─ VoiceSession: LiveKit audio pipeline (CLOUD)
  └─ GaryClient: WebSocket events (CLOUD)

[Cloud — Gary backend]
  ├─ Gary agent (Gemini 2.5 Flash, tools, memory)
  ├─ LiveKit (voice session routing)
  ├─ Deepgram (STT)
  ├─ Cartesia (TTS — not ElevenLabs, see cost below)
  ├─ Gemini Vision (on-demand frames only, never continuous)
  ├─ Postgres (user memory, preferences)
  └─ Stripe (subscription billing)
```

### What the phone processes locally (zero cloud cost)

- Gesture detection (MediaPipe): every frame, local, free
- Object detection (YOLO CoreML): every frame, local, free
- ArUco markers (OpenCV): every frame, local, free
- Smart home commands: local network, free
- Context (calendar/location): local device, free

### What goes to cloud

- Audio (voice sessions): LiveKit → Deepgram → Gemini → Cartesia
- LLM reasoning: Gemini 2.5 Flash per turn
- Scene description: single JPEG frame on demand (not continuous video)
- Event stream: tiny JSON gestures/object events up, commands down

### Monthly cost per user

| Service | Cost/user/month |
|---------|----------------|
| LiveKit Cloud | ~$1.50 |
| Deepgram STT (30 min/day) | ~$3.90 |
| Cartesia TTS (2,000 chars/day) | ~$3.90 |
| Gemini Vision (5–10 calls/day) | ~$0.30 |
| Gemini LLM | ~$1–3 |
| Backend server (shared) | ~$1–5 |
| **Total** | **~$12–18/user/month** |

Note: ElevenLabs would be ~$18/user/month for TTS alone. Cartesia (already in stack) costs 78% less. Use Cartesia.

**Suggested subscription price:** $24–29/month. ~40–60% gross margin at scale.

### Hardware cost comparison

| | With Pi path | Full cloud |
|-|-------------|-----------|
| Glasses electronics | $36–58 | $36–58 |
| PCB + frame | $60–150 | $60–150 |
| Pi + Hailo HAT | $250 | **$0** |
| **Total per unit** | $346–458 | **$96–208** |

### Model conversion (one-time setup)

```bash
# YOLOv8n → CoreML (iOS)
yolo export model=yolov8n.pt format=coreml

# YOLOv8n → TFLite (Android, future)
yolo export model=yolov8n.pt format=tflite
```

MediaPipe Tasks Swift bundles its own models — no conversion needed.

---

## 7. Home Assistant in Cloud Architecture

### The problem

Gary cloud agent can't reach a user's local HA at `192.168.1.6`. It's behind NAT.

### Solution: phone as HA relay (recommended for launch)

```
Gary cloud agent → "turn on kitchen lights" → WebSocket → Phone
Phone (on home WiFi) → http://192.168.1.6:8123 → HA
```

- When phone is on home WiFi: call HA local URL directly (fast, no external access)
- When phone is away: call via Nabu Casa URL or fail gracefully ("you're not home")
- "Am I home?" detection: CoreLocation geofence set during onboarding

### Future: Nabu Casa support

User subscribes to HA Cloud (~$6.50/month). Provides public HTTPS URL. Gary cloud calls it directly. Enables remote control when away from home.

### Users without Home Assistant

Phone hub opens direct smart home control via:

| Platform | API | What you get |
|----------|-----|--------------|
| Apple HomeKit | HomeKit framework (iOS) | Lights, locks, thermostat |
| Matter | MatterSupport (iOS 16+) | Cross-platform devices |
| Philips Hue | Hue local API | Lights without HA |

### Security

HA long-lived token stored in iOS Keychain only. Never sent to Gary cloud backend. Phone makes the HA call locally, sends only the result up.

---

## 8. Phone App Architecture

### Tech stack

| Layer | Framework |
|-------|-----------|
| UI | SwiftUI + @Observable |
| BLE | CoreBluetooth |
| WiFi / WebSocket | Network framework (URLSessionWebSocketTask) |
| Camera stream | AVFoundation + custom MJPEG parser |
| MediaPipe | MediaPipe Tasks Swift (official SDK) |
| YOLO | CoreML + Vision framework |
| ArUco | OpenCV (C++ → Swift via ObjC wrapper) |
| Voice | LiveKit iOS SDK |
| HomeKit | HomeKit framework |
| Calendar | EventKit |
| Location | CoreLocation (CLCircularRegion geofence) |
| Contacts | Contacts framework |
| Subscriptions | StoreKit 2 |
| Secrets | Keychain |
| Dynamic Island | ActivityKit (Live Activities) |

### Modules

#### GlassesManager
Owns physical connection to ESP32. Two channels:
- **BLE**: touch events, battery level, LED commands, bone conduction audio. Works in background.
- **WiFi MJPEG**: camera stream. Foregrounded only.

State machine: `Disconnected → Scanning → BLE Connected → Streaming` with auto-reconnect.

#### VisionEngine
Runs ML inference on every MJPEG frame. All local.

| Model | Latency | Output |
|-------|---------|--------|
| MediaPipe Hands | ~15ms | 21 landmarks per hand |
| YOLOv8n CoreML | ~20ms | Bounding boxes + class labels |
| ArUco OpenCV | ~8ms | Marker ID + pose |

Runs on background `DispatchQueue`. Never blocks main thread.

#### GestureRecognizer
Converts raw landmark data into Gary commands. Stateful — tracks gesture history across frames. Debounce prevents multi-fire from one gesture.

```
Gestures:
- Pinch: thumb tip + index tip distance < threshold, 3 consecutive frames
- Swipe: wrist velocity > threshold in one direction
- Hold pinch: pinch maintained > 500ms
- Head nod / shake: via IMU (v1.1)
```

#### VoiceSession
Wraps LiveKit. Manages full voice pipeline.

```
Pinch → activate() → LiveKit room opens → mic captures
→ Deepgram STT → Gemini LLM → Cartesia TTS
→ audio received → routed to bone conduction via BLE
→ silence → deactivate()
```

#### GaryClient
WebSocket connection to Gary cloud backend.

**Phone → Cloud (events):**
- `gestureDetected` (tiny, frequent)
- `objectsInView` (YOLO results)
- `deviceSeen` (ArUco marker ID)
- `contextUpdate` (calendar/location snapshot)
- `frameForVision` (single JPEG, on-demand only)

**Cloud → Phone (commands):**
- `homeAssistantCall` (service, entityID, data)
- `requestFrame` (Gary wants to see camera)
- `showOverlay` (text to display)
- `playAudio` (TTS URL)

#### SmartHomeManager
Routes home commands to the right backend.

```
execute(command)
  → Is it a HomeKit entity? → HomeKit framework
  → Is it a HA entity? → HA (local if home, Nabu Casa if away)
  → Is it a Hue light? → Hue bridge (local API)
```

#### ContextProvider
Proactively injects user context into every Gary cloud call.

```swift
struct UserContext {
    var upcomingEvents: [CalendarEvent]   // next 3 from EventKit
    var location: String                  // "home" / "office" / "coffee shop"
    var timeOfDay: String
    var devicesSeen: [Int]               // ArUco marker IDs in view
}
```

Sent with every LLM call. Gary always knows "user is at home, meeting in 8 minutes, laptop in view."

#### AppState
Single source of truth. All SwiftUI views observe this only. Managers don't talk to each other directly.

### Background execution

Declared background modes in `Info.plist`:
- `bluetooth-central` — BLE to glasses always works
- `audio` — voice session survives background
- `location` — geofencing for home detection

**What works in background vs foreground:**

| Feature | Background | Foreground |
|---------|-----------|------------|
| BLE touch events | Yes | Yes |
| MJPEG + vision | No (throttled) | Yes |
| Voice session | Yes | Yes |
| Smart home | Yes (via BLE trigger) | Yes |
| Geofencing | Yes | Yes |

Practical result: touch strip is the primary activation in background. Vision-based gestures are the enhancement when app is foregrounded.

### iOS surfaces

| Surface | Gary usage |
|---------|-----------|
| Dynamic Island | Listening / thinking / speaking state arc |
| Live Activities | Lock screen status during voice session |
| Widgets | Quick status, last Gary response |
| Siri Shortcuts | "Hey Siri, ask Gary..." fallback |

### UI philosophy

Minimal. Gary is a presence, not an app.

```
Main screen:
  - Small status dot + state label ("Listening...", "Idle")
  - Glasses battery / signal indicators
  - No buttons — interaction via glasses touch strip or gesture
```

### Build order (12 weeks)

| Weeks | Milestone |
|-------|-----------|
| 1–2 | GlassesManager: BLE + MJPEG → video shows on phone |
| 3–4 | VisionEngine + GestureRecognizer → pinch fires event |
| 5–6 | VoiceSession (LiveKit) → pinch → Gary speaks back |
| 7–8 | GaryClient (WebSocket) + cloud backend → tools work |
| 9–10 | SmartHomeManager + ContextProvider → Gary knows calendar, controls home |
| 11–12 | Dynamic Island, onboarding, StoreKit 2, polish |

Gary is functional by week 6. Everything after is depth.

---

## 9. Recommended Sequencing (Overall)

```
Now → July exhibition
  Hardware: XIAO + 3D printed mount (~$70)
  Software: existing Mac app + voice agent
  Goal: working demo, not a product

Post-exhibition (Month 1–2)
  Custom PCB v1 design (KiCad)
  iOS companion app (Swift) — starts here
  Cloud backend deployment
  Cost: ~$1,500–2,500 for 5 working units + app skeleton

Month 3–6
  iOS app functional (voice + gestures + smart home)
  Subscription billing (Stripe + StoreKit 2)
  Persistent memory
  Off-shelf glasses frame with custom PCB

Month 6–12
  Wenzhou OEM frame engagement
  PCB v2 (refined, lighter, with IMU)
  Android companion app
  50–100 unit small batch
  Budget: $8,000–15,000 (hardware) + ongoing API costs
```

---

## Open Questions

- [ ] Android or iOS first for companion app?
- [ ] Subscription price: $19, $24, or $29/month?
- [ ] Bone conduction vs open-ear for v1 PCB?
- [ ] Which Wenzhou frame supplier to engage with?
- [ ] Build iOS app in-house or contract a Swift dev?
- [ ] What happens to the Mac overlay app post-phone-app? (Kept as desktop companion?)
