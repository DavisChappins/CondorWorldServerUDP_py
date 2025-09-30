#!/usr/bin/env python3
import socket
import struct
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

def save_packet(packet_data, source_ip, source_port, timestamp, output_dir):
    """
    Save packet data to a file.
    
    Args:
        packet_data: Raw packet data
        source_ip: Source IP of the packet
        source_port: Source port of the packet
        timestamp: Timestamp when packet was received
        output_dir: Directory to save packet data
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    filename = f"{output_dir}/packet_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}.bin"
    
    with open(filename, 'wb') as f:
        f.write(packet_data)
    
    print(f"{Fore.CYAN}[*] Packet saved to {filename}{Style.RESET_ALL}")

def setup_raw_socket(target_port=56298):
    """
    Set up a raw socket to capture UDP packets.
    
    Args:
        target_port: Port to filter for (default: 56298)
        
    Returns:
        socket: Configured raw socket
    """
    try:
        # Create a raw socket
        if os.name == 'nt':  # Windows
            # On Windows, we need to use IPPROTO_IP and enable promiscuous mode
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
            sock.bind(('0.0.0.0', 0))
            
            # Enable promiscuous mode
            sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
        else:  # Linux/Unix
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_UDP)
        
        # Set timeout for socket operations
        sock.settimeout(0.5)
        
        print(f"{Fore.GREEN}[+] Raw socket created successfully{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}[*] Listening for UDP packets on port {target_port}{Style.RESET_ALL}")
        
        return sock
    except socket.error as e:
        print(f"{Fore.RED}[!] Failed to create raw socket: {e}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}[*] Note: Raw sockets require administrator/root privileges{Style.RESET_ALL}")
        sys.exit(1)

def cleanup_socket(sock):
    """Clean up the socket before exiting"""
    if os.name == 'nt':
        try:
            # Disable promiscuous mode
            sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
        except:
            pass
    sock.close()

def extract_ip_header(packet):
    """Extract information from IP header"""
    # IP header is the first 20 bytes
    ip_header = packet[0:20]
    
    # Unpack the header according to RFC 791
    iph = struct.unpack('!BBHHHBBH4s4s', ip_header)
    
    version_ihl = iph[0]
    version = version_ihl >> 4
    ihl = version_ihl & 0xF
    
    iph_length = ihl * 4
    
    protocol = iph[6]
    s_addr = socket.inet_ntoa(iph[8])
    d_addr = socket.inet_ntoa(iph[9])
    
    return {
        'version': version,
        'ihl': ihl,
        'iph_length': iph_length,
        'protocol': protocol,
        'src_ip': s_addr,
        'dst_ip': d_addr
    }

def extract_udp_header(packet, ip_header_length):
    """Extract information from UDP header"""
    udp_header = packet[ip_header_length:ip_header_length+8]
    
    # Unpack the UDP header according to RFC 768
    udph = struct.unpack('!HHHH', udp_header)
    
    src_port = udph[0]
    dst_port = udph[1]
    length = udph[2]
    checksum = udph[3]
    
    return {
        'src_port': src_port,
        'dst_port': dst_port,
        'length': length,
        'checksum': checksum
    }

def main():
    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    parser = argparse.ArgumentParser(description='Raw UDP Packet Scraper for Game Server')
    parser.add_argument('-p', '--port', type=int, default=56298, 
                        help='Port to listen on (default: 56298)')
    parser.add_argument('-s', '--save', action='store_true',
                        help='Save packets to files')
    parser.add_argument('-o', '--output', default='packets',
                        help='Output directory for saved packets (default: packets)')
    parser.add_argument('-f', '--filter', default='3.140.13.20',
                        help='Filter packets from this IP address (default: 3.140.13.20)')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Enable debug output')
    parser.add_argument('-n', '--no-filter', action='store_true',
                        help='Disable IP filtering (capture all packets)')
    args = parser.parse_args()
    
    # If no-filter is set, clear the filter
    if args.no_filter:
        args.filter = None
    
    # Set up raw socket
    sock = setup_raw_socket(args.port)
    
    print(f"{Fore.YELLOW}[*] Debug mode: {'Enabled' if args.debug else 'Disabled'}{Style.RESET_ALL}")
    if args.filter:
        print(f"{Fore.YELLOW}[*] Filtering for IP: {args.filter}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}[*] No IP filtering (capturing all packets){Style.RESET_ALL}")
    
    packet_count = 0
    filtered_count = 0
    last_status_time = time.time()
    
    try:
        # Main loop
        global running
        while running:
            try:
                # Receive data from socket with timeout
                try:
                    packet = sock.recv(65535)
                    
                    # Get current timestamp
                    timestamp = datetime.datetime.now()
                    
                    # Extract IP header
                    ip_header = extract_ip_header(packet)
                    
                    # Only process UDP packets (protocol 17)
                    if ip_header['protocol'] != 17:  # UDP protocol number
                        continue
                    
                    # Extract UDP header
                    udp_header = extract_udp_header(packet, ip_header['iph_length'])
                    
                    # Debug output for all packets
                    if args.debug:
                        print(f"{Fore.CYAN}[DEBUG] Received packet from {ip_header['src_ip']}:{udp_header['src_port']} to {ip_header['dst_ip']}:{udp_header['dst_port']}, size: {len(packet)} bytes{Style.RESET_ALL}")
                    
                    # Apply filters
                    if args.filter and ip_header['src_ip'] != args.filter:
                        filtered_count += 1
                        if args.debug and filtered_count % 10 == 0:
                            print(f"{Fore.CYAN}[DEBUG] Filtered {filtered_count} packets so far{Style.RESET_ALL}")
                        continue
                    
                    # Filter for target port
                    if udp_header['dst_port'] != args.port:
                        filtered_count += 1
                        if args.debug and filtered_count % 10 == 0:
                            print(f"{Fore.CYAN}[DEBUG] Filtered {filtered_count} packets so far{Style.RESET_ALL}")
                        continue
                    
                    # Process matching packets
                    packet_count += 1
                    
                    # Extract UDP data
                    header_size = ip_header['iph_length'] + 8  # IP header + UDP header
                    data = packet[header_size:]
                    
                    # Print packet information
                    print(f"\n{Fore.BLUE}[{timestamp}] Packet #{packet_count} from {ip_header['src_ip']}:{udp_header['src_port']} to {ip_header['dst_ip']}:{udp_header['dst_port']}{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}Size: {len(data)} bytes (UDP payload){Style.RESET_ALL}")
                    
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
                        save_packet(data, ip_header['src_ip'], udp_header['src_port'], timestamp, args.output)
                
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
    
    finally:
        # Clean up
        print(f"{Fore.GREEN}[+] Captured {packet_count} packets{Style.RESET_ALL}")
        cleanup_socket(sock)
        sys.exit(0)

if __name__ == "__main__":
    main()
