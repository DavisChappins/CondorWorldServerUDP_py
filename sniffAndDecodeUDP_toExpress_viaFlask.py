#!/usr/bin/env python3
import datetime
import math
import struct
from scapy.all import sniff, UDP
import os
import json
import argparse
import sys
try:
    import requests
except ImportError:
    requests = None
try:
    import navicon_bridge  # Out-of-process 32-bit DLL bridge
except Exception:
    navicon_bridge = None
import threading

# The UDP port the game is using (will be set via CLI argument)
SNIFF_PORT = 56288
SERVER_NAME = ""
LANDSCAPE_TRN_PATH = None  # Will be set based on --landscape argument

# Standard gravity for G-force calculation
GRAVITY_MS2 = 9.80665

# Global file handlers for logging - DISABLED FOR PERFORMANCE

LOG_FILE = None
HEX_LOG_3F_FILE = None
HEX_LOG_8006_FILE = None

# Identity mapping persistence (will be prefixed with PID)
IDENTITY_JSON_FILE = "identity_map.json"
COOKIE_MAP = {}          # cookie (int) -> identity dict
ENTITY_TO_COOKIE = {}    # entity_id (int) -> cookie (int)



# Express.js telemetry forwarding configuration
DEFAULT_EXPRESS_ENDPOINT = "https://server.condormap.com/api/positions"
EXPRESS_ENDPOINT = (os.getenv("EXPRESS_ENDPOINT", DEFAULT_EXPRESS_ENDPOINT) or "").strip()
try:
    EXPRESS_TIMEOUT = float(os.getenv("EXPRESS_TIMEOUT", "0.3"))
except ValueError:
    EXPRESS_TIMEOUT = 0.3
REQUEST_SESSION = None
EXPRESS_POST_FAILURES = 0
EXPRESS_VERIFY_SSL = False  # Set to True if you have valid SSL certificate

# Remote server forwarding configuration (secondary/backup endpoint)
REMOTE_SERVER_ENDPOINT = ""  # Optional secondary endpoint
REMOTE_SESSION = None
REMOTE_POST_FAILURES = 0
REMOTE_VERIFY_SSL = False  # Set to True if you have valid SSL certificate

# Batch positions before sending (1Hz batching)
import time as time_module
POSITION_BATCH = {}  # cookie -> latest position dict
LAST_BATCH_SEND = 0
BATCH_INTERVAL = 0.9  # Send batch every 900ms (1.1Hz)
BATCH_LOCK = threading.Lock()
HTTP_WORKER_THREAD = None
HTTP_WORKER_RUNNING = False

# Performance monitoring
POSITIONS_QUEUED = 0
POSITIONS_SENT = 0
LAST_STATS_PRINT = 0
STATS_PRINT_INTERVAL = 5.0  # Print stats every 5 seconds

# Detailed timing stats (store last 100 samples)
TIMING_STATS = {
    "decode_3d00": [],
    "xy_to_latlon": [],
    "identity_lookup": [],
    "build_payload": [],
    "parse_identity": [],
    "parse_other": [],
    "packet_total": []
}
LAST_TIMING_PRINT = 0
TIMING_PRINT_INTERVAL = 10.0  # Print timing breakdown every 10 seconds
MAX_TIMING_SAMPLES = 100

# Coordinate conversion cache (reduces NaviCon DLL calls by ~95%)
COORD_CACHE = {}  # (x_rounded, y_rounded) -> (lat, lon)
COORD_CACHE_PRECISION = 10.0  # Round to nearest 10 meters
COORD_CACHE_HITS = 0
COORD_CACHE_MISSES = 0


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



