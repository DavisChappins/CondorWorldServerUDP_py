#!/usr/bin/env python3
import argparse
import datetime
import json
import os
import signal
import socket
import sys
import time
from threading import Thread, Lock

from scapy.all import sniff, UDP, IP
from colorama import Fore, Style, init

# Initialize colorama
init(autoreset=True)

# Global variable to control the main loop and threads
running = True

# Lock for writing to the combined log file
log_lock = Lock()

# --- Configuration for data sources (can be overridden by args) ---
DEFAULT_SERVER_IP = "3.140.13.20"
DEFAULT_SERVER_PORT = 56298
DEFAULT_INTERNAL_UDP_HOST = "127.0.0.1"
DEFAULT_INTERNAL_UDP_PORT = 55278
DEFAULT_SPECTATE_FILE = "C:\\Condor3\\Logs\\Spectate.json"
DEFAULT_COMBINED_LOG_FILE = "combined_log.txt"

# --- Helper function from spectate_json_monitor.py (adapted) ---
def read_spectate_json_data(file_path):
    """Reads and returns the raw content of the Spectate.json file."""
    raw_content = ""
    try:
        with open(file_path, 'r') as f:
            raw_content = f.read()
        if not raw_content.strip():
            # print(f"{Fore.YELLOW}[SPECTATE] File is empty: {file_path}{Style.RESET_ALL}")
            return None # Return None for empty file
        # We just want raw content, parsing can happen later if needed by user
        return raw_content
    except FileNotFoundError:
        # print(f"{Fore.RED}[SPECTATE] File not found: {file_path}{Style.RESET_ALL}")
        return None
    except Exception as e:
        # print(f"{Fore.RED}[SPECTATE] Error reading file {file_path}: {e}{Style.RESET_ALL}")
        return None

# --- Internal UDP Catcher (adapted from internal_udp_scraper.py) ---
# This will be a short-lived listener to grab recent packets
internal_udp_socket = None
latest_internal_udp_data = {"timestamp": None, "hex": None, "text": None}
internal_udp_data_lock = Lock()

def internal_udp_listener(host, port, buffer_size=4096):
    global running, internal_udp_socket, latest_internal_udp_data
    try:
        internal_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        internal_udp_socket.bind((host, port))
        internal_udp_socket.settimeout(0.1) # Non-blocking with timeout
        print(f"{Fore.GREEN}[INTERNAL UDP] Listening on {host}:{port}{Style.RESET_ALL}")
        while running:
            try:
                data, addr = internal_udp_socket.recvfrom(buffer_size)
                timestamp = datetime.datetime.now()
                hex_data = data.hex()
                text_data = ""
                try:
                    text_data = data.decode('utf-8', errors='replace')
                except UnicodeDecodeError:
                    text_data = "[Binary Data - Not UTF-8]"
                
                with internal_udp_data_lock:
                    latest_internal_udp_data = {
                        "timestamp": timestamp,
                        "hex": hex_data,
                        "text": text_data
                    }
                # print(f"{Fore.CYAN}[INTERNAL UDP] Captured data.{Style.RESET_ALL}") # Debug
            except socket.timeout:
                continue # No data received, continue loop
            except Exception as e:
                if running: # Avoid error message if we are shutting down
                    print(f"{Fore.RED}[INTERNAL UDP] Error receiving data: {e}{Style.RESET_ALL}")
                time.sleep(0.01) # Small delay to prevent tight loop on error
    except Exception as e:
        print(f"{Fore.RED}[INTERNAL UDP] Listener crashed: {e}{Style.RESET_ALL}")
    finally:
        if internal_udp_socket:
            internal_udp_socket.close()
        print(f"{Fore.YELLOW}[INTERNAL UDP] Listener stopped.{Style.RESET_ALL}")

def get_latest_internal_udp_data():
    with internal_udp_data_lock:
        return latest_internal_udp_data.copy() # Return a copy

# --- Server UDP Packet Handler (adapted from scapy_udp_scraper.py) ---
def server_packet_handler(packet, spectate_file_path, combined_log_file):
    global running
    if not running: # Check if we should stop processing
        return

    if packet.haslayer(UDP) and packet.haslayer(IP):
        ip_layer = packet[IP]
        udp_layer = packet[UDP]
        
        # Using args for IP and port will be handled in main
        # For now, assume it's filtered by sniff function if necessary
        
        timestamp = datetime.datetime.fromtimestamp(packet.time)
        hex_data = packet[UDP].payload.original.hex() # Get raw payload hex

        # # Filter logic: log if starts with '3d', discard if starts with '39'
        # if hex_data.startswith('39'):
        #     # print(f"{Fore.MAGENTA}[SERVER UDP] Discarding packet starting with 39: {hex_data[:10]}...{Style.RESET_ALL}")
        #     return
        
        # if not hex_data.startswith('3d'):
        #     # print(f"{Fore.MAGENTA}[SERVER UDP] Skipping packet not starting with 3d: {hex_data[:10]}...{Style.RESET_ALL}")
        #     return

        # A qualifying server UDP packet is found, now collect other data
        print(f"{Fore.GREEN}[CORRELATOR] Qualifying SERVER UDP packet received. Logging data...{Style.RESET_ALL}")

        # 1. Server UDP Data (already have it)
        server_log_entry = f"SERVER UDP [{timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')}] {hex_data}"

        # 2. Internal UDP Data
        internal_data = get_latest_internal_udp_data()
        internal_log_entry = "INTERNAL UDP: No fresh data"
        if internal_data and internal_data["timestamp"]:
            # Check if internal data is recent enough (e.g., within last second - adjust as needed)
            # This is a simple check; more sophisticated timing might be needed
            # For now, we take the very latest captured by the continuous listener.
            internal_log_entry = f"INTERNAL UDP [{internal_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S.%f')}] HEX: {internal_data['hex']} TEXT: {internal_data['text']}"
        else:
            internal_log_entry = f"INTERNAL UDP [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}] No data available/captured yet"

        # 3. Spectate JSON Data
        spectate_timestamp = datetime.datetime.now()
        spectate_raw_content = read_spectate_json_data(spectate_file_path)
        spectate_log_entry = f"SPECTATE JSON [{spectate_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')}]\n"
        if spectate_raw_content:
            spectate_log_entry += spectate_raw_content
        else:
            spectate_log_entry += "No data or file not found"

        # Combine and write to log
        combined_entry = f"{server_log_entry}\n{internal_log_entry}\n{spectate_log_entry}\n\n"
        
        with log_lock:
            with open(combined_log_file, 'a') as f:
                f.write(combined_entry)
            # print(f"{Fore.BLUE}[CORRELATOR] Logged data to {combined_log_file}{Style.RESET_ALL}")

