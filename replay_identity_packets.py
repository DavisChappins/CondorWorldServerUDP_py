#!/usr/bin/env python3
"""
Replay 3f00/3f01 identity packets from hex log files.
Decodes packets, prints decoded information, and generates a live-updating JSON summary.

CONFIGURATION:
    All settings are configured in the CONFIG section below.
    Edit the "value" fields to customize behavior.
"""

# ============================================================================
# CONFIGURATION - Edit values here to control script behavior
# ============================================================================

CONFIG = {
    # Input/Output
    "logfile": "logs/6476_hex_log_3f00_3f01_20251009_041016.txt",  # Path to hex log file
    "output_dir": "analysis",  # Directory for JSON output
    
    # Replay Behavior
    "rate_ms": 0,  # Delay between packets in ms (0 = no delay)
    "max_packets": None,  # Max packets to process (None = all)
    
    # Console Output
    "console_output": True,  # Print detailed output to console
    "hex_truncate_length": 80,  # Max hex length to display (None = full)
    
    # Filtering
    "skip_chat_entities": True,  # Skip entity_id=20002 (chat messages)
    
    # JSON Output
    "json_indent": 2,  # JSON indentation (None = compact)
    "live_json_update": True,  # Update JSON after each packet
    
    # Error Handling
    "exit_on_file_not_found": True,  # Exit if log file not found
    "show_traceback_on_error": True,  # Show full traceback on errors
    
    # Debugging
    "debug_cookie": "b5cdedff",  # Set to cookie hex (e.g., "b5cdedff") to debug specific player
    "debug_verbose": True,  # Show detailed parsing steps for debug_cookie
    "debug_summary_only": True,  # Only show debug summary at end (not inline)
}


import datetime
import json
import os
import sys
import time
from pathlib import Path


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_config(key: str):
    """Get a configuration value."""
    return CONFIG[key]


def validate_config():
    """Validate configuration values."""
    errors = []
    
    if not isinstance(CONFIG["logfile"], str) or not CONFIG["logfile"]:
        errors.append("logfile must be a non-empty string")
    if not isinstance(CONFIG["output_dir"], str):
        errors.append("output_dir must be a string")
    if not isinstance(CONFIG["rate_ms"], int) or CONFIG["rate_ms"] < 0:
        errors.append("rate_ms must be a non-negative integer")
    
    max_packets = CONFIG["max_packets"]
    if max_packets is not None and (not isinstance(max_packets, int) or max_packets <= 0):
        errors.append("max_packets must be a positive integer or None")
    
    if not isinstance(CONFIG["console_output"], bool):
        errors.append("console_output must be a boolean")
    
    hex_len = CONFIG["hex_truncate_length"]
    if hex_len is not None and (not isinstance(hex_len, int) or hex_len <= 0):
        errors.append("hex_truncate_length must be a positive integer or None")
    
    if not isinstance(CONFIG["skip_chat_entities"], bool):
        errors.append("skip_chat_entities must be a boolean")
    
    json_indent = CONFIG["json_indent"]
    if json_indent is not None and (not isinstance(json_indent, int) or json_indent < 0):
        errors.append("json_indent must be a non-negative integer or None")
    
    if not isinstance(CONFIG["live_json_update"], bool):
        errors.append("live_json_update must be a boolean")
    if not isinstance(CONFIG["exit_on_file_not_found"], bool):
        errors.append("exit_on_file_not_found must be a boolean")
    if not isinstance(CONFIG["show_traceback_on_error"], bool):
        errors.append("show_traceback_on_error must be a boolean")
    
    if errors:
        raise ValueError("Configuration validation failed:\n  - " + "\n  - ".join(errors))


def print_config_summary():
    """Print current configuration."""
    print("=" * 80)
    print("CONFIGURATION")
    print("=" * 80)
    print(f"Input file:              {CONFIG['logfile']}")
    print(f"Output directory:        {CONFIG['output_dir']}")
    print(f"Rate (ms):               {CONFIG['rate_ms']}")
    print(f"Max packets:             {CONFIG['max_packets'] or 'All'}")
    print(f"Console output:          {CONFIG['console_output']}")
    print(f"Hex truncate length:     {CONFIG['hex_truncate_length'] or 'Full'}")
    print(f"Skip chat entities:      {CONFIG['skip_chat_entities']}")
    print(f"JSON indent:             {CONFIG['json_indent']}")
    print(f"Live JSON update:        {CONFIG['live_json_update']}")
    print("=" * 80)
    print()



