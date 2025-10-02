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
CONFIG_FILE = "config.json"
LANDSCAPES_PATH = r"C:\Condor3\Landscapes"


# ============================================================================
# Landscape Management
# ============================================================================

def get_available_landscapes():
    """Scan C:\Condor3\Landscapes for available landscape folders with .trn files"""
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


# ============================================================================
# Configuration Manager
# ============================================================================

class ConfigManager:
    """Manages persistent configuration for servers"""
    
    def __init__(self, config_path=CONFIG_FILE):
        self.config_path = config_path
        self.data = {'servers': []}
        self.load()
    
    def load(self):
        """Load configuration from JSON file"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    self.data = json.load(f)
                    if 'servers' not in self.data:
                        self.data['servers'] = []
            except Exception as e:
                print(f"[!] Error loading config: {e}")
                self.data = {'servers': []}
        else:
            self.data = {'servers': []}
    
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
    
    def add_server(self, server_name, port, landscape='AA3'):
        """Add a new server configuration"""
        server = {
            'id': str(uuid.uuid4()),
            'server_name': server_name,
            'port': port,
            'landscape': landscape,
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
    
    # Check hex log file activity to determine transmitting status
    try:
        # Check 3f00/3f01 identity log files (most reliable indicator)
        log_pattern = f"{pid}_hex_log_3f00_3f01_*.txt"
        log_files = glob.glob(log_pattern)
        
        if not log_files:
            # Try 8006 ACK log files as fallback
            log_pattern = f"{pid}_hex_log_8006_*.txt"
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
                return 'idle'
        else:
            return 'idle'
    except Exception:
        return 'idle'


def start_sniffer(server):
    """Start a sniffer subprocess for the given server"""
    try:
        # Check if port is valid
        port = server['port']
        if not (1024 <= port <= 65535):
            return {'success': False, 'error': 'Invalid port number (must be 1024-65535)'}
        
        # Check if already running
        if server.get('pid') and is_process_running(server['pid']):
            return {'success': False, 'error': 'Server is already running'}
        
        # Get landscape (default to AA3 for backward compatibility)
        landscape = server.get('landscape', 'AA3')
        
        # Build command
        cmd = [
            sys.executable,
            'sniffAndDecodeUDP_toExpress_viaFlask.py',
            '--port', str(port),
            '--server-name', server['server_name'],
            '--landscape', landscape
        ]
        
        # Create logs directory if it doesn't exist
        os.makedirs('logs', exist_ok=True)
        
        # Redirect output to log files to prevent pipe blocking
        stdout_log = open(os.path.join('logs', f'dashboard_{port}_stdout.log'), 'w')
        stderr_log = open(os.path.join('logs', f'dashboard_{port}_stderr.log'), 'w')
        
        # Start process with simple Popen - just like running from command line
        process = subprocess.Popen(
            cmd,
            stdout=stdout_log,
            stderr=stderr_log
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
                with open(os.path.join('logs', f'dashboard_{port}_stderr.log'), 'r') as f:
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
            'status': 'idle',
            'last_started': datetime.now(timezone.utc).isoformat(),
            'last_error': None
        })
        
        return {'success': True, 'pid': pid}
    
    except FileNotFoundError:
        return {'success': False, 'error': 'sniffAndDecodeUDP_toExpress_viaFlask.py not found'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


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
        server['status'] = get_process_status(server)
    
    # Save updated statuses
    config.save()
    
    return jsonify(servers)


@app.route('/api/servers', methods=['POST'])
def api_add_server():
    """Add a new server"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    server_name = data.get('server_name', '').strip()
    port = data.get('port')
    landscape = data.get('landscape', 'AA3').strip()
    
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
    
    server = config.add_server(server_name, port, landscape)
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
    """Stop a server's sniffer process"""
    server = config.get_server(server_id)
    
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    
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
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
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
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
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
        
        .status-idle {
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
                                <th>Landscape</th>
                                <th>Port</th>
                                <th>PID</th>
                                <th style="width: 150px;">Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="servers-table-body">
                            <tr class="empty-state">
                                <td colspan="6">
                                    <i class="bi bi-inbox"></i>
                                    <p>No servers configured yet. Add one below to get started!</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="add-server-section">
            <h5><i class="bi bi-plus-circle"></i> Add New Server</h5>
            <form id="add-server-form" class="row g-3">
                <div class="col-md-4">
                    <label for="server-name" class="form-label">Server Name</label>
                    <input type="text" class="form-control" id="server-name" placeholder="e.g., Condor Server 1" required>
                </div>
                <div class="col-md-3">
                    <label for="server-landscape" class="form-label">Landscape</label>
                    <select class="form-control" id="server-landscape" required>
                        <option value="">Loading...</option>
                    </select>
                </div>
                <div class="col-md-2">
                    <label for="server-port" class="form-label">Port</label>
                    <input type="number" class="form-control" id="server-port" placeholder="56288" min="1024" max="65535" required>
                </div>
                <div class="col-md-3 d-flex align-items-end">
                    <button type="submit" class="btn btn-primary w-100">
                        <i class="bi bi-plus-lg"></i> Add Server
                    </button>
                </div>
            </form>
        </div>
    </div>

    <!-- Alert container at bottom right -->
    <div id="alert-container"></div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let servers = [];
        let landscapes = [];
        
        // Fetch landscapes on load
        async function fetchLandscapes() {
            try {
                const response = await fetch('/api/landscapes');
                const data = await response.json();
                landscapes = data.landscapes;
                
                // Populate landscape dropdown
                const select = document.getElementById('server-landscape');
                if (landscapes.length === 0) {
                    select.innerHTML = '<option value="">No landscapes found in C:\\Condor3\\Landscapes</option>';
                } else {
                    select.innerHTML = landscapes.map(l => 
                        `<option value="${l}"${l === 'AA3' ? ' selected' : ''}>${l}</option>`
                    ).join('');
                }
            } catch (error) {
                console.error('Error fetching landscapes:', error);
                const select = document.getElementById('server-landscape');
                select.innerHTML = '<option value="AA3">AA3 (default)</option>';
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
                        <td colspan="6">
                            <i class="bi bi-inbox"></i>
                            <p>No servers configured yet. Add one below to get started!</p>
                        </td>
                    </tr>
                `;
                return;
            }
            
            tbody.innerHTML = servers.map(server => {
                const statusClass = `status-${server.status}`;
                const statusText = server.status.charAt(0).toUpperCase() + server.status.slice(1);
                const pid = server.pid || '—';
                const isRunning = server.status !== 'off';
                
                const landscape = server.landscape || 'AA3';
                const landscapeDisabled = isRunning ? 'disabled' : '';
                const landscapeTitle = isRunning ? 'Stop server to change landscape' : 'Click to change landscape';
                
                return `
                    <tr>
                        <td><strong>${escapeHtml(server.server_name)}</strong></td>
                        <td>
                            <select class="form-select form-select-sm" ${landscapeDisabled} title="${landscapeTitle}" 
                                    onchange="updateLandscape('${server.id}', this.value)" 
                                    style="min-width: 120px; ${isRunning ? 'opacity: 0.6; cursor: not-allowed;' : ''}">
                                ${landscapes.map(l => `<option value="${l}"${l === landscape ? ' selected' : ''}>${l}</option>`).join('')}
                            </select>
                        </td>
                        <td><span class="badge bg-secondary">${server.port}</span></td>
                        <td><code>${pid}</code></td>
                        <td>
                            <span class="status-led ${statusClass}"></span>
                            ${statusText}
                        </td>
                        <td>
                            ${isRunning ? 
                                `<button class="btn btn-danger btn-action btn-sm" onclick="stopServer('${server.id}')">
                                    <i class="bi bi-stop-circle"></i> Stop
                                </button>` :
                                `<button class="btn btn-success btn-action btn-sm" onclick="startServer('${server.id}')">
                                    <i class="bi bi-play-circle"></i> Start
                                </button>`
                            }
                            <button class="btn btn-secondary btn-action btn-sm" onclick="deleteServer('${server.id}')">
                                <i class="bi bi-trash"></i> Delete
                            </button>
                        </td>
                    </tr>
                `;
            }).join('');
        }
        
        // Add server
        document.getElementById('add-server-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const serverName = document.getElementById('server-name').value.trim();
            const port = parseInt(document.getElementById('server-port').value);
            const landscape = document.getElementById('server-landscape').value;
            
            try {
                const response = await fetch('/api/servers', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({server_name: serverName, port: port, landscape: landscape})
                });
                
                if (response.ok) {
                    showAlert(`Server "${serverName}" added successfully!`, 'success');
                    document.getElementById('add-server-form').reset();
                    fetchServers();
                } else {
                    const error = await response.json();
                    showAlert(error.error || 'Failed to add server', 'danger');
                }
            } catch (error) {
                showAlert('Error: ' + error.message, 'danger');
            }
        });
        
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
        
        // Stop server
        async function stopServer(serverId) {
            try {
                const response = await fetch(`/api/servers/${serverId}/stop`, {method: 'POST'});
                const result = await response.json();
                
                if (response.ok) {
                    showAlert('Server stopped successfully!', 'info');
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
            if (!confirm('Are you sure you want to delete this server?')) return;
            
            try {
                const response = await fetch(`/api/servers/${serverId}`, {method: 'DELETE'});
                
                if (response.ok) {
                    showAlert('Server deleted successfully!', 'info');
                    fetchServers();
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
            alert('Instructions:\\n\\n1. Add a server by entering a name and port\\n2. Click Start to begin sniffing UDP packets\\n3. Monitor status with the LED indicator\\n4. Click Stop to terminate the sniffer\\n5. Delete servers you no longer need\\n\\nNote: This application requires administrator privileges to capture network packets.');
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
        
        // Auto-refresh every 10 seconds
        setInterval(fetchServers, 10000);
        
        // Initial load
        fetchLandscapes();
        fetchServers();
    </script>
</body>
</html>
"""


# ============================================================================
# Main Entry Point
# ============================================================================

def print_reminder(host, port, stop_event):
    """Print periodic reminder to keep window open and visit dashboard"""
    while not stop_event.is_set():
        print(f"\n*** Keep this window open! Go to http://{host}:{port} to configure and manage your servers ***\n")
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
        
        print("=" * 60)
        print("Condor Map Dedicated Server Control Panel")
        print("=" * 60)
        print(f"Dashboard running at: http://{host}:{port}")
        print("Press Ctrl+C to stop")
        print("=" * 60)
        
        # Print initial reminder
        print(f"\n*** Keep this window open! Go to http://{host}:{port} to configure and manage your servers ***\n")
        
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
