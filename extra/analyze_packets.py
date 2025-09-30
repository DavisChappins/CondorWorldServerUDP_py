#!/usr/bin/env python3
import os
import sys
import argparse
import binascii
import struct
import datetime
import json
from colorama import Fore, Style, init

# Initialize colorama for colored output
init()

def load_packet_file(filename):
    """Load a binary packet file"""
    with open(filename, 'rb') as f:
        return f.read()

def analyze_packet_structure(data):
    """
    Attempt to analyze the structure of a packet
    Returns a dictionary of potential fields
    """
    result = {}
    
    # Basic size info
    result['size'] = len(data)
    
    # Check for common header patterns
    if len(data) >= 4:
        result['potential_header'] = binascii.hexlify(data[:4]).decode()
        result['uint32_header'] = struct.unpack('!I', data[:4])[0]
        result['int32_header'] = struct.unpack('!i', data[:4])[0]
        result['float_header'] = struct.unpack('!f', data[:4])[0]
    
    # Look for strings
    printable_chars = []
    for i, b in enumerate(data):
        if 32 <= b < 127:  # Printable ASCII
            printable_chars.append((i, chr(b)))
    
    # Find potential string sequences
    strings = []
    current_string = []
    for i, (pos, char) in enumerate(printable_chars):
        if i > 0 and pos == printable_chars[i-1][0] + 1:
            current_string.append(char)
        else:
            if len(current_string) >= 3:  # Only consider strings of 3+ chars
                strings.append(''.join(current_string))
            current_string = [char]
    
    if len(current_string) >= 3:
        strings.append(''.join(current_string))
    
    result['potential_strings'] = strings
    
    # Look for float sequences (common in game position data)
    floats = []
    for i in range(0, len(data) - 3, 4):
        try:
            value = struct.unpack('!f', data[i:i+4])[0]
            if -1000 < value < 1000:  # Reasonable range for game coordinates
                floats.append((i, value))
        except:
            pass
    
    result['potential_floats'] = floats
    
    return result

def compare_packets(packet1, packet2):
    """
    Compare two packets to find differences
    Returns a dictionary of differences
    """
    result = {
        'size_diff': len(packet2) - len(packet1),
        'byte_differences': []
    }
    
    min_len = min(len(packet1), len(packet2))
    
    # Compare bytes
    for i in range(min_len):
        if packet1[i] != packet2[i]:
            result['byte_differences'].append({
                'position': i,
                'packet1_value': packet1[i],
                'packet2_value': packet2[i],
                'hex1': hex(packet1[i]),
                'hex2': hex(packet2[i])
            })
    
    # Check for additional bytes
    if len(packet1) < len(packet2):
        result['additional_bytes'] = binascii.hexlify(packet2[len(packet1):]).decode()
    elif len(packet1) > len(packet2):
        result['missing_bytes'] = binascii.hexlify(packet1[len(packet2):]).decode()
    
    return result

def find_patterns(packets):
    """
    Find repeating patterns across multiple packets
    Returns a dictionary of patterns
    """
    result = {
        'consistent_bytes': [],
        'variable_bytes': [],
        'potential_counters': []
    }
    
    # Find minimum packet length
    min_len = min(len(p) for p in packets)
    
    # Check each byte position
    for i in range(min_len):
        values = [p[i] for p in packets]
        unique_values = set(values)
        
        if len(unique_values) == 1:
            # Consistent byte across all packets
            result['consistent_bytes'].append({
                'position': i,
                'value': values[0],
                'hex': hex(values[0])
            })
        else:
            # Variable byte
            result['variable_bytes'].append({
                'position': i,
                'unique_values': len(unique_values),
                'values': [hex(v) for v in unique_values]
            })
            
            # Check if it might be a counter
            if len(unique_values) == len(packets) and sorted(values) == values:
                result['potential_counters'].append({
                    'position': i,
                    'values': [hex(v) for v in values]
                })
    
    return result

