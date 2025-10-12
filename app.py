#!/usr/bin/env python3
"""
Condor Map Dedicated Server Control Panel
Flask dashboard for managing multiple UDP sniffer instances
"""

import os
import sys
import json
import uuid
import time
import subprocess
import glob
import threading
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template_string

try:
    import psutil
except ImportError:
    psutil = None
    print("[!] Warning: psutil not installed. Install with: pip install psutil")

app = Flask(__name__)

# Get script directory for all file paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
LANDSCAPES_PATH = r"C:\Condor3\Landscapes"

# Auto-start tracking
auto_start_countdowns = {}  # {server_id: countdown_seconds}
auto_start_lock = threading.Lock()

# Task sync tracking
last_task_sync_time = None
task_sync_lock = threading.Lock()
TASK_SYNC_COOLDOWN = 1800  # 30 minutes in seconds


# ============================================================================
# Landscape Management
# ============================================================================

def get_available_landscapes():
    r"""Scan C:\Condor3\Landscapes for available landscape folders with .trn files"""
    landscapes = []
    
    if not os.path.exists(LANDSCAPES_PATH):
        return landscapes
    
    try:
        for item in os.listdir(LANDSCAPES_PATH):
            item_path = os.path.join(LANDSCAPES_PATH, item)
            if os.path.isdir(item_path):
                # Check if a .trn file with the same name exists
                trn_file = os.path.join(item_path, f"{item}.trn")
                if os.path.isfile(trn_file):
                    landscapes.append(item)
    except Exception as e:
        print(f"[!] Error scanning landscapes: {e}")
    
    return sorted(landscapes)


def get_landscapes_with_paths():
    r"""Get landscapes with their full file paths"""
    landscapes = []
    
    if not os.path.exists(LANDSCAPES_PATH):
        return landscapes
    
    try:
        for item in os.listdir(LANDSCAPES_PATH):
            item_path = os.path.join(LANDSCAPES_PATH, item)
            if os.path.isdir(item_path):
                # Check if a .trn file with the same name exists
                trn_file = os.path.join(item_path, f"{item}.trn")
                if os.path.isfile(trn_file):
                    landscapes.append({
                        'name': item,
                        'path': item_path,
                        'trn_file': trn_file
                    })
    except Exception as e:
        print(f"[!] Error scanning landscapes: {e}")
    
    return sorted(landscapes, key=lambda x: x['name'])


def get_windows_username():
    """Get the current Windows username"""
    return os.environ.get('USERNAME', os.environ.get('USER', 'Administrator'))


def find_user_settings_file():
    """Find the user_settings.xml file in AppData"""
    username = get_windows_username()
    from pathlib import Path
    settings_path = Path(f"C:\\Users\\{username}\\AppData\\Roaming\\Hitziger Solutions\\DSHelper\\user_settings.xml")
    return settings_path


def parse_dshelper_servers():
    """Parse DSHelper user_settings.xml and extract server configurations"""
    import xml.etree.ElementTree as ET
    import os
    
    settings_path = find_user_settings_file()
    
    if not settings_path.exists():
        print(f"[!] DSHelper settings file not found at: {settings_path}")
        return []
    
    try:
        tree = ET.parse(settings_path)
        root = tree.getroot()
        
        servers = []
        
        # Find all ServerSettings elements
        for server_elem in root.findall('.//ServerSettings'):
            try:
                server_id = server_elem.find('Id')
                filename = server_elem.find('Filename')
                displayname = server_elem.find('Displayname')
                
                # Get hostfile data
                hostfile = server_elem.find('Hostfile')
                if hostfile is not None:
                    server_name = hostfile.find('ServerName')
                    port = hostfile.find('Port')
                    
                    filename_value = filename.text if filename is not None else None
                    # Extract just the directory path (e.g., C:\Condor3\)
                    path_value = os.path.dirname(filename_value) + '\\' if filename_value else None
                    
                    server_data = {
                        'id': int(server_id.text) if server_id is not None and server_id.text else None,
                        'filename': filename_value,
                        'path': path_value,
                        'displayname': displayname.text if displayname is not None else None,
                        'server_name': server_name.text if server_name is not None else None,
                        'port': int(port.text) if port is not None and port.text else None
                    }
                    
                    servers.append(server_data)
            except Exception as e:
                print(f"[!] Error parsing server entry: {e}")
                continue
        
        # Sort by ID
        servers.sort(key=lambda x: x['id'] if x['id'] is not None else 999)
        
        return servers
        
    except Exception as e:
        print(f"[!] Error reading DSHelper settings: {e}")
        return []


# ============================================================================
# Configuration Manager
# ============================================================================

