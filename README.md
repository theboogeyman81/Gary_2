# Gary

A personal AI assistant living in smart glasses.

## Architecture

Event-driven agent on a Raspberry Pi 5 hub. Glasses stream POV camera, hand 
camera, and mic audio over WiFi. Pi runs perception pipelines, the agent 
(Pydantic AI), and tools. Cloud (Claude) handles hard reasoning; local models 
handle fast/simple tasks.

## Stack

- Python 3.11+, uv for packages
- Redis pub/sub message bus
- Pydantic AI agent
- Claude API for cloud reasoning
- SQLite for memory
- faster-whisper, openWakeWord, Piper TTS
- YOLOv8 + MediaPipe on Hailo AI HAT

## Project structure

- `agent/` — Pydantic AI agent and main event loop
- `bus/` — Redis pub/sub helpers
- `pipelines/` — voice, hand, POV — publish events
- `tools/` — functions the agent can call
- `memory/` — SQLite for long-term memory
- `events/` — Pydantic event schema
- `config/` — settings, env vars
- `scripts/` — dev utilities (publish events, monitor bus)
- `tests/` — tests

## Setup

Requires Redis running locally:

\`\`\`bash
brew install redis
brew services start redis
\`\`\`

Install dependencies:

\`\`\`bash
uv sync
\`\`\`

Copy environment template and fill in values:

\`\`\`bash
cp .env.example .env
# edit .env with your keys
\`\`\`

## Dev workflow

Three terminals:

\`\`\`bash
# Terminal 1 — watch all events
uv run python -m scripts.monitor_bus

# Terminal 2 — run the agent
uv run python -m agent.main_loop

# Terminal 3 — publish test events
uv run python -m scripts.publish_event speech "hey gary"
\`\`\`