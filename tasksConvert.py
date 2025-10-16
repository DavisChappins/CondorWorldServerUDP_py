import os
from pathlib import Path
import json
import configparser
import requests

try:
    import navicon_bridge
except ImportError:
    navicon_bridge = None
    print("[WARNING] navicon_bridge not available - coordinates will not be converted to lat/lon")

def kg_m2_to_lb_ft2(kg_m2):
    """Convert kg/m² to lb/ft²"""
    # 1 kg/m² = 0.204816 lb/ft²
    return round(kg_m2 * 0.204816, 2)

def kmh_to_knots(kmh):
    """Convert km/h to knots"""
    # 1 km/h = 0.539957 knots
    return round(kmh * 0.539957, 2)

def extract_task_extra_details(config):
    """Extract additional task details from FPL file sections for task_extra_details JSONB field"""
    extra_details = {}
    
    # Extract from GameOptions section if it exists
    if 'GameOptions' in config:
        game_options = config['GameOptions']
        
        # MaxWingLoading
        max_wing_loading = game_options.get('MaxWingLoading', '').strip()
        if max_wing_loading:
            try:
                wing_loading_kg_m2 = float(max_wing_loading)
                extra_details['MaxWingLoadingKgM2'] = wing_loading_kg_m2
                extra_details['MaxWingLoadingLbFt2'] = kg_m2_to_lb_ft2(wing_loading_kg_m2)
            except ValueError:
                pass
        
        # MaxStartGroundSpeed
        max_start_speed = game_options.get('MaxStartGroundSpeed', '').strip()
        if max_start_speed:
            try:
                speed_kmh = float(max_start_speed)
                extra_details['MaxStartGroundSpeedKmh'] = speed_kmh
                extra_details['MaxStartGroundSpeedKt'] = kmh_to_knots(speed_kmh)
            except ValueError:
                pass
    
    # Extract Class from Plane section if it exists
    if 'Plane' in config:
        plane_section = config['Plane']
        plane_class = plane_section.get('Class', '').strip()
        if plane_class:
            extra_details['Class'] = plane_class
    
    return extra_details if extra_details else None

def find_trn_file(landscape_code):
    """Find the .trn file for a given landscape code"""
    script_dir = Path(__file__).parent
    
    # Try common locations
    trn_candidates = [
        script_dir / f"{landscape_code}.trn",
        script_dir / "landscapes" / f"{landscape_code}.trn",
        Path(f"C:\\Condor3_2\\Landscapes\\{landscape_code}\\{landscape_code}.trn"),
        Path(f"C:\\Condor3\\Landscapes\\{landscape_code}\\{landscape_code}.trn"),
        Path(f"C:\\Condor2\\Landscapes\\{landscape_code}\\{landscape_code}.trn"),
    ]
    
    for trn_path in trn_candidates:
        if trn_path.exists():
            return str(trn_path)
    
    return None

def convert_xy_to_latlon(landscape_code, x, y):
    """Convert Condor XY coordinates to Lat/Lon using NaviCon.dll"""
    if navicon_bridge is None:
        return None, None
    
    trn_path = find_trn_file(landscape_code)
    if trn_path is None:
        print(f"  WARNING: .trn file not found for landscape '{landscape_code}'")
        return None, None
    
    try:
        # Use one-shot mode (force_oneshot=True) for batch conversion
        # This is slower but more reliable when switching between different TRN files
        # The persistent process can get stuck when changing landscapes
        lat, lon = navicon_bridge.xy_to_latlon_trn(trn_path, float(x), float(y), timeout=5.0, force_oneshot=True)
        return lat, lon
    except TimeoutError as e:
        print(f"  ERROR: Coordinate conversion timed out: {e}")
        return None, None
    except Exception as e:
        print(f"  ERROR: Coordinate conversion failed: {e}")
        return None, None

