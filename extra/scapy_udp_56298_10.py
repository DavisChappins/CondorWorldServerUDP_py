#!/usr/bin/env python3
import datetime
import math
import struct
from scapy.all import sniff, UDP
from aa3_converter import convert_xy_to_lat_lon
import os
import json
try:
    import navicon_bridge  # Out-of-process 32-bit DLL bridge
except Exception:
    navicon_bridge = None

# The UDP port the game is using
SNIFF_PORT = 56298

# Standard gravity for G-force calculation
GRAVITY_MS2 = 9.80665

# Global file handlers for logging
LOG_FILE = None
HEX_LOG_FILE = None

# Identity mapping persistence
IDENTITY_JSON_FILE = "identity_map.json"
COOKIE_MAP = {}          # cookie (int) -> identity dict
ENTITY_TO_COOKIE = {}    # entity_id (int) -> cookie (int)


def decode_3d00_payload(payload_hex: str) -> dict:
    """Decode a 0x3d00 telemetry payload into useful fields."""
    b = bytes.fromhex(payload_hex)
    words = [b[i:i+4] for i in range(0, len(b), 4) if len(b[i:i+4]) == 4]
    floats = [struct.unpack("<f", w)[0] for w in words]
    u32s = [int.from_bytes(w, "little") for w in words]

    # Field mapping based on analysis
    # First u32 is the cookie/session identifier
    cookie = u32s[0] if u32s else 0
    pos_x = floats[2]
    pos_y = floats[3]
    altitude_m = floats[4]
    altitude_ft = altitude_m * 3.28084 # Conversion to feet

    # Corrected velocity vectors are at floats[5], [6], [7]
    vx, vy, vz = floats[5], floats[6], floats[7]
    speed_mps = math.sqrt(vx * vx + vy * vy + vz * vz)
    speed_kt = speed_mps * 1.9438445
    vario_mps = vz
    vario_kt = vario_mps * 1.9438445 # Vario in knots

    # --- Corrected Heading Calculation ---
    # Calculate heading from vx and vy, negating vx to fix inverted axis
    heading_rad = math.atan2(-vx, vy) # The fix is negating vx here
    heading_deg = math.degrees(heading_rad)
    heading = (heading_deg + 360) % 360  # Convert to 0-360 degrees

    # Corrected acceleration vectors are at floats[8], [9], [10]
    ax, ay, az = floats[8], floats[9], floats[10]
    a_mag = math.sqrt(ax * ax + ay * ay + az * az)
    g_force = a_mag / GRAVITY_MS2 # Calculate G-Force

    tail = u32s[-6:]

    return {
        "cookie": cookie,
        "pos_x": pos_x,
        "pos_y": pos_y,
        "altitude_m": altitude_m,
        "altitude_ft": altitude_ft,
        "speed_mps": speed_mps,
        "speed_kt": speed_kt,
        "heading": heading,
        "vario_mps": vario_mps,
        "vario_kt": vario_kt,
        "ax": ax,
        "ay": ay,
        "az": az,
        "a_mag": a_mag,
        "g_force": g_force,
        "tail": tail,
    }