# ============================================================================
# PACKET PARSING FUNCTIONS
# ============================================================================

def parse_identity_packet_standalone(hex_data: str) -> dict:
    """
    Decode 0x3f00/0x3f01 identity/config packet.
    Returns a dict with parsed fields or error information.
    
    Args:
        hex_data: Hexadecimal string representation of the packet
    
    Returns:
        Dictionary containing:
            - success: True if successfully decoded
            - error: Error message if decoding failed
            - skipped: True if packet was skipped (e.g., chat entity)
            - msg_type: Message type (3f00 or 3f01)
            - seq: Sequence number
            - entity_id: Entity identifier
            - cookie: Session cookie
            - first_name, last_name, cn, registration, country, aircraft: Player data
    """
    try:
        b = bytes.fromhex(hex_data)
        if len(b) < 20:
            return {
                "error": f"Packet too short (len={len(b)})",
                "hex": hex_data
            }

        msg_type = b[0:2].hex()
        if msg_type not in ("3f00", "3f01"):
            return {
                "error": f"Not an identity packet (type=0x{msg_type})",
                "hex": hex_data
            }

        seq = int.from_bytes(b[2:4], "little")
        entity_id = int.from_bytes(b[4:8], "little")
        cookie = int.from_bytes(b[8:12], "little")

        # Skip entity_id 20002 (chat messages, not players) if configured
        if entity_id == 20002 and get_config("skip_chat_entities"):
            return {
                "skipped": True,
                "reason": "entity_id=20002 is chat message",
                "msg_type": msg_type,
                "seq": seq,
                "entity_id": entity_id,
                "cookie": f"{cookie:08x}",
                "hex": hex_data
            }

        def find_next_string(start_offset, min_len=1, max_len=64):
            """Scans for the next length-prefixed ASCII string."""
            i = start_offset
            while i < len(b):
                if i + 1 >= len(b):
                    break
                length = b[i]
                if min_len <= length <= max_len and (i + 1 + length) <= len(b):
                    val_bytes = b[i+1 : i+1+length]
                    try:
                        if all(32 <= c < 127 for c in val_bytes):
                            val = val_bytes.decode('ascii').strip()
                            return val, i + 1 + length
                    except UnicodeDecodeError:
                        pass
                i += 1
            return None, len(b)

        def is_competition_id(s: str) -> bool:
            """Check if a string is the long hex Competition ID."""
            if not s or len(s) < 32:
                return False
            return all(c in '0123456789abcdefABCDEF ' for c in s)

        # Check if we should debug this cookie
        cookie_hex = f"{cookie:08x}"
        debug_this = get_config("debug_cookie") == cookie_hex and get_config("debug_verbose")
        debug_summary_only = get_config("debug_summary_only")
        
        # Scan the entire packet to find all plausible strings, ignoring the Comp ID
        all_strings = []
        all_strings_with_offsets = []  # For debugging
        offset = 12
        
        if debug_this and not debug_summary_only:
            print(f"\n{'='*80}")
            print(f"DEBUG: Parsing cookie {cookie_hex}")
            print(f"Packet length: {len(b)} bytes")
            print(f"Full hex: {hex_data}")
            print(f"{'='*80}")
        
        while offset < len(b):
            if b[offset] == 0x00:
                offset += 1
                continue
            
            val, next_offset = find_next_string(offset)
            if val:
                if not is_competition_id(val):
                    all_strings.append(val)
                    all_strings_with_offsets.append((offset, val, next_offset))
                    if debug_this and not debug_summary_only:
                        print(f"  Found string at offset {offset}: '{val}' (next offset: {next_offset})")
                offset = next_offset
            else:
                break

        # Filter out spurious single-character strings
        filtered_strings = [s for s in all_strings if len(s) > 1]
        
        if debug_this and not debug_summary_only:
            print(f"\nAll strings found: {all_strings}")
            print(f"After filtering (len>1): {filtered_strings}")

        # Assign fields based on the collected strings
        first_name, last_name, country, registration, cn, aircraft = "", "", "", "", "", ""
        
        if filtered_strings:
            # The last valid string in the packet is the aircraft name
            aircraft = filtered_strings.pop()
            
            if debug_this and not debug_summary_only:
                print(f"\nAssigning aircraft (last string): '{aircraft}'")
                print(f"Remaining strings for fields: {filtered_strings}")

            # Assign the remaining fields in their expected order
            if len(filtered_strings) > 0:
                fields_in_order = [None] * 5  # first_name, last_name, country, reg, cn
                for i in range(min(len(filtered_strings), 5)):
                    fields_in_order[i] = filtered_strings[i]
                
                first_name, last_name, country, registration, cn = fields_in_order
                
                if debug_this and not debug_summary_only:
                    print(f"\nField assignments:")
                    print(f"  first_name: '{first_name}'")
                    print(f"  last_name: '{last_name}'")
                    print(f"  country: '{country}'")
                    print(f"  registration: '{registration}'")
                    print(f"  cn: '{cn}'")
                    print(f"  aircraft: '{aircraft}'")
                
                # Clean up None values to empty strings
                first_name = first_name or ""
                last_name = last_name or ""
                country = country or ""
                registration = registration or ""
                cn = cn or ""

        if debug_this and not debug_summary_only:
            print(f"{'='*80}\n")

        result = {
            "success": True,
            "msg_type": msg_type,
            "seq": seq,
            "entity_id": entity_id,
            "cookie": f"{cookie:08x}",
            "cookie_int": cookie,
            "first_name": first_name,
            "last_name": last_name,
            "cn": cn,
            "registration": registration,
            "country": country,
            "aircraft": aircraft,
            "hex": hex_data
        }
        
        # Add debug info if this cookie is being debugged
        if debug_this:
            result["_debug"] = {
                "all_strings": all_strings,
                "filtered_strings": [s for s in all_strings if len(s) > 1],
                "strings_with_offsets": all_strings_with_offsets
            }
        
        return result
    except Exception as e:
        return {
            "error": f"Exception: {e}",
            "hex": hex_data
        }