class ConfigManager:
    """Manages persistent configuration for servers"""
    
    def __init__(self, config_path=CONFIG_FILE):
        self.config_path = config_path
        self.data = {'servers': [], 'groups': []}
        self.load()
    
    def load(self):
        """Load configuration from JSON file"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    self.data = json.load(f)
                    if 'servers' not in self.data:
                        self.data['servers'] = []
                    if 'groups' not in self.data:
                        self.data['groups'] = []
            except Exception as e:
                print(f"[!] Error loading config: {e}")
                self.data = {'servers': [], 'groups': []}
        else:
            self.data = {'servers': [], 'groups': []}
    
    def save(self):
        """Save configuration to JSON file"""
        try:
            # Create backup
            if os.path.exists(self.config_path):
                backup_path = f"{self.config_path}.backup"
                with open(self.config_path, 'r') as f:
                    backup_data = f.read()
                with open(backup_path, 'w') as f:
                    f.write(backup_data)
            
            # Write new config
            with open(self.config_path, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print(f"[!] Error saving config: {e}")
    
    def add_server(self, server_name, port, landscape='AA3', path=None):
        """Add a new server configuration"""
        server = {
            'id': str(uuid.uuid4()),
            'server_name': server_name,
            'port': port,
            'landscape': landscape,
            'group': None,
            'path': path,
            'pid': None,
            'status': 'off',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'last_started': None,
            'last_error': None
        }
        self.data['servers'].append(server)
        self.save()
        return server
    
    def get_server(self, server_id):
        """Get server by ID"""
        for server in self.data['servers']:
            if server['id'] == server_id:
                return server
        return None
    
    def update_server(self, server_id, updates):
        """Update server fields"""
        for server in self.data['servers']:
            if server['id'] == server_id:
                server.update(updates)
                self.save()
                return server
        return None
    
    def delete_server(self, server_id):
        """Delete server configuration"""
        self.data['servers'] = [s for s in self.data['servers'] if s['id'] != server_id]
        self.save()
    
    def get_all_servers(self):
        """Get all servers"""
        return self.data['servers']

    # ---------------------------
    # Soaring Groups Management
    # ---------------------------
    def add_group(self, name):
        """Add a new soaring group (unique by name, case-insensitive)"""
        if not name or not name.strip():
            raise ValueError('Group name is required')
        norm = name.strip().lower()
        for g in self.data.get('groups', []):
            if g.get('name', '').strip().lower() == norm:
                raise ValueError('Group name already exists')
        group = {'id': str(uuid.uuid4()), 'name': name.strip()}
        self.data['groups'].append(group)
        self.save()
        return group

    def get_all_groups(self):
        """Return all soaring groups"""
        return self.data.get('groups', [])

    def delete_group(self, group_id):
        """Delete a group by id and clear it from servers using it"""
        groups_before = len(self.data.get('groups', []))
        self.data['groups'] = [g for g in self.data.get('groups', []) if g.get('id') != group_id]
        # Clear group from servers that referenced this group
        for s in self.data.get('servers', []):
            if s.get('group_id') == group_id:
                s['group_id'] = None
                s['group'] = None
        self.save()
        return groups_before != len(self.data['groups'])


# ============================================================================
# Process Management
# ============================================================================

def is_process_running(pid):
    """Check if a process with given PID is running"""
    if not pid:
        return False
    
    if psutil:
        return psutil.pid_exists(pid)
    else:
        # Fallback: Check if log files exist (process must be running to create them)
        try:
            log_pattern = f"{pid}_*.txt"
            log_files = glob.glob(log_pattern)
            if log_files:
                # If log files exist and are recent, assume process is running
                latest_log = max(log_files, key=os.path.getmtime)
                age = time.time() - os.path.getmtime(latest_log)
                if age < 30:  # Log file modified in last 30 seconds
                    return True
            
            # Try Windows API as backup
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_INFORMATION = 0x0400
            handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, 0, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except:
            # Last resort: check if any log files with this PID exist
            log_pattern = f"{pid}_*.txt"
            return len(glob.glob(log_pattern)) > 0


def get_process_status(server):
    """Determine the current status of a server's sniffer process"""
    # Check if in auto-start countdown
    with auto_start_lock:
        if server['id'] in auto_start_countdowns:
            countdown = auto_start_countdowns[server['id']]
            return f'starting_{countdown}'
    
    pid = server.get('pid')
    
    # Check if process exists
    if not pid or not is_process_running(pid):
        # Clear the PID if process is not running
        if pid:
            config.update_server(server['id'], {'pid': None, 'status': 'off'})
        return 'off'
    
    # Check if process is zombie/defunct (if psutil available)
    if psutil:
        try:
            proc = psutil.Process(pid)
            if proc.status() == psutil.STATUS_ZOMBIE:
                # Clear zombie PID
                config.update_server(server['id'], {'pid': None, 'status': 'error'})
                return 'error'
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Process doesn't exist, clear the PID
            config.update_server(server['id'], {'pid': None, 'status': 'off'})
            return 'off'
    
    # Get logs directory path
    logs_dir = os.path.join(SCRIPT_DIR, 'logs')
    
    # Check hex log file activity to determine transmitting status
    try:
        # Check 3f00/3f01 identity log files (most reliable indicator)
        log_pattern = os.path.join(logs_dir, f"{pid}_hex_log_3f00_3f01_*.txt")
        log_files = glob.glob(log_pattern)
        
        if not log_files:
            # Try 8006 ACK log files as fallback
            log_pattern = os.path.join(logs_dir, f"{pid}_hex_log_8006_*.txt")
            log_files = glob.glob(log_pattern)
        
        if log_files:
            # Get the most recent log file
            latest_log = max(log_files, key=os.path.getmtime)
            mtime = os.path.getmtime(latest_log)
            age = time.time() - mtime
            
            # Transmitting if log modified within last 15 seconds
            # (allows buffer for 10s polling delay)
            if age < 15:
                return 'transmitting'
            else:
                return 'listening'
        else:
            return 'listening'
    except Exception:
        return 'listening'


