#!/usr/bin/env python3
import datetime
import math
import struct
from scapy.all import sniff, UDP
from aa3_converter import convert_xy_to_lat_lon
import os
import json
try:
    import requests
except ImportError:
    requests = None
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
HEX_LOG_3F_FILE = None
HEX_LOG_8006_FILE = None

# Identity mapping persistence
IDENTITY_JSON_FILE = "identity_map.json"
COOKIE_MAP = {}          # cookie (int) -> identity dict
ENTITY_TO_COOKIE = {}    # entity_id (int) -> cookie (int)



# Flask telemetry forwarding configuration
DEFAULT_FLASK_ENDPOINT = "http://127.0.0.1:5000/api/position"
FLASK_ENDPOINT = (os.getenv("FLASK_ENDPOINT", DEFAULT_FLASK_ENDPOINT) or "").strip()
try:
    FLASK_TIMEOUT = float(os.getenv("FLASK_TIMEOUT", "0.3"))
except ValueError:
    FLASK_TIMEOUT = 0.3
REQUEST_SESSION = None
FLASK_POST_FAILURES = 0


# ------------------------
# Flight Plan (FPL) Reassembly State
# ------------------------
FPL_STATE = {
    "task": None,                  # Parsed task dict
    "disabled": {
        "total": None,            # total IDs expected
        "ids": [],                # ordered list of disabled airspace IDs
        "seen": 0,                # count seen so far
        "chunks": {},             # optional: seq -> list[int]
        "seen_seqs": set(),       # set[int] of processed chunk seqs
    },
    "settings": None,             # Parsed settings dict
    "written": False,             # whether an .fpl file has been written this run
}



