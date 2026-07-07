# Pinch — Product Repo (`gary-product`)

> Built by: Pratham Yaligar
> Status: Active development. Exhibition phase is over. Building the real product.
> Platform decision: Android first (developer has Android phone + Mac mini for testing)

---

## What We're Building

**Pinch** is a pair of AI-powered smart glasses — the hardware. **Gary** is the ambient AI assistant that runs on them. Together they are a single product: always-on intelligence that lives on your face, not your phone.

The closest reference point is Meta Ray-Ban glasses, but with a different architecture:
- No on-device compute — ESP32-S3 is the only chip on the glasses
- Phone (Android) is the processing hub for vision and context
- Cloud handles all AI reasoning (Gemini 2.5 Flash), voice (Deepgram + Cartesia), memory (Postgres)
- No Raspberry Pi. No customer-side infrastructure. Full cloud.

**Tagline:** *Your world, hands-free.*
**Design philosophy:** A presence, not an app. Minimal, ambient, invisible until needed.

---

## Repo Structure

```
gary-product/
├── android/          ← Kotlin + Jetpack Compose companion app  (M2)
├── cloud/            ← FastAPI backend, Gary agent, voice pipeline  (M3)
├── hardware/         ← KiCad PCB files, 3D models, ESP32 firmware  (M4)
├── docs/             ← specs, architecture diagrams, BOM
└── CLAUDE.md         ← this file
```

**Gary_2** (the original Mac laptop overlay app) lives in a separate repo and is NOT touched here. It served the exhibition. This repo is the product.

---

## System Architecture — Three Layers

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1 — GLASSES (ESP32-S3)                                   │
│                                                                 │
│  OV5640 camera → MJPEG stream over WiFi → Phone                │
│  ICS-43434 mics ×2 → audio over BLE → Phone                   │
│  BGT60TR13C 60GHz radar → SPI → ESP32 → BLE gesture events    │
│  AT42QT1010 touch strip → BLE tap events → Phone              │
│  MAX98357A amp + bone conduction ← audio via BLE ← Phone      │
│  BQ24079 charger, LiPo ×2, USB-C, privacy LED                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │ BLE (always-on) + WiFi (MJPEG)
┌──────────────────────────▼──────────────────────────────────────┐
│  LAYER 2 — PHONE (Android companion app)                        │
│                                                                 │
│  GlassesManager    BLE + MJPEG, auto-reconnect, LED control    │
│  VisionEngine      MediaPipe Hands + YOLOv8n TFLite + ArUco   │
│  GestureRecognizer Radar BLE events → Gary commands            │
│  VoiceSession      LiveKit room, mic, bone conduction output   │
│  GaryClient        WebSocket to cloud event bus                │
│  SmartHomeManager  HA local relay → Nabu Casa when away        │
│  ContextProvider   Calendar + Location + Contacts              │
│                                                                 │
│  All vision runs LOCAL (zero cloud cost per frame)             │
└──────────────────────────┬──────────────────────────────────────┘
                           │ WebSocket + LiveKit (cloud only)
┌──────────────────────────▼──────────────────────────────────────┐
│  LAYER 3 — CLOUD (Gary backend)                                 │
│                                                                 │
│  Gary agent        Gemini 2.5 Flash + tools + memory           │
│  Voice pipeline    LiveKit → Deepgram STT → Cartesia TTS       │
│  Vision (on-demand) Gemini Vision, single frames only          │
│  WebSocket server  Event bus (phone ↔ cloud)                   │
│  Postgres          User memory, conversation summaries         │
│  Stripe            Subscription billing                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Layer 1 — Hardware (ESP32-S3 Glasses)

### Design target
Looks like Meta Ray-Ban. Feels like glasses, not a gadget. Target weight: 55–70g.

### Electronics BOM per unit

