import os
from pathlib import Path
import json
import configparser

try:
    import navicon_bridge
except ImportError:
    navicon_bridge = None
    print("[WARNING] navicon_bridge not available - coordinates will not be converted to lat/lon")

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
        lat, lon = navicon_bridge.xy_to_latlon_trn(trn_path, float(x), float(y))
        return lat, lon
    except Exception as e:
        print(f"  ERROR: Coordinate conversion failed: {e}")
        return None, None

def parse_fpl_file(fpl_path):
    """Parse a Condor .fpl file and extract relevant task information"""
    print(f"Parsing: {fpl_path.name}")
    
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
        
        return task_data
        
    except Exception as e:
        print(f"  ERROR: Failed to parse {fpl_path.name}: {e}")
        return None

def update_tasks_json_with_taskids(script_dir, flightplans_dir):
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
                if start_time and 'DSHelperStartTime' not in fpl_data:
                    # Rebuild fpl_data with DSHelperStartTime after TaskName
                    new_fpl_data = {}
                    for key, value in fpl_data.items():
                        new_fpl_data[key] = value
                        if key == 'TaskName':
                            new_fpl_data['DSHelperStartTime'] = start_time
                    
                    # Save the updated flight plan JSON
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(new_fpl_data, f, indent=2, ensure_ascii=False)
                    
                    print(f"    Added DSHelperStartTime to {json_filename}")
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
    
    # Find all .fpl files
    fpl_files = list(flightplans_dir.glob("*.fpl"))
    
    if not fpl_files:
        print("No .fpl files found in flightplans directory")
        return
    
    print(f"Found {len(fpl_files)} flight plan file(s)\n")
    
    converted_count = 0
    
    for fpl_path in fpl_files:
        try:
            # Parse the FPL file
            task_data = parse_fpl_file(fpl_path)
            
            if task_data is None:
                continue
            
            # Create JSON output path (same name but .json extension)
            json_path = fpl_path.with_suffix('.json')
            
            # Save to JSON
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(task_data, f, indent=2, ensure_ascii=False)
            
            print(f"  Saved to: {json_path.name}\n")
            converted_count += 1
            
        except Exception as e:
            print(f"ERROR: Failed to process {fpl_path.name}: {e}\n")
            continue
    
    print("=" * 60)
    print(f"Conversion complete! Converted {converted_count}/{len(fpl_files)} files")
    print("=" * 60)
    
    # Update tasks.json with TaskIDs if it exists
    update_tasks_json_with_taskids(script_dir, flightplans_dir)

if __name__ == "__main__":
    convert_all_fpl_files()