def send_position_to_express(payload: dict) -> None:
    """Queue position for async sending to Express.js endpoint."""
    if not EXPRESS_ENDPOINT:
        return
    if requests is None:
        return

    cookie = payload.get("cookie")
    if cookie is None:
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
    payload_to_send["cookie"] = cookie
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
    
    # Add identity data for server-side deduplication
    identity = COOKIE_MAP.get(cookie, {})
    if identity:
        cn = identity.get("cn", "")
        registration = identity.get("registration", "")
        first_name = identity.get("first_name", "")
        last_name = identity.get("last_name", "")
        
        payload_to_send["cn"] = cn
        payload_to_send["registration"] = registration
        payload_to_send["first_name"] = first_name
        payload_to_send["last_name"] = last_name
        payload_to_send["country"] = identity.get("country", "")
        payload_to_send["aircraft"] = identity.get("aircraft", "")
        
        # Composite key for easy server-side deduplication
        if cn and registration:
            payload_to_send["cn_registration"] = f"{cn}_{registration}"
        elif registration:
            payload_to_send["cn_registration"] = registration
        elif cn:
            payload_to_send["cn_registration"] = cn
        else:
            payload_to_send["cn_registration"] = ""
        
        # Full player identifier: CN_Registration_FirstName_LastName
        id_parts = []
        if cn:
            id_parts.append(cn)
        if registration:
            id_parts.append(registration)
        if first_name:
            id_parts.append(first_name)
        if last_name:
            id_parts.append(last_name)
        
        payload_to_send["id_cn_registration_firstname_lastname"] = "_".join(id_parts) if id_parts else ""

    # DO NOT timestamp here - will be timestamped at send time for accuracy
    # payload_to_send.setdefault("timestamp", datetime.datetime.utcnow().isoformat() + "Z")

    # Store in batch (overwrites previous position for same cookie)
    global POSITIONS_QUEUED, POSITION_BATCH, LAST_BATCH_SEND, BATCH_LOCK
    
    with BATCH_LOCK:
        POSITION_BATCH[cookie] = payload_to_send
        POSITIONS_QUEUED += 1
        
        # Check if it's time to send the batch
        now = time_module.time()
        if now - LAST_BATCH_SEND >= BATCH_INTERVAL:
            flush_position_batch()
            LAST_BATCH_SEND = now


def flush_position_batch() -> None:
    """Send all batched positions to Express endpoint as an array."""
    global REQUEST_SESSION, EXPRESS_POST_FAILURES, POSITION_BATCH, SERVER_NAME, SNIFF_PORT
    global REMOTE_SESSION, REMOTE_POST_FAILURES, POSITIONS_SENT, LAST_STATS_PRINT
    
    # Must be called with BATCH_LOCK held
    if not POSITION_BATCH:
        return
    
    if requests is None:
        EXPRESS_POST_FAILURES += 1
        return
    
    # Convert batch dict to array
    positions_array = list(POSITION_BATCH.values())
    batch_size = len(positions_array)
    
    # Add timestamps NOW (at send time)
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"
    for pos in positions_array:
        pos["timestamp"] = timestamp
    
    # Clear batch before sending (so new positions can accumulate)
    POSITION_BATCH.clear()
    
    # Prepare custom headers
    headers = {
        "X-Server-Name": SERVER_NAME or "",
        "X-Port-Number": str(SNIFF_PORT)
    }
    
    # Send to Express endpoint
    send_start = time_module.time()
    try:
        if REQUEST_SESSION is None:
            REQUEST_SESSION = requests.Session()
            # Disable SSL warnings if verification is disabled
            if not EXPRESS_VERIFY_SSL:
                try:
                    import urllib3
                    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                except Exception:
                    pass
        
        REQUEST_SESSION.post(EXPRESS_ENDPOINT, json=positions_array, headers=headers, 
                           timeout=EXPRESS_TIMEOUT, verify=EXPRESS_VERIFY_SSL)
        send_duration = time_module.time() - send_start
        POSITIONS_SENT += batch_size
        
        # Print stats periodically
        now = time_module.time()
        if now - LAST_STATS_PRINT >= STATS_PRINT_INTERVAL:
            print(f"[STATS] Queued: {POSITIONS_QUEUED} | Sent: {POSITIONS_SENT} | Batch Size: {batch_size} | Last Send: {send_duration*1000:.1f}ms | Failures: {EXPRESS_POST_FAILURES}")
            LAST_STATS_PRINT = now
            
    except Exception as e:
        EXPRESS_POST_FAILURES += 1
        print(f"[!] Express POST failed: {e} (failures: {EXPRESS_POST_FAILURES})")
    
    # Send to secondary/backup remote server (if configured)
    if REMOTE_SERVER_ENDPOINT:
        try:
            if REMOTE_SESSION is None:
                REMOTE_SESSION = requests.Session()
            REMOTE_SESSION.post(REMOTE_SERVER_ENDPOINT, json=positions_array, headers=headers, 
                              timeout=EXPRESS_TIMEOUT, verify=REMOTE_VERIFY_SSL)
        except Exception as e:
            REMOTE_POST_FAILURES += 1
            if REMOTE_POST_FAILURES <= 3:
                print(f"[!] Remote backup POST failed: {e}")