def fetch_servers_with_paths():
    """Fetch list of configured servers with their paths from the dashboard API or local config.json as fallback"""
    # First try the running dashboard API
    host = os.getenv('DASHBOARD_HOST', '127.0.0.1')
    port = os.getenv('DASHBOARD_PORT', '5001')
    url = f"http://{host}:{port}/api/servers"
    try:
        print(f"  Attempting to fetch servers from dashboard API...")
        resp = requests.get(url, timeout=2.0)
        if resp.ok:
            servers = resp.json()
            # Return list of dicts with server_name, path, and group
            server_list = [{'name': s.get('server_name'), 'path': s.get('path'), 'group': s.get('group')} 
                          for s in servers if s.get('server_name') and s.get('path')]
            print(f"  Successfully fetched {len(server_list)} server(s) from API")
            for srv in server_list:
                group_info = f" (group: {srv['group']})" if srv.get('group') else ""
                print(f"    - {srv['name']}: {srv['path']}{group_info}")
            return server_list
        else:
            print(f"  Dashboard API returned status {resp.status_code}, trying config.json...")
    except Exception as e:
        print(f"  Dashboard API not available ({type(e).__name__}), trying config.json...")
    
    # Fallback: read config.json in the same directory as this script
    try:
        config_path = Path(__file__).parent / 'config.json'
        if config_path.exists():
            print(f"  Reading servers from config.json...")
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                servers = cfg.get('servers', [])
                server_list = [{'name': s.get('server_name'), 'path': s.get('path'), 'group': s.get('group')} 
                              for s in servers if s.get('server_name') and s.get('path')]
                print(f"  Found {len(server_list)} server(s) in config.json")
                for srv in server_list:
                    group_info = f" (group: {srv['group']})" if srv.get('group') else ""
                    print(f"    - {srv['name']}: {srv['path']}{group_info}")
                return server_list
        else:
            print(f"  config.json not found at {config_path}")
    except Exception as e:
        print(f"  Error reading config.json: {e}")
    
    print(f"  No servers found, continuing without them")
    return []

