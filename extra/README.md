# Condor Server UDP Scraper

A Python tool to capture and analyze UDP packets from a multiplayer game server in real-time.

## Features

- Captures UDP packets from a specific IP address and port
- Displays packet data with timestamps
- Shows both hexadecimal and ASCII representations of packet data
- Option to save raw packet data to files for later analysis
- Colorized output for better readability

## Installation

1. Install the required dependencies:

```
pip install -r requirements.txt
```

## Usage

Basic usage to capture UDP packets from 3.140.13.20 on port 56298:

```
python server_udp_scraper.py
```

### Command-line Options

- `-p, --port PORT`: Port to listen on (default: 56298)
- `-s, --save`: Save packets to files
- `-o, --output DIR`: Output directory for saved packets (default: 'packets')
- `-f, --filter IP`: Filter packets from this IP address (default: 3.140.13.20)

### Examples

Listen on a different port:
```
python server_udp_scraper.py -p 12345
```

Save all packets to files:
```
python server_udp_scraper.py -s
```

Save packets to a custom directory:
```
python server_udp_scraper.py -s -o game_packets
```

Filter packets from a different IP:
```
python server_udp_scraper.py -f 192.168.1.100
```

## Future Extensions

This tool is part of a larger project to decode multiplayer game server communications. Future versions will include:
- Integration with additional data sources
- Protocol decoding capabilities
- Real-time visualization of game state