# ============================================================================
# OUTPUT FORMATTING FUNCTIONS
# ============================================================================

def format_decoded_output(result: dict, line_num: int) -> str:
    """
    Format the decoded packet for console output.
    
    Args:
        result: Decoded packet dictionary from parse_identity_packet_standalone
        line_num: Line number in the log file
    
    Returns:
        Formatted string for console display
    """
    if result.get("error"):
        return f"[Line {line_num}] ERROR: {result['error']}\n    HEX: {result.get('hex', 'N/A')}"
    
    if result.get("skipped"):
        return f"[Line {line_num}] SKIPPED: {result['reason']}\n    Cookie: {result['cookie']}\n    HEX: {result['hex']}"
    
    if result.get("success"):
        # Apply hex truncation based on configuration
        hex_data = result['hex']
        truncate_len = get_config("hex_truncate_length")
        if truncate_len and len(hex_data) > truncate_len:
            hex_display = f"{hex_data[:truncate_len]}..."
        else:
            hex_display = hex_data
        
        output = [
            f"[Line {line_num}] IDENTITY PACKET DECODED",
            f"    Message Type: 0x{result['msg_type']}",
            f"    Seq: {result['seq']}",
            f"    Entity ID: {result['entity_id']}",
            f"    Cookie: {result['cookie']}",
            f"    CN: {result['cn']}",
            f"    Name: {result['first_name']} {result['last_name']}",
            f"    Registration: {result['registration']}",
            f"    Country: {result['country']}",
            f"    Aircraft: {result['aircraft']}",
            f"    HEX: {hex_display}"
        ]
        return "\n".join(output)
    
    return f"[Line {line_num}] UNKNOWN RESULT: {result}"



# ============================================================================
# MAIN REPLAY FUNCTION
# ============================================================================

