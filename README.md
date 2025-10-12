# Condor Server UDP Scraper

A Python tool to sniff, decode, and log UDP traffic from Condor (port 56298 by default). It parses multiple in-game packet types, reconstructs basic Flight Plan (.fpl) files from captured packets, and persists pilot identity mappings.

## Features

- **Sniff live UDP traffic** on a configurable port (default `56298`).
- **Decode key packet families**:
  - `0x3d00` Telemetry: position (X/Y), altitude, speed, heading, vertical speed, accel vectors.
  - `0x3f00 / 0x3f01` Identity/config: pilot info (CN, name, registration, country, aircraft), cookie mapping.
  - `0x1f00` FPL task core: landscape, turnpoints with geometry.
  - `0x0700` and `0x0f00` Disabled airspaces list (chunked).
  - `0x2f00` Settings bundle: description, plane class (heuristic), weather zone, common options.
  - `0x8006` Short acknowledgements.
- **Reconstruct .fpl files** from captured task/settings/disabled-airspaces.
- **Multiple logs** written per run (human-readable and hex-only).
- **Identity persistence** into `identity_map.json` (regenerated each run).
- **XY→Lat/Lon conversion** using `navicon_bridge` with landscape-specific `.trn` files from `C:\Condor3\Landscapes\`.
- **Web dashboard** for managing multiple UDP sniffer instances with landscape selection.

## Repository Layout

- `app.py` — Flask web dashboard for managing multiple UDP sniffer instances.
- `sniffAndDecodeUDP_toExpress_viaFlask.py` — main sniffer/decoder entrypoint.
- `navicon_bridge.py` — calls 32-bit NaviCon via helper EXE & landscape `.trn` files.
- `replay_hex_log.py` — offline parser for hex-only logs (uses legacy parser in `scapy_udp_56298_14.py`).
- `scapy_udp_56298_*.py` — prior analysis scripts and parsers.
- `Condor3XY2LatLon.exe` — helper executable used by `navicon_bridge.py`.
- `extra/` — utilities and experiments (including a separate README).
- `requirements.txt` — Python dependencies for core tools.
- `DASHBOARD_README.md` — detailed documentation for the Flask dashboard.
- `QUICKSTART.md` — quick start guide for new users.

## Requirements

- **Python**: 3.9+
- **Windows** with **Npcap** installed (Scapy uses Npcap/WinPcap for sniffing)
- **Administrator privileges** (maybe) to capture packets
- **Python packages** (install via `requirements.txt`):
  - `scapy>=2.5.0`
  - `numpy>=1.24`
  - `Flask>=3.0`
  - `requests>=2.31`
  - `psutil>=5.9.0`

Install Python packages:

```bash
pip install -r requirements.txt
```

Npcap (required on Windows): https://nmap.org/npcap/

Tip: Installing Wireshark also offers to install Npcap. Ensure the "Install Npcap" option is checked during Wireshark setup.

## Quick Start

### Using the Flask Dashboard (Recommended)

1. **Start the Flask dashboard** (Run as Administrator on Windows):

```bash
python app.py
```

2. **Open your browser** and navigate to `http://127.0.0.1:5001`

3. **Add a server**:
   - Enter a server name (e.g., "Condor Server 1")
   - Select a landscape from the dropdown (e.g., AA3, Slovenia3, Colorado_C2)
   - Enter the UDP port (e.g., 56288 or 56298)
   - Click "Add Server"

4. **Start the server** by clicking the green "Start" button

5. The sniffer will begin capturing packets and you'll see:
   - Real-time status updates (Listening → Transmitting)
   - Process ID (PID) in the dashboard
   - Log files created in the `logs/` directory

6. **Change landscape**: Stop the server, select a different landscape from the dropdown, then start again

7. **Monitor multiple servers**: Add and manage multiple UDP sniffers on different ports simultaneously

### Manual Command Line Usage (Advanced)

Alternatively, you can run the sniffer directly from the command line:

```bash
python sniffAndDecodeUDP_toExpress_viaFlask.py --port 56288 --server-name "My Server" --landscape AA3
```

The sniffer will output:
```
[*] PID: 12345
[*] Server Name: My Server
[*] Landscape: AA3
[*] TRN File: C:\Condor3\Landscapes\AA3\AA3.trn
[*] Starting UDP packet sniffer on port 56288
[*] Logging 3f00/3f01 HEX strings to: logs/12345_hex_log_3f00_3f01_YYYYMMDD_HHMMSS.txt
[*] Logging 8006 HEX strings to: logs/12345_hex_log_8006_YYYYMMDD_HHMMSS.txt
[*] Identity map JSON: logs/12345_identity_map.json
============================================================
```

When packets arrive, decoded lines print to the console and log files. If enough FPL-related packets are captured, an `udp_fpl_YYYYMMDD_HHMMSS.fpl` is written to the repo root.

## Outputs Per Run

All log files are stored in the `logs/` directory:

