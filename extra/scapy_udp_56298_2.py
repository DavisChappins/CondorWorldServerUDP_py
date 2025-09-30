#!/usr/bin/env python3
import datetime
from scapy.all import sniff, UDP

# The UDP port the game is using
SNIFF_PORT = 56298

# Global file handler for logging
LOG_FILE = None

def parse_telemetry_packet(hex_data: str) -> str:
    """Decodes the long telemetry packets."""
    try:
        msg_type = hex_data[0:4]
        
        # Extract CN and ID, converting from little-endian hex to decimal
        cn_hex = hex_data[4:8]
        cn_bytes = bytes.fromhex(cn_hex)
        cn_decimal = int.from_bytes(cn_bytes, 'little')
        
        id_hex = hex_data[8:16]
        id_bytes = bytes.fromhex(id_hex)
        id_decimal = int.from_bytes(id_bytes, 'little')
        
        # --- MODIFICATION: Full payload is now included ---
        payload_hex = hex_data[16:]
        
        # Build the formatted output string
        output = (
            f"[+] TELEMETRY PACKET DETECTED\n"
            f"    - Message Type: 0x{msg_type}\n"
            f"    - Counter (CN): {cn_decimal} (0x{cn_hex})\n"
            f"    - Identifier (ID): {id_decimal} (0x{id_hex})\n"
            f"    - Payload HEX: {payload_hex}"  # No longer truncated
        )
        return output
    except Exception as e:
        return f"[!] Error parsing Telemetry packet: {e}\n    HEX: {hex_data}"

def parse_ack_packet(hex_data: str) -> str:
    """Decodes the short acknowledgement packets."""
    try:
        msg_type = hex_data[0:8]
        
        # Extract the acknowledged CN, converting from little-endian hex to decimal
        ack_cn_hex = hex_data[8:12]
        ack_cn_bytes = bytes.fromhex(ack_cn_hex)
        ack_cn_decimal = int.from_bytes(ack_cn_bytes, 'little')
        
        payload_hex = hex_data[16:]
        
        # Build the formatted output string
        output = (
            f"[<] ACKNOWLEDGEMENT PACKET DETECTED\n"
            f"    - Message Type: 0x{msg_type}\n"
            f"    - Acknowledged CN: {ack_cn_decimal} (0x{ack_cn_hex})\n"
            f"    - Payload HEX: {payload_hex}"
        )
        return output
    except Exception as e:
        return f"[!] Error parsing ACK packet: {e}\n    HEX: {hex_data}"

def packet_handler(packet):
    """
    This function is called for each packet sniffed. It identifies the packet
    type and calls the appropriate parser.
    """
    if UDP not in packet or packet[UDP].dport != SNIFF_PORT:
        return

    payload = packet[UDP].payload.original
    hex_data = payload.hex()
    
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    
    if hex_data.startswith(('3d00', '3900', '3100')):
        parsed_output = parse_telemetry_packet(hex_data)
    elif hex_data.startswith('8006'):
        parsed_output = parse_ack_packet(hex_data)
    else:
        parsed_output = f"[?] UNKNOWN PACKET TYPE\n    HEX: {hex_data}"

    final_output = f"[{timestamp}] {parsed_output}"
    
    print(final_output)
    print("-" * 60)
    
    LOG_FILE.write(final_output + "\n")
    LOG_FILE.flush()

def main():
    """
    Sets up the log file and starts the sniffing process.
    """
    global LOG_FILE
    
    log_filename = f"udp_sniff_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    try:
        with open(log_filename, "w") as LOG_FILE:
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