def parse_telemetry_packet(hex_data: str) -> str:
    """Decodes telemetry packets (0x3d00 and friends)."""
    try:
        msg_type = hex_data[0:4]
        cn_bytes = bytes.fromhex(hex_data[4:8])
        cn_decimal = int.from_bytes(cn_bytes, "little")
        id_bytes = bytes.fromhex(hex_data[8:16])
        id_decimal = int.from_bytes(id_bytes, "little")
        payload_hex = hex_data[16:]

        if msg_type == "3d00":
            decoded = decode_3d00_payload(payload_hex)
            # Prefer conversion via NaviCon.dll bridge (AA3.trn in project root), fallback to calibrated model
            lat = lon = float('nan')
            try:
                if navicon_bridge is not None:
                    lat, lon = navicon_bridge.xy_to_latlon_default(decoded["pos_x"], decoded["pos_y"])
                else:
                    raise RuntimeError("navicon_bridge not available")
            except Exception:
                # Fallback to parametric converter
                lat, lon = convert_xy_to_lat_lon(decoded["pos_x"], decoded["pos_y"])

            # Identity lookup by cookie
            cookie = decoded.get("cookie", 0)
            cookie_hex = f"{cookie:08x}"
            ident = COOKIE_MAP.get(cookie)
            if ident:
                def _clean(s: str) -> str:
                    return s.replace("\r", " ").replace("\n", " ").strip() if s else ""
                cn = _clean(ident.get("cn", ""))
                first = _clean(ident.get("first_name", ""))
                last = _clean(ident.get("last_name", ""))
                aircraft = _clean(ident.get("aircraft", ""))
                parts = [p for p in (cn, first, last) if p]
                extra = f" | Aircraft: {aircraft}" if aircraft else ""
                identity_line = (" ".join(parts) + extra + f" [cookie {cookie_hex}]").strip()
                if not parts:
                    identity_line = f"unknown [cookie {cookie_hex}]"
            else:
                identity_line = f"unknown [cookie {cookie_hex}]"

            output = (
                f"[+] TELEMETRY PACKET DETECTED\n"
                f"    - Message Type: 0x{msg_type}\n"
                f"    - Counter (CN): {cn_decimal}\n"
                f"    - Identifier (ID): {id_decimal}\n"
                f"    - Full HEX: {hex_data}\n"
                f"    - Identity: {identity_line}\n"
                f"    - pos_x: {decoded['pos_x']:.1f}, pos_y: {decoded['pos_y']:.1f}\n"
                f"    - Lat/Lon: {lat:.5f}, {lon:.5f}\n"
                f"    - (Lon,Lat): {lon:.5f}, {lat:.5f}\n"
                f"    - Altitude: {decoded['altitude_m']:.2f} m ({decoded['altitude_ft']:.0f} ft)\n"
                f"    - Speed (GS): {decoded['speed_mps']:.2f} m/s ({decoded['speed_kt']:.1f} kt)\n"
                f"    - Heading: {decoded['heading']:.1f}°\n"
                f"    - Vertical Velocity: {decoded['vario_mps']:.2f} m/s ({decoded['vario_kt']:.1f} kt)\n"
                f"    - G-Force: (incorrect) {decoded['g_force']:.2f} G\n"
                f"    - Accel: ({decoded['ax']:.2f}, {decoded['ay']:.2f}, {decoded['az']:.2f}), |a|={decoded['a_mag']:.2f} m/s^2\n"
                f"    - Tail u32: {decoded['tail']}"
            )
        else:
            output = (
                f"[+] TELEMETRY PACKET DETECTED\n"
                f"    - Message Type: 0x{msg_type}\n"
                f"    - Counter (CN): {cn_decimal}\n"
                f"    - Identifier (ID): {id_decimal}\n"
                f"    - Full HEX: {hex_data}"
            )
        return output
    except Exception as e:
        return f"[!] Error parsing Telemetry packet: {e}\n    HEX: {hex_data}"


def parse_ack_packet(hex_data: str) -> str:
    """Decodes the short acknowledgement packets."""
    try:
        msg_type = hex_data[0:8]
        ack_cn_bytes = bytes.fromhex(hex_data[8:12])
        ack_cn_decimal = int.from_bytes(ack_cn_bytes, "little")
        payload_hex = hex_data[12:]

        output = (
            f"[<] ACKNOWLEDGEMENT PACKET DETECTED\n"
            f"    - Message Type: 0x{msg_type}\n"
            f"    - Acknowledged CN: {ack_cn_decimal}\n"
            f"    - Full HEX: {hex_data}\n"
            f"    - Payload HEX: {payload_hex}"
        )
        return output
    except Exception as e:
        return f"[!] Error parsing ACK packet: {e}\n    HEX: {hex_data}"


def persist_identity_map():
    """Persist the current identity mappings to JSON."""
    try:
        by_cookie = {}
        for ck, ident in COOKIE_MAP.items():
            by_cookie[f"{ck:08x}"] = ident
        by_entity = {str(eid): f"{COOKIE_MAP.get(ck, {}).get('cookie', ck):08x}" for eid, ck in ENTITY_TO_COOKIE.items()}
        data = {
            "generated_at": datetime.datetime.now().isoformat(),
            "by_cookie": by_cookie,
            "by_entity": by_entity,
        }
        tmp_path = IDENTITY_JSON_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as jf:
            json.dump(data, jf, ensure_ascii=False, indent=2)
        os.replace(tmp_path, IDENTITY_JSON_FILE)
    except Exception:
        # Keep runtime resilient; don't crash on IO issues
        pass

