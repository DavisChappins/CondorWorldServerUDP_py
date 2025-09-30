#!/usr/bin/env python3
import os
import sys
import json
import time
import datetime
import argparse
import signal
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

def read_spectate_json(file_path):
    """
    Read and parse the Spectate.json file
    
    Args:
        file_path: Path to the Spectate.json file
        
    Returns:
        tuple: (parsed_data, raw_content) where parsed_data is the JSON data or None if error,
               and raw_content is the raw file content as a string
    """
    raw_content = ""
    try:
        with open(file_path, 'r') as f:
            raw_content = f.read()
            
        if not raw_content.strip():
            print(f"{Fore.RED}[!] File is empty: {file_path}{Style.RESET_ALL}")
            return None, raw_content
            
        try:
            data = json.loads(raw_content)
            return data, raw_content
        except json.JSONDecodeError as e:
            print(f"{Fore.RED}[!] Error decoding JSON from {file_path}: {e}{Style.RESET_ALL}")
            return None, raw_content
            
    except FileNotFoundError:
        print(f"{Fore.RED}[!] File not found: {file_path}{Style.RESET_ALL}")
        return None, raw_content
    except Exception as e:
        print(f"{Fore.RED}[!] Error reading file: {e}{Style.RESET_ALL}")
        return None, raw_content

def log_spectate_data(data, raw_content, timestamp, log_file):
    """
    Log spectate data to a file
    
    Args:
        data: JSON data to log (can be None)
        raw_content: Raw file content as string
        timestamp: Timestamp for the log entry
        log_file: Path to the log file
    """
    # Format the log entry
    log_entry = f"SPECTATE JSON {timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')}\n"
    
    # Add the raw content exactly as it appears in the file
    log_entry += f"{raw_content}\n\n"
    
    # Write to log file
    with open(log_file, 'a') as f:
        f.write(log_entry)

def main():
    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    parser = argparse.ArgumentParser(description='Condor Spectate.json Monitor')
    parser.add_argument('-f', '--file', default='C:\\Condor3\\Logs\\Spectate.json',
                        help='Path to Spectate.json file (default: C:\\Condor3\\Logs\\Spectate.json)')
    parser.add_argument('-o', '--output', default='spectate_log.txt',
                        help='Output log file (default: spectate_log.txt)')
    parser.add_argument('-i', '--interval', type=float, default=1.0,
                        help='Polling interval in seconds (default: 1.0)')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Enable debug output')
    parser.add_argument('-c', '--clear', action='store_true',
                        help='Clear the log file before starting')
    args = parser.parse_args()
    
    # Check if the spectate file exists
    if not os.path.exists(args.file):
        print(f"{Fore.RED}[!] Spectate file not found: {args.file}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}[*] Will keep checking for file to appear...{Style.RESET_ALL}")
    
    # Clear the log file if requested
    if args.clear and os.path.exists(args.output):
        try:
            os.remove(args.output)
            print(f"{Fore.GREEN}[+] Cleared log file: {args.output}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[!] Failed to clear log file: {e}{Style.RESET_ALL}")
    
    print(f"{Fore.GREEN}[+] Starting Spectate.json monitor{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}[*] Monitoring file: {args.file}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}[*] Polling interval: {args.interval} seconds{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}[*] Debug mode: {'Enabled' if args.debug else 'Disabled'}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}[*] Press Ctrl+C to stop{Style.RESET_ALL}")
    
    # Track file modification time to avoid re-reading unchanged files
    last_mtime = 0
    read_count = 0
    last_status_time = time.time()
    
    # Main loop
    global running
    while running:
        try:
            current_time = time.time()
            
            # Check if file exists
            if os.path.exists(args.file):
                # Get file modification time
                mtime = os.path.getmtime(args.file)
                
                # Only read if file has been modified or it's our first read
                if mtime != last_mtime or read_count == 0:
                    # Read and parse the JSON file
                    data, raw_content = read_spectate_json(args.file)
                    
                    # Print the raw content exactly as it appears in the file
                    print(f"{Fore.MAGENTA}Raw content:{Style.RESET_ALL}")
                    print(raw_content)
                    
                    if data:
                        # Get current timestamp
                        timestamp = datetime.datetime.now()
                        
                        # Log the data
                        log_spectate_data(data, raw_content, timestamp, args.output)
                        
                        # Update tracking variables
                        last_mtime = mtime
                        read_count += 1
                    
                    else:
                        print(f"{Fore.RED}[!] Failed to read or parse {args.file}{Style.RESET_ALL}")
                
                # Print status message periodically if no changes
                elif current_time - last_status_time > 5:
                    print(f"{Fore.YELLOW}[*] Waiting for changes to {args.file}... (Press Ctrl+C to exit){Style.RESET_ALL}")
                    last_status_time = current_time
            
            else:
                # File doesn't exist, print status periodically
                if current_time - last_status_time > 5:
                    print(f"{Fore.YELLOW}[*] Waiting for {args.file} to appear... (Press Ctrl+C to exit){Style.RESET_ALL}")
                    last_status_time = current_time
            
            # Sleep for the specified interval
            time.sleep(args.interval)
            
        except Exception as e:
            print(f"{Fore.RED}[!] Error: {e}{Style.RESET_ALL}")
            if args.debug:
                import traceback
                traceback.print_exc()
            time.sleep(1)  # Prevent CPU spinning on repeated errors
    
    # Clean up
    print(f"{Fore.GREEN}[+] Monitored {read_count} updates to {args.file}{Style.RESET_ALL}")
    sys.exit(0)

if __name__ == "__main__":
    main()