def parse_fpl_file(fpl_path, servers_list=None, task_server_path=None):
    """Parse a Condor .fpl file and extract relevant task information"""
    print(f"Parsing: {fpl_path.name}")
    if task_server_path:
        print(f"  Task server path: {task_server_path}")
    
    try:
        config = configparser.ConfigParser()
        config.read(fpl_path, encoding='utf-8')
        
        if 'Task' not in config:
            print(f"  WARNING: No [Task] section found in {fpl_path.name}")
            return None
        
        task_section = config['Task']
        
        # Extract basic task info - build with specific order
        task_data = {}
        
        # Add CondorClubTaskID first if it exists
        condor_task_id = task_section.get('TaskID', '').strip()
        if condor_task_id:
            task_data['CondorClubTaskID'] = condor_task_id
        
        # Add remaining fields in order
        task_data['TaskName'] = task_section.get('TaskName', '')
        task_data['Landscape'] = task_section.get('Landscape', '')
        
        # Extract task type and related settings from GameOptions (if it exists)
        if 'GameOptions' in config:
            game_options = config['GameOptions']
            is_aat = int(game_options.get('AAT', '0')) == 1
            task_data['TaskType'] = 'AAT' if is_aat else 'Racing'
            
            # AAT time (only if AAT task)
            if is_aat:
                aat_time = float(game_options.get('AATTime', '0'))
                task_data['AATTimeHours'] = aat_time
            else:
                task_data['AATTimeHours'] = None
            
            # Start window settings
            start_window_hours = float(game_options.get('StartTimeWindow', '0'))
            start_window_minutes = round(start_window_hours * 60)
            task_data['StartWindowMinutes'] = start_window_minutes
            task_data['RegattaStart'] = (start_window_minutes == 0)
        else:
            # Default values if GameOptions section is missing
            task_data['TaskType'] = 'Racing'
            task_data['AATTimeHours'] = None
            task_data['StartWindowMinutes'] = 0
            task_data['RegattaStart'] = True
        
        # Get original count (includes takeoff point at index 0)
        original_count = int(task_section.get('Count', 0))
        # Actual turnpoint count excludes the takeoff (index 0)
        actual_count = original_count - 1
        
        task_data['TPCount'] = actual_count
        task_data['Turnpoints'] = []
        
        landscape = task_data['Landscape']
        
        if actual_count < 1:
            print(f"  WARNING: Task has less than 1 turnpoint")
            # Match servers by path
            matched_servers, matched_group = match_servers_by_path(servers_list, task_server_path)
            task_data['servers'] = matched_servers
            if matched_group:
                task_data['ServerGroup'] = matched_group
            return task_data
        
        # Check if we can convert coordinates
        trn_path = find_trn_file(landscape) if navicon_bridge else None
        if trn_path:
            print(f"  Using landscape file: {trn_path}")
        elif navicon_bridge:
            print(f"  WARNING: .trn file not found for landscape '{landscape}' - coordinates will remain as XY")
        
        # Process turnpoints from index 1 to original_count-1 (skip 0 which is takeoff)
        # We'll use human index starting from 1
        for i in range(1, original_count):
            tp_name = task_section.get(f'TPName{i}', '')
            tp_pos_x = task_section.get(f'TPPosX{i}', '0')
            tp_pos_y = task_section.get(f'TPPosY{i}', '0')
            tp_radius = task_section.get(f'TPRadius{i}', '0')
            tp_angle = task_section.get(f'TPAngle{i}', '0')
            tp_width = task_section.get(f'TPWidth{i}', '0')
            tp_height = task_section.get(f'TPHeight{i}', '0')
            
            # Determine if this is Start (first) or Finish (last)
            human_index = i  # Human-readable index starting from 1
            if i == 1:
                display_name = 'Start'
            elif i == original_count - 1:
                display_name = 'Finish'
            else:
                display_name = tp_name
            
            # Convert XY to Lat/Lon
            lat, lon = convert_xy_to_latlon(landscape, tp_pos_x, tp_pos_y)
            
            # Build turnpoint object with clean field names
            turnpoint = {
                'Id': human_index,
                'Name': display_name,
                'X': tp_pos_x,
                'Y': tp_pos_y,
                'Lat': lat if lat is not None else tp_pos_y,
                'Lon': lon if lon is not None else tp_pos_x,
                'RadiusMeters': tp_radius,
                'Angle': tp_angle,
                'MinAltMeters': tp_width,
                'MaxAltMeters': tp_height
            }
            
            task_data['Turnpoints'].append(turnpoint)
            
            if lat is not None and lon is not None:
                print(f"  TP{human_index}: {display_name} ({lat:.5f}, {lon:.5f}) - Radius: {tp_radius}m")
            else:
                print(f"  TP{human_index}: {display_name} (XY: {tp_pos_x}, {tp_pos_y}) - Radius: {tp_radius}m")
        
        # Extract task_additional_details
        task_additional_details = extract_task_extra_details(config)
        if task_additional_details:
            task_data['task_additional_details'] = task_additional_details
            print(f"  Extracted additional details: {task_additional_details}")
        
        # Match servers by path and append at the end for readability (after Turnpoints)
        matched_servers, matched_group = match_servers_by_path(servers_list, task_server_path)
        task_data['servers'] = matched_servers
        if matched_group:
            task_data['ServerGroup'] = matched_group
        print(f"  Matched {len(matched_servers)} server(s) by path: {matched_servers}")
        if matched_group:
            print(f"  Server group: {matched_group}")
        return task_data
        
    except Exception as e:
        print(f"  ERROR: Failed to parse {fpl_path.name}: {e}")
        return None

def match_servers_by_path(servers_list, task_server_path):
    """Match servers by comparing their path with the task's serverPath
    Returns: (matched_server_names, matched_server_group)
    """
    if not servers_list or not task_server_path:
        print(f"  No path matching: servers_list={bool(servers_list)}, task_server_path={task_server_path}")
        return [], None
    
    # Normalize paths for comparison (remove trailing backslash, convert to lowercase)
    normalized_task_path = task_server_path.rstrip('\\').lower()
    print(f"  Normalized task path for matching: {normalized_task_path}")
    
    matched_names = []
    matched_group = None
    for server in servers_list:
        server_path_raw = server.get('path', '')
        # Handle both directory paths and full exe paths
        # If it's a full path to exe, extract the directory
        if server_path_raw.lower().endswith('.exe'):
            from pathlib import Path
            server_path = str(Path(server_path_raw).parent).rstrip('\\').lower()
        else:
            server_path = server_path_raw.rstrip('\\').lower()
        
        if server_path == normalized_task_path:
            matched_names.append(server['name'])
            # Use the group from the first matched server
            if matched_group is None:
                matched_group = server.get('group')
            group_info = f" (group: {matched_group})" if matched_group else ""
            print(f"  [MATCH] Server '{server['name']}' (path: {server['path']}){group_info}")
        else:
            print(f"  [SKIP] Server '{server['name']}' (path: {server['path']} != {task_server_path})")
    
    return matched_names, matched_group

