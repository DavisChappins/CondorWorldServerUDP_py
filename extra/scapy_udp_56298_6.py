#!/usr/bin/env python3
import datetime
import math
import struct
from scapy.all import sniff, UDP
from aa3_converter import convert_xy_to_lat_lon
import os
try:
    import navicon_bridge  # Out-of-process 32-bit DLL bridge
except Exception:
    navicon_bridge = None

# The UDP port the game is using
SNIFF_PORT = 56298

# Global file handler for logging
LOG_FILE = None


def decode_3d00_payload(payload_hex: str) -> dict:
    """Decode a 0x3d00 telemetry payload into useful fields."""
    b = bytes.fromhex(payload_hex)
    words = [b[i:i+4] for i in range(0, len(b), 4) if len(b[i:i+4]) == 4]
    floats = [struct.unpack("<f", w)[0] for w in words]
    u32s = [int.from_bytes(w, "little") for w in words]

    # Corrected field mapping based on latest findings
    pos_x = floats[2]
    pos_y = floats[3]
    altitude_m = floats[4]
    altitude_ft = altitude_m * 3.28084 # Conversion to feet
    heading_raw = floats[5] # Adjusted index for heading
    heading = (heading_raw % 360.0 + 360.0) % 360.0

    # Velocities and accelerations seem to be further down
    vx, vy, vz = floats[11], floats[12], floats[13]
    speed_mps = math.sqrt(vx * vx + vy * vy + vz * vz)
    speed_kt = speed_mps * 1.9438445
    vario_mps = vz
    vario_fpm = vario_mps * 196.850394

    ax, ay, az = floats[14], floats[15], floats[16]
    a_mag = math.sqrt(ax * ax + ay * ay + az * az)

    tail = u32s[-6:]

    return {
        "pos_x": pos_x,
        "pos_y": pos_y,
        "altitude_m": altitude_m,
        "altitude_ft": altitude_ft,
        "heading_deg": heading,
        "speed_mps": speed_mps,
        "speed_kt": speed_kt,
        "vario_mps": vario_mps,
        "vario_fpm": vario_fpm,
        "ax": ax,
        "ay": ay,
        "az": az,
        "a_mag": a_mag,
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
            output = (
                f"[+] TELEMETRY PACKET DETECTED\n"
                f"    - Message Type: 0x{msg_type}\n"
                f"    - Counter (CN): {cn_decimal}\n"
                f"    - Identifier (ID): {id_decimal}\n"
                f"    - Full HEX: {hex_data}\n"
                f"    - pos_x: {decoded['pos_x']:.1f}, pos_y: {decoded['pos_y']:.1f}\n"
                f"    - Lat/Lon: {lat:.5f}, {lon:.5f}\n"
                f"    - (Lon,Lat): {lon:.5f}, {lat:.5f}\n"
                f"    - Altitude: {decoded['altitude_m']:.2f} m ({decoded['altitude_ft']:.0f} ft)\n"
                f"    - Heading: (incorrect) {decoded['heading_deg']:.1f}°\n"
                f"    - Speed: (incorrect){decoded['speed_mps']:.2f} m/s ({decoded['speed_kt']:.1f} kt)\n"
                f"    - Vario: (incorrect) {decoded['vario_mps']:.2f} m/s ({decoded['vario_fpm']:.0f} fpm)\n"
                f"    - Accel: (incorrect)({decoded['ax']:.2f}, {decoded['ay']:.2f}, {decoded['az']:.2f}), |a|={decoded['a_mag']:.2f}\n"
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


def packet_handler(packet):
    """Main handler function for processing each captured packet."""
    if UDP not in packet or packet[UDP].dport != SNIFF_PORT:
        return

    payload = packet[UDP].payload.original
    hex_data = payload.hex()

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    parsed_output = ""

    if hex_data.startswith(("3d00", "3900", "3100")):
        parsed_output = parse_telemetry_packet(hex_data)
    elif hex_data.startswith("8006"):
        parsed_output = parse_ack_packet(hex_data)
    else:
        parsed_output = f"[?] UNKNOWN PACKET TYPE\n    - Full HEX: {hex_data}"

    final_output = f"[{timestamp}] {parsed_output}"
    print(final_output)
    print("-" * 60)

    if LOG_FILE:
        LOG_FILE.write(final_output + "\n")
        LOG_FILE.flush()


def main():
    """Sets up logging and starts the packet sniffer."""
    global LOG_FILE
    log_filename = f"udp_sniff_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    try:
        with open(log_filename, "w") as f:
            LOG_FILE = f
            print(f"[*] Starting UDP packet sniffer on port {SNIFF_PORT}")
            print(f"[*] Logging to file: {log_filename}")
            print("=" * 60)

            bpf_filter = f"udp and port {SNIFF_PORT}"
            sniff(filter=bpf_filter, prn=packet_handler, store=0)

    except PermissionError:
        print("\n[!] PERMISSION ERROR: Please run this script with administrator/root privileges.")
    except Exception as e:
        print(f"\n[!] An error occurred: {e}")


if __name__ == "__main__":
    main()