| Component | Part | Cost |
|-----------|------|------|
| MCU | ESP32-S3-WROOM-1 | $3.50 |
| Camera | OV5640 + wide-angle M12 lens (120°) | $6–8 |
| Gesture radar | Infineon BGT60TR13C (60GHz Soli-style) | $5–8 |
| Audio amp | MAX98357A I2S | $1.50 |
| Bone conduction | Piezo transducer | $8–12 |
| Mics | ICS-43434 PDM MEMS ×2 | $2.00 |
| Battery charger | BQ24079 (wearable-safe) | $1.50 |
| Batteries | LiPo 150mAh slim ×2 | $8–12 |
| Touch strip | AT42QT1010 capacitive IC | $0.80 |
| IMU | MPU-6050 (head gestures, v1.1) | $0.80 |
| USB-C | Charging + UART flash | $0.30 |
| Privacy LED | RGB | $0.30 |
| FPC ribbon + passives | — | $4–6 |
| **Total BOM** | | **$42–66/unit** |

### PCB design
- 2 boards per pair: right temple (MCU + camera + radar + touch + charger) and left temple (mics + amp + bone conduction + battery)
- FPC ribbon connector between temples
- Tool: KiCad
- Fab: JLCPCB (PCB + PCBA, 10-unit batch)
- PCB + assembly cost: $40–70/unit

### Radar — Project Soli style (Infineon BGT60TR13C)
Replaces a second camera entirely. Radar → SPI → ESP32 → BLE gesture event → phone.

Gesture set (90%+ accuracy):
- **Pinch** → Wake / confirm
- **Double pinch** → Mode switch
- **Hold pinch (>500ms)** → Push to talk
- **Swipe right** → Next / skip / dismiss
- **Swipe left** → Back
- **Swipe up** → Volume / brightness up
- **Swipe down** → Volume / brightness down
- **Air tap** → Single select
- **Grab (closed fist)** → Stop / cancel
- **Thumb-slide on index (rub)** → Brightness slider (~80–85% accuracy)

Radar vs camera tradeoffs:
- Works in dark, through fabrics, 5ms latency vs 20–30ms
- No absolute position (only increment/decrement)
- Accuracy drops to ~70–75% while walking (body motion noise)
- Fix intent detection: require pinch-first to enter gesture mode

### Camera
OV5640 with 120° wide-angle M12 lens. MJPEG stream over WiFi to phone. WiFi bandwidth is the bottleneck, not the sensor. No second camera — radar handles gestures.

### Frame progression
- v0 (now): Off-shelf glasses + 3D printed temple mount + XIAO ESP32-S3 Sense ($50–70)
- v1 (Month 2–4): Custom PCB + off-shelf or SLA 3D printed frame ($102–216/unit)
- v2 (Month 6–12): Refined PCB + Wenzhou OEM injection-molded frame (MOQ 100–500, $12–25/unit + $5K–15K tooling)

---

## Layer 2 — Android Companion App

### Why Android
Developer has an Android phone and a Mac mini. Android first, iOS later.

### Tech stack

| Layer | Framework |
|-------|-----------|
| UI | Kotlin + Jetpack Compose |
| BLE | Android BLE (BluetoothLeScanner) + Foreground Service |
| Camera stream | OkHttp WebSocket + custom MJPEG decoder |
| Gesture ML | MediaPipe Tasks Android |
| Object detection | YOLOv8n TFLite |
| ArUco | OpenCV Android SDK |
| Voice | LiveKit Android SDK |
| Smart home | OkHttp HTTP (HA local API) |
| Calendar | Android Calendar Provider |
| Location | Android Geofencing API |
| Contacts | Android Contacts ContentProvider |
| Secrets | Android Keystore |
| Subscriptions | Google Play Billing Library |
| Background | Foreground Service (`connectedDevice|microphone`) |
| Min SDK | API 26 (Android 8) |