def start_sniffer(server):
    """Start a sniffer subprocess for the given server"""
    try:
        # Check if port is valid
        port = server['port']
        if not (1024 <= port <= 65535):
            return {'success': False, 'error': 'Invalid port number (must be 1024-65535)'}
        
        # Require Soaring Group before starting
        if not server.get('group'):
            return {'success': False, 'error': 'Soaring Group must be selected before starting'}
        
        # Check if already running
        if server.get('pid') and is_process_running(server['pid']):
            return {'success': False, 'error': 'Server is already running'}
        
        # Get landscape (default to AA3 for backward compatibility)
        landscape = server.get('landscape', 'AA3')
        
        # Get absolute path to the sniffer script (in same directory as app.py)
        sniffer_script = os.path.join(SCRIPT_DIR, 'sniffAndDecodeUDP_toExpress_viaFlask.py')
        
        # Build command
        cmd = [
            sys.executable,
            sniffer_script,
            '--port', str(port),
            '--server-name', server['server_name'],
            '--landscape', landscape
        ]
        
        # Create logs directory if it doesn't exist (in script directory)
        logs_dir = os.path.join(SCRIPT_DIR, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        
        # Redirect output to log files to prevent pipe blocking
        stdout_log = open(os.path.join(logs_dir, f'dashboard_{port}_stdout.log'), 'w')
        stderr_log = open(os.path.join(logs_dir, f'dashboard_{port}_stderr.log'), 'w')
        
        # Start process with simple Popen - set cwd to script directory
        process = subprocess.Popen(
            cmd,
            stdout=stdout_log,
            stderr=stderr_log,
            cwd=SCRIPT_DIR
        )
        
        pid = process.pid
        
        # Wait a moment to check if process starts successfully
        time.sleep(0.5)
        poll_result = process.poll()
        
        if poll_result is not None:
            # Process already exited - read error from log file
            error_msg = f"Process exited immediately (code {poll_result})"
            try:
                stderr_log.close()
                with open(os.path.join(logs_dir, f'dashboard_{port}_stderr.log'), 'r') as f:
                    stderr_output = f.read()
                    if stderr_output:
                        error_msg += f": {stderr_output[:200]}"
            except:
                pass
            
            config.update_server(server['id'], {
                'pid': None,
                'status': 'off',
                'last_error': error_msg
            })
            return {'success': False, 'error': error_msg}
        
        # Update server config
        config.update_server(server['id'], {
            'pid': pid,
            'status': 'listening',
            'last_started': datetime.now(timezone.utc).isoformat(),
            'last_error': None
        })
        
        # Trigger task sync after starting
        trigger_task_sync_async()
        
        return {'success': True, 'pid': pid}
    
    except FileNotFoundError:
        return {'success': False, 'error': 'sniffAndDecodeUDP_toExpress_viaFlask.py not found'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def run_task_sync_sequence():
    """Run tasksGet.py -> tasksConvert.py -> tasksUpload.py in sequence"""
    global last_task_sync_time
    
    with task_sync_lock:
        # Check cooldown
        if last_task_sync_time is not None:
            elapsed = time.time() - last_task_sync_time
            if elapsed < TASK_SYNC_COOLDOWN:
                remaining = int(TASK_SYNC_COOLDOWN - elapsed)
                print(f"[TASK-SYNC] Skipping - cooldown active ({remaining}s remaining)")
                return
        
        # Update last sync time
        last_task_sync_time = time.time()
    
    print("\n" + "=" * 60)
    print("[TASK-SYNC] Starting task synchronization sequence")
    print("=" * 60)
    
    scripts = [
        ('tasksGet.py', 'Fetching tasks from scheduler'),
        ('tasksConvert.py', 'Converting flight plans'),
        ('tasksUpload.py', 'Uploading tasks to server')
    ]
    
    for script_name, description in scripts:
        script_path = os.path.join(SCRIPT_DIR, script_name)
        
        if not os.path.exists(script_path):
            print(f"[TASK-SYNC] ERROR: {script_name} not found at {script_path}")
            continue
        
        print(f"\n[TASK-SYNC] Running {script_name}: {description}")
        print(f"[TASK-SYNC] {'=' * 50}")
        
        try:
            # Run the script and capture output with UTF-8 encoding
            # Timeout: tasksGet=60s, tasksConvert=300s (5min for many files), tasksUpload=120s
            timeout_map = {
                'tasksGet.py': 60,
                'tasksConvert.py': 300,  # 5 minutes for converting many flight plans
                'tasksUpload.py': 120
            }
            timeout = timeout_map.get(script_name, 60)
            
            result = subprocess.run(
                [sys.executable, script_path],
                cwd=SCRIPT_DIR,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',  # Replace characters that can't be decoded
                timeout=timeout
            )
            
            # Print stdout
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    print(f"[TASK-SYNC] {line}")
            
            # Print stderr if there were errors
            if result.stderr:
                for line in result.stderr.strip().split('\n'):
                    print(f"[TASK-SYNC] ERROR: {line}")
            
            # Check return code
            if result.returncode == 0:
                print(f"[TASK-SYNC] {script_name} completed successfully")
            else:
                print(f"[TASK-SYNC] {script_name} failed with exit code {result.returncode}")
                print(f"[TASK-SYNC] Stopping sequence - cannot proceed without {script_name}")
                return  # Stop the sequence on error
        
        except subprocess.TimeoutExpired:
            print(f"[TASK-SYNC] {script_name} timed out after {timeout} seconds")
            print(f"[TASK-SYNC] Stopping sequence - cannot proceed without {script_name}")
            return  # Stop the sequence on timeout
        except Exception as e:
            print(f"[TASK-SYNC] {script_name} error: {e}")
            print(f"[TASK-SYNC] Stopping sequence - cannot proceed without {script_name}")
            return  # Stop the sequence on exception
    
    print("\n" + "=" * 60)
    print("[TASK-SYNC] Task synchronization sequence complete")
    print("=" * 60 + "\n")


def trigger_task_sync_async():
    """Trigger task sync in a background thread"""
    thread = threading.Thread(target=run_task_sync_sequence, daemon=True)
    thread.start()


def stop_sniffer(server):
    """Stop a running sniffer process"""
    try:
        pid = server.get('pid')
        
        if not pid:
            return {'success': False, 'error': 'No PID recorded'}
        
        if not is_process_running(pid):
            # Process already stopped, clean up
            config.update_server(server['id'], {
                'pid': None,
                'status': 'off'
            })
            return {'success': True, 'message': 'Process was already stopped'}
        
        # Terminate process
        if psutil:
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                proc.wait(timeout=5)
                
                # Force kill if still running
                if proc.is_running():
                    proc.kill()
            except psutil.NoSuchProcess:
                pass
        else:
            # Fallback for Windows without psutil
            if os.name == 'nt':
                os.system(f'taskkill /F /PID {pid}')
            else:
                os.kill(pid, 15)  # SIGTERM
                time.sleep(1)
                try:
                    os.kill(pid, 9)  # SIGKILL
                except:
                    pass
        
        # Update server config
        config.update_server(server['id'], {
            'pid': None,
            'status': 'off'
        })
        
        # Trigger task sync after stopping
        trigger_task_sync_async()
        
        return {'success': True, 'message': 'Process stopped'}
    
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ============================================================================
# Flask Routes
# ============================================================================

@app.route('/')
def index():
    """Render the main dashboard"""
    return render_template_string(DASHBOARD_HTML)


@app.route('/api/servers', methods=['GET'])
def api_get_servers():
    """Get all servers with current status"""
    servers = config.get_all_servers()
    
    # Update status for each server
    for server in servers:
        status = get_process_status(server)
        server['status'] = status
        # Don't save countdown statuses to config
        if not status.startswith('starting_'):
            config.update_server(server['id'], {'status': status})
    
    return jsonify(servers)


@app.route('/api/servers', methods=['POST'])
def api_add_server():
    """Add a new server"""
    data = request.get_json()
    
    print(f"\n[DEBUG-API] ========================================")
    print(f"[DEBUG-API] Received POST /api/servers")
    print(f"[DEBUG-API] Raw request data: {repr(data)}")
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    server_name = data.get('server_name', '').strip()
    port = data.get('port')
    landscape = data.get('landscape', 'AA3').strip()
    path = data.get('path', '').strip() or None
    
    print(f"[DEBUG-API] Extracted path from request: {repr(path)}")
    print(f"[DEBUG-API] Path type: {type(path)}")
    if path:
        print(f"[DEBUG-API] Path character codes: {[ord(c) for c in path[:50]]}")
    
    if not server_name:
        return jsonify({'error': 'Server name is required'}), 400
    
    if not landscape:
        return jsonify({'error': 'Landscape is required'}), 400
    
    try:
        port = int(port)
        if not (1024 <= port <= 65535):
            return jsonify({'error': 'Port must be between 1024 and 65535'}), 400
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid port number'}), 400
    
    # Check for duplicate port
    for server in config.get_all_servers():
        if server['port'] == port:
            return jsonify({'error': f'Port {port} is already in use'}), 400
    
    print(f"[DEBUG-API] About to call config.add_server with path: {repr(path)}")
    server = config.add_server(server_name, port, landscape, path)
    print(f"[DEBUG-API] Server created, path in result: {repr(server.get('path'))}")
    print(f"[DEBUG-API] ========================================\n")
    return jsonify(server), 201


@app.route('/api/servers/<server_id>', methods=['DELETE'])
def api_delete_server(server_id):
    """Delete a server"""
    server = config.get_server(server_id)
    
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    
    # Stop if running
    if server.get('pid') and is_process_running(server['pid']):
        stop_sniffer(server)
    
    config.delete_server(server_id)
    return jsonify({'success': True})


@app.route('/api/servers/<server_id>/start', methods=['POST'])
def api_start_server(server_id):
    """Start a server's sniffer process"""
    server = config.get_server(server_id)
    
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    
    result = start_sniffer(server)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 400


@app.route('/api/servers/<server_id>/stop', methods=['POST'])
def api_stop_server(server_id):
    """Stop a server's sniffer process or cancel countdown"""
    server = config.get_server(server_id)
    
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    
    # Check if server is in countdown
    with auto_start_lock:
        if server_id in auto_start_countdowns:
            # Cancel the countdown by removing it
            auto_start_countdowns.pop(server_id, None)
            config.update_server(server_id, {'status': 'off'})
            return jsonify({'success': True, 'message': 'Countdown cancelled'})
    
    result = stop_sniffer(server)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 400


@app.route('/api/servers/<server_id>/status', methods=['GET'])
def api_get_server_status(server_id):
    """Get real-time status of a specific server"""
    server = config.get_server(server_id)
    
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    
    status = get_process_status(server)
    config.update_server(server_id, {'status': status})
    
    return jsonify({'status': status, 'pid': server.get('pid')})


@app.route('/api/landscapes', methods=['GET'])
def api_get_landscapes():
    """Get list of available landscapes"""
    landscapes = get_available_landscapes()
    return jsonify({'landscapes': landscapes})


@app.route('/api/servers/<server_id>/landscape', methods=['PUT'])
def api_update_landscape(server_id):
    """Update server landscape (only when stopped)"""
    server = config.get_server(server_id)
    
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    
    # Check if server is running
    if server.get('pid') and is_process_running(server['pid']):
        return jsonify({'error': 'Cannot change landscape while server is running. Stop the server first.'}), 400
    
    data = request.get_json()
    landscape = data.get('landscape', '').strip()
    
    if not landscape:
        return jsonify({'error': 'Landscape is required'}), 400
    
    # Verify landscape exists
    available = get_available_landscapes()
    if landscape not in available:
        return jsonify({'error': f'Landscape "{landscape}" not found in {LANDSCAPES_PATH}'}), 400
    
    config.update_server(server_id, {'landscape': landscape})
    return jsonify({'success': True, 'landscape': landscape})


@app.route('/api/dshelper/servers', methods=['GET'])
def api_get_dshelper_servers():
    """Get servers detected from DSHelper user_settings.xml"""
    servers = parse_dshelper_servers()
    return jsonify(servers)


@app.route('/api/landscapes/details', methods=['GET'])
def api_get_landscapes_details():
    """Get landscapes with full path information"""
    landscapes = get_landscapes_with_paths()
    return jsonify(landscapes)


@app.route('/api/groups', methods=['GET'])
def api_get_groups():
    """Get all soaring groups"""
    return jsonify({'groups': config.get_all_groups()})


@app.route('/api/groups', methods=['POST'])
def api_add_group():
    """Create a new soaring group"""
    data = request.get_json()
    name = (data or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'Group name is required'}), 400
    try:
        group = config.add_group(name)
        return jsonify(group), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/servers/<server_id>/group', methods=['PUT'])
def api_update_group(server_id):
    """Assign or clear a soaring group for a server (only when stopped)"""
    server = config.get_server(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    
    # Must be stopped to change group to keep UX simple
    if server.get('pid') and is_process_running(server['pid']):
        return jsonify({'error': 'Cannot change group while server is running. Stop the server first.'}), 400
    
    data = request.get_json() or {}
    group_id = (data.get('group_id') or '').strip()
    if not group_id:
        # Clear
        updated = config.update_server(server_id, {'group': None, 'group_id': None})
        return jsonify({'success': True, 'server': updated})
    
    # Validate group exists
    groups = config.get_all_groups()
    match = next((g for g in groups if g.get('id') == group_id), None)
    if not match:
        return jsonify({'error': 'Group not found'}), 404
    
    updated = config.update_server(server_id, {'group_id': match['id'], 'group': match['name']})
    return jsonify({'success': True, 'server': updated})


# ============================================================================
# Dashboard HTML Template
# ============================================================================

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Condor Map Dedicated Server Control Panel</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
    <style>
        body {
            background: linear-gradient(135deg, #e0e7ff 0%, #f3f4f6 100%);
            min-height: 100vh;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        
        .navbar {
            background: rgba(255, 255, 255, 0.95) !important;
            backdrop-filter: blur(10px);
            box-shadow: 0 2px 20px rgba(0,0,0,0.1);
        }
        
        .navbar-brand {
            font-weight: 700;
            font-size: 1.4rem;
            color: #667eea !important;
        }
        
        .nav-link {
            color: #666 !important;
            font-weight: 500;
            transition: color 0.3s;
        }
        
        .nav-link:hover {
            color: #667eea !important;
        }
        
        .container-main {
            margin-top: 2rem;
            margin-bottom: 2rem;
        }
        
        .card {
            border: none;
            border-radius: 15px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
            background: white;
        }
        
        .card-header {
            background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
            color: white;
            border-radius: 15px 15px 0 0 !important;
            padding: 1.5rem;
            font-weight: 600;
            font-size: 1.2rem;
        }
        
        .card-header-purple {
            background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
            color: white;
            border-radius: 15px 15px 0 0 !important;
            padding: 1.5rem;
            font-weight: 600;
            font-size: 1.2rem;
        }
        
        .table {
            margin-bottom: 0;
        }
        
        .table thead th {
            border-bottom: 2px solid #dee2e6;
            font-weight: 600;
            color: #495057;
            padding: 1rem;
        }
        
        .table tbody td {
            vertical-align: middle;
            padding: 1rem;
        }
        
        .status-led {
            width: 14px;
            height: 14px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 8px;
            box-shadow: 0 0 8px rgba(0,0,0,0.2);
        }
        
        .status-off {
            background: #6c757d;
        }
        
        .status-listening {
            background: #28a745;
            box-shadow: 0 0 12px rgba(40, 167, 69, 0.6);
        }
        
        .status-transmitting {
            background: #28a745;
            animation: pulse 1s infinite;
            box-shadow: 0 0 12px rgba(40, 167, 69, 0.8);
        }
        
        .status-error {
            background: #dc3545;
            box-shadow: 0 0 12px rgba(220, 53, 69, 0.6);
        }
        
        .status-starting {
            background: #ffc107;
            animation: pulse 1s infinite;
            box-shadow: 0 0 12px rgba(255, 193, 7, 0.8);
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }
        
        .btn-action {
            padding: 0.4rem 1rem;
            font-size: 0.9rem;
            border-radius: 8px;
            font-weight: 500;
            transition: all 0.3s;
        }
        
        .btn-success {
            background: #28a745;
            border: none;
        }
        
        .btn-success:hover {
            background: #218838;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(40, 167, 69, 0.4);
        }
        
        .btn-danger {
            background: #dc3545;
            border: none;
        }
        
        .btn-danger:hover {
            background: #c82333;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(220, 53, 69, 0.4);
        }
        
        .btn-secondary {
            background: #6c757d;
            border: none;
        }
        
        .btn-secondary:hover {
            background: #5a6268;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(108, 117, 125, 0.4);
        }
        
        .btn-warning {
            background: #ffc107;
            border: none;
            color: #000;
        }
        
        .btn-warning:hover {
            background: #e0a800;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(255, 193, 7, 0.4);
            color: #000;
        }
        
        .add-server-section {
            background: #f8f9fa;
            padding: 2rem;
            border-radius: 12px;
            margin-top: 2rem;
        }
        
        .add-server-section h5 {
            color: #495057;
            font-weight: 600;
            margin-bottom: 1.5rem;
        }
        
        .form-control {
            border-radius: 8px;
            border: 2px solid #e0e0e0;
            padding: 0.6rem 1rem;
            transition: border-color 0.3s;
        }
        
        .form-control:focus {
            border-color: #667eea;
            box-shadow: 0 0 0 0.2rem rgba(102, 126, 234, 0.25);
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: none;
            padding: 0.6rem 2rem;
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.3s;
        }
        
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
        }
        
        .empty-state {
            text-align: center;
            padding: 3rem;
            color: #6c757d;
        }
        
        .empty-state i {
            font-size: 4rem;
            margin-bottom: 1rem;
            opacity: 0.3;
        }
        
        .badge {
            padding: 0.5rem 1rem;
            border-radius: 8px;
            font-weight: 500;
        }
        
        .alert {
            border-radius: 12px;
            border: none;
        }
        
        #alert-container {
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 9999;
            max-width: 400px;
        }
        
        #alert-container .alert {
            margin-bottom: 10px;
            animation: slideInUp 0.3s ease-out;
        }
        
        @keyframes slideInUp {
            from {
                transform: translateY(100px);
                opacity: 0;
            }
            to {
                transform: translateY(0);
                opacity: 1;
            }
        }
        
        @keyframes spin {
            from {
                transform: rotate(0deg);
            }
            to {
                transform: rotate(360deg);
            }
        }
        
        .spin {
            animation: spin 1s linear infinite;
        }
        
        .btn-refresh {
            background: linear-gradient(135deg, #e9ecef 0%, #dee2e6 100%);
            color: #495057;
            border: none;
            padding: 0.5rem 1.2rem;
            border-radius: 8px;
            font-weight: 500;
            transition: all 0.3s;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        
        .btn-refresh:hover {
            background: linear-gradient(135deg, #dee2e6 0%, #ced4da 100%);
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            color: #495057;
        }
        
        .btn-refresh:active {
            transform: translateY(0);
            box-shadow: 0 2px 6px rgba(0,0,0,0.1);
        }
        
        .btn-add-active {
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            color: white;
            border: none;
            padding: 0.4rem 1rem;
            border-radius: 6px;
            font-weight: 500;
            font-size: 0.875rem;
            transition: all 0.3s;
            box-shadow: 0 2px 6px rgba(40, 167, 69, 0.3);
        }
        
        .btn-add-active:hover:not(:disabled) {
            background: linear-gradient(135deg, #218838 0%, #1ea87a 100%);
            transform: translateY(-2px);
            box-shadow: 0 4px 10px rgba(40, 167, 69, 0.4);
            color: white;
        }
        
        .btn-add-active:disabled {
            background: linear-gradient(135deg, #e9ecef 0%, #dee2e6 100%);
            color: #6c757d;
            box-shadow: none;
        }
        
        .btn-success:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .group-required-warning {
            color: #dc3545;
            font-size: 0.75rem;
            font-weight: 500;
            margin-top: 0.25rem;
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-light">
        <div class="container-fluid">
            <a class="navbar-brand" href="/">
                <i class="bi bi-radar"></i> Condor Map Dedicated Server Control Panel
            </a>
            <div class="ms-auto">
                <a class="nav-link d-inline-block" href="#" onclick="showInstructions(); return false;">
                    <i class="bi bi-info-circle"></i> Instructions
                </a>
                <a class="nav-link d-inline-block" href="#" onclick="showHelp(); return false;">
                    <i class="bi bi-question-circle"></i> Get Help
                </a>
            </div>
        </div>
    </nav>

    <div class="container container-main">
        <div class="card">
            <div class="card-header">
                <i class="bi bi-server"></i> Active Servers
            </div>
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead>
                            <tr>
                                <th>Server Name</th>
                                <th>Group</th>
                                <th>Landscape</th>
                                <th>Port</th>
                                <th>Path</th>
                                <th>PID</th>
                                <th style="width: 150px;">Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="servers-table-body">
                            <tr class="empty-state">
                                <td colspan="8">
                                    <i class="bi bi-inbox"></i>
                                    <p>No servers configured yet. Add one below to get started!</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="card mt-4">
            <div class="card-header d-flex justify-content-between align-items-center">
                <span><i class="bi bi-search"></i> Detected Servers</span>
                <button class="btn btn-refresh" onclick="refreshDetectedServers()" title="Refresh detected servers">
                    <i class="bi bi-arrow-clockwise"></i> Refresh
                </button>
            </div>
            <div class="card-body p-0">
                <p class="text-muted small px-3 pt-3 mb-2">
                    <i class="bi bi-info-circle"></i> Servers detected from DSHelper configuration
                </p>
                <div class="table-responsive">
                    <table class="table table-hover mb-0">
                        <thead>
                            <tr>
                                <th style="width: 60px;">ID</th>
                                <th>DSHelper Name</th>
                                <th>Condor Server Name</th>
                                <th>Port</th>
                                <th>Path to Dedicated Server</th>
                                <th style="width: 180px;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="detected-servers-table-body">
                            <tr class="empty-state">
                                <td colspan="6" class="text-center py-4">
                                    <i class="bi bi-hourglass-split"></i>
                                    <p>Loading detected servers...</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="card mt-4">
            <div class="card-header d-flex justify-content-between align-items-center">
                <span><i class="bi bi-people"></i> Soaring Group</span>
                <button class="btn btn-refresh" onclick="refreshGroups()" title="Refresh groups">
                    <i class="bi bi-arrow-clockwise"></i> Refresh
                </button>
            </div>
            <div class="card-body">
                <p class="text-muted small mb-3">
                    <i class="bi bi-info-circle"></i> A soaring group is a collection of servers running the same or similar task. If you have a contest on Condor Club but run multiple servers (different times or A/B/C servers), groups let you manage them under one name. If you only have one server you still nee
                </p>
                <div class="row g-3 align-items-end">
                    <div class="col-md-6">
                        <label for="group-name-input" class="form-label">Group Name</label>
                        <input type="text" id="group-name-input" class="form-control" placeholder="e.g., Contest Day 1 Group A/B/C" />
                    </div>
                    <div class="col-md-3">
                        <button class="btn btn-primary w-100" onclick="addGroup()">
                            <i class="bi bi-plus-circle"></i> Add Group
                        </button>
                    </div>
                </div>
                <div class="table-responsive mt-3">
                    <table class="table table-hover mb-0">
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>Members</th>
                            </tr>
                        </thead>
                        <tbody id="groups-table-body">
                            <tr class="empty-state">
                                <td colspan="2" class="text-center py-4">
                                    <i class="bi bi-hourglass-split"></i>
                                    <p>Loading groups...</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="card mt-4">
            <div class="card-header d-flex justify-content-between align-items-center">
                <span><i class="bi bi-map"></i> Detected Landscapes</span>
                <button class="btn btn-refresh" onclick="refreshDetectedLandscapes()" title="Refresh detected landscapes">
                    <i class="bi bi-arrow-clockwise"></i> Refresh
                </button>
            </div>
            <div class="card-body p-0">
                <p class="text-muted small px-3 pt-3 mb-2">
                    <i class="bi bi-info-circle"></i> Landscapes detected from C:\Condor3\Landscapes
                </p>
                <div class="table-responsive">
                    <table class="table table-hover mb-0">
                        <thead>
                            <tr>
                                <th>Landscape Name</th>
                                <th>File Location</th>
                            </tr>
                        </thead>
                        <tbody id="detected-landscapes-table-body">
                            <tr class="empty-state">
                                <td colspan="2" class="text-center py-4">
                                    <i class="bi bi-hourglass-split"></i>
                                    <p>Loading detected landscapes...</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <!-- Alert container at bottom right -->
    <div id="alert-container"></div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let servers = [];
        let landscapes = [];
        let detectedServers = [];
        let detectedLandscapes = [];
        let groups = [];
        
        // Fetch detected landscapes with paths
        async function fetchDetectedLandscapes() {
            try {
                const response = await fetch('/api/landscapes/details');
                detectedLandscapes = await response.json();
                renderDetectedLandscapes();
            } catch (error) {
                console.error('Error fetching detected landscapes:', error);
                const tbody = document.getElementById('detected-landscapes-table-body');
                tbody.innerHTML = `
                    <tr class="empty-state">
                        <td colspan="2" class="text-center py-4 text-danger">
                            <i class="bi bi-exclamation-triangle"></i>
                            <p>Error loading detected landscapes</p>
                        </td>
                    </tr>
                `;
            }
        }
        
        // Render detected landscapes table
        function renderDetectedLandscapes() {
            const tbody = document.getElementById('detected-landscapes-table-body');
            
            if (detectedLandscapes.length === 0) {
                tbody.innerHTML = `
                    <tr class="empty-state">
                        <td colspan="2" class="text-center py-4">
                            <i class="bi bi-inbox"></i>
                            <p>No landscapes detected in C:\\Condor3\\Landscapes</p>
                        </td>
                    </tr>
                `;
                return;
            }
            
            tbody.innerHTML = detectedLandscapes.map(landscape => {
                return `
                    <tr>
                        <td><strong>${escapeHtml(landscape.name)}</strong></td>
                        <td><code class="small">${escapeHtml(landscape.path)}</code></td>
                    </tr>
                `;
            }).join('');
        }
        
        // Refresh detected landscapes
        async function refreshDetectedLandscapes() {
            const tbody = document.getElementById('detected-landscapes-table-body');
            tbody.innerHTML = `
                <tr class="empty-state">
                    <td colspan="2" class="text-center py-4">
                        <i class="bi bi-arrow-clockwise spin"></i>
                        <p>Refreshing...</p>
                    </td>
                </tr>
            `;
            await fetchDetectedLandscapes();
            showAlert('Detected landscapes refreshed!', 'info');
        }
        
        // Fetch detected servers from DSHelper
        async function fetchDetectedServers() {
            try {
                const response = await fetch('/api/dshelper/servers');
                detectedServers = await response.json();
                renderDetectedServers();
            } catch (error) {
                console.error('Error fetching detected servers:', error);
                const tbody = document.getElementById('detected-servers-table-body');
                tbody.innerHTML = `
                    <tr class="empty-state">
                        <td colspan="5" class="text-center py-4 text-danger">
                            <i class="bi bi-exclamation-triangle"></i>
                            <p>Error loading detected servers</p>
                        </td>
                    </tr>
                `;
            }
        }
        
        // Check if a detected server is already in active servers (by port)
        function isServerActive(port) {
            return servers.some(s => s.port === port);
        }
        
        // Render detected servers table
        function renderDetectedServers() {
            const tbody = document.getElementById('detected-servers-table-body');
            
            if (detectedServers.length === 0) {
                tbody.innerHTML = `
                    <tr class="empty-state">
                        <td colspan="6" class="text-center py-4">
                            <i class="bi bi-inbox"></i>
                            <p>No servers detected from DSHelper</p>
                        </td>
                    </tr>
                `;
                return;
            }
            
            tbody.innerHTML = detectedServers.map(server => {
                const filename = server.filename || 'N/A';
                const isActive = isServerActive(server.port);
                
                return `
                    <tr>
                        <td class="text-center"><strong>${server.id !== null ? server.id : '—'}</strong></td>
                        <td>${escapeHtml(server.displayname || 'N/A')}</td>
                        <td>${escapeHtml(server.server_name || 'N/A')}</td>
                        <td><span class="badge bg-secondary">${server.port || 'N/A'}</span></td>
                        <td><code class="small">${escapeHtml(filename)}</code></td>
                        <td>
                            <button class="btn btn-add-active" onclick='addToActive(${JSON.stringify(server.server_name)}, ${server.port}, ${JSON.stringify(server.filename || "")})' ${isActive ? 'disabled' : ''} style="${isActive ? 'opacity: 0.5; cursor: not-allowed;' : ''}">
                                <i class="bi bi-plus-circle"></i> Add to Active
                            </button>
                        </td>
                    </tr>
                `;
            }).join('');
        }
        
        // Add detected server to active servers
        async function addToActive(serverName, port, path) {
            console.log('[DEBUG-JS] ========================================');
            console.log('[DEBUG-JS] addToActive called');
            console.log('[DEBUG-JS] serverName:', serverName);
            console.log('[DEBUG-JS] port:', port);
            console.log('[DEBUG-JS] path (raw):', path);
            console.log('[DEBUG-JS] path type:', typeof path);
            console.log('[DEBUG-JS] path length:', path ? path.length : 0);
            if (path) {
                console.log('[DEBUG-JS] path char codes:', Array.from(path).map(c => c.charCodeAt(0)));
            }
            
            try {
                const payload = {
                    server_name: serverName,
                    port: port,
                    landscape: 'AA3',
                    path: path || null
                };
                
                console.log('[DEBUG-JS] Payload to send:', payload);
                console.log('[DEBUG-JS] Payload JSON:', JSON.stringify(payload));
                console.log('[DEBUG-JS] ========================================');
                
                // Default to AA3 landscape - user can change it later
                const response = await fetch('/api/servers', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                
                if (response.ok) {
                    showAlert(`Server "${serverName}" added to Active Servers!`, 'success');
                    await fetchServers();
                    renderDetectedServers(); // Re-render to disable button
                } else {
                    const error = await response.json();
                    showAlert(error.error || 'Failed to add server', 'danger');
                }
            } catch (error) {
                showAlert('Error: ' + error.message, 'danger');
            }
        }
        
        // Refresh detected servers
        async function refreshDetectedServers() {
            const tbody = document.getElementById('detected-servers-table-body');
            tbody.innerHTML = `
                <tr class="empty-state">
                    <td colspan="6" class="text-center py-4">
                        <i class="bi bi-arrow-clockwise spin"></i>
                        <p>Refreshing...</p>
                    </td>
                </tr>
            `;
            await fetchDetectedServers();
            showAlert('Detected servers refreshed!', 'info');
        }
        
        // Fetch landscapes on load
        async function fetchLandscapes() {
            try {
                const response = await fetch('/api/landscapes');
                const data = await response.json();
                landscapes = data.landscapes;
                // No dropdown to populate anymore - landscapes are used in renderServers()
            } catch (error) {
                console.error('Error fetching landscapes:', error);
                // Set default if fetch fails
                landscapes = ['AA3'];
            }
        }
        
        // Fetch servers on load
        async function fetchServers() {
            try {
                const response = await fetch('/api/servers');
                servers = await response.json();
                renderServers();
            } catch (error) {
                showAlert('Error fetching servers: ' + error.message, 'danger');
            }
        }
        
        // Render servers table
        function renderServers() {
            const tbody = document.getElementById('servers-table-body');
            
            if (servers.length === 0) {
                tbody.innerHTML = `
                    <tr class="empty-state">
                        <td colspan="8">
                            <i class="bi bi-inbox"></i>
                            <p>No servers configured yet. Add one below to get started!</p>
                        </td>
                    </tr>
                `;
                return;
            }
            
            tbody.innerHTML = servers.map(server => {
                // Handle countdown status
                let statusClass, statusText, isRunning, isCountdown;
                if (server.status.startsWith('starting_')) {
                    const countdown = server.status.split('_')[1];
                    statusClass = 'status-starting';
                    statusText = `Starting in ${countdown}s`;
                    isRunning = true; // Disable controls during countdown
                    isCountdown = true;
                } else {
                    statusClass = `status-${server.status}`;
                    statusText = server.status.charAt(0).toUpperCase() + server.status.slice(1);
                    isRunning = server.status !== 'off';
                    isCountdown = false;
                }
                const pid = server.pid || '—';
                
                const landscape = server.landscape || 'AA3';
                const landscapeDisabled = isRunning ? 'disabled' : '';
                const landscapeTitle = isRunning ? 'Stop server to change landscape' : 'Click to change landscape';
                
                const groupId = server.group_id || '';
                const groupDisabled = isRunning ? 'disabled' : '';
                const groupTitle = isRunning ? 'Stop server to change group' : 'Click to assign group';
                
                const path = server.path || 'N/A';
                const hasGroup = !!server.group;
                
                return `
                    <tr>
                        <td><strong>${escapeHtml(server.server_name)}</strong></td>
                        <td>
                            <select class="form-select form-select-sm" ${groupDisabled} title="${groupTitle}"
                                    onchange="updateGroup('${server.id}', this.value)"
                                    style="min-width: 140px; ${isRunning ? 'opacity: 0.6; cursor: not-allowed;' : ''}">
                                <option value="">— None —</option>
                                ${groups.map(g => `<option value="${g.id}"${g.id === groupId ? ' selected' : ''}>${escapeHtml(g.name)}</option>`).join('')}
                            </select>
                        </td>
                        <td>
                            <select class="form-select form-select-sm" ${landscapeDisabled} title="${landscapeTitle}" 
                                    onchange="updateLandscape('${server.id}', this.value)" 
                                    style="min-width: 120px; ${isRunning ? 'opacity: 0.6; cursor: not-allowed;' : ''}">
                                ${landscapes.map(l => `<option value="${l}"${l === landscape ? ' selected' : ''}>${l}</option>`).join('')}
                            </select>
                        </td>
                        <td><span class="badge bg-secondary">${server.port}</span></td>
                        <td><code class="small">${escapeHtml(path)}</code></td>
                        <td><code>${pid}</code></td>
                        <td>
                            <span class="status-led ${statusClass}"></span>
                            ${statusText}
                        </td>
                        <td>
                            ${isRunning ? 
                                `<button class="btn btn-${isCountdown ? 'warning' : 'danger'} btn-action btn-sm" onclick="stopServer('${server.id}')">
                                    <i class="bi bi-${isCountdown ? 'x-circle' : 'stop-circle'}"></i> ${isCountdown ? 'Cancel' : 'Stop'}
                                </button>` :
                                `<div>
                                    <button class="btn btn-success btn-action btn-sm" onclick="startServer('${server.id}')" ${hasGroup ? '' : 'disabled'}>
                                        <i class="bi bi-play-circle"></i> Start
                                    </button>
                                    ${!hasGroup ? '<div class="group-required-warning"><i class="bi bi-exclamation-triangle"></i> Select a Group first</div>' : ''}
                                </div>`
                            }
                            <button class="btn btn-secondary btn-action btn-sm" onclick="deleteServer('${server.id}')">
                                <i class="bi bi-x-circle"></i> Remove
                            </button>
                        </td>
                    </tr>
                `;
            }).join('');
        }

        // Groups API
        async function fetchGroups() {
            try {
                const response = await fetch('/api/groups');
                const data = await response.json();
                groups = data.groups || [];
                renderGroups();
                // Also re-render servers to refresh dropdowns
                renderServers();
            } catch (e) {
                console.error('Error fetching groups', e);
            }
        }

        function renderGroups() {
            const tbody = document.getElementById('groups-table-body');
            if (!tbody) return;
            if (!groups || groups.length === 0) {
                tbody.innerHTML = `
                    <tr class="empty-state">
                        <td colspan="2" class="text-center py-4">
                            <i class="bi bi-inbox"></i>
                            <p>No groups yet. Create one to organize servers.</p>
                        </td>
                    </tr>
                `;
                return;
            }
            // Compute member counts from current servers
            const counts = {};
            (servers || []).forEach(s => {
                if (s.group_id) counts[s.group_id] = (counts[s.group_id] || 0) + 1;
            });
            tbody.innerHTML = groups.map(g => `
                <tr>
                    <td><strong>${escapeHtml(g.name)}</strong></td>
                    <td>${counts[g.id] || 0}</td>
                </tr>
            `).join('');
        }

        async function addGroup() {
            const input = document.getElementById('group-name-input');
            const name = (input?.value || '').trim();
            if (!name) { showAlert('Enter a group name', 'warning'); return; }
            try {
                const resp = await fetch('/api/groups', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name})});
                const result = await resp.json();
                if (resp.ok) {
                    showAlert('Group added!', 'success');
                    input.value = '';
                    await fetchGroups();
                } else {
                    showAlert(result.error || 'Failed to add group', 'danger');
                }
            } catch (e) {
                showAlert('Error: ' + e.message, 'danger');
            }
        }

        async function refreshGroups() {
            const tbody = document.getElementById('groups-table-body');
            if (tbody) {
                tbody.innerHTML = `
                    <tr class="empty-state">
                        <td colspan="2" class="text-center py-4">
                            <i class="bi bi-arrow-clockwise spin"></i>
                            <p>Refreshing...</p>
                        </td>
                    </tr>
                `;
            }
            await fetchGroups();
            showAlert('Groups refreshed!', 'info');
        }

        async function updateGroup(serverId, groupId) {
            try {
                const resp = await fetch(`/api/servers/${serverId}/group`, { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({group_id: groupId})});
                const result = await resp.json();
                if (resp.ok) {
                    showAlert('Group updated', 'success');
                    await fetchServers();
                    renderGroups();
                } else {
                    showAlert(result.error || 'Failed to update group', 'danger');
                    await fetchServers();
                }
            } catch (e) {
                showAlert('Error: ' + e.message, 'danger');
                await fetchServers();
            }
        }
        
        // Start server
        async function startServer(serverId) {
            try {
                const response = await fetch(`/api/servers/${serverId}/start`, {method: 'POST'});
                const result = await response.json();
                
                if (response.ok) {
                    showAlert('Server started successfully!', 'success');
                    fetchServers();
                } else {
                    showAlert(result.error || 'Failed to start server', 'danger');
                }
            } catch (error) {
                showAlert('Error: ' + error.message, 'danger');
            }
        }
        
        // Stop server or cancel countdown
        async function stopServer(serverId) {
            try {
                const response = await fetch(`/api/servers/${serverId}/stop`, {method: 'POST'});
                const result = await response.json();
                
                if (response.ok) {
                    const message = result.message || 'Server stopped successfully!';
                    const alertType = message.includes('cancelled') ? 'warning' : 'info';
                    showAlert(message, alertType);
                    fetchServers();
                } else {
                    showAlert(result.error || 'Failed to stop server', 'danger');
                }
            } catch (error) {
                showAlert('Error: ' + error.message, 'danger');
            }
        }
        
        // Delete server
        async function deleteServer(serverId) {
            if (!confirm('Are you sure you want to remove this server?')) return;
            
            try {
                const response = await fetch(`/api/servers/${serverId}`, {method: 'DELETE'});
                
                if (response.ok) {
                    showAlert('Server deleted successfully!', 'info');
                    await fetchServers();
                    renderDetectedServers(); // Update detected servers to show "Add to Active" button
                } else {
                    showAlert('Failed to delete server', 'danger');
                }
            } catch (error) {
                showAlert('Error: ' + error.message, 'danger');
            }
        }
        
        // Update landscape
        async function updateLandscape(serverId, landscape) {
            try {
                const response = await fetch(`/api/servers/${serverId}/landscape`, {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({landscape: landscape})
                });
                
                if (response.ok) {
                    showAlert('Landscape updated successfully!', 'success');
                    fetchServers();
                } else {
                    const error = await response.json();
                    showAlert(error.error || 'Failed to update landscape', 'danger');
                    fetchServers(); // Refresh to revert dropdown
                }
            } catch (error) {
                showAlert('Error: ' + error.message, 'danger');
                fetchServers(); // Refresh to revert dropdown
            }
        }
        
        // Show alert
        function showAlert(message, type) {
            const alertContainer = document.getElementById('alert-container');
            const alert = document.createElement('div');
            alert.className = `alert alert-${type} alert-dismissible fade show`;
            alert.innerHTML = `
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;
            alertContainer.appendChild(alert);
            
            setTimeout(() => alert.remove(), 5000);
        }
        
        // Show instructions
        function showInstructions() {
            alert('Instructions:\\n\\n1. Add a server by entering a name and port\\n2. Click Start to begin sniffing UDP packets\\n3. Monitor status with the LED indicator\\n4. Click Stop to terminate the sniffer\\n5. Delete servers you no longer need\\n\\nNote: This application may require administrator privileges to capture network packets.');
        }
        
        // Show help
        function showHelp() {
            alert('Need Help?\\n\\nFor support, please:\\n- Check that you are running as Administrator\\n- Ensure the sniffer script is in the same directory\\n- Verify ports are not already in use\\n- Check that scapy and psutil are installed\\n\\nFor more information, visit the project documentation.');
        }
        
        // Escape HTML
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Smart auto-refresh: 1s during countdown, 10s when stable
        let refreshInterval = null;
        let currentRefreshRate = 1000;
        let lastCountdownEndTime = null;
        
        function smartRefresh() {
            fetchServers().then(() => {
                // Check if any server is in countdown/starting state
                const hasCountdown = servers.some(s => s.status.startsWith('starting_'));
                
                // Track when countdown ends
                if (hasCountdown) {
                    lastCountdownEndTime = null; // Reset if still counting down
                } else if (lastCountdownEndTime === null && currentRefreshRate === 1000) {
                    // Countdown just ended, record the time
                    lastCountdownEndTime = Date.now();
                    console.log('All servers started. Will switch to 10s refresh in 5 seconds...');
                }
                
                // Determine new refresh rate
                let newRefreshRate = 1000;
                if (!hasCountdown && lastCountdownEndTime !== null) {
                    const timeSinceEnd = Date.now() - lastCountdownEndTime;
                    if (timeSinceEnd >= 5000) {
                        newRefreshRate = 10000; // Switch to 10s after 5s delay
                    }
                }
                
                // Update interval if rate changed
                if (newRefreshRate !== currentRefreshRate) {
                    currentRefreshRate = newRefreshRate;
                    clearInterval(refreshInterval);
                    refreshInterval = setInterval(smartRefresh, currentRefreshRate);
                    console.log(`Refresh rate changed to ${currentRefreshRate}ms`);
                }
            });
        }
        
        // Start with 1s refresh (for initial countdown)
        refreshInterval = setInterval(smartRefresh, 1000);
        
        // Initial load
        fetchLandscapes();
        fetchGroups();
        fetchServers();
        fetchDetectedServers();
        fetchDetectedLandscapes();
    </script>
</body>
</html>
"""


# ============================================================================
# Main Entry Point
# ============================================================================

def auto_start_server_with_countdown(server, delay_seconds):
    """Auto-start a server after a countdown delay"""
    server_id = server['id']
    server_name = server['server_name']
    
    print(f"[AUTO-START] {server_name} will start in {delay_seconds} seconds...")
    
    # Countdown loop
    for remaining in range(delay_seconds, 0, -1):
        with auto_start_lock:
            # Check if countdown was cancelled
            if server_id not in auto_start_countdowns:
                print(f"[AUTO-START] {server_name}: Countdown cancelled by user")
                return
            auto_start_countdowns[server_id] = remaining
        print(f"[AUTO-START] {server_name}: Starting in {remaining}...")
        time.sleep(1)
    
    # Check one more time before starting
    with auto_start_lock:
        if server_id not in auto_start_countdowns:
            print(f"[AUTO-START] {server_name}: Countdown cancelled by user")
            return
        # Remove from countdown tracking
        auto_start_countdowns.pop(server_id, None)
    
    # Start the server
    print(f"[AUTO-START] {server_name}: Starting now!")
    result = start_sniffer(server)
    
    if result['success']:
        print(f"[AUTO-START] {server_name}: Successfully started (PID: {result['pid']})")
    else:
        print(f"[AUTO-START] {server_name}: Failed to start - {result.get('error', 'Unknown error')}")


def start_auto_start_sequence():
    """Start all servers from config with staggered delays"""
    servers = config.get_all_servers()
    
    if not servers:
        print("[AUTO-START] No servers configured. Skipping auto-start.")
        return
    
    print("\n" + "=" * 60)
    print(f"[AUTO-START] Found {len(servers)} server(s) in config")
    print("=" * 60)
    
    # Start each server in a separate thread with staggered delays
    for index, server in enumerate(servers):
        # Skip servers with no Soaring Group set
        if not server.get('group'):
            print(f"[AUTO-START] {server['server_name']}: Skipping (no Soaring Group assigned)")
            continue
        # Skip servers that are already running
        if server.get('pid') and is_process_running(server['pid']):
            print(f"[AUTO-START] {server['server_name']}: Already running (PID: {server['pid']}), skipping")
            continue
        
        # Calculate delay: first server at 5s, second at 10s, third at 15s, etc.
        delay = (index + 1) * 5
        
        # Initialize countdown tracking
        with auto_start_lock:
            auto_start_countdowns[server['id']] = delay
        
        # Start countdown thread
        thread = threading.Thread(
            target=auto_start_server_with_countdown,
            args=(server, delay),
            daemon=True
        )
        thread.start()
    
    print("=" * 60 + "\n")


def print_reminder(host, port, stop_event):
    """Print periodic reminder to keep window open and visit dashboard"""
    while not stop_event.is_set():
        # Get current server status
        servers = config.get_all_servers()
        
        # Build status message
        print("\n" + "=" * 80)
        print("CONDOR MAP CONTROL PANEL - Keep this window open!")
        print("=" * 80)
        print(f"Dashboard: http://{host}:{port}")
        print(f"Purpose: Sending UDP data to condormap.com for real-time tracking")
        print("-" * 80)
        
        if servers:
            print("Active Servers:")
            for server in servers:
                status = get_process_status(server)
                pid = server.get('pid', 'N/A')
                landscape = server.get('landscape', 'N/A')
                port_num = server.get('port', 'N/A')
                group = server.get('group', 'None')
                path = server.get('path', 'N/A')
                
                status_icon = "●" if status in ['listening', 'transmitting'] else "○"
                server_name = server['server_name']
                print(f"  {status_icon} {server_name}")
                print(f"    Group: {group} | Landscape: {landscape} | Port: {port_num}")
                # Print path directly - it should already have backslashes from the database
                print("    Path: " + str(path))
                print(f"    PID: {pid} | Status: {status.upper()}")
        else:
            print("No servers configured. Visit dashboard to add servers.")
        
        print("=" * 80 + "\n")
        stop_event.wait(30)  # Wait 30 seconds or until stop event is set


if __name__ == '__main__':
    try:
        # Initialize config manager
        config = ConfigManager()
        
        # Check for psutil
        if not psutil:
            print("[!] Warning: psutil is not installed. Some features may not work correctly.")
            print("[!] Install with: pip install psutil")
        
        # Get host and port from environment or use defaults
        host = os.getenv('DASHBOARD_HOST', '127.0.0.1')
        try:
            port = int(os.getenv('DASHBOARD_PORT', '5001'))
        except ValueError:
            port = 5001
        
        print("=" * 80)
        print("CONDOR MAP DEDICATED SERVER CONTROL PANEL")
        print("=" * 80)
        print(f"Dashboard: http://{host}:{port}")
        print(f"Purpose: Sending UDP data to condormap.com for real-time tracking")
        print("Press Ctrl+C to stop")
        print("=" * 80)
        
        # Start auto-start sequence for configured servers
        start_auto_start_sequence()
        
        # Start reminder thread
        stop_event = threading.Event()
        reminder_thread = threading.Thread(target=print_reminder, args=(host, port, stop_event), daemon=True)
        reminder_thread.start()
        
        app.run(host=host, port=port, debug=False, threaded=True)
    
    except ImportError as e:
        print("\n" + "=" * 60)
        print("ERROR: Missing required package")
        print("=" * 60)
        print(f"Import error: {e}")
        print("\nPlease install required packages:")
        print("  pip install -r requirements.txt")
        print("\nOr install individually:")
        print("  pip install flask psutil")
        print("=" * 60)
        input("\nPress Enter to close this window...")
    
    except Exception as e:
        print("\n" + "=" * 60)
        print("ERROR: Application crashed")
        print("=" * 60)
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {e}")
        print("\nPlease check:")
        print("  - All required packages are installed (pip install -r requirements.txt)")
        print("  - Port 5001 is not already in use")
        print("  - You have necessary permissions")
        print("=" * 60)
        input("\nPress Enter to close this window...")
    
    except KeyboardInterrupt:
        print("\n\nShutting down gracefully...")
        print("Dashboard stopped.")
