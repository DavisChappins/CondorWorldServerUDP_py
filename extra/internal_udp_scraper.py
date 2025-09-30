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

def log_packet_data(packet_data, source_ip, source_port, timestamp, log_file):
    """
    Log packet data to a single log file.
    
    Args:
        packet_data: Raw packet data
        source_ip: Source IP of the packet
        source_port: Source port of the packet
        timestamp: Timestamp when packet was received
        log_file: Path to the log file
    """
    # Convert packet data to hex
    hex_data = binascii.hexlify(packet_data).decode()
    
    # Try to decode as text
    try:
        text_data = packet_data.decode('utf-8', errors='replace')
    except:
        text_data = "[Unable to decode as text]"
    
    # Format the log entry
    log_entry = f"INTERNAL CONDOR UDP {timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')}\nHEX: {hex_data}\nTEXT: {text_data}\n\n"
    
    # Write to log file
    with open(log_file, 'a') as f:
        f.write(log_entry)

def setup_udp_listener(host='127.0.0.1', port=55278, buffer_size=4096):
    """
    Set up a UDP socket to listen for incoming packets.
    
    Args:
        host: Host to bind to (default: 127.0.0.1)
        port: Port to listen on (default: 55278)
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
        
        print(f"{Fore.YELLOW}[*] Waiting for internal UDP packets on 127.0.0.1:55278...{Style.RESET_ALL}")
        
        return sock
    except socket.error as e:
        print(f"{Fore.RED}[!] Failed to create socket: {e}{Style.RESET_ALL}")
        sys.exit(1)

def main():
    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    parser = argparse.ArgumentParser(description='Internal Condor UDP Packet Scraper')
    parser.add_argument('-p', '--port', type=int, default=55278, 
                        help='Port to listen on (default: 55278)')
    parser.add_argument('-o', '--output', default='internal_udp_log.txt',
                        help='Output log file (default: internal_udp_log.txt)')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Enable debug output')
    parser.add_argument('-c', '--clear', action='store_true',
                        help='Clear the log file before starting')
    args = parser.parse_args()
    
    # Clear the log file if requested
    if args.clear and os.path.exists(args.output):
        try:
            os.remove(args.output)
            print(f"{Fore.GREEN}[+] Cleared log file: {args.output}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[!] Failed to clear log file: {e}{Style.RESET_ALL}")
    
    # Set up UDP socket
    sock = setup_udp_listener(port=args.port)
    
    print(f"{Fore.YELLOW}[*] Debug mode: {'Enabled' if args.debug else 'Disabled'}{Style.RESET_ALL}")
    
    packet_count = 0
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
                
                # Process packet
                packet_count += 1
                
                # Print packet information
                print(f"\n{Fore.BLUE}[{timestamp}] Packet #{packet_count} from {addr[0]}:{addr[1]}{Style.RESET_ALL}")
                print(f"{Fore.WHITE}Size: {len(data)} bytes (UDP payload){Style.RESET_ALL}")
                
                # Try to decode as text first
                try:
                    text_data = data.decode('utf-8', errors='replace')
                    print(f"{Fore.GREEN}Text: {Style.RESET_ALL}")
                    print(f"  {text_data}")
                except:
                    print(f"{Fore.RED}[!] Could not decode as text{Style.RESET_ALL}")
                    # Print hex dump of the data as fallback
                    hex_dump = binascii.hexlify(data).decode()
                    print(f"{Fore.GREEN}Hex: {Style.RESET_ALL}")
                    print(f"  {hex_dump}")
                
                # Log the packet data
                log_packet_data(data, addr[0], addr[1], timestamp, args.output)
                    
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