def http_worker_thread() -> None:
    """Background thread that periodically flushes position batches."""
    global HTTP_WORKER_RUNNING, LAST_BATCH_SEND, BATCH_LOCK
    
    if requests is None:
        print("[!] ERROR: requests module not available, HTTP worker cannot start")
        return
    
    print(f"[+] HTTP worker thread started")
    print(f"[+] Primary endpoint: {EXPRESS_ENDPOINT}")
    if REMOTE_SERVER_ENDPOINT:
        print(f"[+] Backup endpoint: {REMOTE_SERVER_ENDPOINT}")
    print(f"[+] Batch interval: {BATCH_INTERVAL*1000:.0f}ms (sending latest position per glider)")
    
    while HTTP_WORKER_RUNNING:
        try:
            time_module.sleep(0.1)  # Check every 100ms
            
            now = time_module.time()
            if now - LAST_BATCH_SEND >= BATCH_INTERVAL:
                with BATCH_LOCK:
                    flush_position_batch()
                    LAST_BATCH_SEND = now
                    
        except Exception as e:
            print(f"[!] HTTP worker error: {e}")
            pass

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
    global TIMING_STATS
    try:
        msg_type = hex_data[0:4]
        cn_bytes = bytes.fromhex(hex_data[4:8])
        cn_decimal = int.from_bytes(cn_bytes, "little")
        id_bytes = bytes.fromhex(hex_data[8:16])
        id_decimal = int.from_bytes(id_bytes, "little")
        payload_hex = hex_data[16:]

        if msg_type == "3d00":
            t_start = time_module.time()
            decoded = decode_3d00_payload(payload_hex)
            t_decode = time_module.time() - t_start
            TIMING_STATS["decode_3d00"].append(t_decode)
            if len(TIMING_STATS["decode_3d00"]) > MAX_TIMING_SAMPLES:
                TIMING_STATS["decode_3d00"].pop(0)
            # Require NaviCon.dll bridge for coordinate conversion
            if navicon_bridge is None:
                raise RuntimeError("navicon_bridge is required but not available. Ensure navicon_bridge.py is properly configured.")
            
            # Use the landscape-specific TRN file with caching
            global COORD_CACHE, COORD_CACHE_HITS, COORD_CACHE_MISSES
            t_start = time_module.time()
            
            # Round coordinates to cache precision (10m grid)
            x_rounded = round(decoded["pos_x"] / COORD_CACHE_PRECISION) * COORD_CACHE_PRECISION
            y_rounded = round(decoded["pos_y"] / COORD_CACHE_PRECISION) * COORD_CACHE_PRECISION
            cache_key = (x_rounded, y_rounded)
            
            # Check cache first
            if cache_key in COORD_CACHE:
                lat, lon = COORD_CACHE[cache_key]
                COORD_CACHE_HITS += 1
            else:
                # Cache miss - call DLL
                if LANDSCAPE_TRN_PATH:
                    lat, lon = navicon_bridge.xy_to_latlon_trn(LANDSCAPE_TRN_PATH, decoded["pos_x"], decoded["pos_y"])
                else:
                    lat, lon = navicon_bridge.xy_to_latlon_default(decoded["pos_x"], decoded["pos_y"])
                COORD_CACHE[cache_key] = (lat, lon)
                COORD_CACHE_MISSES += 1
                
                # Limit cache size to prevent memory bloat
                if len(COORD_CACHE) > 10000:
                    # Remove oldest 20% of entries
                    keys_to_remove = list(COORD_CACHE.keys())[:2000]
                    for k in keys_to_remove:
                        del COORD_CACHE[k]
            
            t_latlon = time_module.time() - t_start
            TIMING_STATS["xy_to_latlon"].append(t_latlon)
            if len(TIMING_STATS["xy_to_latlon"]) > MAX_TIMING_SAMPLES:
                TIMING_STATS["xy_to_latlon"].pop(0)

            # Identity lookup by cookie
            t_start = time_module.time()
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
            
            t_identity = time_module.time() - t_start
            TIMING_STATS["identity_lookup"].append(t_identity)
            if len(TIMING_STATS["identity_lookup"]) > MAX_TIMING_SAMPLES:
                TIMING_STATS["identity_lookup"].pop(0)

            t_start = time_module.time()
            send_position_to_express({
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
            t_build = time_module.time() - t_start
            TIMING_STATS["build_payload"].append(t_build)
            if len(TIMING_STATS["build_payload"]) > MAX_TIMING_SAMPLES:
                TIMING_STATS["build_payload"].pop(0)

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


# Track last identity persist time to throttle writes
LAST_IDENTITY_PERSIST = 0
IDENTITY_PERSIST_INTERVAL = 5.0  # Only write every 5 seconds

def persist_identity_map():
    """Persist the current identity mappings to JSON (throttled for performance)."""
    global LAST_IDENTITY_PERSIST
    
    # Throttle: only write every 5 seconds
    now = time_module.time()
    if now - LAST_IDENTITY_PERSIST < IDENTITY_PERSIST_INTERVAL:
        return
    
    LAST_IDENTITY_PERSIST = now
    
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
        # Write directly without temp file for performance
        with open(IDENTITY_JSON_FILE, "w", encoding="utf-8") as jf:
            json.dump(data, jf, ensure_ascii=False, indent=2)
    except Exception:
        # Keep runtime resilient; don't crash on IO issues
        pass
def parse_identity_packet(hex_data: str) -> str:
    """Decode 0x3f00/0x3f01 identity/config packet and update mappings."""
    global TIMING_STATS
    t_start = time_module.time()
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

        # Skip entity_id 20002 (chat messages, not players)
        if entity_id == 20002:
            return f"[=] IDENTITY PACKET SKIPPED (entity_id=20002 is chat message)\n    - Cookie: {cookie:08x}\n    - Full HEX: {hex_data}"

        # --- FIXED-OFFSET PARSING (entity_id 20001 = full player data, entity_id 1 = abbreviated) ---
        
        def read_string_at_offset(offset):
            """Read length-prefixed ASCII string at fixed offset."""
            if offset >= len(b):
                return ""
            length = b[offset]
            if length > 0 and offset + 1 + length <= len(b):
                try:
                    val_bytes = b[offset + 1 : offset + 1 + length]
                    if all(32 <= c < 127 for c in val_bytes):
                        return val_bytes.decode('ascii', errors='ignore').strip()
                except:
                    pass
            return ""
        
        first_name, last_name, country, registration, cn, aircraft = "", "", "", "", "", ""
        
        if entity_id == 20001:
            # Full player data packet (224 bytes) - use fixed offsets
            first_name = read_string_at_offset(19)
            last_name = read_string_at_offset(36)
            country = read_string_at_offset(53)
            registration = read_string_at_offset(70)
            cn = read_string_at_offset(78)
            aircraft = read_string_at_offset(189)
            
        elif entity_id == 1:
            # Abbreviated packet (45 bytes) - only has abbreviated name at offset 12
            # DO NOT use this data - it's incomplete and causes "D.Redman" as aircraft bug
            # Skip parsing entity_id=1 packets to avoid overwriting good data
            return f"[=] IDENTITY PACKET SKIPPED (entity_id=1 is abbreviated format)\n    - Cookie: {cookie:08x}"
        
        # --- End Fixed-Offset Parsing ---

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
        
        t_parse = time_module.time() - t_start
        TIMING_STATS["parse_identity"].append(t_parse)
        if len(TIMING_STATS["parse_identity"]) > MAX_TIMING_SAMPLES:
            TIMING_STATS["parse_identity"].pop(0)

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
        return f"[!] Not a TASK packet (type=0x{msg_type})\n    - Full HEX: {hex_data}"

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
            return f"[!] Error parsing TASK (1f00): could not locate Landscape string\n    - Full HEX: {hex_data}"
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
    return (f"[+] FPL TASK parsed: Landscape={landscape}, Turnpoints={len(tps)}\n    - Full HEX: {hex_data}")


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
        return f"[=] FPL DisabledAirspaces: duplicate chunk seq={seq} ignored ({seen}{('/'+str(tot)) if tot else ''})\n    - Full HEX: {hex_data}"
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
    return f"[+] FPL DisabledAirspaces: {seen}{('/'+str(tot)) if tot else ''} IDs collected\n    - Full HEX: {hex_data}"


def parse_settings_packet(hex_data: str) -> str:
    """Parse 0x2f00: bundle of Plane, Weather, GameOptions, Description (strings are LP-ASCII)."""
    b = bytes.fromhex(hex_data)
    if len(b) < 4:
        return f"[!] SETTINGS packet too short (len={len(b)})\n    - Full HEX: {hex_data}"
    msg_type = b[0:2].hex()
    if msg_type != "2f00":
        return f"[!] Not a SETTINGS packet (type=0x{msg_type})\n    - Full HEX: {hex_data}"

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
    return f"[+] FPL Settings parsed: plane='{plane or '?'}', weather='{weather_zone or '?'}', desc_len={len(description)}\n    - Full HEX: {hex_data}"


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
    if navicon_bridge is not None:
        try:
            for idx, tp in enumerate(task["turnpoints"]):
                try:
                    lat, lon = navicon_bridge.xy_to_latlon_default(tp['x'], tp['y'])
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
        # Silent mode - FPL written without console output
    except Exception as e:
        # Silent mode - no error output
        pass

def packet_handler(packet):
    """Main handler function for processing each captured packet."""
    global TIMING_STATS, LAST_TIMING_PRINT
    
    t_packet_start = time_module.time()
    
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

    # Process packets silently for performance
    if hex_data.startswith(("3d00", "3900", "3100")):
        # Telemetry packets - no logging, just process
        parse_telemetry_packet(hex_data)
    elif hex_data.startswith("1f00"):
        t_start = time_module.time()
        parse_fpl_task_packet(hex_data)
        TIMING_STATS["parse_other"].append(time_module.time() - t_start)
    elif hex_data.startswith(("0700", "0f00")):
        t_start = time_module.time()
        parse_disabled_list_packet(hex_data)
        TIMING_STATS["parse_other"].append(time_module.time() - t_start)
    elif hex_data.startswith("2f00"):
        t_start = time_module.time()
        parse_settings_packet(hex_data)
        TIMING_STATS["parse_other"].append(time_module.time() - t_start)
    elif hex_data.startswith(("3f00", "3f01")):
        # Identity packets - log to file for debugging
        parse_identity_packet(hex_data)
        if HEX_LOG_3F_FILE:
            HEX_LOG_3F_FILE.write(hex_data + "\n")
            HEX_LOG_3F_FILE.flush()
    elif hex_data.startswith("8006"):
        # ACK packets - no logging for performance
        t_start = time_module.time()
        parse_ack_packet(hex_data)
        TIMING_STATS["parse_other"].append(time_module.time() - t_start)
    
    # Track total packet processing time
    t_packet_total = time_module.time() - t_packet_start
    TIMING_STATS["packet_total"].append(t_packet_total)
    if len(TIMING_STATS["packet_total"]) > MAX_TIMING_SAMPLES:
        TIMING_STATS["packet_total"].pop(0)
    
    # Print timing breakdown periodically
    now = time_module.time()
    if now - LAST_TIMING_PRINT >= TIMING_PRINT_INTERVAL:
        print_timing_stats()
        LAST_TIMING_PRINT = now


def print_timing_stats():
    """Print detailed timing breakdown."""
    global TIMING_STATS
    
    def avg_ms(samples):
        if not samples:
            return 0.0
        return (sum(samples) / len(samples)) * 1000
    
    def max_ms(samples):
        if not samples:
            return 0.0
        return max(samples) * 1000
    
    global COORD_CACHE_HITS, COORD_CACHE_MISSES
    
    print("\n" + "="*70)
    print("[TIMING BREAKDOWN] Average (Max) per operation:")
    print("="*70)
    print(f"  decode_3d00:      {avg_ms(TIMING_STATS['decode_3d00']):6.2f}ms ({max_ms(TIMING_STATS['decode_3d00']):6.2f}ms) - Parse telemetry binary")
    print(f"  xy_to_latlon:     {avg_ms(TIMING_STATS['xy_to_latlon']):6.2f}ms ({max_ms(TIMING_STATS['xy_to_latlon']):6.2f}ms) - NaviCon DLL call")
    print(f"  identity_lookup:  {avg_ms(TIMING_STATS['identity_lookup']):6.2f}ms ({max_ms(TIMING_STATS['identity_lookup']):6.2f}ms) - Identity dict lookup")
    print(f"  build_payload:    {avg_ms(TIMING_STATS['build_payload']):6.2f}ms ({max_ms(TIMING_STATS['build_payload']):6.2f}ms) - Build & queue position")
    print(f"  parse_identity:   {avg_ms(TIMING_STATS['parse_identity']):6.2f}ms ({max_ms(TIMING_STATS['parse_identity']):6.2f}ms) - Parse identity packets")
    print(f"  parse_other:      {avg_ms(TIMING_STATS['parse_other']):6.2f}ms ({max_ms(TIMING_STATS['parse_other']):6.2f}ms) - Other packet types")
    print(f"  packet_total:     {avg_ms(TIMING_STATS['packet_total']):6.2f}ms ({max_ms(TIMING_STATS['packet_total']):6.2f}ms) - TOTAL per packet")
    print("="*70)
    
    # Calculate CPU usage estimate
    if TIMING_STATS['packet_total']:
        avg_packet_time = avg_ms(TIMING_STATS['packet_total'])
        packets_per_sec = len(TIMING_STATS['packet_total']) / TIMING_PRINT_INTERVAL
        cpu_usage_pct = (avg_packet_time / 1000) * packets_per_sec * 100
        print(f"  Packet rate: {packets_per_sec:.1f} pkt/s | Est. CPU usage: {cpu_usage_pct:.1f}%")
    
    # Coordinate cache stats
    total_lookups = COORD_CACHE_HITS + COORD_CACHE_MISSES
    if total_lookups > 0:
        cache_hit_rate = (COORD_CACHE_HITS / total_lookups) * 100
        print(f"  Coord cache: {len(COORD_CACHE)} entries | Hit rate: {cache_hit_rate:.1f}% ({COORD_CACHE_HITS}/{total_lookups})")
    print("="*70 + "\n")

def main():
    """Sets up packet sniffer with async HTTP worker."""
    global LOG_FILE, HEX_LOG_3F_FILE, HEX_LOG_8006_FILE, SNIFF_PORT, SERVER_NAME, IDENTITY_JSON_FILE, LANDSCAPE_TRN_PATH
    global HTTP_WORKER_THREAD, HTTP_WORKER_RUNNING
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Condor UDP Packet Sniffer')
    parser.add_argument('--port', type=int, required=True, help='UDP port to sniff')
    parser.add_argument('--server-name', type=str, default='', help='Server name for identification')
    parser.add_argument('--landscape', type=str, default='AA3', help='Landscape name (e.g., AA3, Slovenia3, Colorado_C2)')
    args = parser.parse_args()
    
    SNIFF_PORT = args.port
    SERVER_NAME = args.server_name
    
    # Build path to landscape TRN file
    landscape_name = args.landscape
    LANDSCAPE_TRN_PATH = rf"C:\Condor3\Landscapes\{landscape_name}\{landscape_name}.trn"
    
    # Verify TRN file exists
    if not os.path.exists(LANDSCAPE_TRN_PATH):
        import sys
        sys.stderr.write(f"[!] ERROR: Landscape TRN file not found: {LANDSCAPE_TRN_PATH}\n")
        sys.stderr.write(f"[!] Please ensure the landscape '{landscape_name}' is installed in C:\\Condor3\\Landscapes\\\n")
        sys.exit(1)
    
    # Get PID for identity map file
    pid = os.getpid()
    
    # Create logs directory if it doesn't exist
    logs_dir = "logs"
    os.makedirs(logs_dir, exist_ok=True)
    
    # Create identity map JSON file and 3f00/3f01 hex log
    IDENTITY_JSON_FILE = os.path.join(logs_dir, f"{pid}_identity_map.json")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    hex_log_3f_filename = os.path.join(logs_dir, f"{pid}_hex_log_3f00_3f01_{timestamp}.txt")

    try:
        # Start fresh identity map each run
        try:
            if os.path.exists(IDENTITY_JSON_FILE):
                os.remove(IDENTITY_JSON_FILE)
        except Exception:
            pass

        # Enable 3f00/3f01 logging for identity debugging
        LOG_FILE = None
        HEX_LOG_3F_FILE = open(hex_log_3f_filename, "w", encoding="utf-8")
        HEX_LOG_8006_FILE = None
        
        print(f"[+] Starting sniffer on port {SNIFF_PORT}")
        print(f"[+] Server: {SERVER_NAME or '(unnamed)'}")
        print(f"[+] Landscape: {landscape_name}")
        print(f"[+] Primary endpoint: {EXPRESS_ENDPOINT}")
        if REMOTE_SERVER_ENDPOINT:
            print(f"[+] Backup endpoint: {REMOTE_SERVER_ENDPOINT}")
        print(f"[+] HTTP timeout: {EXPRESS_TIMEOUT}s")
        print(f"[+] SSL verify: {EXPRESS_VERIFY_SSL}")
        print("="*60)
        
        # Initialize timing stats and cache
        global LAST_TIMING_PRINT, COORD_CACHE, COORD_CACHE_HITS, COORD_CACHE_MISSES
        LAST_TIMING_PRINT = time_module.time()
        COORD_CACHE.clear()
        COORD_CACHE_HITS = 0
        COORD_CACHE_MISSES = 0
        
        # Initialize batch sending
        global LAST_BATCH_SEND
        LAST_BATCH_SEND = time_module.time()
        
        # Start HTTP worker thread for periodic batch sending
        HTTP_WORKER_RUNNING = True
        HTTP_WORKER_THREAD = threading.Thread(target=http_worker_thread, daemon=True)
        HTTP_WORKER_THREAD.start()
        
        # Start packet sniffing
        bpf_filter = f"udp and port {SNIFF_PORT}"
        print(f"[+] Sniffing with filter: {bpf_filter}")
        print(f"[+] Waiting for packets...\n")
        sniff(filter=bpf_filter, prn=packet_handler, store=0)

    except PermissionError:
        import sys
        sys.stderr.write("\n[!] PERMISSION ERROR: Please run this script with administrator/root privileges.\n")
    except Exception as e:
        import sys
        sys.stderr.write(f"\n[!] An error occurred: {e}\n")
    finally:
        # Close log files
        if HEX_LOG_3F_FILE:
            HEX_LOG_3F_FILE.close()
        
        # Stop HTTP worker thread
        HTTP_WORKER_RUNNING = False
        if HTTP_WORKER_THREAD:
            HTTP_WORKER_THREAD.join(timeout=2.0)


if __name__ == "__main__":
    main()