- `logs/{PID}_hex_log_3f00_3f01_*.txt` — hex-only identity/config packets.
- `logs/{PID}_hex_log_8006_*.txt` — hex-only acknowledgement packets.
- `logs/{PID}_identity_map.json` — cookie→identity and entity→cookie mappings (regenerated each run).
- `logs/dashboard_{port}_stdout.log` — dashboard process stdout logs.
- `logs/dashboard_{port}_stderr.log` — dashboard process stderr logs.
- `udp_fpl_*.fpl` — reconstructed Flight Plan (when enough data observed) - saved in root directory.

## XY → Lat/Lon Conversion

The sniffer uses `navicon_bridge` to convert Condor's XY coordinates to Lat/Lon using landscape-specific terrain files:

- **Landscape-specific conversion**: `navicon_bridge.xy_to_latlon_trn(trn_path, x, y)` uses:
  - Landscape `.trn` file from `C:\Condor3\Landscapes\{landscape}\{landscape}.trn`
  - `Condor3XY2LatLon.exe` (32-bit helper)

The landscape is selected when adding a server in the dashboard or via the `--landscape` command-line argument. The script will verify the TRN file exists on startup and exit with an error if not found.

## Telemetry Packet Map (0x3d00)

The `0x3d00` telemetry payload is parsed as a sequence of 4-byte little-endian words. Each word is interpreted both as `u32` (little-endian) and as `float32` (`<f`). The fields used are shown below; indices are zero-based into the 4-byte words list:

- **[0] cookie (u32)**
  - Session/player cookie. Displayed in hex in logs.

- **[1] unknown**
  - Not used by current decoder.

- **[2] pos_x (float32)**
- **[3] pos_y (float32)**

- **[4] altitude_m (float32)**
  - Derived: `altitude_ft = altitude_m * 3.28084`.

- **[5] vx (float32)**
- **[6] vy (float32)**
- **[7] vz (float32)**
  - Derived:
    - `speed_mps = sqrt(vx^2 + vy^2 + vz^2)`
    - `speed_kt = speed_mps * 1.9438445`
    - `vario_mps = vz`
    - `vario_kt = vario_mps * 1.9438445`
    - `heading` (degrees, 0–360) from corrected formula `atan2(-vx, vy)` then degrees and normalized.

- **[8] ax (float32)**
- **[9] ay (float32)**
- **[10] az (float32)**
  - Derived:
    - `a_mag = sqrt(ax^2 + ay^2 + az^2)`
    - `g_force = a_mag / 9.80665` (shown as "(incorrect)" pending better calibration)

- **Tail fields**: the decoder preserves the last 6 words as `u32` in `tail` for inspection (`u32s[-6:]`). Their meaning is currently unknown.

Endianness summary:
- `u32`: little-endian
- `float32`: little-endian (`struct.unpack('<f', ...)`)

## Offline Replay (Optional)

You can parse previously captured hex-only logs without sniffing:

```bash
python replay_hex_log.py path\to\hex_file.txt --delay-ms 5 --direction REPLAY
```

Notes:
- `replay_hex_log.py` currently imports parsers from `scapy_udp_56298_14.py`. Keep that file present.
- Use the specific hex logs for the packet family you want to replay, e.g. `hex_log_3d00_*.txt` for telemetry.

## Configuration

- **Permissions**: If you get a permission error, re-run as Administrator.

## Known Limitations

- **Admin + Npcap required** on Windows for live sniffing.
- **Condor 3 landscapes required** for coordinate conversion. The script needs access to `C:\Condor3\Landscapes\` with valid `.trn` files.
- **G-Force displayed as "(incorrect)"**. The magnitude is computed from raw accel vectors and divided by g; may not match in-game UI.
- **Identity parsing is heuristic**. `parse_identity_packet()` scans length-prefixed ASCII; fields may occasionally misalign or be missing.
- **FPL reconstruction is best-effort**. The .fpl is written only after task, settings, and disabled-airspace data are sufficiently observed; content may be incomplete if packets were missed.
- **Windows-focused**. Sniffing path is validated on Windows; other platforms are untested here.

## Troubleshooting
- **No packets show up**:
  - Verify the correct port and that traffic is local to the machine.
  - Ensure Npcap is installed and you're running as Administrator.
  - Check Windows Firewall rules.
- **Landscape not found**:
  - Ensure the landscape is installed in `C:\Condor3\Landscapes\{landscape}\`
  - Verify the `.trn` file exists: `C:\Condor3\Landscapes\{landscape}\{landscape}.trn`
  - The dashboard will only show landscapes with valid `.trn` files.
- **Lat/Lon conversion errors**:
  - Confirm `Condor3XY2LatLon.exe` is in the repo root.
  - Verify the selected landscape's `.trn` file exists and is accessible.
- **.fpl not written**:
  - You may not have captured all required packets yet (task + settings + full/known disabled-airspaces).
- **Dashboard won't start**:
  - Ensure Flask is installed: `pip install flask`
  - Check if port 5001 is already in use.

## License

Not specified. If you plan to publish or share, add a `LICENSE` file.
