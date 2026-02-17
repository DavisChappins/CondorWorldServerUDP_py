# Dashboard README

## Overview

`app.py` runs a Flask dashboard to manage multiple Condor UDP sniffer processes (`sniffAndDecodeUDP_toExpress_viaFlask.py`).

## Requirements

- Python dependencies: `pip install -r requirements.txt`
- Windows + Npcap for packet capture
- Run elevated (Administrator) for sniffing

## Start

```bash
python app.py
```

Dashboard URL:
- `http://127.0.0.1:5001` (default)

Optional env vars:
- `DASHBOARD_HOST` (default `127.0.0.1`)
- `DASHBOARD_PORT` (default `5001`)

## Core Features

- Multi-server config with persistent `config.json`
- Group management (servers require a group before start)
- Landscape detection from `C:\Condor3\Landscapes`
- DSHelper server detection from user settings XML
- Start/stop per server with subprocess PID tracking
- Auto-start countdown for saved servers on dashboard launch
- Smart refresh behavior:
  - Fast refresh during countdown
  - Slower refresh after systems stabilize
- Background task sync trigger:
  - `tasksGet.py` -> `tasksConvert.py` -> `tasksUpload.py`
  - 30-minute cooldown between sync runs

## Typical Workflow

1. Create one or more groups.
2. Add server entries manually or from DSHelper detected servers.
3. Select landscape and group for each server.
4. Start server.
5. Monitor status and logs.

## Status Values

- `off`: process not running
- `starting_N`: auto-start countdown in progress
- `listening`: process running, waiting/no recent packet writes
- `transmitting`: recent packet activity seen in logs
- `error`: failed or invalid process state

## Log Files

Dashboard logs:
- `logs/dashboard_{port}_stdout.log`
- `logs/dashboard_{port}_stderr.log`

Sniffer logs:
- `logs/{PID}_hex_log_3f00_3f01_*.txt`
- `logs/{PID}_identity_map.json`

Generated FPL output (if packet set is complete):
- `udp_fpl_YYYYMMDD_HHMMSS.fpl` in repo root

## API Endpoints

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

## Sniffer Forwarding Notes

The dashboard starts sniffer processes that forward telemetry to:
- default: `https://server.condormap.com/api/positions`
- override via `EXPRESS_ENDPOINT`

Other sniffer env controls:
- `EXPRESS_TIMEOUT`

## Troubleshooting

- Start button disabled:
  - Assign a group to the server first.
- Landscape update fails:
  - Ensure `.trn` exists under `C:\Condor3\Landscapes\<name>\<name>.trn`.
- Sniffer exits immediately:
  - Check `logs/dashboard_{port}_stderr.log`.
  - Verify Npcap and elevated privileges.
- No DSHelper servers detected:
  - Verify DSHelper `user_settings.xml` path exists for current user.
