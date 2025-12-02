# Copilot Instructions for Ambient-Node

This repository implements a small multi-service embedded stack that uses MQTT as its IPC bus. The notes below summarize the architecture, data formats (MQTT payloads), systemd unit files provided under `Services/`, and the core runtime responsibilities of each container so an AI coding agent can make safe, focused changes.

## High-level architecture
- Services (see `docker-compose.yml`):
  - `ai-service` — camera input, face detection/recognition, publishes face events and positions.
  - `db-service` — owns persistence (Postgres), session lifecycle, canonical topic shapes and event logging.
  - `fan-service` — subscribes to face positions and user/device commands, sends serial commands to fan hardware.
  - `mqtt_broker` — Mosquitto MQTT broker.
  - `Services/ble_gateway.py` — optional BLE gateway running as a systemd service on Pi; proxies BLE commands ↔ MQTT and handles chunked image upload.

## Systemd services (local/pi deployment)
- `Services/ambient-node.service` — runs `docker compose up` for the full stack. Useful on a Pi-based installation.
- `Services/ambient-ble-gateway.service` — runs the BLE gateway script directly from `Services/ble_gateway.py` inside a Python venv. Key env: `PYTHONUNBUFFERED=1` and `User=pi` in the unit.
- `Services/rpicam-stream.service` — an rpicam streaming helper (streams camera frames over TCP to `tcp://0.0.0.0:8888`).

Paths and behavior:
- The systemd units assume the repository is installed to `/home/pi/ambient-node` and that the BLE gateway has a `.venv` with Python available. Adjust `WorkingDirectory` and `ExecStart` if you run elsewhere.

## Core logic per container (summary + important files)
- ai-service (`ai-service/`)
  - Entry: `main.py` — main loop does: start camera, rotate frames 180°, resize to `PROCESSING_WIDTH x PROCESSING_HEIGHT` (640x360), run MediaPipe face detection, apply NMS, convert detection coords back to FHD (1920x1080), update `FaceTracker`, and periodically publish `ambient/ai/face-position` (target 4Hz).
  - Recognition: `face_recognition.py` — TFLite interpreter produces embeddings; embeddings saved under `${FACE_DIR}/${user_id}/embedding.npy` and metadata in `metadata.json`.
  - Tracking: `face_tracker.py` — greedy nearest-distance matching (max distance default 150px), keeps last_seen and last_identified timestamps.
  - MQTT: `mqtt_client.py` — subscribes to `ambient/user/*`, `ambient/session/active`, `ambient/command/mode`. Publishes `ambient/ai/face-detected` (qos=1), `ambient/ai/face-position` (qos=0), `ambient/ai/face-lost` (qos=1).

- db-service (`db-service/`)
  - Entry: `main.py` — starts MQTT client and DB wrapper, registers `EventHandlers` from `handlers.py`.
  - Handlers: `handlers.py` — authoritative source of canonical payload shapes, session lifecycle logic, event logging into Postgres tables (`user_sessions`, `device_events`, `users`, `current_status`). It publishes `ambient/session/active` with `retain=True` and `qos=1`.
  - Config: `config.py` — DB connection/env settings. Docker compose mounts `./init.sql` into Postgres init; note: `init.sql` may be in deployment packaging (not in repo root here).

- fan-service (`fan-service/`)
  - Entry: `main.py` — subscribes to `ambient/command/*` and `ambient/ai/*` topics. Translates position or command payloads into serial commands via `FanHardware.send_command()`.
  - Hardware: `hardware.py` — opens serial port (`SERIAL_PORT`, `SERIAL_BAUDRATE`) and implements `_read_loop()` + `send_command(cmd)`; commands are ASCII lines like `P (x,y)`, `S <speed>`, `N 1` (natural wind), `R 0/1` (rotation enable), `A <dir> <toggle>`.

- BLE gateway (`Services/ble_gateway.py`)
  - Runs as a standalone process on Pi when systemd unit enabled. Accepts BLE writes containing either full JSON or chunked payloads labeled `<CHUNK:i/N>...` and an `END` marker. Reassembles and converts into MQTT topic publishes (e.g., `ambient/user/register`, `ambient/command/mode`, `ambient/user/select`).