def parse_identity_packet(hex_data: str) -> str:
    """Decode 0x3f00/3f01 identity/config packet and update mappings."""
    try:
        b = bytes.fromhex(hex_data)
        if len(b) < 20:
            return f"[!] Identity packet too short (len={len(b)})\n    HEX: {hex_data}"
        
        msg_type = b[0:2].hex()
        if msg_type not in ("3f00", "3f01"):
            return f"[!] Not an identity packet (type=0x{msg_type})\n    HEX: {hex_data}"

        seq = int.from_bytes(b[2:4], "little")
        entity_id = int.from_bytes(b[4:8], "little")
        cookie = int.from_bytes(b[8:12], "little")

        # --- New Parsing Logic ---
        
        offset = 12
        # Skip initial padding/reserved bytes
        while offset < len(b) and b[offset] == 0x00:
            offset += 1
        
        def find_next_string(start_offset):
            """Scans for the next length-prefixed ASCII string."""
            i = start_offset
            while i < len(b):
                length = b[i]
                # Plausible length for a name/field? (e.g., 2-32 chars)
                if 2 <= length <= 32 and (i + 1 + length) <= len(b):
                    val_bytes = b[i+1 : i+1+length]
                    try:
                        # Check if all bytes are printable ASCII
                        if all(32 <= c < 127 for c in val_bytes):
                            val = val_bytes.decode('ascii').strip()
                            # Return the found string and the offset AFTER this field
                            return val, i + 1 + length
                    except UnicodeDecodeError:
                        pass # Not a valid string, continue scanning
                i += 1
            return "", len(b) # Not found

        # Find fields in their expected order
        first_name, offset = find_next_string(offset)
        last_name, offset = find_next_string(offset)
        country, offset = find_next_string(offset)
        registration, offset = find_next_string(offset)
        cn, offset = find_next_string(offset)

        # The aircraft name is often one of the last fields in the packet
        aircraft, _ = find_next_string(offset) # Search the rest of the packet for it
        if not aircraft:
             # Fallback for aircraft if it's not the next immediate string
             temp_offset = max(offset, len(b) - 64) # Scan last 64 bytes
             aircraft, _ = find_next_string(temp_offset)

        # --- End New Logic ---

        # Update mappings (preserve existing non-empty fields)
        existing = COOKIE_MAP.get(cookie, {})
        COOKIE_MAP[cookie] = {
            "cookie": cookie,
            "entity_id": entity_id,
            "first_name": first_name or existing.get("first_name", ""),
            "last_name": last_name or existing.get("last_name", ""),
            "cn": cn or existing.get("cn", ""),
            "registration": registration or existing.get("registration", ""),
            "country": country or existing.get("country", ""),
            "aircraft": aircraft or existing.get("aircraft", ""),
            "seen_at": datetime.datetime.now().isoformat(),
        }
        ENTITY_TO_COOKIE[entity_id] = cookie
        persist_identity_map()

        return (
            f"[+] IDENTITY PACKET DETECTED\n"
            f"    - Message Type: 0x{msg_type}\n"
            f"    - Seq: {seq}\n"
            f"    - Entity ID: {entity_id}\n"
            f"    - Cookie: {cookie:08x}\n"
            f"    - Full HEX: {hex_data}\n"
            f"    - CN: {cn}\n"
            f"    - Name: {first_name} {last_name}\n"
            f"    - Registration: {registration}\n"
            f"    - Country: {country}\n"
            f"    - Aircraft: {aircraft}"
        )
    except Exception as e:
        return f"[!] Error parsing identity packet: {e}\n    HEX: {hex_data}"

def packet_handler(packet):
    """Main handler function for processing each captured packet."""
    if UDP not in packet or packet[UDP].dport != SNIFF_PORT:
        return

    payload = packet[UDP].payload.original
    hex_data = payload.hex()

    timestamp = datetime.datetime.now().strftime("%Y-m-d %H:%M:%S.%f")[:-3]
    parsed_output = ""

    if hex_data.startswith(("3d00", "3900", "3100")):
        # If it's a 3d00 packet, write the hex to the dedicated log
        if hex_data.startswith("3d00") and HEX_LOG_FILE:
            HEX_LOG_FILE.write(hex_data + "\n")
            HEX_LOG_FILE.flush()
        parsed_output = parse_telemetry_packet(hex_data)
    elif hex_data.startswith(("3f00", "3f01")):
        parsed_output = parse_identity_packet(hex_data)
    elif hex_data.startswith("8006"):
        parsed_output = parse_ack_packet(hex_data)
    else:
        parsed_output = f"[?] UNKNOWN PACKET TYPE\n    - Full HEX: {hex_data}"

    final_output = f"[{timestamp}] {parsed_output}"
    print(final_output)
    print("-" * 60)

    # Write to the main, detailed log file
    if LOG_FILE:
        LOG_FILE.write(final_output + "\n")
        LOG_FILE.flush()


def main():
    """Sets up logging and starts the packet sniffer."""
    global LOG_FILE, HEX_LOG_FILE
    log_filename = f"udp_sniff_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    hex_log_filename = f"hex_log_3d00_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    try:
        # Start fresh identity map each run
        try:
            if os.path.exists(IDENTITY_JSON_FILE):
                os.remove(IDENTITY_JSON_FILE)
        except Exception:
            pass

        # Use a single 'with' block to manage both files
        with open(log_filename, "w") as f, open(hex_log_filename, "w") as hf:
            LOG_FILE = f
            HEX_LOG_FILE = hf
            print(f"[*] Starting UDP packet sniffer on port {SNIFF_PORT}")
            print(f"[*] Logging detailed output to: {log_filename}")
            print(f"[*] Logging 3d00 HEX strings to: {hex_log_filename}")
            print("=" * 60)

            bpf_filter = f"udp and port {SNIFF_PORT}"
            sniff(filter=bpf_filter, prn=packet_handler, store=0)

    except PermissionError:
        print("\n[!] PERMISSION ERROR: Please run this script with administrator/root privileges.")
    except Exception as e:
        print(f"\n[!] An error occurred: {e}")


if __name__ == "__main__":
    main()