def send_position_to_flask(payload: dict) -> None:
    """Send latest telemetry to the configured Flask endpoint."""
    global REQUEST_SESSION, FLASK_POST_FAILURES
    if not FLASK_ENDPOINT:
        return
    if requests is None:
        if FLASK_POST_FAILURES == 0:
            msg = "[!] requests library is not available; skipping Flask forwarding."
            print(msg)
            if LOG_FILE:
                LOG_FILE.write(msg + "\n")
                LOG_FILE.flush()
        FLASK_POST_FAILURES += 1
        return

    glider_id = payload.get("id")
    if glider_id is None:
        return

    def _coerce_float(value):
        try:
            value_f = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value_f):
            return None
        return value_f

    lat_f = _coerce_float(payload.get("lat"))
    lon_f = _coerce_float(payload.get("lon"))
    if lat_f is None or lon_f is None:
        return

    payload_to_send = dict(payload)
    payload_to_send["id"] = str(glider_id)
    payload_to_send["lat"] = lat_f
    payload_to_send["lon"] = lon_f

    alt_f = _coerce_float(payload.get("alt_m", payload.get("altitude_m")))
    if alt_f is not None:
        payload_to_send["alt_m"] = alt_f
    else:
        payload_to_send.pop("alt_m", None)
    payload_to_send.pop("altitude_m", None)

    heading_f = _coerce_float(payload.get("heading_deg", payload.get("heading")))
    if heading_f is not None:
        payload_to_send["heading_deg"] = heading_f
    else:
        payload_to_send.pop("heading_deg", None)
    payload_to_send.pop("heading", None)

    speed_f = _coerce_float(payload.get("speed_mps"))
    if speed_f is not None:
        payload_to_send["speed_mps"] = speed_f

    vario_f = _coerce_float(payload.get("vario_mps"))
    if vario_f is not None:
        payload_to_send["vario_mps"] = vario_f

    payload_to_send.setdefault("timestamp", datetime.datetime.utcnow().isoformat() + "Z")

    try:
        if REQUEST_SESSION is None:
            REQUEST_SESSION = requests.Session()
        REQUEST_SESSION.post(FLASK_ENDPOINT, json=payload_to_send, timeout=FLASK_TIMEOUT)
    except Exception as exc:
        FLASK_POST_FAILURES += 1
        if FLASK_POST_FAILURES < 5 or FLASK_POST_FAILURES % 25 == 0:
            msg = f"[!] Failed to POST telemetry to Flask endpoint ({FLASK_ENDPOINT}): {exc}"
            print(msg)
            if LOG_FILE:
                LOG_FILE.write(msg + "\n")
                LOG_FILE.flush()

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
            
            # Extract individual identity fields
            def _clean(s: str) -> str:
                return s.replace("\r", " ").replace("\n", " ").strip() if s else ""
            
            if ident:
                id_cn = _clean(ident.get("cn", ""))
                id_fname = _clean(ident.get("first_name", ""))
                id_lname = _clean(ident.get("last_name", ""))
                id_aircraft = _clean(ident.get("aircraft", ""))
                id_reg = _clean(ident.get("registration", ""))
                id_country = _clean(ident.get("country", ""))
                
                # Build legacy identity_line for backward compatibility
                parts = [p for p in (id_cn, id_fname, id_lname) if p]
                extra = f" | Aircraft: {id_aircraft}" if id_aircraft else ""
                identity_line = (" ".join(parts) + extra + f" [cookie {cookie_hex}]").strip()
                if not parts:
                    identity_line = f"unknown [cookie {cookie_hex}]"
            else:
                id_cn = ""
                id_fname = ""
                id_lname = ""
                id_aircraft = ""
                id_reg = ""
                id_country = ""
                identity_line = f"unknown [cookie {cookie_hex}]"

            send_position_to_flask({
                "id": id_decimal,
                "cn": cn_decimal,
                "cookie": cookie,
                "identity": identity_line,
                "id_aircraft": id_aircraft,
                "id_cn": id_cn,
                "id_reg": id_reg,
                "id_fname": id_fname,
                "id_lname": id_lname,
                "id_country": id_country,
                "lat": lat,
                "lon": lon,
                "altitude_m": decoded['altitude_m'],
                "speed_mps": decoded['speed_mps'],
                "heading_deg": decoded['heading'],
                "vario_mps": decoded['vario_mps'],
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "aircraft": id_aircraft,
            })

            output = (
                f"[+] TELEMETRY PACKET DETECTED\n"
                f"    - Message Type: 0x{msg_type}\n"
                f"    - Counter (CN): {cn_decimal}\n"
                f"    - Identifier (ID): {id_decimal}\n"
                f"    - Full HEX: {hex_data}\n"
                f"    - Identity: {identity_line}\n"
                f"    - id_aircraft: {id_aircraft}\n"
                f"    - id_cn: {id_cn}\n"
                f"    - id_reg: {id_reg}\n"
                f"    - id_fname: {id_fname}\n"
                f"    - id_lname: {id_lname}\n"
                f"    - id_country: {id_country}\n"
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
    """Decode 0x3f00/0x3f01 identity/config packet and update mappings."""
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

        # --- New, More Robust Parsing Logic ---

        def find_next_string(start_offset, min_len=1, max_len=64):
            """Scans for the next length-prefixed ASCII string."""
            i = start_offset
            while i < len(b):
                # Ensure there's at least one byte for length and potential content
                if i + 1 >= len(b):
                    break
                length = b[i]
                if min_len <= length <= max_len and (i + 1 + length) <= len(b):
                    val_bytes = b[i+1 : i+1+length]
                    try:
                        # Check if all bytes are printable ASCII
                        if all(32 <= c < 127 for c in val_bytes):
                            val = val_bytes.decode('ascii').strip()
                            return val, i + 1 + length
                    except UnicodeDecodeError:
                        pass # Not a valid string, continue scanning
                i += 1
            return None, len(b)

        def is_competition_id(s: str) -> bool:
            """Check if a string is the long hex Competition ID."""
            if not s or len(s) < 32:
                return False
            # ID is composed of hex characters and sometimes spaces
            return all(c in '0123456789abcdefABCDEF ' for c in s)

        # 1. Scan the entire packet to find all plausible strings, ignoring the Comp ID
        all_strings = []
        offset = 12
        while offset < len(b):
            # Start scan after header and any zero padding
            if b[offset] == 0x00:
                offset += 1
                continue
            
            val, next_offset = find_next_string(offset)
            if val:
                if not is_competition_id(val):
                    all_strings.append(val)
                offset = next_offset
            else:
                break # No more strings found

        # Filter out spurious single-character strings to prevent field shifts
        all_strings = [s for s in all_strings if len(s) > 1]

        # 2. Assign fields based on the collected strings
        first_name, last_name, country, registration, cn, aircraft = "", "", "", "", "", ""
        
        if not all_strings:
            # Packet contained no usable strings, do nothing.
            pass
        else:
            # The last valid string in the packet is the aircraft name
            aircraft = all_strings.pop()

            # Assign the remaining fields in their expected order
            # This handles cases where some fields might be missing
            if len(all_strings) > 0:
                fields_in_order = [None] * 5 # first_name, last_name, country, reg, cn
                for i in range(min(len(all_strings), 5)):
                    fields_in_order[i] = all_strings[i]
                
                first_name, last_name, country, registration, cn = fields_in_order
                
                # Clean up None values to empty strings
                first_name = first_name or ""
                last_name = last_name or ""
                country = country or ""
                registration = registration or ""
                cn = cn or ""

        # --- End New Logic ---

        # Update mappings (preserve existing non-empty fields)
        existing = COOKIE_MAP.get(cookie, {})
        COOKIE_MAP[cookie] = {
            "cookie": cookie, "entity_id": entity_id,
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
        # It's helpful to log the exception for debugging
        import traceback
        traceback.print_exc()
        return f"[!] Error parsing identity packet: {e}\n    HEX: {hex_data}"


# ========================
# FPL decoding helpers
# ========================
def _read_u16_le(b: bytes, off: int) -> tuple[int, int]:
    if off + 2 > len(b):
        raise ValueError("u16 out of range")
    return int.from_bytes(b[off:off+2], "little"), off + 2


def _read_u32_le(b: bytes, off: int) -> tuple[int, int]:
    if off + 4 > len(b):
        raise ValueError("u32 out of range")
    return int.from_bytes(b[off:off+4], "little"), off + 4


def _read_f32_le(b: bytes, off: int) -> tuple[float, int]:
    if off + 4 > len(b):
        raise ValueError("f32 out of range")
    return struct.unpack_from("<f", b, off)[0], off + 4


def _read_f64_le(b: bytes, off: int) -> tuple[float, int]:
    if off + 8 > len(b):
        raise ValueError("f64 out of range")
    return struct.unpack_from("<d", b, off)[0], off + 8


def _read_lp_ascii(b: bytes, off: int, min_len: int = 0, max_len: int = 255) -> tuple[str, int]:
    if off >= len(b):
        raise ValueError("lp string out of range (len byte)")
    ln = b[off]
    if ln < min_len or ln > max_len or off + 1 + ln > len(b):
        raise ValueError("lp string invalid length")
    s = b[off+1:off+1+ln]
    # ensure printable ascii
    if not all(32 <= c < 127 for c in s):
        raise ValueError("lp string non-ascii")
    return s.decode("ascii"), off + 1 + ln


def _find_first_lp_ascii(b: bytes, start: int = 0, window: int = 64) -> tuple[str, int]:
    """Scan forward for first plausible length-prefixed ASCII string.
    Returns (string, offset_after_string)."""
    i = max(0, start)
    end = min(len(b), i + window)
    while i < end:
        try:
            s, j = _read_lp_ascii(b, i, min_len=1, max_len=64)
            return s, j
        except Exception:
            i += 1
    # fallback: try entire buffer
    i = 0
    while i < len(b):
        try:
            s, j = _read_lp_ascii(b, i, min_len=1, max_len=64)
            return s, j
        except Exception:
            i += 1
    raise ValueError("no lp ascii string found")


def parse_fpl_task_packet(hex_data: str) -> str:
    """Parse 0x1f00 core task packet: Landscape, Count, and Turnpoints."""
    b = bytes.fromhex(hex_data)
    if len(b) < 4:
        return f"[!] TASK packet too short (len={len(b)})\n    HEX: {hex_data}"
    msg_type = b[0:2].hex()
    if msg_type != "1f00":
        return f"[!] Not a TASK packet (type=0x{msg_type})"

    # Deterministic: assume 2-byte type + 2-byte seq, then LP-ASCII Landscape
    off = 4 if len(b) >= 4 else 2
    try:
        # Primary attempt
        landscape, off = _read_lp_ascii(b, off, min_len=1, max_len=32)
        count, off = _read_u32_le(b, off)
        # Validate
        if not (1 <= count <= 64):
            raise ValueError(f"implausible turnpoint count: {count}")
    except Exception:
        # Fallback: look for specific AA3 marker (03 'A''A''3')
        marker = b"\x03AA3"
        idx = b.find(marker)
        if idx == -1:
            return "[!] Error parsing TASK (1f00): could not locate Landscape string"
        landscape = "AA3"
        off = idx + 1 + 3
        try:
            count, off = _read_u32_le(b, off)
            if not (1 <= count <= 64):
                return f"[!] Error parsing TASK (1f00): invalid Count={count}"
        except Exception as e:
            return f"[!] Error parsing TASK (1f00): {e}"

    try:
        tps = []
        for i in range(count):
            name, off = _read_lp_ascii(b, off, min_len=1, max_len=64)
            # X (f64), Y (f32), Radius (u32), Angle (u32), Alt (f32)
            x, off = _read_f64_le(b, off)
            y, off = _read_f32_le(b, off)
            radius, off = _read_u32_le(b, off)
            angle, off = _read_u32_le(b, off)
            alt, off = _read_f32_le(b, off)
            tps.append({
                "name": name,
                "x": x,
                "y": y,
                "radius": radius,
                "angle": angle,
                "altitude": alt,
            })
    except Exception as e:
        return f"[!] Error parsing TASK (1f00): {e}"

    FPL_STATE["task"] = {
        "landscape": landscape,
        "count": len(tps),
        "turnpoints": tps,
    }
    _attempt_write_fpl()
    return (f"[+] FPL TASK parsed: Landscape={landscape}, Turnpoints={len(tps)}")


def parse_disabled_list_packet(hex_data: str) -> str:
    """Parse 0x0700 (first) and 0x0f00 (continuation) chunked DisabledAirspaces list."""
    b = bytes.fromhex(hex_data)
    if len(b) < 4:
        return f"[!] DISABLED packet too short (len={len(b)})"
    msg_type = b[0:2].hex()
    if msg_type not in ("0700", "0f00"):
        return f"[!] Not a DISABLED packet (type=0x{msg_type})"

    # 2-byte seq at [2:4]; payload starts at 4
    seq = int.from_bytes(b[2:4], "little")
    if seq in FPL_STATE["disabled"]["seen_seqs"]:
        tot = FPL_STATE["disabled"]["total"]
        seen = len(FPL_STATE["disabled"]["ids"])
        return f"[=] FPL DisabledAirspaces: duplicate chunk seq={seq} ignored ({seen}{('/'+str(tot)) if tot else ''})"
    FPL_STATE["disabled"]["seen_seqs"].add(seq)

    off = 4
    total = FPL_STATE["disabled"].get("total")
    # First 0700 chunk carries total count (u32)
    if msg_type == "0700" and total is None and off + 4 <= len(b):
        total, off = _read_u32_le(b, off)
        FPL_STATE["disabled"]["total"] = total

    # Remaining are u16 IDs
    ids = []
    remaining_items = None
    if FPL_STATE["disabled"].get("total") is not None:
        remaining_items = max(0, FPL_STATE["disabled"]["total"] - len(FPL_STATE["disabled"]["ids"]))
    while off + 2 <= len(b):
        if remaining_items is not None and remaining_items <= 0:
            break
        v, off = _read_u16_le(b, off)
        ids.append(v)
        if remaining_items is not None:
            remaining_items -= 1

    # Append while preserving order and preventing duplicates
    existing_set = set(FPL_STATE["disabled"]["ids"])
    for v in ids:
        if v not in existing_set:
            FPL_STATE["disabled"]["ids"].append(v)
            existing_set.add(v)
    FPL_STATE["disabled"]["seen"] = len(FPL_STATE["disabled"]["ids"])

    _attempt_write_fpl()
    tot = FPL_STATE["disabled"]["total"]
    seen = FPL_STATE["disabled"]["seen"]
    return f"[+] FPL DisabledAirspaces: {seen}{('/'+str(tot)) if tot else ''} IDs collected"


def parse_settings_packet(hex_data: str) -> str:
    """Parse 0x2f00: bundle of Plane, Weather, GameOptions, Description (strings are LP-ASCII)."""
    b = bytes.fromhex(hex_data)
    if len(b) < 4:
        return f"[!] SETTINGS packet too short (len={len(b)})"
    msg_type = b[0:2].hex()
    if msg_type != "2f00":
        return f"[!] Not a SETTINGS packet (type=0x{msg_type})"

    # Collect all plausible LP strings in the payload region
    strings = []
    i = 2
    try:
        _ = int.from_bytes(b[2:4], "little")
        i = 4
    except Exception:
        i = 2

    j = i
    while j < len(b):
        try:
            s, j2 = _read_lp_ascii(b, j, min_len=1, max_len=80)
            strings.append(s)
            j = j2
        except Exception:
            j += 1

    # Heuristics to pick fields
    description = ""
    plane = ""
    weather_zone = ""
    # choose the longest string as description
    if strings:
        description = max(strings, key=len)
    # plane often contains a dash or the word meter/MS/etc
    for s in strings:
        if ("meter" in s.lower()) or ("-" in s) or ("ms" in s.lower()) or ("js" in s.lower()) or ("as" in s.lower()):
            plane = s
            break
    # weather zone: prefer exact 'Base' if present; else shortest printable
    # direct signature 04 42 61 73 65 (len=4, 'Base')
    sig_base = bytes.fromhex("0442617365")
    if sig_base in b:
        weather_zone = "Base"
    else:
        for s in strings:
            if s.strip() == "Base":
                weather_zone = "Base"
                break
        if not weather_zone:
            for s in strings:
                if len(s) <= 8 and s.isascii() and s.isprintable():
                    weather_zone = s
                    break

    # Some numeric options (best-effort)
    start_height = None
    # look for bytes of 1500.0f -> 00 80 BB 44
    sig = bytes.fromhex("0080bb44")
    if sig in b:
        start_height = 1500

    FPL_STATE["settings"] = {
        "description": description,
        "plane": plane,
        "weather_zone": weather_zone,
        "start_height": start_height,
    }
    _attempt_write_fpl()
    return f"[+] FPL Settings parsed: plane='{plane or '?'}', weather='{weather_zone or '?'}', desc_len={len(description)}"


def _attempt_write_fpl():
    """Write a timestamped .fpl if all main sections are present and not yet written."""
    if FPL_STATE.get("written"):
        return
    task = FPL_STATE.get("task")
    settings = FPL_STATE.get("settings")
    disabled = FPL_STATE.get("disabled", {})
    total = disabled.get("total")
    ids = disabled.get("ids", [])

    if not task:
        return
    # Require a plausible task with at least one turnpoint
    if task.get("count", 0) <= 0:
        return
    # If total is known, require we have collected at least total IDs; else accept what we have
    if total is not None and len(ids) < total:
        return
    if not settings:
        return

    # Compose .fpl content (best-effort keys based on analysis)
    lines = []
    lines.append("[Task]")
    lines.append(f"Landscape={task['landscape']}")
    lines.append(f"Count={task['count']}")
    for idx, tp in enumerate(task["turnpoints"]):
        lines.append(f"TPName{idx}={tp['name']}")
        lines.append(f"TPPosX{idx}={tp['x']:.6f}")
        lines.append(f"TPPosY{idx}={tp['y']:.6f}")
        lines.append(f"TPRadius{idx}={tp['radius']}")
        lines.append(f"TPAngle{idx}={tp['angle']}")
        lines.append(f"TPAltitude{idx}={tp['altitude']:.2f}")

    # Optional: convert to lat/lon as extra fields (helpful for inspection)
    try:
        for idx, tp in enumerate(task["turnpoints"]):
            try:
                if navicon_bridge is not None:
                    lat, lon = navicon_bridge.xy_to_latlon_default(tp['x'], tp['y'])
                else:
                    lat, lon = convert_xy_to_lat_lon(tp['x'], tp['y'])
                lines.append(f"TPLat{idx}={lat:.6f}")
                lines.append(f"TPLon{idx}={lon:.6f}")
            except Exception:
                pass
    except Exception:
        pass

    # Write DisabledAirspaces under [Task] as a single CSV line
    if ids:
        # If total known, trim to total just in case
        if total is not None and len(ids) > total:
            ids = ids[:total]
        ids_str = ",".join(str(v) for v in ids)
        lines.append(f"DisabledAirspaces={ids_str}")

    if settings:
        lines.append("")
        lines.append("[Plane]")
        if settings.get("plane"):
            # Use 'Class=' label to match Condor .fpl convention
            lines.append(f"Class={settings['plane']}")

        lines.append("")
        lines.append("[Weather]")
        if settings.get("weather_zone"):
            # Minimal weather: declare one zone and name it
            lines.append("WZCount=1")
            lines.append("")
            lines.append("[WeatherZone0]")
            lines.append(f"Name={settings['weather_zone']}")

        lines.append("")
        lines.append("[GameOptions]")
        if settings.get("start_height") is not None:
            lines.append(f"StartHeight={settings['start_height']}")

        lines.append("")
        lines.append("[Description]")
        if settings.get("description"):
            # Ensure single-line safety
            desc = settings["description"].replace("\r", " ").replace("\n", " ")
            lines.append(f"Text={desc}")

    content = "\n".join(lines) + "\n"
    fname = f"udp_fpl_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.fpl"
    try:
        abspath = os.path.abspath(fname)
        with open(abspath, "w", encoding="utf-8") as f:
            f.write(content)
        FPL_STATE["written"] = True
        msg = f"[*] Wrote reconstructed FPL to {abspath}"
        print(msg)
        if LOG_FILE:
            LOG_FILE.write(msg + "\n")
            LOG_FILE.flush()
    except Exception as e:
        print(f"[!] Failed to write FPL: {e}")

def packet_handler(packet):
    """Main handler function for processing each captured packet."""
    if UDP not in packet:
        return

    udp = packet[UDP]
    if udp.dport == SNIFF_PORT:
        direction = "OUT"
    elif udp.sport == SNIFF_PORT:
        direction = "IN"
    else:
        return

    payload = udp.payload.original
    hex_data = payload.hex()

    timestamp = datetime.datetime.now().strftime("%Y-m-d %H:%M:%S.%f")[:-3]
    parsed_output = ""

    if hex_data.startswith(("3d00", "3900", "3100")):
        # If it's a 3d00 packet, write the hex to the dedicated log
        if hex_data.startswith("3d00") and HEX_LOG_FILE:
            HEX_LOG_FILE.write(hex_data + "\n")
            HEX_LOG_FILE.flush()
        parsed_output = parse_telemetry_packet(hex_data)
    elif hex_data.startswith("1f00"):
        parsed_output = parse_fpl_task_packet(hex_data)
    elif hex_data.startswith(("0700", "0f00")):
        parsed_output = parse_disabled_list_packet(hex_data)
    elif hex_data.startswith("2f00"):
        parsed_output = parse_settings_packet(hex_data)
    elif hex_data.startswith(("3f00", "3f01")):
        # Also write 3f00/3f01 packets to a dedicated combined hex log
        if HEX_LOG_3F_FILE:
            HEX_LOG_3F_FILE.write(hex_data + "\n")
            HEX_LOG_3F_FILE.flush()
        parsed_output = parse_identity_packet(hex_data)
    elif hex_data.startswith("8006"):
        parsed_output = parse_ack_packet(hex_data)
        # Write ACK packets' raw hex to a dedicated hex-only log
        if HEX_LOG_8006_FILE:
            HEX_LOG_8006_FILE.write(hex_data + "\n")
            HEX_LOG_8006_FILE.flush()
    else:
        parsed_output = f"[?] UNKNOWN PACKET TYPE\n    - Full HEX: {hex_data}"

    final_output = f"[{timestamp}] [{direction}] {parsed_output}"
    print(final_output)
    print("-" * 60)

    # Write to the main, detailed log file
    if LOG_FILE:
        LOG_FILE.write(final_output + "\n")
        LOG_FILE.flush()


def main():
    """Sets up logging and starts the packet sniffer."""
    global LOG_FILE, HEX_LOG_FILE, HEX_LOG_3F_FILE, HEX_LOG_8006_FILE
    log_filename = f"udp_sniff_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    hex_log_filename = f"hex_log_3d00_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    identity_hex_log_filename = f"hex_log_3f00_3f01_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    hex8006_log_filename = f"hex_log_8006_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    try:
        # Start fresh identity map each run
        try:
            if os.path.exists(IDENTITY_JSON_FILE):
                os.remove(IDENTITY_JSON_FILE)
        except Exception:
            pass

        # Use a single 'with' block to manage all files
        with open(log_filename, "w") as f, open(hex_log_filename, "w") as hf, open(identity_hex_log_filename, "w") as hf3f, open(hex8006_log_filename, "w") as hf8006:
            LOG_FILE = f
            HEX_LOG_FILE = hf
            HEX_LOG_3F_FILE = hf3f
            HEX_LOG_8006_FILE = hf8006
            print(f"[*] Starting UDP packet sniffer on port {SNIFF_PORT}")
            print(f"[*] Logging detailed output to: {log_filename}")
            print(f"[*] Logging 3d00 HEX strings to: {hex_log_filename}")
            print(f"[*] Logging 3f00/3f01 HEX strings to: {identity_hex_log_filename}")
            print(f"[*] Logging 8006 HEX strings to: {hex8006_log_filename}")
            print("=" * 60)

            bpf_filter = f"udp and port {SNIFF_PORT}"
            sniff(filter=bpf_filter, prn=packet_handler, store=0)

    except PermissionError:
        print("\n[!] PERMISSION ERROR: Please run this script with administrator/root privileges.")
    except Exception as e:
        print(f"\n[!] An error occurred: {e}")


if __name__ == "__main__":
    main()