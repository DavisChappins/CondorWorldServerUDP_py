#!/usr/bin/env python3
import json
import argparse
import sys
import os
from colorama import Fore, Style, init

# Initialize colorama for colored output
init()

def decode_spectate_json(data):
    """
    Decode and explain each field in the Spectate JSON data
    
    Args:
        data: Parsed JSON data
    """
    if not isinstance(data, list):
        print(f"{Fore.RED}Expected a list of gliders, but got {type(data)}{Style.RESET_ALL}")
        return
    
    print(f"{Fore.GREEN}Found {len(data)} gliders in the data{Style.RESET_ALL}")
    
    for i, glider in enumerate(data):
        print(f"\n{Fore.YELLOW}=== GLIDER #{i+1} DETAILED DECODING ==={Style.RESET_ALL}")
        
        # Player Identification
        print(f"\n{Fore.CYAN}--- PLAYER IDENTIFICATION ---{Style.RESET_ALL}")
        print(f"{Fore.WHITE}ID: {glider.get('ID', 'N/A')} - Unique player identifier{Style.RESET_ALL}")
        print(f"{Fore.WHITE}CN: {glider.get('CN', 'N/A')} - Competition Number (displayed on glider){Style.RESET_ALL}")
        print(f"{Fore.WHITE}RN: {glider.get('RN', 'N/A')} - Registration Number{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Name: {glider.get('firstname', 'N/A')} {glider.get('lastname', 'N/A')} - Pilot name{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Country: {glider.get('country', 'N/A')} - Pilot's country{Style.RESET_ALL}")
        
        # Aircraft Information
        print(f"\n{Fore.CYAN}--- AIRCRAFT INFORMATION ---{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Aircraft: {glider.get('plane', 'N/A')} - Glider model{Style.RESET_ALL}")
        
        # Position and Movement
        print(f"\n{Fore.CYAN}--- POSITION AND MOVEMENT ---{Style.RESET_ALL}")
        
        # Parse latitude
        lat_str = glider.get('latitude', 'N/A')
        lat_decoded = "N/A"
        if lat_str != 'N/A':
            try:
                # Format is typically "DD.MM.SSSN" or "DD.MM.SSSS"
                parts = lat_str.split('.')
                if len(parts) >= 3:
                    degrees = parts[0]
                    minutes = parts[1]
                    seconds = parts[2].rstrip('NS')
                    direction = 'N' if 'N' in lat_str else 'S' if 'S' in lat_str else ''
                    lat_decoded = f"{degrees}° {minutes}' {seconds}\" {direction} (Degrees.Minutes.Seconds)"
            except:
                lat_decoded = "Could not parse"
        
        # Parse longitude
        lon_str = glider.get('longitude', 'N/A')
        lon_decoded = "N/A"
        if lon_str != 'N/A':
            try:
                # Format is typically "DDD.MM.SSSE" or "DDD.MM.SSSW"
                parts = lon_str.split('.')
                if len(parts) >= 3:
                    degrees = parts[0]
                    minutes = parts[1]
                    seconds = parts[2].rstrip('EW')
                    direction = 'E' if 'E' in lon_str else 'W' if 'W' in lon_str else ''
                    lon_decoded = f"{degrees}° {minutes}' {seconds}\" {direction} (Degrees.Minutes.Seconds)"
            except:
                lon_decoded = "Could not parse"
        
        print(f"{Fore.WHITE}Latitude: {glider.get('latitude', 'N/A')} - {lat_decoded}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Longitude: {glider.get('longitude', 'N/A')} - {lon_decoded}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Altitude: {glider.get('altitude', 'N/A')} meters - Height above sea level{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Speed: {glider.get('speed', 'N/A')} km/h - Current airspeed{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Heading: {glider.get('heading', 'N/A')}° - Direction of travel (0-359, 0=North, 90=East){Style.RESET_ALL}")
        print(f"{Fore.WHITE}Vario: {glider.get('vario', 'N/A')} cm/s - Vertical speed (positive=climbing, negative=sinking){Style.RESET_ALL}")
        
        # Game Status
        print(f"\n{Fore.CYAN}--- GAME STATUS ---{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Status: {glider.get('playerstatus', 'N/A')} - Current player status in the game{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Selected: {glider.get('selected', 'N/A')} - Whether this glider is currently selected{Style.RESET_ALL}")
        
        # Competition Information
        print(f"\n{Fore.CYAN}--- COMPETITION INFORMATION ---{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Rank: {glider.get('rank', 'N/A')} - Current position in the competition{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Score: {glider.get('score', 'N/A')} - Current score{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Penalty: {glider.get('penalty', 'N/A')} - Any penalties applied{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Average Speed: {glider.get('averagespeed', 'N/A')} - Average speed during the task{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Distance: {glider.get('dist', 'N/A')} - Distance flown in the task{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Time: {glider.get('time', 'N/A')} - Time taken or elapsed time{Style.RESET_ALL}")
        
        # Additional fields
        print(f"\n{Fore.CYAN}--- OTHER FIELDS ---{Style.RESET_ALL}")
        for key, value in glider.items():
            if key not in ['ID', 'CN', 'RN', 'firstname', 'lastname', 'country', 'plane', 
                          'latitude', 'longitude', 'altitude', 'speed', 'heading', 'vario',
                          'playerstatus', 'selected', 'rank', 'score', 'penalty', 
                          'averagespeed', 'dist', 'time']:
                print(f"{Fore.WHITE}{key}: {value} - Additional field{Style.RESET_ALL}")

def main():
    parser = argparse.ArgumentParser(description='Decode Condor Spectate.json Format')
    parser.add_argument('-f', '--file', default='C:\\Condor3\\Logs\\Spectate.json',
                        help='Path to Spectate.json file (default: C:\\Condor3\\Logs\\Spectate.json)')
    parser.add_argument('-j', '--json', 
                        help='JSON string to decode (alternative to file)')
    args = parser.parse_args()
    
    # Get JSON data either from file or direct input
    data = None
    
    if args.json:
        try:
            data = json.loads(args.json)
        except json.JSONDecodeError as e:
            print(f"{Fore.RED}Error decoding JSON string: {e}{Style.RESET_ALL}")
            sys.exit(1)
    else:
        if not os.path.exists(args.file):
            print(f"{Fore.RED}File not found: {args.file}{Style.RESET_ALL}")
            sys.exit(1)
            
        try:
            with open(args.file, 'r') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"{Fore.RED}Error decoding JSON from {args.file}: {e}{Style.RESET_ALL}")
            sys.exit(1)
        except Exception as e:
            print(f"{Fore.RED}Error reading file: {e}{Style.RESET_ALL}")
            sys.exit(1)
    
    # Decode and explain the data
    decode_spectate_json(data)

if __name__ == "__main__":
    main()
