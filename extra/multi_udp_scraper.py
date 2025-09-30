#!/usr/bin/env python3
import socket
import datetime
import binascii
import os
import sys
import argparse
import threading
import json
from colorama import Fore, Style, init

# Initialize colorama for colored output
init()

class UDPListener(threading.Thread):
    def __init__(self, name, host='0.0.0.0', port=56298, filter_ip=None, 
                 save_packets=False, output_dir='packets', buffer_size=4096):
        """
        Initialize a UDP listener thread.
        
        Args:
            name: Name of this listener (for identification)
            host: Host to bind to
            port: Port to listen on
            filter_ip: Only process packets from this IP (None = accept all)
            save_packets: Whether to save packet data to files
            output_dir: Directory to save packet data
            buffer_size: Maximum buffer size for received packets
        """
        threading.Thread.__init__(self)
        self.daemon = True
        self.name = name
        self.host = host
        self.port = port
        self.filter_ip = filter_ip
        self.save_packets = save_packets
        self.output_dir = f"{output_dir}/{name}"
        self.buffer_size = buffer_size
        self.running = True
        self.packet_count = 0
        
        # Create output directory if saving packets
        if self.save_packets and not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
    
    def setup_socket(self):
        """Set up the UDP socket for this listener"""
        try:
            # Create UDP socket
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # Set socket options to reuse address
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Bind socket to address and port
            self.sock.bind((self.host, self.port))
            
            print(f"{Fore.GREEN}[+] UDP listener '{self.name}' started on {self.host}:{self.port}{Style.RESET_ALL}")
            if self.filter_ip:
                print(f"{Fore.YELLOW}[*] Filtering for packets from {self.filter_ip}{Style.RESET_ALL}")
            
            return True
        except socket.error as e:
            print(f"{Fore.RED}[!] Failed to create socket for '{self.name}': {e}{Style.RESET_ALL}")
            return False
    
    def save_packet(self, packet_data, source, timestamp):
        """Save packet data to a file"""
        filename = f"{self.output_dir}/packet_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}.bin"
        
        with open(filename, 'wb') as f:
            f.write(packet_data)
        
        print(f"{Fore.CYAN}[*] {self.name}: Packet saved to {filename}{Style.RESET_ALL}")
    
    def run(self):
        """Main thread loop for capturing packets"""
        if not self.setup_socket():
            return
        
        try:
            while self.running:
                # Receive data from socket
                data, addr = self.sock.recvfrom(self.buffer_size)
                
                # Get current timestamp
                timestamp = datetime.datetime.now()
                
                # Check if we should process this packet
                if self.filter_ip is None or addr[0] == self.filter_ip:
                    self.packet_count += 1
                    
                    # Print packet information
                    print(f"\n{Fore.BLUE}[{timestamp}] {self.name} - Packet #{self.packet_count} from {addr[0]}:{addr[1]}{Style.RESET_ALL}")
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
                    if self.save_packets:
                        self.save_packet(data, addr, timestamp)
        
        except Exception as e:
            print(f"{Fore.RED}[!] Error in listener '{self.name}': {e}{Style.RESET_ALL}")
        
        finally:
            self.sock.close()
            print(f"{Fore.YELLOW}[*] Listener '{self.name}' stopped. Captured {self.packet_count} packets.{Style.RESET_ALL}")
    
    def stop(self):
        """Stop the listener thread"""
        self.running = False

def load_config(config_file):
    """
    Load listener configurations from a JSON file.
    
    Args:
        config_file: Path to the configuration file
        
    Returns:
        list: List of listener configurations
    """
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        return config.get('listeners', [])
    except Exception as e:
        print(f"{Fore.RED}[!] Failed to load configuration: {e}{Style.RESET_ALL}")
        return []

def main():
    parser = argparse.ArgumentParser(description='Multi-Stream UDP Packet Scraper')
    parser.add_argument('-c', '--config', default='config.json',
                        help='Configuration file (default: config.json)')
    parser.add_argument('-s', '--save', action='store_true',
                        help='Save packets to files')
    parser.add_argument('-o', '--output', default='packets',
                        help='Base output directory for saved packets (default: packets)')
    args = parser.parse_args()
    
    # Check if config file exists, if not create a default one
    if not os.path.exists(args.config):
        print(f"{Fore.YELLOW}[*] Configuration file not found. Creating default configuration...{Style.RESET_ALL}")
        default_config = {
            "listeners": [
                {
                    "name": "server",
                    "port": 56298,
                    "filter_ip": "3.140.13.20"
                },
                # Add placeholders for the two additional streams
                {
                    "name": "stream2",
                    "port": 56299,
                    "filter_ip": null  # Set to null to accept all IPs
                },
                {
                    "name": "stream3",
                    "port": 56300,
                    "filter_ip": null  # Set to null to accept all IPs
                }
            ]
        }
        
        with open(args.config, 'w') as f:
            json.dump(default_config, f, indent=4)
    
    # Load listener configurations
    listener_configs = load_config(args.config)
    
    if not listener_configs:
        print(f"{Fore.RED}[!] No listener configurations found. Exiting.{Style.RESET_ALL}")
        sys.exit(1)
    
    # Create and start listeners
    listeners = []
    for config in listener_configs:
        listener = UDPListener(
            name=config.get('name', 'unnamed'),
            port=config.get('port', 56298),
            filter_ip=config.get('filter_ip'),
            save_packets=args.save,
            output_dir=args.output
        )
        listeners.append(listener)
        listener.start()
    
    print(f"{Fore.GREEN}[+] Started {len(listeners)} UDP listeners{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}[*] Press Ctrl+C to stop{Style.RESET_ALL}")
    
    try:
        # Keep the main thread running
        while True:
            pass
    
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}[*] Shutting down...{Style.RESET_ALL}")
        
        # Stop all listeners
        for listener in listeners:
            listener.stop()
        
        # Wait for all listeners to finish
        for listener in listeners:
            listener.join(1.0)
        
        print(f"{Fore.GREEN}[+] All listeners stopped{Style.RESET_ALL}")
        sys.exit(0)

if __name__ == "__main__":
    main()