### Kotlin / Jetpack Compose primer (developer is new to Kotlin)
- `@Composable` functions = UI components (like React components)
- `mutableStateOf` = reactive state (like `useState`)
- `Modifier` = styling/layout (like CSS)
- `Column` / `Row` / `Box` = flexbox equivalents
- Coroutines = Python asyncio — `launch {}` for fire-and-forget, `async/await` for results
- `ViewModel` = state holder that survives screen rotation
- `StateFlow` = observable stream (like RxJS Observable but simpler)

### Module breakdown

#### GlassesManager
Owns physical connection to ESP32.
- BLE: touch events, battery, LED commands, bone conduction audio — works in background via Foreground Service
- WiFi MJPEG: camera stream — foregrounded only
- State machine: `Disconnected → Scanning → BLE_Connected → Streaming` with auto-reconnect and exponential backoff

#### VisionEngine
Runs ML inference on every MJPEG frame on a background coroutine. All local — zero cloud cost per frame.

| Model | Framework | Latency | Output |
|-------|-----------|---------|--------|
| MediaPipe Hands | MediaPipe Tasks Android | ~15ms | 21 landmarks per hand |
| YOLOv8n | TFLite | ~20ms | Bounding boxes + class labels |
| ArUco | OpenCV Android | ~8ms | Marker ID + pose |

Never write frames to disk. 3–5 frame ring buffer in RAM (~250KB max).

#### GestureRecognizer
Converts radar BLE events (primary) or MediaPipe landmarks (fallback) into Gary commands. Stateful — tracks gesture history across events. Debounce prevents multi-fire from one gesture.

#### VoiceSession
Wraps LiveKit. Full voice pipeline:
```
Pinch → activate()
→ LiveKit room opens + mic starts
→ Deepgram STT → Gemini LLM → Cartesia TTS
→ audio chunks received → routed to bone conduction via BLE
→ silence / pinch again → deactivate()
```

#### GaryClient
WebSocket connection to Gary cloud backend. Reconnects with exponential backoff + JWT re-auth.

**Phone → Cloud events (small, frequent):**
- `gestureDetected` — tiny, many per session
- `objectsInView` — YOLO results
- `deviceSeen` — ArUco marker ID
- `contextUpdate` — calendar/location snapshot
- `frameForVision` — single JPEG, on-demand only (NOT continuous)

**Cloud → Phone commands (occasional):**
- `homeAssistantCall` — service, entityID, data
- `requestFrame` — Gary wants to see camera right now
- `showOverlay` — text to display on phone
- `playAudio` — TTS audio

#### SmartHomeManager
Routes home commands to the right backend:
```
execute(command)
  → Is it HA entity? → HA (local API if home, Nabu Casa if away)
  → Is it Hue? → Hue bridge local API
  → Unknown? → error to cloud, Gary speaks "I don't recognize that device"
```
"Am I home?" = Android Geofencing API. Geofence set during onboarding.
HA long-lived token stored in Android Keystore ONLY. Never sent to cloud.

#### ContextProvider
Proactively builds and injects user context into every Gary cloud call:
```kotlin
data class UserContext(
    val upcomingEvents: List<CalendarEvent>,  // next 3, from Calendar Provider
    val location: String,                      // "home" / "office" / "unknown"
    val timeOfDay: String,                     // "morning" / "afternoon" / "evening"
    val devicesSeen: List<Int>                 // ArUco marker IDs in current frame
)
```

### UI (Jetpack Compose)
Minimal. Gary is a presence, not an app.

- **MainScreen** — small status dot + state label ("Listening…", "Idle"), glasses battery, no buttons
- **OnboardingScreen** — glasses pair → smart home setup → permissions
- **SettingsScreen** — HA URL, subscription status, voice settings
- **PermissionsScreen** — BLE, mic, location runtime permission requests
- **Persistent notification** — Foreground Service status (required by Android)

### AndroidManifest permissions
```xml
BLUETOOTH_SCAN, BLUETOOTH_CONNECT, BLUETOOTH_ADVERTISE
RECORD_AUDIO
ACCESS_FINE_LOCATION
INTERNET
FOREGROUND_SERVICE
foregroundServiceType="connectedDevice|microphone"
```