def update_tasks_json_with_taskids(script_dir, flightplans_dir, servers_list):
    """Update tasks.json with TaskID from converted flight plan JSONs AND add DSHelperStartTime to flight plan JSONs"""
    tasks_json_path = script_dir / "tasks.json"
    
    # Check if tasks.json exists
    if not tasks_json_path.exists():
        print("\nNo tasks.json found - skipping TaskID update")
        return
    
    print("\n" + "=" * 60)
    print("Updating tasks.json with TaskIDs and adding DSHelperStartTime to flight plans")
    print("=" * 60)
    
    try:
        # Load tasks.json
        with open(tasks_json_path, 'r', encoding='utf-8') as f:
            tasks = json.load(f)
        
        if not isinstance(tasks, list):
            print("ERROR: tasks.json is not a list")
            return
        
        updated_tasks_count = 0
        updated_fpl_count = 0
        
        # For each task, try to find the corresponding flight plan JSON
        for task in tasks:
            fpl_path = task.get('localFlightplan')
            if not fpl_path:
                continue
            
            # Convert to Path and get the JSON equivalent
            fpl_file = Path(fpl_path)
            json_filename = fpl_file.stem + '.json'
            json_path = flightplans_dir / json_filename
            
            # Check if the converted JSON exists
            if not json_path.exists():
                print(f"  Skipping: {fpl_file.name} (JSON not found)")
                continue
            
            try:
                # Read the converted flight plan JSON
                with open(json_path, 'r', encoding='utf-8') as f:
                    fpl_data = json.load(f)
                
                # Extract CondorClubTaskID and insert after 'id' in tasks.json
                condor_task_id = fpl_data.get('CondorClubTaskID')
                if condor_task_id:
                    # Rebuild task dict with CondorClubTaskID right after 'id'
                    new_task = {}
                    for key, value in task.items():
                        new_task[key] = value
                        if key == 'id':
                            new_task['CondorClubTaskID'] = condor_task_id
                    
                    # Update the task in place
                    task.clear()
                    task.update(new_task)
                    
                    print(f"  Updated task '{task.get('description', 'unknown')}' with CondorClubTaskID: {condor_task_id}")
                    updated_tasks_count += 1
                else:
                    print(f"  No CondorClubTaskID found in {json_filename} (this is OK)")
                
                # Add DSHelperStartTime to the flight plan JSON (insert after TaskName)
                start_time = task.get('startTime')
                task_server_path = task.get('serverPath')
                needs_update = False
                
                if start_time and 'DSHelperStartTime' not in fpl_data:
                    # Rebuild fpl_data with DSHelperStartTime after TaskName
                    new_fpl_data = {}
                    for key, value in fpl_data.items():
                        new_fpl_data[key] = value
                        if key == 'TaskName':
                            new_fpl_data['DSHelperStartTime'] = start_time
                    fpl_data = new_fpl_data
                    needs_update = True
                    print(f"    Added DSHelperStartTime to {json_filename}")
                
                # Update servers list and ServerGroup based on serverPath matching
                if task_server_path:
                    matched_servers, matched_group = match_servers_by_path(servers_list, task_server_path)
                    if matched_servers != fpl_data.get('servers', []):
                        fpl_data['servers'] = matched_servers
                        needs_update = True
                        print(f"    Updated servers list to {matched_servers} based on path {task_server_path}")
                    if matched_group and matched_group != fpl_data.get('ServerGroup'):
                        fpl_data['ServerGroup'] = matched_group
                        needs_update = True
                        print(f"    Updated ServerGroup to '{matched_group}'")
                
                # Save if anything changed
                if needs_update:
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(fpl_data, f, indent=2, ensure_ascii=False)
                    updated_fpl_count += 1
                    
            except Exception as e:
                print(f"  ERROR: Failed to process {json_filename}: {e}")
                continue
        
        # Save updated tasks.json
        if updated_tasks_count > 0:
            with open(tasks_json_path, 'w', encoding='utf-8') as f:
                json.dump(tasks, f, indent=2, ensure_ascii=False)
            print(f"\nUpdated {updated_tasks_count} task(s) in tasks.json")
        else:
            print("\nNo tasks were updated in tasks.json")
        
        if updated_fpl_count > 0:
            print(f"Updated {updated_fpl_count} flight plan(s) with DSHelperStartTime")
            
    except Exception as e:
        print(f"ERROR: Failed to update: {e}")