def replay_identity_log():
    """
    Replay 3f00/3f01 packets from a log file using configuration settings.
    
    This function reads the log file specified in CONFIG, decodes identity packets,
    prints decoded information (if console_output is enabled), and generates a
    live-updating JSON summary file.
    
    All behavior is controlled by the CONFIG dictionary at the top of this file.
    
    Returns:
        None
    
    Raises:
        SystemExit: If log file not found and exit_on_file_not_found is True
    """
    # Load configuration values
    log_path = get_config("logfile")
    output_dir = get_config("output_dir")
    rate_ms = get_config("rate_ms")
    max_packets = get_config("max_packets")
    console_output = get_config("console_output")
    
    # Check if log file exists
    if not os.path.exists(log_path):
        print(f"[!] ERROR: Log file not found: {log_path}")
        if get_config("exit_on_file_not_found"):
            sys.exit(1)
        else:
            return
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate output filename based on input filename
    input_filename = Path(log_path).stem
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"{input_filename}_analysis_{timestamp}.json"
    output_path = os.path.join(output_dir, output_filename)
    
    # Print configuration summary and replay header
    if console_output:
        print_config_summary()
        print("=" * 80)
        print(f"IDENTITY PACKET REPLAY")
        print("=" * 80)
        print(f"Input file:  {log_path}")
        print(f"Output file: {output_path}")
        print(f"Rate:        {rate_ms}ms delay between packets" if rate_ms > 0 else "Rate:        No delay (maximum speed)")
        print(f"Max packets: {max_packets if max_packets else 'All'}")
        print("=" * 80)
        print()
    
    # Summary statistics
    summary = {
        "input_file": log_path,
        "output_file": output_path,
        "start_time": datetime.datetime.now().isoformat(),
        "end_time": None,
        "total_lines": 0,
        "packets_processed": 0,
        "packets_decoded": 0,
        "packets_skipped": 0,
        "packets_error": 0,
        "unique_cookies": {},
        "unique_entities": {},
        "packet_types": {"3f00": 0, "3f01": 0},
        "players": {}
    }
    
    # Debug tracking
    debug_packets = []  # Collect all debug packets for summary
    
    start_time = time.time()
    line_num = 0
    
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.strip()
                summary["total_lines"] += 1
                
                if not line:
                    continue
                
                # Only process 3f00 and 3f01 packets
                if not (line.startswith("3f00") or line.startswith("3f01")):
                    continue
                
                line_num += 1
                summary["packets_processed"] += 1
                
                # Decode the packet
                result = parse_identity_packet_standalone(line)
                
                # Collect debug info if present
                if "_debug" in result:
                    debug_packets.append({
                        "line_num": line_num,
                        "seq": result.get("seq"),
                        "msg_type": result.get("msg_type"),
                        "result": result
                    })
                
                # Print decoded output if console output is enabled
                if console_output:
                    output = format_decoded_output(result, line_num)
                    print(output)
                    print("-" * 80)
                
                # Update summary statistics
                if result.get("error"):
                    summary["packets_error"] += 1
                elif result.get("skipped"):
                    summary["packets_skipped"] += 1
                elif result.get("success"):
                    summary["packets_decoded"] += 1
                    
                    # Track packet types
                    msg_type = result["msg_type"]
                    summary["packet_types"][msg_type] = summary["packet_types"].get(msg_type, 0) + 1
                    
                    # Track unique cookies
                    cookie = result["cookie"]
                    if cookie not in summary["unique_cookies"]:
                        summary["unique_cookies"][cookie] = {
                            "first_seen_line": line_num,
                            "last_seen_line": line_num,
                            "packet_count": 1
                        }
                    else:
                        summary["unique_cookies"][cookie]["last_seen_line"] = line_num
                        summary["unique_cookies"][cookie]["packet_count"] += 1
                    
                    # Track unique entities
                    entity_id = result["entity_id"]
                    if entity_id not in summary["unique_entities"]:
                        summary["unique_entities"][entity_id] = {
                            "first_seen_line": line_num,
                            "last_seen_line": line_num,
                            "packet_count": 1,
                            "cookie": cookie
                        }
                    else:
                        summary["unique_entities"][entity_id]["last_seen_line"] = line_num
                        summary["unique_entities"][entity_id]["packet_count"] += 1
                    
                    # Build player profile (merge data from multiple packets)
                    if cookie not in summary["players"]:
                        summary["players"][cookie] = {
                            "cookie": cookie,
                            "cookie_int": result["cookie_int"],
                            "entity_id": entity_id,
                            "first_name": result["first_name"],
                            "last_name": result["last_name"],
                            "cn": result["cn"],
                            "registration": result["registration"],
                            "country": result["country"],
                            "aircraft": result["aircraft"],
                            "first_seen_line": line_num,
                            "last_seen_line": line_num,
                            "packet_count": 1,
                            "packet_types_used": {msg_type: 1}
                        }
                    else:
                        # Merge data (prefer non-empty values)
                        player = summary["players"][cookie]
                        player["first_name"] = result["first_name"] or player["first_name"]
                        player["last_name"] = result["last_name"] or player["last_name"]
                        player["cn"] = result["cn"] or player["cn"]
                        player["registration"] = result["registration"] or player["registration"]
                        player["country"] = result["country"] or player["country"]
                        player["aircraft"] = result["aircraft"] or player["aircraft"]
                        player["last_seen_line"] = line_num
                        player["packet_count"] += 1
                        # Track packet types used by this player
                        if msg_type in player["packet_types_used"]:
                            player["packet_types_used"][msg_type] += 1
                        else:
                            player["packet_types_used"][msg_type] = 1
                
                # Write summary JSON after each packet (live update) if configured
                if get_config("live_json_update"):
                    summary["end_time"] = datetime.datetime.now().isoformat()
                    summary["elapsed_seconds"] = time.time() - start_time
                    
                    with open(output_path, "w", encoding="utf-8") as jf:
                        json.dump(summary, jf, indent=get_config("json_indent"), ensure_ascii=False)
                
                # Check if we've hit max packets
                if max_packets and summary["packets_processed"] >= max_packets:
                    if console_output:
                        print(f"\n[*] Reached max packets limit ({max_packets}). Stopping.")
                    break
                
                # Apply rate limiting
                if rate_ms > 0:
                    time.sleep(rate_ms / 1000.0)
    
    except KeyboardInterrupt:
        if console_output:
            print("\n\n[!] Interrupted by user (Ctrl+C)")
    except Exception as e:
        print(f"\n[!] ERROR: {e}")
        if get_config("show_traceback_on_error"):
            import traceback
            traceback.print_exc()
    finally:
        # Final summary update (always write at the end)
        summary["end_time"] = datetime.datetime.now().isoformat()
        summary["elapsed_seconds"] = time.time() - start_time
        
        with open(output_path, "w", encoding="utf-8") as jf:
            json.dump(summary, jf, indent=get_config("json_indent"), ensure_ascii=False)
        
        # Print final statistics if console output is enabled
        if console_output:
            print("\n" + "=" * 80)
            print("REPLAY COMPLETE - SUMMARY")
            print("=" * 80)
            print(f"Total lines read:      {summary['total_lines']}")
            print(f"Packets processed:     {summary['packets_processed']}")
            print(f"  - Decoded:           {summary['packets_decoded']}")
            print(f"  - Skipped:           {summary['packets_skipped']}")
            print(f"  - Errors:            {summary['packets_error']}")
            print(f"Unique cookies:        {len(summary['unique_cookies'])}")
            print(f"Unique entities:       {len(summary['unique_entities'])}")
            print(f"Players identified:    {len(summary['players'])}")
            print(f"Packet types:")
            for ptype, count in summary["packet_types"].items():
                print(f"  - 0x{ptype}:           {count}")
            print(f"Elapsed time:          {summary['elapsed_seconds']:.2f}s")
            print(f"\nAnalysis saved to:     {output_path}")
            print("=" * 80)
            
            # Print player list
            if summary["players"]:
                print("\nPLAYERS IDENTIFIED:")
                print("-" * 80)
                for cookie, player in summary["players"].items():
                    name = f"{player['first_name']} {player['last_name']}".strip() or "(no name)"
                    cn = player['cn'] or "(no CN)"
                    aircraft = player['aircraft'] or "(no aircraft)"
                    
                    # Format packet types
                    packet_types = ", ".join([f"0x{pt}({count})" for pt, count in player['packet_types_used'].items()])
                    
                    print(f"  Cookie {cookie}: {name} | CN: {cn} | Aircraft: {aircraft} | Types: {packet_types}")
                print("-" * 80)
            
            # Print and save debug summary if debug packets were collected
            if debug_packets and get_config("debug_cookie"):
                debug_cookie = get_config('debug_cookie')
                debug_output_path = os.path.join(output_dir, f"debug_{debug_cookie}_{timestamp}.txt")
                
                # Build debug output
                debug_lines = []
                debug_lines.append("="*80)
                debug_lines.append(f"DEBUG SUMMARY FOR COOKIE: {debug_cookie}")
                debug_lines.append("="*80)
                debug_lines.append(f"Total packets found: {len(debug_packets)}")
                debug_lines.append("")
                
                for idx, pkt in enumerate(debug_packets, 1):
                    result = pkt["result"]
                    debug_info = result.get("_debug", {})
                    
                    # Decode cookie and entity_id from hex
                    hex_data = result.get('hex', '')
                    try:
                        b = bytes.fromhex(hex_data)
                        entity_id = int.from_bytes(b[4:8], "little") if len(b) >= 8 else "N/A"
                        cookie_int = int.from_bytes(b[8:12], "little") if len(b) >= 12 else "N/A"
                        cookie_hex = f"{cookie_int:08x}" if isinstance(cookie_int, int) else "N/A"
                    except:
                        entity_id = "N/A"
                        cookie_hex = "N/A"
                    
                    debug_lines.append(f"[Packet {idx}] Line {pkt['line_num']} | Type: 0x{pkt['msg_type']} | Seq: {pkt['seq']}")
                    debug_lines.append(f"  Cookie: {result.get('cookie', 'N/A')} (int: {result.get('cookie_int', 'N/A')})")
                    debug_lines.append(f"  Entity ID: {result.get('entity_id', 'N/A')}")
                    debug_lines.append(f"  Packet length: {len(b) if 'b' in locals() else 'N/A'} bytes")
                    
                    # Show strings with their byte offsets
                    strings_with_offsets = debug_info.get('strings_with_offsets', [])
                    if strings_with_offsets:
                        debug_lines.append(f"  Strings found with offsets:")
                        for offset, string, next_offset in strings_with_offsets:
                            length = len(string)
                            debug_lines.append(f"    Offset {offset:3d}: '{string}' (len={length}, next_offset={next_offset})")
                    else:
                        debug_lines.append(f"  All strings found: {debug_info.get('all_strings', [])}")
                    
                    debug_lines.append(f"  After filter (len>1): {debug_info.get('filtered_strings', [])}")
                    debug_lines.append(f"  Final assignment:")
                    debug_lines.append(f"    first_name:   '{result.get('first_name', '')}'")
                    debug_lines.append(f"    last_name:    '{result.get('last_name', '')}'")
                    debug_lines.append(f"    country:      '{result.get('country', '')}'")
                    debug_lines.append(f"    registration: '{result.get('registration', '')}'")
                    debug_lines.append(f"    cn:           '{result.get('cn', '')}'")
                    debug_lines.append(f"    aircraft:     '{result.get('aircraft', '')}'")
                    debug_lines.append(f"  Hex (first 100 chars): {result.get('hex', '')[:100]}...")
                    debug_lines.append(f"  Full hex: {result.get('hex', '')}")
                    debug_lines.append("")
                
                debug_lines.append("="*80)
                
                # Write to file
                with open(debug_output_path, "w", encoding="utf-8") as df:
                    df.write("\n".join(debug_lines))
                
                # Print to console
                print(f"\n{'='*80}")
                print(f"DEBUG SUMMARY FOR COOKIE: {debug_cookie}")
                print(f"{'='*80}")
                print(f"Total packets found: {len(debug_packets)}")
                print(f"\nDebug output saved to: {debug_output_path}")
                print(f"{'='*80}")



# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """
    Main entry point for the script.
    
    Validates configuration and starts the replay process.
    All settings are controlled by the CONFIG dictionary at the top of this file.
    
    Usage:
        1. Edit the CONFIG dictionary at the top of this file
        2. Run: python replay_identity_packets.py
        
    No command-line arguments are needed or accepted.
    """
    try:
        # Validate configuration before starting
        validate_config()
        
        # Run the replay
        replay_identity_log()
        
    except ValueError as e:
        print(f"\n[!] CONFIGURATION ERROR: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n[!] Script interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