### Build order (12 weeks to functional product)
| Weeks | What ships |
|-------|-----------|
| 1–2 | GlassesManager: BLE scan + connect + MJPEG → video on screen |
| 3–4 | VisionEngine + GestureRecognizer: pinch fires an event |
| 5–6 | VoiceSession (LiveKit): pinch → Gary speaks back |
| 7–8 | GaryClient (WebSocket) + cloud backend: tools work |
| 9–10 | SmartHomeManager + ContextProvider: calendar + home control |
| 11–12 | Onboarding, Play Billing, polish |

Gary is functional and talkable by Week 6. Everything after is depth.

---

## Layer 3 — Cloud Backend

### Stack
- **API**: FastAPI (Python 3.11+)
- **Database**: Postgres (users, memory, conversation summaries)
- **Cache/pubsub**: Redis
- **Voice**: LiveKit Cloud (WebRTC session management)
- **STT**: Deepgram Nova-3 (<300ms latency)
- **LLM**: Gemini 2.5 Flash
- **TTS**: Cartesia Sonic (NOT ElevenLabs — 78% cheaper)
- **Vision**: Gemini Vision API (on-demand only, never continuous)
- **Auth**: JWT + refresh tokens
- **Billing**: Stripe webhooks
- **Deploy**: Railway / Render / Fly.io (TBD at deploy time)
- **Infra**: Docker + docker-compose

### Gary Agent
Port the existing Gary agent logic from Gary_2 (`laptop_app/voice_agent.py`) to a cloud service. The agent already has:
- Gemini 2.5 Flash integration via LiveKit AgentSession
- Tools: control_bulb, control_tv, launch_tv_app, annotate_screen, begin_teaching, next_lesson_block, get_youtube_notes
- GARY_SYSTEM_PROMPT defining personality

New tools needed for cloud version:
- `relay_home_assistant_command` — sends command down WebSocket to phone
- `request_frame_from_glasses` — asks phone for a single camera JPEG
- `lookup_user_memory` — queries Postgres for learned user facts
- `save_user_memory` — stores learned facts in Postgres

### Voice pipeline (cloud)
```
Phone mic PCM → LiveKit room → Deepgram (STT, <300ms)
→ Gary agent (Gemini 2.5 Flash, tool dispatch)
→ Cartesia TTS (streaming chunk mode)
→ LiveKit → Phone → bone conduction speaker
```
Deepgram Streaming API. Cartesia chunk mode (Gary starts speaking before full response is generated). This is the biggest latency win.

### WebSocket event bus
Single WebSocket connection per user session. Protocol:
```json
// Phone → Cloud
{ "type": "gestureDetected", "gesture": "pinch", "ts": 1234567890 }
{ "type": "objectsInView", "objects": ["laptop", "coffee"], "ts": ... }
{ "type": "deviceSeen", "markerId": 3, "ts": ... }
{ "type": "frameForVision", "jpeg_b64": "...", "ts": ... }

// Cloud → Phone
{ "type": "homeAssistantCall", "service": "light.turn_off", "entityId": "light.kitchen" }
{ "type": "requestFrame", "reason": "user asked what they're looking at" }
{ "type": "showOverlay", "text": "That's a Philips Hue bulb, model A19" }
```

### Monthly cost per user
| Service | Cost/user/month |
|---------|----------------|
| LiveKit Cloud | ~$1.50 |
| Deepgram STT (30 min/day) | ~$3.90 |
| Cartesia TTS (2,000 chars/day) | ~$3.90 |
| Gemini Vision (5–10 calls/day) | ~$0.30 |
| Gemini LLM (2.5 Flash) | ~$1–3 |
| Backend server (shared) | ~$1–5 |
| **Total** | **~$12–18/user/month** |

Subscription price: **$24–29/month** (~40–60% gross margin at scale).

### Data stored in Postgres
- User accounts (email, hashed password, JWT tokens)
- Gary memory: learned facts per user (~100KB per user, lifetime)
- Conversation summaries: text only, ~5MB per user per year
- Subscription status (Stripe customer ID, plan, expiry)

