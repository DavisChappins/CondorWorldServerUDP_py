#!/usr/bin/env python3
import datetime
import binascii
import os
import sys
import argparse
import signal
import time
from colorama import Fore, Style, init

# Initialize colorama for colored output
init()

# Global variable to control the main loop
running = True

def signal_handler(sig, frame):
    """Handle Ctrl+C and other signals to gracefully exit"""
    global running
    print(f"\n{Fore.YELLOW}[*] Signal received, shutting down...{Style.RESET_ALL}")
    running = False

def log_packet_hex(packet_data, source_ip, source_port, timestamp, log_file):
    """
    Log packet hex data to a single log file.
    
    Args:
        packet_data: Raw packet data
        source_ip: Source IP of the packet
        source_port: Source port of the packet
        timestamp: Timestamp when packet was received
        log_file: Path to the log file
    """
    # Convert packet data to hex
    hex_data = binascii.hexlify(packet_data).decode()
    
    # Format the log entry
    log_entry = f"SERVER UDP HEX {timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')} {hex_data}\n"
    
    # Write to log file
    with open(log_file, 'a') as f:
        f.write(log_entry)

def packet_callback(packet, args):
    """Callback function for each captured packet"""
    global packet_count, filtered_count
    
    # Get current timestamp
    timestamp = datetime.datetime.now()
    
    # Extract IP and port information
    if 'IP' in packet and 'UDP' in packet:
        src_ip = packet['IP'].src
        dst_ip = packet['IP'].dst
        src_port = packet['UDP'].sport
        dst_port = packet['UDP'].dport
        
        # Debug output for all packets
        if args.debug:
            print(f"{Fore.CYAN}[DEBUG] Received packet from {src_ip}:{src_port} to {dst_ip}:{dst_port}, size: {len(packet['UDP'].payload)} bytes{Style.RESET_ALL}")
        
        # Apply filters - we want packets FROM the server TO us
        if args.filter and src_ip != args.filter:
            global filtered_count
            filtered_count += 1
            if args.debug and filtered_count % 10 == 0:
                print(f"{Fore.CYAN}[DEBUG] Filtered {filtered_count} packets so far{Style.RESET_ALL}")
            return
        
        # Filter for specific port if requested
        if args.port and src_port != args.port:
            filtered_count += 1
            if args.debug and filtered_count % 10 == 0:
                print(f"{Fore.CYAN}[DEBUG] Filtered {filtered_count} packets so far{Style.RESET_ALL}")
            return
        
        # Process matching packets
        global packet_count
        packet_count += 1
        
        # Extract UDP data
        raw_data = bytes(packet['UDP'].payload)
        
        # Print packet information
        print(f"\n{Fore.BLUE}[{timestamp}] Packet #{packet_count} from {src_ip}:{src_port} to {dst_ip}:{dst_port}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Size: {len(raw_data)} bytes (UDP payload){Style.RESET_ALL}")
        
        # Print hex dump of the data
        hex_dump = binascii.hexlify(raw_data).decode()
        print(f"{Fore.GREEN}Hex: {Style.RESET_ALL}")
        print(f"  {hex_dump}")
        
        # Log the packet hex data
        log_packet_hex(raw_data, src_ip, src_port, timestamp, args.output)

def main():
    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    parser = argparse.ArgumentParser(description='Scapy UDP Packet Scraper for Game Server')
    parser.add_argument('-p', '--port', type=int, default=56298, 
                        help='Server source port to capture (default: 56298)')
    parser.add_argument('-o', '--output', default='server_udp_log.txt',
                        help='Output log file (default: server_udp_log.txt)')
    parser.add_argument('-f', '--filter', default='3.140.13.20',
                        help='Filter packets from this IP address (default: 3.140.13.20)')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Enable debug output')
    parser.add_argument('-n', '--no-filter', action='store_true',
                        help='Disable IP filtering (capture all packets)')
    parser.add_argument('-i', '--interface', default=None,
                        help='Network interface to sniff on (default: auto-detect)')
    parser.add_argument('--no-port', action='store_true',
                        help='Disable port filtering (capture all ports from the specified IP)')
    parser.add_argument('-c', '--clear', action='store_true',
                        help='Clear the log file before starting')
    args = parser.parse_args()
    
    # If no-filter is set, clear the filter
    if args.no_filter:
        args.filter = None
        
    # If no-port is set, clear the port filter
    if args.no_port:
        args.port = None
        
    # Clear the log file if requested
    if args.clear and os.path.exists(args.output):
        try:
            os.remove(args.output)
            print(f"{Fore.GREEN}[+] Cleared log file: {args.output}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[!] Failed to clear log file: {e}{Style.RESET_ALL}")
    
    # Import scapy here to avoid slow startup time if there's an error in the script
    try:
        from scapy.all import sniff, IP, UDP
        print(f"{Fore.GREEN}[+] Successfully imported scapy{Style.RESET_ALL}")
    except ImportError:
        print(f"{Fore.RED}[!] Failed to import scapy. Please install it with 'pip install scapy'{Style.RESET_ALL}")
        sys.exit(1)
    
    print(f"{Fore.YELLOW}[*] Debug mode: {'Enabled' if args.debug else 'Disabled'}{Style.RESET_ALL}")
    if args.filter:
        print(f"{Fore.YELLOW}[*] Filtering for IP: {args.filter}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}[*] No IP filtering (capturing all packets){Style.RESET_ALL}")
    
    if args.port:
        print(f"{Fore.YELLOW}[*] Filtering for server source port: {args.port}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}[*] No port filtering (capturing all ports){Style.RESET_ALL}")
    if args.interface:
        print(f"{Fore.YELLOW}[*] Using interface: {args.interface}{Style.RESET_ALL}")
    
    # Initialize global counters
    global packet_count, filtered_count
    packet_count = 0
    filtered_count = 0
    
    # Create a filter string for scapy
    # We want packets FROM the server TO us, so we need to capture packets where
    # the source IP is the server and any source port
    if args.filter:
        filter_str = f"udp and src host {args.filter}"
    else:
        filter_str = "udp"
    
    try:
        # Start sniffing
        print(f"{Fore.GREEN}[+] Starting packet capture with filter: {filter_str}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}[*] Press Ctrl+C to stop capturing{Style.RESET_ALL}")
        
        # Start sniffing in a non-blocking way
        from scapy.all import AsyncSniffer
        sniffer = AsyncSniffer(
            filter=filter_str,
            prn=lambda pkt: packet_callback(pkt, args),
            iface=args.interface,
            store=False
        )
        sniffer.start()
        
        # Main loop to keep the program running and handle Ctrl+C
        global running
        last_status_time = time.time()
        while running:
            time.sleep(0.1)  # Small sleep to prevent CPU hogging
            
            # Print status message periodically if no packets
            current_time = time.time()
            if packet_count == 0 and current_time - last_status_time > 5:
                print(f"{Fore.YELLOW}[*] Waiting for packets... (Press Ctrl+C to exit){Style.RESET_ALL}")
                last_status_time = current_time
    
    except KeyboardInterrupt:
        running = False
    
    finally:
        # Stop sniffing
        try:
            sniffer.stop()
        except:
            pass
        
        # Print summary
        print(f"\n{Fore.GREEN}[+] Captured {packet_count} packets{Style.RESET_ALL}")
        print(f"{Fore.GREEN}[+] Filtered {filtered_count} packets{Style.RESET_ALL}")
        sys.exit(0)

if __name__ == "__main__":
    main()
