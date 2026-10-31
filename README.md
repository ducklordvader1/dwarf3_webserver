# DWARF 3 Web Controller (`dwarf_web`)

A standalone Python web application for controlling a **DWARF 3 smart
telescope** directly from a PC, without the official mobile app. It speaks the
telescope's native WebSocket protocol and re-streams the camera over the
browser, giving full control of camera, astro, focus, motion and device
functions from any device on the local network.

The protocol implementation targets the **October 2026** DWARF 3 firmware
generation. See [Protocol notes](#protocol-notes) and the changelog header
in `dwarflab_controller.py` for version-specific details.

> **Security:** This application has no authentication, authorization, or
> transport encryption of any kind. Run it only on an internal, trusted
> network — never expose it directly to the public internet.
>
> It also runs Flask-SocketIO on the built-in Werkzeug development server
> (`allow_unsafe_werkzeug=True`), which is fine for single-user LAN use but
> is not a hardened production server. For anything beyond a trusted local
> network, front it with a proper WSGI/ASGI server and a reverse proxy.

---

## Download (standalone, no Python needed)

Prebuilt **one-folder** binaries for **Linux x64** and **Windows x64** are
attached to each [GitHub Release](../../releases). They bundle Python, all
dependencies, the web UI, and `ffmpeg`/`ffprobe` - nothing to install.

1. Download the zip for your platform (`dwarf3_webserver-linux-x64.zip` or
   `dwarf3_webserver-windows-x64.zip`) and extract it anywhere.
2. Run it, passing your telescope's IP:

   **Windows** - open a terminal in the extracted folder:
   ```bat
   cd dwarf3_webserver
   dwarf3_webserver.exe 192.168.1.10
   ```

   **Linux** - from a terminal:
   ```bash
   cd dwarf3_webserver
   ./dwarf3_webserver 192.168.1.10
   ```
3. Open <http://localhost:5000>.

The same `--host` / `--port` options described under [Options](#options) work on
the binary too.

> **Windows SmartScreen / antivirus:** the binaries are unsigned, so Windows may
> show a "Windows protected your PC" prompt (click *More info -> Run anyway*) and
> some antivirus tools may flag them - this is a known false-positive pattern for
> PyInstaller apps, not a sign of malware. If you'd rather not trust a binary,
> run from source instead (below).

The rest of this document describes **running from source** and the underlying
protocol.

---

## Components

| File | Purpose |
|------|---------|
| `dwarflab_controller.py` | Core library. Hand-rolled proto3 encoder/decoder, the full `WsCmd` command map, and the `DwarfLab` class (WebSocket connect, auto-reconnect, send helpers, live-state tracking from notifications). No Flask dependency — reusable on its own. |
| `server.py` | Flask + Flask-SocketIO web server. ~60 REST endpoints, an RTSP→MJPEG proxy for the live view, a single-frame snapshot endpoint, and a SocketIO broadcaster that pushes telescope state to the browser every 2 s. |
| `static/index.html` | Single-page browser UI served at `/`. |
| `start_dwarf.sh` | Starts the server as a detached daemon (writes PID to `/tmp/dwarf_web.pid`, logs to `/tmp/dwarf_web.log`). |
| `stop_dwarf.sh` | Stops the daemon via the PID file. |
| `start_dwarf.bat` | Windows equivalent of `start_dwarf.sh` (detached window, logs to `%TEMP%\dwarf_web.log`). |
| `stop_dwarf.bat` | Windows equivalent of `stop_dwarf.sh`. |

---

## Quick start

### Linux / macOS

```bash
# 1. Install dependencies (once)
pip3 install flask flask-socketio opencv-python-headless requests websocket-client

#    ffmpeg/ffprobe are also required for the RTSP proxy and /stream/info:
sudo apt install -y ffmpeg

# 2. Start the server, pointing it at the telescope's IP
./start_dwarf.sh 192.168.1.10
#    (defaults to 192.168.1.10 if no IP is given)

# 3. Open the UI
#    http://<this-host-ip>:5000

# 4. Stop it
./stop_dwarf.sh
```

### Windows

```bat
REM 1. Install dependencies (once); ensure Python 3 and ffmpeg are on PATH
pip install flask flask-socketio opencv-python-headless requests websocket-client

REM 2. Start the server (defaults to 192.168.1.10 if no IP is given)
start_dwarf.bat 192.168.1.10

REM 3. Open the UI
REM    http://localhost:5000

REM 4. Stop it
stop_dwarf.bat
```

> Download ffmpeg for Windows from <https://www.gyan.dev/ffmpeg/builds/> and
> add its `bin` folder to your `PATH` so `ffmpeg`/`ffprobe` are available.

The telescope must be joined to the same network. Its default soft-AP address
is `192.168.88.1`; once joined to your WiFi it gets a DHCP lease (the examples
here assume `192.168.1.10`).

### Options

`server.py` accepts an optional telescope IP (first argument) plus:

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `0.0.0.0` | Interface to bind to. `0.0.0.0` exposes the UI on the LAN; use `127.0.0.1` to restrict it to this machine. There is no authentication, so only bind on a trusted network. |
| `--port` | `5000` | Web server TCP port. |

```bash
# bind to localhost only, on a custom port
python3 server.py 192.168.1.10 --host 127.0.0.1 --port 8080
```

---

## Network / protocol summary

| Channel | Endpoint | Notes |
|---------|----------|-------|
| WebSocket control | `ws://<ip>:9900/?client_id=<uuid>` | Binary proto3 `WsPacket` frames. One command channel. |
| RTSP — tele lens | `rtsp://<ip>:554/ch0/stream0` | H.264, re-proxied to MJPEG at `/stream`. |
| RTSP — wide lens | `rtsp://<ip>:554/ch1/stream0` | Re-proxied at `/stream/wide`. |
| HTTP (device) | `http://<ip>:8082/` | `deviceInfo` etc., used by `/api/device_info`. |

### WsPacket wire format (proto3)

| Field | # | Type | Meaning |
|-------|---|------|---------|
| major_version | 1 | varint | `WS_MAJOR_VERSION_NUMBER` = 2 |
| minor_version | 2 | varint | `WS_MINOR_VERSION_NUMBER` = 7 |
| device_id | 3 | varint | 1 = app client |
| module_id | 4 | varint | Module the `cmd` belongs to (see `WsModuleId` ordinals) |
| cmd | 5 | varint | Command number (the `WsCmd` enum) |
| type | 6 | varint | 0 = request |
| data | 7 | bytes | Command-specific proto3 payload |
| client_id | 8 | string | UUID identifying this client |

`dwarflab_controller.build_ws_packet()` builds this; `parse_ws_packet()` decodes
incoming notifications. `module_id` is derived automatically from the command
number by `_module_for_cmd()`, mirroring `WsCmd.getModuleId()` in the app.

---

## Startup sequence (cold start, no phone)

Bringing the live stream up from a cold device requires three WebSocket
commands in order, then reading the RTSP URL:

1. `CMD_GLOBAL_TASK_MANAGER_ENTER_CAMERA` (16404) — `enter_camera()`
2. `CMD_CAMERA_TELE_OPEN_CAMERA` (10000) — `open_camera()`
3. `CMD_ASTRO_GO_LIVE` (11010) — `go_live()`

The `POST /api/camera/start_live` endpoint performs this whole sequence, after
which `/stream` is live. For the wide lens use `open_camera_wide()` +
`CMD_ASTRO_WIDE_GO_LIVE` (11020).

---

## REST API

All command endpoints are `POST` and return `{"status":"ok"|"error", ...}`.
Streaming/status endpoints are `GET`.

### Streaming & status
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Web UI |
| GET | `/stream` | MJPEG live view, tele lens (ch0) |
| GET | `/stream/wide` | MJPEG live view, wide lens (ch1) |
| GET | `/snapshot?channel=ch0\|ch1` | Single JPEG frame |
| GET | `/stream/info` | `ffprobe` summary of both RTSP streams |
| GET | `/api/status` | Connection flag + full live-state dict |
| POST | `/api/connect` | (Re)connect to the telescope |
| GET | `/api/device_info` | HTTP `deviceInfo` passthrough |

### Camera
`/api/camera/` — `open`, `close`, `start_live`, `photo`, `photo_raw`,
`burst` (`{count}`), `burst_stop`, `record_start`, `record_stop`,
`timelapse_start`, `timelapse_stop`, `params` (exposure/gain/brightness/
contrast/saturation/sharpness/wb_mode/wb_ct/ircut/jpg_quality),
`resolution` (`{resolution, framerate}`).

### Astro
`/api/astro/` — `calibrate_start`, `calibrate_stop`,
`goto_dso` (`{ra, dec, name}`, RA in hours), `goto_solar` (`{target}` 0–8),
`goto_stop`, `goto_one_click`, `one_click_stop`, `go_live`,
`stack_start` (`{exp_ms, gain, count}`), `stack_stop`,
`plate_solve`, `plate_solve_stop`, `sky_finder`, `sky_finder_stop`,
`ai_enhance`, `ai_enhance_stop`, `one_click_shoot`.

### Focus
`/api/focus/` — `auto`, `astro`, `astro_stop`, `in`, `out`, `stop`,
`step` (`{steps}`).

### Motion
`/api/motion/` — `joystick` (`{x, y}`, each −100…100; converted to the
polar `vector_angle`/`vector_length` doubles the firmware expects),
`joystick_stop`, `track_start`, `track_stop`.

### System
`/api/system/` — `sync_time`, `location` (`{lat, lon, alt}`),
`led_on`, `led_off`, `reboot`, `power_down`.

### Device (module 18, 17000-range)
All accept optional `{"enabled": true|false}`, default `true`.

| Path | Command | Effect |
|------|---------|--------|
| `/api/device/lens_defog` | `CMD_DEVICE_LENS_DEFOG` (17000) | Lens defog heater on/off |
| `/api/device/auto_cooling` | `CMD_DEVICE_AUTO_COOLING` (17001) | CMOS cooling fan on/off |
| `/api/device/auto_shutdown` | `CMD_DEVICE_AUTO_SHUTDOWN` (17002) | Auto shutdown on/off |
| `/api/device/anti_tangle` | `CMD_DEVICE_ANTI_TANGLE` (17003) | Cable anti-tangle (electronic limit) on/off |

Each sends `Req{State}{ state: int32 }` (field 1, varint) where `state` = 1
(on) / 0 (off), matching `DeviceSwitchState.fromEnabled()` in the app.

---

## Live state & notifications

`DwarfLab.state` is kept current from the telescope's push notifications and
returned by `/api/status` (and broadcast over SocketIO as `state_update`).
Tracked fields include: `connected`, `battery`, `temperature`, `cmos_temp`,
`focus_position`, `wide_focus_position`, `goto_state`, `tracking`, `stacking`,
`stacking_progress`, `lens_defog`, `auto_cooling`, `auto_shutdown`,
`anti_tangle`.

Relevant notification commands: `CMD_NOTIFY_ELE` (15201, battery),
`CMD_NOTIFY_TEMPERATURES` (15203), `CMD_NOTIFY_FOCUS_POSITION` (15257),
`CMD_NOTIFY_WIDE_FOCUS_POSITION` (15300), `CMD_NOTIFY_LENS_DEFOG_STATE`
(15301), `CMD_NOTIFY_AUTO_COOLING_STATE` (15302), `CMD_NOTIFY_AUTO_SHUTDOWN_STATE`
(15303), `CMD_NOTIFY_ANTI_TANGLE_STATE` (15306), plus the astro goto / tracking /
stacking state notifications.

---

## Protocol notes

* The command map is kept verbatim against each firmware generation. In the
  October 2026 generation the command map is packed as an obfuscated enum, with
  several numbers hidden behind aliased constants (resolved in the controller's
  changelog).
* `module_id` is the **ordinal** of the `WsModuleId` enum (no explicit numbers),
  so device commands route to module **18**, not 17.
* Known protocol quirks handled in the controller: `CMD_CAMERA_WIDE_START/STOP_RECORD`
  are 12030/12031 (not 12005/6); `CMD_ASTRO_WIDE_GO_LIVE` is 11020 (11019 is
  `STOP_EQ_SOLVING`); the voice-assistant module (16800) is intentionally **not**
  implemented.

---

## Updating for a new firmware generation

When the DWARF 3 protocol changes, refresh the controller's command map:

1. Obtain the updated command map for the new firmware generation.
2. Diff it against the controller's `CMD_*` constants.
3. For any new command, determine its payload message and proto field
   layout, plus the `WsModuleId` ordinal used for routing.
4. Add the constant, a `DwarfLab` method, and (if it pushes state) a notify
   handler + a `state` field; add a REST endpoint in `server.py`.

---

## Related

* `dwarf32stellarium/` (sibling project) — bridges this controller to
  **Stellarium**'s telescope-control protocol for point-and-slew from the sky map.
