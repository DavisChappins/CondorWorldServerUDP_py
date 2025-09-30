#!/usr/bin/env python3
import socket
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

def setup_udp_listener(host='0.0.0.0', port=56298, buffer_size=4096):
    """
    Set up a UDP socket to listen for incoming packets.
    
    Args:
        host: Host to bind to (default: 0.0.0.0 - all interfaces)
        port: Port to listen on (default: 56298)
        buffer_size: Maximum buffer size for received packets
        
    Returns:
        socket: Configured UDP socket
    """
    try:
        # Create UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Set socket options to reuse address
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Set timeout for socket operations
        sock.settimeout(0.5)
        
        # Increase buffer size for better performance
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        
        try:
            # Bind socket to address and port
            sock.bind((host, port))
            print(f"{Fore.GREEN}[+] UDP listener started on {host}:{port}{Style.RESET_ALL}")
            
            # Get the actual socket buffer size after setting
            bufsize = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
            print(f"{Fore.GREEN}[+] Socket receive buffer size: {bufsize} bytes{Style.RESET_ALL}")
            
        except socket.error as e:
            print(f"{Fore.RED}[!] Failed to bind socket: {e}{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}[*] Try running with administrator privileges or use a different port{Style.RESET_ALL}")
            sys.exit(1)
        
        print(f"{Fore.YELLOW}[*] Waiting for packets from 3.140.13.20...{Style.RESET_ALL}")
        
        return sock
    except socket.error as e:
        print(f"{Fore.RED}[!] Failed to create socket: {e}{Style.RESET_ALL}")
        sys.exit(1)

def save_packet(packet_data, source, timestamp, output_dir):
    """
    Save packet data to a file.
    
    Args:
        packet_data: Raw packet data
        source: Source address of the packet
        timestamp: Timestamp when packet was received
        output_dir: Directory to save packet data
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    filename = f"{output_dir}/packet_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}.bin"
    
    with open(filename, 'wb') as f:
        f.write(packet_data)
    
    print(f"{Fore.CYAN}[*] Packet saved to {filename}{Style.RESET_ALL}")

def main():
    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    parser = argparse.ArgumentParser(description='UDP Packet Scraper for Game Server')
    parser.add_argument('-p', '--port', type=int, default=56298, 
                        help='Port to listen on (default: 56298)')
    parser.add_argument('-s', '--save', action='store_true',
                        help='Save packets to files')
    parser.add_argument('-o', '--output', default='packets',
                        help='Output directory for saved packets (default: packets)')
    parser.add_argument('-f', '--filter', default='3.140.13.20',
                        help='Filter packets from this IP address (default: 3.140.13.20)')
    parser.add_argument('-sp', '--source-port', type=int, default=None,
                        help='Filter packets from this source port (default: None - accept all ports)')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Enable debug output')
    parser.add_argument('-n', '--no-filter', action='store_true',
                        help='Disable IP filtering (capture all packets)')
    args = parser.parse_args()
    
    # If no-filter is set, clear the filter
    if args.no_filter:
        args.filter = None
    
    # Set up UDP socket
    sock = setup_udp_listener(port=args.port)
    
    print(f"{Fore.YELLOW}[*] Debug mode: {'Enabled' if args.debug else 'Disabled'}{Style.RESET_ALL}")
    if args.filter:
        print(f"{Fore.YELLOW}[*] Filtering for IP: {args.filter}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}[*] No IP filtering (capturing all packets){Style.RESET_ALL}")
        
    if args.source_port:
        print(f"{Fore.YELLOW}[*] Filtering for source port: {args.source_port}{Style.RESET_ALL}")
    
    packet_count = 0
    filtered_count = 0
    last_status_time = time.time()
    
    # Main loop
    global running
    while running:
        try:
            # Receive data from socket with timeout
            try:
                data, addr = sock.recvfrom(4096)
                
                # Get current timestamp
                timestamp = datetime.datetime.now()
                
                # Debug output for all packets
                if args.debug:
                    print(f"{Fore.CYAN}[DEBUG] Received packet from {addr[0]}:{addr[1]}, size: {len(data)} bytes{Style.RESET_ALL}")
                
                # Apply filters
                if args.filter and addr[0] != args.filter:
                    filtered_count += 1
                    if args.debug and filtered_count % 10 == 0:
                        print(f"{Fore.CYAN}[DEBUG] Filtered {filtered_count} packets so far{Style.RESET_ALL}")
                    continue
                    
                if args.source_port and addr[1] != args.source_port:
                    filtered_count += 1
                    if args.debug and filtered_count % 10 == 0:
                        print(f"{Fore.CYAN}[DEBUG] Filtered {filtered_count} packets so far{Style.RESET_ALL}")
                    continue
                    
                # Process matching packets
                packet_count += 1
                
                # Print packet information
                print(f"\n{Fore.BLUE}[{timestamp}] Packet #{packet_count} from {addr[0]}:{addr[1]}{Style.RESET_ALL}")
                print(f"{Fore.WHITE}Size: {len(data)} bytes{Style.RESET_ALL}")
                
                # Print hex dump of the data
                hex_dump = binascii.hexlify(data).decode()
                print(f"{Fore.GREEN}Hex: {Style.RESET_ALL}")
                
                # Format hex dump in rows of 16 bytes
                for i in range(0, len(hex_dump), 32):
                    print(f"  {hex_dump[i:i+32]}")
                
                # Try to print as ASCII if possible
                try:
                    ascii_data = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data)
                    print(f"{Fore.GREEN}ASCII: {Style.RESET_ALL}")
                    
                    # Format ASCII in rows of 16 characters
                    for i in range(0, len(ascii_data), 16):
                        print(f"  {ascii_data[i:i+16]}")
                except:
                    print(f"{Fore.RED}[!] Could not decode as ASCII{Style.RESET_ALL}")
                
                # Save packet if requested
                if args.save:
                    save_packet(data, addr, timestamp, args.output)
                    
            except socket.timeout:
                # No data received within timeout period
                current_time = time.time()
                # Print status every 5 seconds if no packets
                if current_time - last_status_time > 5:
                    print(f"{Fore.YELLOW}[*] Waiting for packets... (Press Ctrl+C to exit){Style.RESET_ALL}")
                    last_status_time = current_time
                continue
                
        except Exception as e:
            print(f"{Fore.RED}[!] Error: {e}{Style.RESET_ALL}")
            if args.debug:
                import traceback
                traceback.print_exc()
            time.sleep(1)  # Prevent CPU spinning on repeated errors
    
    # Clean up
    print(f"{Fore.GREEN}[+] Captured {packet_count} packets{Style.RESET_ALL}")
    sock.close()
    sys.exit(0)

if __name__ == "__main__":
    main()