### What is NEVER stored
- Raw audio (discard immediately after Deepgram transcription)
- Camera frames / JPEG images (process and discard, never write to DB)
- Full audio recordings
- Continuous vision results at 30fps

---

## Data & Privacy Rules (Non-negotiable)

These are architectural constraints, not guidelines. Every implementation decision must respect them.

### GOLDEN RULE
**Streaming data never touches disk. Only derived text results persist.**

| Data type | Lifecycle | Risk if violated |
|-----------|-----------|-----------------|
| MJPEG frames | Ring buffer (3–5 frames, ~250KB RAM) → VisionEngine → discard | Accidental write() = 1.5MB/sec = 5.4GB/hour |
| Audio PCM | RAM only → LiveKit → discard after send | Debug logger = 10MB/minute |
| Gemini Vision JPEG | Grab → API call → discard. Max ~1 second in memory | Caching on backend = legal liability |
| Gesture/object events | Tiny JSON, no storage needed | Negligible |
| LLM conversation | Text summarized → Postgres | Fine. This is what we keep. |

### Security
- HA long-lived token: Android Keystore only. Never sent to cloud. Phone calls HA locally, sends only result up.
- JWT: stored in Android Keystore. Refresh token rotation on every use.
- Gemini Vision: your backend never persists the image. Only the text description is stored.

### Privacy product angle
"Gary doesn't store your camera feed or audio" — this is a real differentiator vs Alexa / Nest. Build it into the architecture from day one, not as an afterthought.

---

## Home Assistant Integration

### Architecture
Gary cloud agent → sends `homeAssistantCall` command → WebSocket → Phone → HA local HTTP API.

Why phone as relay:
- Gary cloud can't reach `192.168.1.6` — it's behind NAT
- Phone is already on the home WiFi network
- No port forwarding or VPN required

### "Am I home?" detection
Android Geofencing API. User sets home location during onboarding. Phone checks geofence before each HA call:
- On home WiFi: `http://192.168.1.6:8123` (fast, local)
- Away from home: Nabu Casa URL (user subscribes to HA Cloud, ~$6.50/month) or graceful failure

### Users without HA
- Philips Hue: local API on same LAN (auto-discover bridge during onboarding)
- Google Home: (consider for v2, requires Google API access)

---

## Complete Interaction Flow

### Startup (~4–5 seconds)
1. ESP32 boots → BLE advertisement
2. Android Foreground Service (always running) sees advertisement → connects
3. BLE handshake: share WiFi credentials if needed
4. ESP32 joins home WiFi → MJPEG stream available
5. Phone opens MJPEG socket → VisionEngine starts
6. GaryClient opens WebSocket → cloud
7. ContextProvider pulls calendar, location
8. Glasses LED: green pulse → Gary is live

### Voice interaction
1. User pinches → radar → ESP32 → BLE → Phone
2. GestureRecognizer: `pinch` → VoiceSession.activate()
3. LiveKit room created, mic opens, glasses LED blue
4. User speaks → PCM → Deepgram STT → transcript
5. Transcript + UserContext → Gemini 2.5 Flash
6. Agent dispatches tool (e.g., `relay_home_assistant_command`)
7. Command → WebSocket → Phone → HA → lights off
8. Agent speaks response → Cartesia chunks → LiveKit → Phone → bone conduction
9. Lights off while Gary is still talking. Parallel execution.

Total perceived latency: ~1.2–1.8s from end of speech to Gary speaking.

### Gesture-only (no voice)
1. Radar → ESP32 → BLE → Phone → `gestureDetected(swipe_right)` → WebSocket → cloud
2. Agent: context-aware routing:
   - Music playing? → next track
   - Notification showing? → dismiss
   - Teaching mode? → next lesson block
   - Default → no action
3. Command → WebSocket → Phone → execute

