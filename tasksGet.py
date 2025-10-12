import os
import xml.etree.ElementTree as ET
import json
import shutil
from pathlib import Path
import html

def get_windows_username():
    """Get the current Windows username"""
    return os.environ.get('USERNAME', os.environ.get('USER', 'Administrator'))

def find_scheduler_file():
    """Find the scheduler.dat file in AppData"""
    username = get_windows_username()
    scheduler_path = Path(f"C:\\Users\\{username}\\AppData\\Roaming\\Hitziger Solutions\\DSHelper\\scheduler.dat")
    print(f"Looking for scheduler file at: {scheduler_path}")
    return scheduler_path

def parse_nested_xml(xml_string):
    """Parse the nested XML string that's HTML-encoded"""
    try:
        # Decode HTML entities
        decoded = html.unescape(xml_string)
        # Parse the XML
        root = ET.fromstring(decoded)
        return root
    except Exception as e:
        print(f"Error parsing nested XML: {e}")
        return None

def extract_local_flightplan(options_text):
    """Extract LocalFlightplan from the nested XML in Options"""
    if not options_text:
        return None
    
    nested_root = parse_nested_xml(options_text)
    if nested_root is None:
        return None
    
    # Find LocalFlightplan element
    local_flightplan = nested_root.find('LocalFlightplan')
    if local_flightplan is not None and local_flightplan.text:
        return local_flightplan.text.strip()
    
    return None

def extract_server_path(options_text):
    """Extract ServerPath directory from the nested XML in Options"""
    if not options_text:
        return None
    
    nested_root = parse_nested_xml(options_text)
    if nested_root is None:
        return None
    
    # Find ServerPath element
    server_path = nested_root.find('ServerPath')
    if server_path is not None and server_path.text:
        full_path = server_path.text.strip()
        # Extract just the directory (e.g., C:\Condor3_2\ from C:\Condor3_2\CondorDedicated.exe)
        path_obj = Path(full_path)
        if path_obj.parent:
            # Return directory with trailing backslash
            return str(path_obj.parent) + "\\"
    
    return None

def parse_scheduler_file(scheduler_path):
    """Parse the scheduler.dat XML file and extract relevant information"""
    print(f"Reading scheduler file...")
    
    try:
        tree = ET.parse(scheduler_path)
        root = tree.getroot()
    except FileNotFoundError:
        print(f"ERROR: Scheduler file not found at {scheduler_path}")
        return []
    except ET.ParseError as e:
        print(f"ERROR: Failed to parse XML: {e}")
        return []
    except Exception as e:
        print(f"ERROR: Unexpected error reading file: {e}")
        return []
    
    tasks = []
    
    # Find all SchedulerItem elements
    scheduler_items = root.findall('.//SchedulerItem')
    print(f"Found {len(scheduler_items)} scheduler items")
    
    for item in scheduler_items:
        try:
            # Extract basic info
            task_id = item.find('Id')
            description = item.find('Description')
            
            # Extract StartTime from Trigger
            trigger = item.find('.//Trigger/SchedulerTriggerItem/StartTime')
            
            # Extract LocalFlightplan and ServerPath from nested XML in Actions/Options
            local_flightplan = None
            server_path = None
            actions = item.find('.//Actions/SchedulerActionItem/Options')
            if actions is not None and actions.text:
                local_flightplan = extract_local_flightplan(actions.text)
                server_path = extract_server_path(actions.text)
            
            # Only add if we have the required fields
            if task_id is not None and description is not None:
                task_data = {
                    'id': task_id.text.strip() if task_id.text else None,
                    'description': description.text.strip() if description.text else None,
                    'startTime': trigger.text.strip() if trigger is not None and trigger.text else None,
                    'localFlightplan': local_flightplan,
                    'serverPath': server_path
                }
                
                tasks.append(task_data)
                print(f"Extracted task {task_data['id']}: {task_data['description']}")
                if local_flightplan:
                    print(f"  Flight plan: {local_flightplan}")
                if server_path:
                    print(f"  Server path: {server_path}")
                if task_data['startTime']:
                    print(f"  Start time: {task_data['startTime']} (UTC)")
        
        except Exception as e:
            print(f"ERROR: Failed to process scheduler item: {e}")
            continue
    
    return tasks

def save_tasks_to_json(tasks, output_path):
    """Save tasks to JSON file"""
    print(f"\nSaving tasks to JSON file: {output_path}")
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(tasks, f, indent=2, ensure_ascii=False)
        print(f"Successfully saved {len(tasks)} tasks to JSON")
    except Exception as e:
        print(f"ERROR: Failed to save JSON file: {e}")

def copy_flight_plans(tasks, output_dir):
    """Copy flight plan files to the flightplans directory"""
    print(f"\nCopying flight plans to: {output_dir}")
    
    # Create the flightplans directory if it doesn't exist
    try:
        output_dir.mkdir(exist_ok=True)
        print(f"Created/verified flightplans directory")
    except Exception as e:
        print(f"ERROR: Failed to create flightplans directory: {e}")
        return
    
    copied_count = 0
    for task in tasks:
        flight_plan_path = task.get('localFlightplan')
        if not flight_plan_path:
            continue
        
        source_path = Path(flight_plan_path)
        
        try:
            if not source_path.exists():
                print(f"WARNING: Flight plan file not found: {source_path}")
                continue
            
            # Copy to flightplans directory with the same filename
            dest_path = output_dir / source_path.name
            shutil.copy2(source_path, dest_path)
            print(f"Copied: {source_path.name}")
            copied_count += 1
            
        except Exception as e:
            print(f"ERROR: Failed to copy {source_path}: {e}")
    
    print(f"\nSuccessfully copied {copied_count} flight plan files")

def main():
    print("=" * 60)
    print("Condor Scheduler Task Extractor")
    print("=" * 60)
    
    # Get the script directory
    script_dir = Path(__file__).parent
    
    # Find and parse scheduler file
    scheduler_path = find_scheduler_file()
    tasks = parse_scheduler_file(scheduler_path)
    
    if not tasks:
        print("\nNo tasks found or error occurred")
        return
    
    # Save to JSON
    json_output_path = script_dir / "tasks.json"
    save_tasks_to_json(tasks, json_output_path)
    
    # Copy flight plans
    flightplans_dir = script_dir / "flightplans"
    copy_flight_plans(tasks, flightplans_dir)
    
    print("\n" + "=" * 60)
    print("Processing complete!")
    print("=" * 60)

if __name__ == "__main__":
    main()
