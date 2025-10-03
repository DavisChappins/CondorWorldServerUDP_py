# NaviCon Helper Build Instructions

## Overview

There are **two versions** of the NaviCon helper executable:

1. **Condor3XY2LatLon.exe** - One-shot version (for batch conversion)
2. **Condor3XY2LatLon_persistent.exe** - Persistent version (for real-time UDP)

## When Each is Used

### One-Shot Version (`Condor3XY2LatLon.exe`)
- **Used by**: `tasksConvert.py` (batch flight plan conversion)
- **Why**: More reliable when switching between different landscapes/TRN files
- **Speed**: Slower (spawns new process for each coordinate)
- **Reliability**: High - no state issues

### Persistent Version (`Condor3XY2LatLon_persistent.exe`)
- **Used by**: UDP sniffer (real-time coordinate conversion)
- **Why**: Much faster for repeated conversions on same landscape
- **Speed**: Fast (keeps process alive, reuses DLL)
- **Reliability**: Can hang when switching landscapes

## Building

### Build One-Shot Version

```batch
# Open: x86 Native Tools Command Prompt for VS 2022
cd C:\path\to\CondorWorldServerUDP_py
build_oneshot.bat
```

This creates `Condor3XY2LatLon.exe` in the project root.

### Build Persistent Version

```batch
# Open: x86 Native Tools Command Prompt for VS 2022
cd C:\path\to\CondorWorldServerUDP_py
build_persistent.bat
```

This creates `Condor3XY2LatLon_persistent.exe` in the project root.

## Deployment to VPS

Copy **both** executables to your VPS:

```
Condor3XY2LatLon.exe              (for batch conversion)
Condor3XY2LatLon_persistent.exe   (for UDP sniffer)
```

## Troubleshooting

### Error: "One-shot helper not found"

This means `tasksConvert.py` needs the one-shot version but it's missing.

**Solution**: Run `build_oneshot.bat` to compile it.

### Conversion hangs on VPS

This happens when using the persistent version for batch conversion with multiple landscapes.

**Solution**: The code now automatically uses one-shot mode for `tasksConvert.py` to avoid this issue.

### "Helper failed (rc=1)" with usage message

This means the wrong exe is being called with wrong arguments.

**Solution**: Make sure `Condor3XY2LatLon.exe` (one-shot) exists in the project root.