def print_hex_dump(data, highlight_positions=None):
    """
    Print a hex dump of the data with optional highlighting
    """
    hex_dump = binascii.hexlify(data).decode()
    
    print(f"{Fore.GREEN}Hex dump:{Style.RESET_ALL}")
    
    # Format hex dump in rows of 16 bytes (32 hex chars)
    for i in range(0, len(hex_dump), 32):
        row_hex = hex_dump[i:i+32]
        row_bytes = data[i//2:(i//2)+16]
        
        # Print byte position
        print(f"{Fore.CYAN}{i//2:04x}{Style.RESET_ALL}: ", end="")
        
        # Print hex values
        for j in range(0, len(row_hex), 2):
            byte_pos = (i//2) + (j//2)
            byte_hex = row_hex[j:j+2]
            
            if highlight_positions and byte_pos in highlight_positions:
                print(f"{Fore.RED}{byte_hex}{Style.RESET_ALL}", end=" ")
            else:
                print(byte_hex, end=" ")
            
            # Add extra space every 8 bytes
            if j == 14:
                print(" ", end="")
        
        # Pad if incomplete row
        if len(row_hex) < 32:
            padding = (32 - len(row_hex)) // 2
            print("   " * padding, end="")
        
        # Print ASCII representation
        print("  |  ", end="")
        for b in row_bytes:
            if 32 <= b < 127:
                if highlight_positions and (byte_pos - len(row_bytes) + list(row_bytes).index(b)) in highlight_positions:
                    print(f"{Fore.RED}{chr(b)}{Style.RESET_ALL}", end="")
                else:
                    print(chr(b), end="")
            else:
                print(".", end="")
        
        print()

def main():
    parser = argparse.ArgumentParser(description='Analyze captured UDP packets')
    parser.add_argument('-d', '--directory', default='packets',
                        help='Directory containing packet files (default: packets)')
    parser.add_argument('-c', '--compare', nargs=2, metavar=('FILE1', 'FILE2'),
                        help='Compare two specific packet files')
    parser.add_argument('-p', '--pattern', action='store_true',
                        help='Find patterns across all packets')
    parser.add_argument('-s', '--structure', metavar='FILE',
                        help='Analyze structure of a specific packet')
    parser.add_argument('-o', '--output', default='analysis.json',
                        help='Output file for analysis results (default: analysis.json)')
    parser.add_argument('--limit', type=int, default=None,
                        help='Limit the number of packets to analyze')
    args = parser.parse_args()
    
    # Check if directory exists
    if not os.path.exists(args.directory):
        print(f"{Fore.RED}[!] Directory '{args.directory}' does not exist{Style.RESET_ALL}")
        sys.exit(1)
    
    # Compare two specific packets
    if args.compare:
        file1, file2 = args.compare
        
        if not os.path.exists(file1) or not os.path.exists(file2):
            print(f"{Fore.RED}[!] One or both packet files do not exist{Style.RESET_ALL}")
            sys.exit(1)
        
        packet1 = load_packet_file(file1)
        packet2 = load_packet_file(file2)
        
        print(f"{Fore.GREEN}[+] Comparing packets:{Style.RESET_ALL}")
        print(f"  File 1: {file1} ({len(packet1)} bytes)")
        print(f"  File 2: {file2} ({len(packet2)} bytes)")
        
        differences = compare_packets(packet1, packet2)
        
        print(f"\n{Fore.YELLOW}[*] Size difference: {differences['size_diff']} bytes{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}[*] Byte differences: {len(differences['byte_differences'])}{Style.RESET_ALL}")
        
        if differences['byte_differences']:
            print("\nDifferent bytes:")
            highlight_positions = [d['position'] for d in differences['byte_differences']]
            
            print("\nPacket 1:")
            print_hex_dump(packet1, highlight_positions)
            
            print("\nPacket 2:")
            print_hex_dump(packet2, highlight_positions)
            
            print("\nDetailed differences:")
            for diff in differences['byte_differences']:
                print(f"  Position {diff['position']}: {diff['hex1']} -> {diff['hex2']}")
        
        # Save results
        with open(args.output, 'w') as f:
            json.dump(differences, f, indent=2)
        
        print(f"\n{Fore.GREEN}[+] Analysis saved to {args.output}{Style.RESET_ALL}")
    
    # Analyze structure of a specific packet
    elif args.structure:
        if not os.path.exists(args.structure):
            print(f"{Fore.RED}[!] Packet file '{args.structure}' does not exist{Style.RESET_ALL}")
            sys.exit(1)
        
        packet = load_packet_file(args.structure)
        
        print(f"{Fore.GREEN}[+] Analyzing packet structure:{Style.RESET_ALL}")
        print(f"  File: {args.structure} ({len(packet)} bytes)")
        
        structure = analyze_packet_structure(packet)
        
        print("\nHex dump:")
        print_hex_dump(packet)
        
        print(f"\n{Fore.YELLOW}[*] Potential header: {structure['potential_header']}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}[*] As uint32: {structure['uint32_header']}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}[*] As int32: {structure['int32_header']}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}[*] As float: {structure['float_header']:.6f}{Style.RESET_ALL}")
        
        if structure['potential_strings']:
            print(f"\n{Fore.YELLOW}[*] Potential strings:{Style.RESET_ALL}")
            for s in structure['potential_strings']:
                print(f"  {s}")
        
        if structure['potential_floats']:
            print(f"\n{Fore.YELLOW}[*] Potential float values (position, value):{Style.RESET_ALL}")
            for pos, val in structure['potential_floats']:
                print(f"  {pos}: {val:.6f}")
        
        # Save results
        with open(args.output, 'w') as f:
            json.dump(structure, f, indent=2)
        
        print(f"\n{Fore.GREEN}[+] Analysis saved to {args.output}{Style.RESET_ALL}")
    
    # Find patterns across all packets
    elif args.pattern:
        # Get all packet files
        packet_files = []
        for root, _, files in os.walk(args.directory):
            for file in files:
                if file.startswith('packet_') and file.endswith('.bin'):
                    packet_files.append(os.path.join(root, file))
        
        if not packet_files:
            print(f"{Fore.RED}[!] No packet files found in '{args.directory}'{Style.RESET_ALL}")
            sys.exit(1)
        
        # Sort by timestamp
        packet_files.sort()
        
        # Limit if requested
        if args.limit and args.limit < len(packet_files):
            packet_files = packet_files[:args.limit]
        
        print(f"{Fore.GREEN}[+] Finding patterns across {len(packet_files)} packets{Style.RESET_ALL}")
        
        # Load all packets
        packets = [load_packet_file(f) for f in packet_files]
        
        # Find patterns
        patterns = find_patterns(packets)
        
        print(f"\n{Fore.YELLOW}[*] Consistent bytes: {len(patterns['consistent_bytes'])}{Style.RESET_ALL}")
        if patterns['consistent_bytes']:
            print("  First 10 consistent bytes:")
            for i, b in enumerate(patterns['consistent_bytes'][:10]):
                print(f"    Position {b['position']}: {b['hex']}")
        
        print(f"\n{Fore.YELLOW}[*] Variable bytes: {len(patterns['variable_bytes'])}{Style.RESET_ALL}")
        if patterns['variable_bytes']:
            print("  First 10 variable bytes:")
            for i, b in enumerate(patterns['variable_bytes'][:10]):
                print(f"    Position {b['position']}: {b['unique_values']} unique values")
        
        print(f"\n{Fore.YELLOW}[*] Potential counters: {len(patterns['potential_counters'])}{Style.RESET_ALL}")
        if patterns['potential_counters']:
            print("  Potential counter positions:")
            for i, c in enumerate(patterns['potential_counters']):
                print(f"    Position {c['position']}: {c['values'][:5]}...")
        
        # Save results
        with open(args.output, 'w') as f:
            json.dump(patterns, f, indent=2)
        
        print(f"\n{Fore.GREEN}[+] Analysis saved to {args.output}{Style.RESET_ALL}")
    
    else:
        print(f"{Fore.YELLOW}[*] No analysis option selected. Use -c, -p, or -s.{Style.RESET_ALL}")
        parser.print_help()

if __name__ == "__main__":
    main()
