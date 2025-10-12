import os
import json
import requests
from pathlib import Path


def load_task_files(flightplans_dir):
    """Load all .json task files from the flightplans directory"""
    print(f"Looking for task files in: {flightplans_dir}")
    
    if not flightplans_dir.exists():
        print(f"ERROR: Flightplans directory not found: {flightplans_dir}")
        return []
    
    # Find all .json files
    json_files = list(flightplans_dir.glob("*.json"))
    
    if not json_files:
        print("No .json task files found in flightplans directory")
        return []
    
    print(f"Found {len(json_files)} task file(s)\n")
    
    tasks = []
    for json_path in json_files:
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                task_data = json.load(f)
                tasks.append(task_data)
                print(f"  Loaded: {json_path.name}")
        except Exception as e:
            print(f"  ERROR: Failed to load {json_path.name}: {e}")
            continue
    
    return tasks


def validate_task(task):
    """Validate that a task has required fields for upload"""
    # Check if task has at least one server
    servers = task.get('servers', [])
    if not servers or len(servers) == 0:
        return False, "No servers specified"
    
    # Check if task has required fields
    if not task.get('TaskName'):
        return False, "Missing TaskName"
    
    return True, None


def upload_tasks(tasks, api_base_url="https://server.condormap.com/api"):
    """Upload tasks to the server - single or bulk depending on count"""
    if not tasks:
        print("\nNo tasks to upload")
        return
    
    # Filter out invalid tasks
    valid_tasks = []
    invalid_tasks = []
    
    print("\n" + "=" * 60)
    print(f"Validating {len(tasks)} task(s)...")
    print("=" * 60)
    
    for task in tasks:
        is_valid, error = validate_task(task)
        if is_valid:
            valid_tasks.append(task)
        else:
            invalid_tasks.append({
                'task': task,
                'error': error
            })
            task_name = task.get('TaskName', 'Unknown')
            print(f"  [SKIP] {task_name}: {error}")
    
    if invalid_tasks:
        print(f"\nSkipped {len(invalid_tasks)} invalid task(s)")
    
    if not valid_tasks:
        print("\nNo valid tasks to upload")
        return
    
    print(f"\nProceeding with {len(valid_tasks)} valid task(s)")
    
    # Common headers for all requests
    headers = {
        'x-task-upload': 'true',
        'Content-Type': 'application/json'
    }
    
    print("\n" + "=" * 60)
    print(f"Uploading {len(valid_tasks)} task(s) to {api_base_url}")
    print("=" * 60)
    
    # Use valid_tasks instead of tasks for the rest of the function
    tasks = valid_tasks
    
    if len(tasks) == 1:
        # Single task upload
        url = f"{api_base_url}/tasks"
        task = tasks[0]
        
        print(f"\nUploading single task: {task.get('TaskName', 'Unknown')}")
        print(f"  CondorClubTaskID: {task.get('CondorClubTaskID', 'N/A')}")
        print(f"  Servers: {', '.join(task.get('servers', []))}")
        server_group = task.get('ServerGroup')
        if server_group:
            print(f"  ServerGroup: {server_group}")
        print(f"  Endpoint: POST {url}")
        
        try:
            response = requests.post(url, json=task, headers=headers, timeout=10)
            
            if response.ok:
                print(f"  SUCCESS: Task uploaded (Status: {response.status_code})")
                try:
                    print(f"  Response: {response.json()}")
                except:
                    print(f"  Response: {response.text}")
            else:
                print(f"  FAILED: Status {response.status_code}")
                print(f"  Response: {response.text}")
                
        except requests.exceptions.RequestException as e:
            print(f"  ERROR: Failed to upload task: {e}")
    
    else:
        # Bulk upload
        url = f"{api_base_url}/tasks/bulk"
        payload = {"tasks": tasks}
        
        print(f"\nUploading {len(tasks)} tasks in bulk")
        for i, task in enumerate(tasks, 1):
            server_group = task.get('ServerGroup', 'N/A')
            print(f"  {i}. {task.get('TaskName', 'Unknown')} (ID: {task.get('CondorClubTaskID', 'N/A')}, Group: {server_group})")
        print(f"  Endpoint: POST {url}")
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            
            if response.ok:
                print(f"\n  SUCCESS: All tasks uploaded (Status: {response.status_code})")
                try:
                    print(f"  Response: {response.json()}")
                except:
                    print(f"  Response: {response.text}")
            else:
                print(f"\n  FAILED: Status {response.status_code}")
                print(f"  Response: {response.text}")
                
        except requests.exceptions.RequestException as e:
            print(f"\n  ERROR: Failed to upload tasks: {e}")


def main():
    print("=" * 60)
    print("Condor Task Uploader")
    print("=" * 60)
    
    # Get the script directory and flightplans subdirectory
    script_dir = Path(__file__).parent
    flightplans_dir = script_dir / "flightplans"
    
    # Load all task files
    tasks = load_task_files(flightplans_dir)
    
    if not tasks:
        print("\nNo tasks loaded. Exiting.")
        return
    
    # Upload tasks to server
    # You can override the API base URL via environment variable
    api_base_url = os.getenv('CONDOR_API_URL', 'https://server.condormap.com/api')
    #api_base_url = os.getenv('CONDOR_API_URL', 'http://localhost:3000/api')
    upload_tasks(tasks, api_base_url)
    
    print("\n" + "=" * 60)
    print("Upload complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