## MQTT topics & canonical payloads (extracted from code)
Below are the canonical topics and the exact JSON shapes produced/consumed by services. Prefer these shapes when writing code or tests.

- ambient/user/register (BLE or external UI → DB & AI)
  - Example payload: {"user_id":"u123","username":"Alice","image_path":"/var/lib/ambient-node/users/u123/u123.png","timestamp":"2025-11-29T12:34:56"}
  - Side effects: DB inserts user, AI service receives register to create embedding via `FaceRecognizer.register_user()`.

- ambient/user/update
  - Example: {"user_id":"u123","username":"Alice","image_path":"...","timestamp":"..."}

- ambient/user/select (select users for active session)
  - Example: {"user_list":[{"user_id":"u123"},{"user_id":"u456"}],"timestamp":"..."}
  - DB will close any previous session and create a new `user_sessions` row. DB publishes `ambient/session/active` (retain, qos=1): {"session_id":"sess-...","user_list":[...],"timestamp":"..."}

- ambient/session/active (DB → other services) [RETAINED, qos=1]
  - Example: {"session_id":"sess-abc","user_list":[{"user_id":"u123"}],"timestamp":"..."}

- ambient/ai/face-detected (AI → DB)
  - Payload: {"user_id":"u123","confidence":0.84,"timestamp":"..."} (published with qos=1)

- ambient/ai/face-position (AI → Fan)
  - Payload: {"user_id":"u123","x":960,"y":540,"timestamp":"..."} (published with qos=0 for low latency)

- ambient/ai/face-lost (AI → DB)
  - Payload: {"user_id":"u123","duration_seconds":1.2,"timestamp":"..."} (qos=1)

- ambient/command/mode (UI/BLE → DB/FAN/AI)
  - Example: {"type":"motor","mode":"ai_tracking","user_id":"u123","timestamp":"..."}
  - DB records mode change; AI listens for mode changes and will reset tracker when mode != `ai_tracking`.

- ambient/command/speed, ambient/command/direction, ambient/command/timer
  - Speed: {"speed":3,"user_id":"u123","timestamp":"..."}
  - Direction: {"direction":"left","toggleOn":1,"user_id":"u123","timestamp":"..."}
  - Timer: {"duration_sec":3600,"user_id":"u123","timestamp":"..."}

When creating new topics, follow these patterns: include `user_id` when relevant, include `timestamp` (ISO8601), and publish session changes from `db-service` with `retain=True` and `qos=1`.

## Data storage & file locations
- Default persistent paths used by services (inside containers or mounted host volumes):
  - `/var/lib/ambient-node/users` — per-user directories containing `embedding.npy` and `metadata.json`.
  - `/var/lib/ambient-node/captures` — temporary captures (AI service configurable via `SAVE_DIR`).

## Common change vectors and safety notes for AI agents
- When adjusting detection/recognition parameters, change them in `ai-service/config.py` and keep transformations consistent across `_detect_faces()` and `FaceTracker.identify_faces()`.
- Do not change MQTT topic names or retained/QoS semantics without updating `db-service/handlers.py` and all subscribers; the DB is authoritative for `ambient/session/active`.
- Serial command format is hardware-protocol-specific; changes to commands must be coordinated with any firmware or hardware docs. Fan commands center on `P`, `S`, `N`, `R`, `A` prefixes.

## Troubleshooting & local testing tips
- Local dev on Windows: use WSL2 or a Pi for device access (camera/serial). For headless debugging, run services without devices by stubbing inputs (e.g., run `ai-service` with a recorded video or skip camera access).
- To inspect MQTT traffic quickly (local): `mosquitto_sub -h localhost -t '#' -v` (in a Linux environment).
- If `init.sql` is needed for Postgres initial schema, check deployment packaging — `docker-compose.yml` mounts `./init.sql` into the Postgres container, but this repo copy may be absent; look in deployment artifacts or ask the repo owner for the SQL file.

---
If you want, I can now:
- add a short `scripts/debug_publish.py` that publishes canonical MQTT messages for local testing, or
- expand the DB schema section by creating a best-effort `init.sql` skeleton based on `db-service/handlers.py` queries.
Tell me which and I will proceed.
