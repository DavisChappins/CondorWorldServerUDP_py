#!/usr/bin/env python3
import argparse
import datetime
import os
import sys
import time

# Reuse the parsing logic from sniffAndDecodeUDP_toExpress.py
try:
    from sniffAndDecodeUDP_toExpress import (
        parse_identity_packet,
        parse_ack_packet,
        parse_telemetry_packet,
        parse_fpl_task_packet,
        parse_disabled_list_packet,
        parse_settings_packet,
        flush_position_batch,
    )
except Exception as e:
    print(f"[!] Failed to import parsers from sniffAndDecodeUDP_toExpress.py: {e}")
    print(f"[!] Make sure sniffAndDecodeUDP_toExpress.py is in the same directory")
    sys.exit(1)


def parse_line(hex_data: str) -> str:
    """Dispatch to appropriate parser based on packet type, mirroring packet_handler()."""
    hex_data = hex_data.strip().lower()
    if not hex_data:
        return ""

    try:
        if hex_data.startswith(("3d00", "3900", "3100")):
            return parse_telemetry_packet(hex_data)
        elif hex_data.startswith("1f00"):
            return parse_fpl_task_packet(hex_data)
        elif hex_data.startswith(("0700", "0f00")):
            return parse_disabled_list_packet(hex_data)
        elif hex_data.startswith("2f00"):
            return parse_settings_packet(hex_data)
        elif hex_data.startswith(("3f00", "3f01")):
            return parse_identity_packet(hex_data)
        elif hex_data.startswith("8006"):
            return parse_ack_packet(hex_data)
        else:
            return f"[?] UNKNOWN PACKET TYPE\n    - Full HEX: {hex_data}"
    except Exception as e:
        return f"[!] Error parsing line: {e}\n    HEX: {hex_data}"


def replay_file(path: str, delay_ms: int = 0, max_lines: int | None = None, direction: str = "IN", send_to_express: bool = False):
    """Read hex lines from file and parse each as if streaming in."""
    if not os.path.exists(path):
        print(f"[!] File not found: {path}")
        sys.exit(2)

    print(f"[*] Replaying: {path}")
    if send_to_express:
        print(f"[*] Sending positions to Express.js (batched every 1.0s at 1Hz)")
    else:
        print(f"[*] Dry-run mode (not sending to Express.js)")
    print("-" * 60)

    count = 0
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            parsed_output = parse_line(line)
            if not parsed_output:
                continue

            # Match timestamp format used in packet_handler()
            ts = datetime.datetime.now().strftime("%Y-m-d %H:%M:%S.%f")[:-3]
            final_output = f"[{ts}] [{direction}] {parsed_output}"
            print(final_output)
            print("-" * 60)

            count += 1
            if max_lines is not None and count >= max_lines:
                break
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
    
    # Flush any remaining batched positions to Express.js
    if send_to_express:
        print(f"\n[*] Flushing final batch to Express.js...")
        flush_position_batch()
        print(f"[*] Replay complete. Processed {count} packets.")


def main():
    ap = argparse.ArgumentParser(description="Replay hex log and decode packets, optionally sending to Express.js backend.")
    ap.add_argument("logfile", help="Path to hex log file (one hex packet per line)")
    ap.add_argument("--delay-ms", type=int, default=0, help="Delay between lines in milliseconds (simulate streaming)")
    ap.add_argument("--max-lines", type=int, default=None, help="Stop after N lines (for quick tests)")
    ap.add_argument("--direction", choices=["IN", "OUT", "REPLAY"], default="REPLAY", help="Direction label to display")
    ap.add_argument("--send-to-express", action="store_true", help="Send positions to Express.js server (batched at 1Hz)")
    args = ap.parse_args()

    replay_file(args.logfile, delay_ms=args.delay_ms, max_lines=args.max_lines, direction=args.direction, send_to_express=args.send_to_express)


if __name__ == "__main__":
    main()
