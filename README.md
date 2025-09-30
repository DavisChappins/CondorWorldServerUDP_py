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
- **XY→Lat/Lon conversion** via 2 modes:
  - Preferred: `navicon_bridge` using `AA3.trn` + helper EXE.
  - Fallback: parametric model in `aa3_converter.py` (NumPy-based).

## Repository Layout

- `sniffAndDecodeUDP.py` — main sniffer/decoder entrypoint.
- `aa3_converter.py` — parametric XY→Lat/Lon conversion (NumPy).
- `navicon_bridge.py` — calls 32-bit NaviCon via helper EXE & `AA3.trn`.
- `replay_hex_log.py` — offline parser for hex-only logs (uses legacy parser in `scapy_udp_56298_14.py`).
- `scapy_udp_56298_*.py` — prior analysis scripts and parsers.
- `AA3.trn` — terrain resource for NaviCon (keep in repo root). found in landscapes folder not in github
- `Condor3XY2LatLon.exe` — helper executable used by `navicon_bridge.py`.
- `extra/` — utilities and experiments (including a separate README).
- `requirements.txt` — Python dependencies for core tools.

## Requirements

- **Python**: 3.9+
- **Windows** with **Npcap** installed (Scapy uses Npcap/WinPcap for sniffing)
- **Administrator privileges** (maybe) to capture packets
- **Python packages** (install via `requirements.txt`):
  - `scapy`
  - `numpy` (for `aa3_converter.py` fallback conversion)

Install Python packages:

```bash
pip install -r requirements.txt
```

Npcap (required on Windows): https://nmap.org/npcap/

Tip: Installing Wireshark also offers to install Npcap. Ensure the "Install Npcap" option is checked during Wireshark setup.

## Quick Start

1. Open an elevated terminal (Run as Administrator) on Windows.
2. Ensure Npcap is installed and the game/server is emitting UDP on port 56298.
3. From the repo root, run:

```bash
python sniffAndDecodeUDP.py
```

4. You should see console output like:

```
[*] Starting UDP packet sniffer on port 56298
[*] Logging detailed output to: udp_sniff_log_YYYYMMDD_HHMMSS.txt
[*] Logging 3d00 HEX strings to: hex_log_3d00_YYYYMMDD_HHMMSS.txt
[*] Logging 3f00/3f01 HEX strings to: hex_log_3f00_3f01_YYYYMMDD_HHMMSS.txt
[*] Logging 8006 HEX strings to: hex_log_8006_YYYYMMDD_HHMMSS.txt
============================================================
```

5. When packets arrive, decoded lines print to the console and to the main log.
6. If enough FPL-related packets are captured, an `udp_fpl_YYYYMMDD_HHMMSS.fpl` is written to the repo root.

## Outputs Per Run

- `udp_sniff_log_*.txt` — full, timestamped, human-readable decode log.
- `hex_log_3d00_*.txt` — hex-only telemetry packets.
- `hex_log_3f00_3f01_*.txt` — hex-only identity/config packets.
- `hex_log_8006_*.txt` — hex-only acknowledgement packets.
- `identity_map.json` — cookie→identity and entity→cookie mappings (regenerated each run).
- `udp_fpl_*.fpl` — reconstructed Flight Plan (when enough data observed).

## XY → Lat/Lon Conversion

By default, `sniffAndDecodeUDP.py` tries the high-fidelity NaviCon path and falls back to the parametric model if unavailable.

- Preferred path: `navicon_bridge.xy_to_latlon_default(x, y)` uses:
  - `AA3.trn` in the repo root
  - `Condor3XY2LatLon.exe` (32-bit helper)

If either is missing or errors occur, the fallback `convert_xy_to_lat_lon(x, y)` from `aa3_converter.py` is used (less accurate but self-contained; requires NumPy).

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

- **Sniff port**: Update `SNIFF_PORT` at the top of `sniffAndDecodeUDP.py` if your game/server uses a different port.
- **Permissions**: If you get a permission error, re-run as Administrator.

## Known Limitations

- **Admin + Npcap required** on Windows for live sniffing.
- **G-Force displayed as “(incorrect)”**. The magnitude is computed from raw accel vectors and divided by g; may not match in-game UI.
- **Identity parsing is heuristic**. `parse_identity_packet()` scans length-prefixed ASCII; fields may occasionally misalign or be missing.
- **FPL reconstruction is best-effort**. The .fpl is written only after task, settings, and disabled-airspace data are sufficiently observed; content may be incomplete if packets were missed.
- **Lat/Lon accuracy** depends on the conversion path. The NaviCon path needs `AA3.trn` and the 32-bit helper; the fallback model is approximate.
- **Windows-focused**. Sniffing path is validated on Windows; other platforms are untested here.

## Troubleshooting

- **No packets show up**:
  - Verify the correct port (`SNIFF_PORT`) and that traffic is local to the machine.
  - Ensure Npcap is installed and you’re running the shell as Administrator.
  - Check Windows Firewall rules.
- **Lat/Lon conversion errors**:
  - Confirm `AA3.trn` and `Condor3XY2LatLon.exe` are in the repo root for the NaviCon path.
  - If missing, install NumPy and rely on the fallback converter.
- **.fpl not written**:
  - You may not have captured all required packets yet (task + settings + full/known disabled-airspaces).

## License

Not specified. If you plan to publish or share, add a `LICENSE` file.
