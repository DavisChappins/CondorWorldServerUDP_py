# Condor Server UDP Scraper

Windows-first tooling for Condor dedicated servers:
- `app.py`: Flask dashboard to manage multiple UDP sniffers
- `sniffAndDecodeUDP_toExpress_viaFlask.py`: UDP sniffer/decoder/forwarder
- `tasksGet.py` -> `tasksConvert.py` -> `tasksUpload.py`: task sync pipeline

## Requirements

### External software
- Python 3.9+
- Windows with **Npcap** installed (required by Scapy for packet capture)
- Condor landscapes in `C:\Condor3\Landscapes\{landscape}\{landscape}.trn`
- Elevated terminal (Run as Administrator) for live sniffing

Npcap download: <https://nmap.org/npcap/>

### Python packages
Install all Python dependencies:

```bash
pip install -r requirements.txt
```

`requirements.txt` includes:
- `scapy`
- `numpy`
- `Flask`
- `requests`
- `psutil`
- `colorama` (needed by several scripts in `extra/`)

## Quick Start (Dashboard)

1. Install dependencies (`pip install -r requirements.txt`).
2. Install Npcap.
3. Start dashboard as Administrator:

```bash
python app.py
```

4. Open `http://127.0.0.1:5001`.
5. Create at least one **Soaring Group**.
6. Add a server (or import from DSHelper detection), choose landscape, assign group.
7. Click **Start**.

Notes:
- A server must have a group assigned before it can start.
- On dashboard startup, saved servers auto-start with staggered countdowns (5s, 10s, 15s, ...).

## Setup Self-Test (Windows-friendly)

Run the included environment test before first use:

```bash
python test_setup.py
```

Or on Windows, double-click:

```text
run_test_setup.bat
```

What it checks:
- Python version
- Required Python modules from `requirements.txt`
- Administrator privileges (Windows)
- Npcap presence (Windows service/path checks)
- Scapy interface detection and a tiny capture smoke test

The script pauses at the end on Windows so the command window stays open.

If you do not want pause behavior:

```bash
python test_setup.py --no-pause
```

## What The App Does

### Dashboard (`app.py`)
- Manage multiple sniffers by server name/port/landscape/group.
- Detect DSHelper servers from:
  `C:\Users\<USER>\AppData\Roaming\Hitziger Solutions\DSHelper\user_settings.xml`
- Detect installed landscapes from `C:\Condor3\Landscapes`.
- Track runtime status: `off`, `starting_N`, `listening`, `transmitting`, `error`.
- Start/stop sniffer subprocesses and store persistent config in `config.json`.
- Trigger background task sync sequence:
  `tasksGet.py` -> `tasksConvert.py` -> `tasksUpload.py`
  (30 minute cooldown between runs).

### Sniffer (`sniffAndDecodeUDP_toExpress_viaFlask.py`)
- Captures UDP traffic on configured port with Scapy.
- Decodes packet families:
  - `0x3d00`: telemetry (position, altitude, speed, heading, vario, accel)
  - `0x3f00/0x3f01`: identity/config
  - `0x1f00`: FPL task core
  - `0x0700` and `0x0f00`: disabled airspaces
  - `0x2f00`: settings bundle
  - `0x8006`: acknowledgements
- Converts XY to lat/lon through `navicon_bridge.py` and helper EXE(s).
- Batches and forwards positions to CondorMap endpoint.
- Reconstructs `udp_fpl_*.fpl` when task/settings/disabled-airspace data are complete.
- Persists identity mappings per process.

Forwarding defaults and env vars:
- Default endpoint: `https://server.condormap.com/api/positions`
- `EXPRESS_ENDPOINT`
- `EXPRESS_TIMEOUT`

## Output Files

Created in `logs/`:
- `logs/dashboard_{port}_stdout.log`
- `logs/dashboard_{port}_stderr.log`
- `logs/{PID}_hex_log_3f00_3f01_*.txt`
- `logs/{PID}_identity_map.json`

Created in repo root (when enough FPL data is captured):
- `udp_fpl_YYYYMMDD_HHMMSS.fpl`

## Offline Replay

`replay_hex_log.py` replays hex logs through existing parser functions.

```bash
python replay_hex_log.py path\to\hex_log.txt --delay-ms 5 --direction REPLAY
```

Important: this script imports `sniffAndDecodeUDP_toFlask.py`. In this repo that file is currently under `extra/`, so run with an import path that includes `extra/` (or move/copy the file).

PowerShell example:

```powershell
$env:PYTHONPATH="extra"
python replay_hex_log.py logs\some_log.txt --direction REPLAY
```

## Task Sync Scripts

- `tasksGet.py`
  - Reads DSHelper scheduler data from `scheduler.dat`
  - Writes `tasks.json`
  - Copies referenced `.fpl` files into `flightplans/`
- `tasksConvert.py`
  - Converts `.fpl` files to `.json`
  - Optionally maps XY->lat/lon using `navicon_bridge`
  - Matches tasks to servers/groups using dashboard API or `config.json`
- `tasksUpload.py`
  - Uploads one or many converted tasks to CondorMap API
  - Uses `CONDOR_API_URL` override if provided

## API Endpoints (Dashboard)

- `GET /api/servers`
- `POST /api/servers`
- `DELETE /api/servers/<server_id>`
- `POST /api/servers/<server_id>/start`
- `POST /api/servers/<server_id>/stop`
- `GET /api/servers/<server_id>/status`
- `GET /api/landscapes`
- `PUT /api/servers/<server_id>/landscape`
- `GET /api/dshelper/servers`
- `GET /api/landscapes/details`
- `GET /api/groups`
- `POST /api/groups`
- `PUT /api/servers/<server_id>/group`

## Repository Layout

- `app.py` - dashboard UI + API + process management
- `sniffAndDecodeUDP_toExpress_viaFlask.py` - main sniffer/decoder
- `navicon_bridge.py` - helper bridge for XY->lat/lon conversion
- `replay_hex_log.py` - offline replay
- `tasksGet.py` / `tasksConvert.py` / `tasksUpload.py` - task pipeline
- `DASHBOARD_README.md` - dashboard-focused documentation
- `QUICKSTART.md` - short setup guide
- `extra/` - archived/experimental utilities and legacy variants
