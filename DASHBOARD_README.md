# Condor Map Dedicated Server Control Panel

A modern web-based dashboard for managing multiple Condor UDP packet sniffer instances.

## Features

- ✨ **Modern Bootstrap UI** - Beautiful, responsive interface
- 🚀 **Multi-Server Management** - Run multiple sniffers on different ports simultaneously
- 📊 **Real-Time Status Monitoring** - Live status indicators (Off, Listening, Transmitting, Error)
- 💾 **Persistent Configuration** - Servers saved to `config.json`
- 🔄 **Auto-Refresh** - Status updates every 2 seconds
- 🎯 **Process Isolation** - Each sniffer runs as independent subprocess with unique PID
- 📝 **PID-Prefixed Logging** - All log files include PID for easy identification

## Requirements

```bash
pip install -r requirements.txt
```

Required packages:
- Flask >= 3.0
- psutil >= 5.9.0
- scapy >= 2.5.0
- requests >= 2.31
- numpy >= 1.24

## Installation

1. Ensure all dependencies are installed:
   ```bash
   pip install -r requirements.txt
   ```

2. Verify `sniffAndDecodeUDP_toExpress_viaFlask.py` is in the same directory as `app.py`

## Usage

### Starting the Dashboard

**Windows (Run as Administrator):**
```bash
python app.py
```

**Linux/Mac (Run with sudo):**
```bash
sudo python3 app.py
```

> ⚠️ **Important**: Administrator/root privileges are required because the sniffer uses scapy to capture network packets.

The dashboard will start at: `http://127.0.0.1:5001`

### Adding a Server

1. Scroll to the "Add New Server" section at the bottom
2. Enter a **Server Name** (e.g., "Condor Server 1")
3. Enter a **Port** number (1024-65535, typically 56288 for Condor)
4. Click **Add Server**

### Managing Servers

- **Start**: Click the green "Start" button to launch the sniffer
- **Stop**: Click the red "Stop" button to terminate the sniffer
- **Delete**: Click the gray "Delete" button to remove the server (stops it first if running)

### Status Indicators

| Status | LED Color | Description |
|--------|-----------|-------------|
| **Off** | Gray | Process not running |
| **Listening** | Green (solid) | Process running, waiting for packets |
| **Transmitting** | Green (flashing) | Process running, actively receiving packets |
| **Error** | Red | Process crashed or failed to start |

## Log Files

All log files are prefixed with the process PID for easy identification:

- `{PID}_udp_sniff_log_{timestamp}.txt` - Main detailed log
- `{PID}_hex_log_3d00_{timestamp}.txt` - Telemetry packets (0x3d00)
- `{PID}_hex_log_3f00_3f01_{timestamp}.txt` - Identity packets
- `{PID}_hex_log_8006_{timestamp}.txt` - ACK packets
- `{PID}_identity_map.json` - Identity mapping

## Configuration

### Dashboard Settings

Environment variables (optional):
- `DASHBOARD_HOST` - Host to bind to (default: `127.0.0.1`)
- `DASHBOARD_PORT` - Port for dashboard (default: `5001`)

Example:
```bash
set DASHBOARD_HOST=0.0.0.0
set DASHBOARD_PORT=8080
python app.py
```

### Sniffer Settings

Each sniffer instance forwards telemetry to Express.js:
- Default endpoint: `http://127.0.0.1:3000/api/positions`
- Override with `EXPRESS_ENDPOINT` environment variable

## Configuration File

Servers are stored in `config.json`:

```json
{
  "servers": [
    {
      "id": "uuid-string",
      "server_name": "Condor Server 1",
      "port": 56288,
      "pid": 12345,
      "status": "idle",
      "created_at": "2025-10-01T16:00:00Z",
      "last_started": "2025-10-01T16:30:00Z",
      "last_error": null
    }
  ]
}
```

## Troubleshooting

### "Permission Error"
- **Windows**: Run Command Prompt or PowerShell as Administrator
- **Linux/Mac**: Use `sudo` to run the script

### "Port already in use"
- Each server must have a unique port
- Check if another application is using the port
- Use a different port number (1024-65535)

### "sniffAndDecodeUDP_toExpress_viaFlask.py not found"
- Ensure the sniffer script is in the same directory as `app.py`
- Check the filename is correct

### Process shows "Error" status
- Check the log files (prefixed with PID) for error messages
- Verify scapy is installed correctly
- Ensure you have network capture permissions

### Status not updating
- The dashboard auto-refreshes every 2 seconds
- Check browser console for JavaScript errors
- Verify the Flask server is running

## Architecture

### Components

1. **app.py** - Flask dashboard server
   - Web UI with Bootstrap 5
   - REST API for server management
   - Process management and monitoring

2. **sniffAndDecodeUDP_toExpress_viaFlask.py** - UDP sniffer
   - Accepts `--port` and `--server-name` CLI arguments
   - Creates PID-prefixed log files
   - Forwards telemetry to Express.js

3. **config.json** - Persistent storage
   - Server configurations
   - PIDs and status
   - Timestamps

### Process Flow

```
User adds server → Saved to config.json
User clicks Start → Subprocess launched with CLI args
Sniffer starts → Creates PID-prefixed logs
Packets captured → Forwarded to Express.js
Dashboard polls → Updates status every 2s
User clicks Stop → Process terminated gracefully
```

## API Endpoints

### GET `/api/servers`
Returns all servers with current status

### POST `/api/servers`
Add a new server
```json
{
  "server_name": "Server 1",
  "port": 56288
}
```

### DELETE `/api/servers/<id>`
Delete a server (stops if running)

### POST `/api/servers/<id>/start`
Start a server's sniffer process

### POST `/api/servers/<id>/stop`
Stop a server's sniffer process

### GET `/api/servers/<id>/status`
Get real-time status of a specific server

## Security Notes

- Dashboard binds to `127.0.0.1` by default (localhost only)
- To allow remote access, set `DASHBOARD_HOST=0.0.0.0` (not recommended for production)
- No authentication is implemented (add reverse proxy with auth for production)
- Requires elevated privileges due to packet capture

## License

See main project README for license information.

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review log files for error messages
3. Ensure all dependencies are installed
4. Verify administrator/root privileges

---

**Made with ❤️ for the Condor soaring community**