### Scene understanding
1. User: "Gary, what's wrong with my code?"
2. Agent calls `request_frame_from_glasses`
3. Cloud → WebSocket → Phone: `requestFrame`
4. Phone grabs single JPEG from ring buffer → sends to cloud
5. Cloud → Gemini Vision → text description
6. Agent formulates response → TTS → bone conduction
7. JPEG discarded. Never stored.

### End of session
1. User removes glasses → BLE disconnects
2. VoiceSession deactivated, LiveKit room closed
3. GaryClient sends `sessionEnd` event
4. Cloud: conversation → summary → Postgres, raw state discarded
5. Phone: frame buffer and audio buffers cleared

---

## Latency Targets

| Interaction | Target |
|-------------|--------|
| Radar gesture → action | ~300ms |
| Voice → smart home action | ~1.1s |
| Voice → Gary speaks first word | ~1.2–1.8s |
| Scene understanding | ~1.4s |
| Proactive notification | ~50ms |
| ArUco device recognition | ~60ms |

---

## Milestones

### M2 — Android App (current focus)
See `android/` directory. Build order is weeks 1–12 above.

### M3 — Cloud Backend
See `cloud/` directory. FastAPI + Postgres + Redis + Gary agent port.

### M4 — Hardware v1
See `hardware/` directory. Custom PCB (KiCad), BGT60TR13C radar prototype, OV5640 camera, 3D printed frame.

---

## Decisions Already Made

| Decision | Choice | Reason |
|----------|--------|--------|
| Platform | Android first | Developer has Android phone for testing |
| TTS | Cartesia (not ElevenLabs) | 78% cheaper — ElevenLabs would be $18/user/month on TTS alone |
| LLM | Gemini 2.5 Flash | Already in Gary stack, best capability/cost ratio |
| STT | Deepgram Nova-3 | <300ms, already proven in Gary_2 |
| Gesture input | BGT60TR13C radar | Replaces hand camera — no camera means no MediaPipe needed for gestures |
| Smart home | HA as relay (phone) | Avoids NAT problem, Nabu Casa for away |
| Data storage | Text summaries only, never raw audio/video | Privacy architecture + avoid catastrophic storage bills |
| Subscription price | $24–29/month | ~40–60% gross margin at $12–18 COGS |
| No Raspberry Pi | Eliminated | Phone is the hub, cloud is compute. Saves $250/deployment |
| No fine-tuning | Not yet | System prompt handles Gary's personality well. Revisit at scale |

---

## How to Work in This Repo

- **One module at a time.** Don't touch cloud/ while android/ is incomplete.
- **Kotlin learner context.** Developer is new to Kotlin. Explain patterns (coroutines, @Composable, StateFlow) when introducing them. Link to Android docs when non-obvious.
- **Privacy constraints are hard rules.** If implementing frame or audio handling: no write(), no logging of raw data, no debug modes that persist data.
- **Small PRs, runnable steps.** Each milestone task should be independently runnable to test before moving on.
- **Gary_2 is off-limits.** Never import, reference, or copy-paste from `/Users/prathamyaligar/Desktop/Gary_2` into this repo. Port the Gary agent logic by re-implementing it cleanly in the cloud service.
- **Always verify on device.** Android emulator is not reliable for BLE or camera testing. Use a real Android phone.

---

## Open Questions (decide before starting each milestone)

- [ ] New repo name: `gary-product` or `pinch` or something else?
- [ ] Cloud host: Railway, Render, or Fly.io?
- [ ] HA remote access: Nabu Casa support at launch or Phase 2?
- [ ] iOS: when to add (after Android stable, need to buy iPhone)?
- [ ] Mac overlay app from Gary_2: keep as desktop companion product alongside phone app?
- [ ] Soli radar: order BGT60TR13C breakout board before committing to PCB design?
- [ ] Frame sourcing: use off-shelf frame for v1 or go straight to SLA 3D print?

---

*Last updated: 2026-07-02. Source: full Gary_2 brainstorm session.*