def signal_handler(sig, frame):
    global running
    print(f"\n{Fore.YELLOW}[CORRELATOR] Signal received, shutting down...{Style.RESET_ALL}")
    running = False
    # Scapy's sniff might need more forceful stopping if it's blocking
    # For now, 'running' flag should cause packet_handler and internal listener to stop

def main():
    global running, DEFAULT_SERVER_IP, DEFAULT_SERVER_PORT, DEFAULT_INTERNAL_UDP_HOST, DEFAULT_INTERNAL_UDP_PORT, DEFAULT_SPECTATE_FILE, DEFAULT_COMBINED_LOG_FILE

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    parser = argparse.ArgumentParser(description='Condor Data Correlator')
    parser.add_argument('--server_ip', default=DEFAULT_SERVER_IP, help=f'Server IP to sniff (default: {DEFAULT_SERVER_IP})')
    parser.add_argument('--server_port', type=int, default=DEFAULT_SERVER_PORT, help=f'Server port to sniff (default: {DEFAULT_SERVER_PORT})')
    parser.add_argument('--internal_host', default=DEFAULT_INTERNAL_UDP_HOST, help=f'Internal UDP host (default: {DEFAULT_INTERNAL_UDP_HOST})')
    parser.add_argument('--internal_port', type=int, default=DEFAULT_INTERNAL_UDP_PORT, help=f'Internal UDP port (default: {DEFAULT_INTERNAL_UDP_PORT})')
    parser.add_argument('--spectate_file', default=DEFAULT_SPECTATE_FILE, help=f'Path to Spectate.json (default: {DEFAULT_SPECTATE_FILE})')
    parser.add_argument('--log_file', default=DEFAULT_COMBINED_LOG_FILE, help=f'Combined log file (default: {DEFAULT_COMBINED_LOG_FILE})')
    parser.add_argument('-c', '--clear_log', action='store_true', help='Clear the log file before starting (default: overwrite/append)')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable verbose debug output (Not fully implemented yet)')
    args = parser.parse_args()

    # Overwrite log file if it exists (as per user request for each run)
    if os.path.exists(args.log_file):
        print(f"{Fore.YELLOW}[CORRELATOR] Clearing existing log file: {args.log_file}{Style.RESET_ALL}")
        with open(args.log_file, 'w') as f:
            f.write("") # Truncate the file
    else:
        print(f"{Fore.GREEN}[CORRELATOR] Log file will be created: {args.log_file}{Style.RESET_ALL}")

    print(f"{Fore.GREEN}[CORRELATOR] Starting data correlator...{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  Server UDP: Sniffing on {args.server_ip}:{args.server_port}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  Internal UDP: Listening on {args.internal_host}:{args.internal_port}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  Spectate JSON: Monitoring {args.spectate_file}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  Logging to: {args.log_file}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}[CORRELATOR] Press Ctrl+C to stop.{Style.RESET_ALL}")

    # Start Internal UDP listener in a separate thread
    internal_listener_thread = Thread(target=internal_udp_listener, args=(args.internal_host, args.internal_port), daemon=True)
    internal_listener_thread.start()

    # Scapy filter string
    scapy_filter = f"udp and src host {args.server_ip} and src port {args.server_port}"
    print(f"{Fore.MAGENTA}[SCAPY] Using filter: {scapy_filter}{Style.RESET_ALL}")

    # Start Scapy sniffing
    # The 'prn' function gets called for each packet that matches the filter.
    # 'stop_filter' can be used to stop sniffing when 'running' is False.
    # 'store=0' means we don't store packets in memory, they are processed by prn.
    try:
        sniff(
            filter=scapy_filter,
            prn=lambda pkt: server_packet_handler(pkt, args.spectate_file, args.log_file),
            stop_filter=lambda pkt: not running,  # Stop sniffing when running is False
            store=0,
            iface=None # Sniff on all interfaces, or specify one if needed
        )
    except Exception as e:
        # This might catch permission errors if not run as admin/root on some systems
        print(f"{Fore.RED}[SCAPY] Error starting packet sniffer: {e}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Please ensure you have necessary permissions (e.g., run as administrator/root) and Npcap/WinPcap is installed (Windows).{Style.RESET_ALL}")
        running = False # Signal other parts to stop

    # Wait for internal listener thread to finish if it hasn't already
    if internal_listener_thread.is_alive():
        print(f"{Fore.YELLOW}[CORRELATOR] Waiting for internal UDP listener to shut down...{Style.RESET_ALL}")
        internal_listener_thread.join(timeout=2)
    
    print(f"{Fore.GREEN}[CORRELATOR] Script finished.{Style.RESET_ALL}")
    sys.exit(0)

if __name__ == "__main__":
    main()