def convert_all_fpl_files():
    """Convert all .fpl files in the flightplans directory to JSON"""
    print("=" * 60)
    print("Condor Flight Plan Converter")
    print("=" * 60)
    
    # Get the script directory and flightplans subdirectory
    script_dir = Path(__file__).parent
    flightplans_dir = script_dir / "flightplans"
    
    print(f"\nLooking for flight plans in: {flightplans_dir}")
    
    if not flightplans_dir.exists():
        print(f"ERROR: Flightplans directory not found: {flightplans_dir}")
        return
    
    # Fetch servers with paths once to avoid multiple API calls
    servers_list = fetch_servers_with_paths()
    if servers_list:
        print(f"\nFound {len(servers_list)} server(s) from dashboard/config:")
        for srv in servers_list:
            group_info = f" (group: {srv['group']})" if srv.get('group') else ""
            print(f"  - {srv['name']}: {srv['path']}{group_info}")
    else:
        print("\nNo servers found from dashboard/config (this is OK)")
    
    # Find all .fpl files
    fpl_files = list(flightplans_dir.glob("*.fpl"))
    
    if not fpl_files:
        print("No .fpl files found in flightplans directory")
        return
    
    print(f"Found {len(fpl_files)} flight plan file(s)\n")
    
    # Load tasks.json to get serverPath for each flight plan
    tasks_json_path = script_dir / "tasks.json"
    tasks_map = {}
    if tasks_json_path.exists():
        try:
            with open(tasks_json_path, 'r', encoding='utf-8') as f:
                tasks = json.load(f)
                # Map flight plan filename to serverPath
                for task in tasks:
                    fpl_path_str = task.get('localFlightplan')
                    if fpl_path_str:
                        fpl_name = Path(fpl_path_str).name
                        tasks_map[fpl_name] = task.get('serverPath')
                print(f"\nLoaded serverPath mappings for {len(tasks_map)} task(s) from tasks.json")
        except Exception as e:
            print(f"\nWARNING: Could not load tasks.json: {e}")
    else:
        print(f"\nWARNING: tasks.json not found - will not match servers by path")
    
    converted_count = 0
    
    for idx, fpl_path in enumerate(fpl_files, 1):
        try:
            print(f"\n[{idx}/{len(fpl_files)}] Processing {fpl_path.name}...")
            # Get the serverPath for this flight plan from tasks.json
            task_server_path = tasks_map.get(fpl_path.name)
            # Parse the FPL file
            task_data = parse_fpl_file(fpl_path, servers_list=servers_list, task_server_path=task_server_path)
            
            if task_data is None:
                print(f"  Skipped (parse returned None)\n")
                continue
            
            # Create JSON output path (same name but .json extension)
            json_path = fpl_path.with_suffix('.json')
            
            # Save to JSON
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(task_data, f, indent=2, ensure_ascii=False)
            
            print(f"  Saved to: {json_path.name}\n")
            converted_count += 1
            
        except Exception as e:
            print(f"ERROR: Failed to process {fpl_path.name}: {e}")
            import traceback
            traceback.print_exc()
            print()
            continue
    
    print("=" * 60)
    print(f"Conversion complete! Converted {converted_count}/{len(fpl_files)} files")
    print("=" * 60)
    
    # Update tasks.json with TaskIDs if it exists
    print(f"\n" + "=" * 60)
    print(f"Starting tasks.json update...")
    print("=" * 60)
    try:
        update_tasks_json_with_taskids(script_dir, flightplans_dir, servers_list)
        print(f"\ntasks.json update completed")
    except Exception as e:
        print(f"\nERROR during tasks.json update: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    convert_all_fpl_files()
