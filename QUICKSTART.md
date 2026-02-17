# Quick Start - Condor Dashboard

## 1) Install

```bash
pip install -r requirements.txt
```

Also install **Npcap** on Windows:
<https://nmap.org/npcap/>

## 2) Start Dashboard (Administrator)

```bash
python app.py
```

Open: `http://127.0.0.1:5001`

## 3) First Run Setup

1. Create a **Soaring Group** (required before start).
2. Add a server (or import detected DSHelper server).
3. Select the server landscape.
4. Start the server.

## Key Notes

- Must run elevated for live packet capture (Administrator on Windows).
- Condor landscape `.trn` files are required at:
  `C:\Condor3\Landscapes\{landscape}\{landscape}.trn`
- A running server status can be:
  `starting_N`, `listening`, or `transmitting`.
- Existing configured servers may auto-start with countdowns when `app.py` launches.

## Logs

- `logs/dashboard_{port}_stdout.log`
- `logs/dashboard_{port}_stderr.log`
- `logs/{PID}_hex_log_3f00_3f01_*.txt`
- `logs/{PID}_identity_map.json`
- `udp_fpl_*.fpl` (repo root, when enough FPL packets are captured)

## Troubleshooting

- Dashboard not opening:
  - Check port `5001` availability.
  - Check terminal output for Flask errors.
- Start fails:
  - Assign a group first.
  - Verify port range `1024-65535` and uniqueness.
  - Verify selected landscape `.trn` exists.
- No packets:
  - Confirm Npcap is installed.
  - Re-run as Administrator.
