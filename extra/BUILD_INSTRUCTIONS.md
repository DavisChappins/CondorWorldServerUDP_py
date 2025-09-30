# Building Condor3XY2LatLon.exe

This guide explains how to compile the `Condor3XY2LatLon.cpp` utility for high-precision coordinate conversion.

## Prerequisites

You need **32-bit MSVC** (Microsoft Visual C++ Compiler) because Condor3 and its NaviCon.DLL are 32-bit applications.

### Option 1: Visual Studio (Recommended)

1. **Install Visual Studio 2022 Community** (free)
   - Download from: https://visualstudio.microsoft.com/downloads/
   - During installation, select **"Desktop development with C++"**
   - Make sure to check **"MSVC v143 - VS 2022 C++ x86/x64 build tools"**
   - Also check **"C++ ATL for latest v143 build tools (x86 & x64)"**

### Option 2: Build Tools Only (Smaller Download)

1. **Install Build Tools for Visual Studio 2022**
   - Download from: https://visualstudio.microsoft.com/downloads/ (scroll to "All Downloads" → "Tools for Visual Studio")
   - Select **"Desktop development with C++"** workload
   - Ensure x86 (32-bit) tools are included

## Building the Executable

### Method 1: Using Developer Command Prompt (Easiest)

1. **Open "x86 Native Tools Command Prompt for VS 2022"**
   - Press Windows key, type "x86 Native Tools"
   - This sets up the 32-bit compiler environment automatically

2. **Navigate to the extra directory:**
   ```cmd
   cd "C:\Users\Main\Documents\webdev\git\condorServerUDPscraper\extra"
   ```

3. **Compile:**
   ```cmd
   cl Condor3XY2LatLon.cpp advapi32.lib
   ```

4. **Verify the build:**
   ```cmd
   dir Condor3XY2LatLon.exe
   ```

### Method 2: Using PowerShell with Manual Setup

1. **Open PowerShell as Administrator**

2. **Set up the MSVC environment:**
   ```powershell
   # For Visual Studio 2022 (adjust path if different)
   & "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat"
   ```

3. **Navigate and compile:**
   ```powershell
   cd "C:\Users\Main\Documents\webdev\git\condorServerUDPscraper\extra"
   cl Condor3XY2LatLon.cpp advapi32.lib
   ```

### Method 3: Using CMake (Advanced)

Create a `CMakeLists.txt` file in the `extra/` directory:

```cmake
cmake_minimum_required(VERSION 3.10)
project(Condor3XY2LatLon)

set(CMAKE_CXX_STANDARD 11)

add_executable(Condor3XY2LatLon Condor3XY2LatLon.cpp)
target_link_libraries(Condor3XY2LatLon advapi32)
```

Then build:
```cmd
mkdir build
cd build
cmake .. -A Win32
cmake --build . --config Release
```

## What Changed in the New Version?

### Precision Improvements:

- **Added `#include <iomanip>`** for precision control
- **Added `std::fixed` and `std::setprecision(8)`** to output 8 decimal places
- **Old output:** `5.9901,44.0555` (4-5 decimal places, ~8-11 meter precision)
- **New output:** `5.99010000,44.05550000` (8 decimal places, ~0.79-1.11 cm precision)

### Geographic Precision at 45° Latitude:

| Decimal Places | Longitude Precision | Latitude Precision |
|----------------|---------------------|-------------------|
| 4 (old) | ~7.9 meters | ~11.1 meters |
| 5 | ~0.79 meters | ~1.11 meters |
| 6 | ~7.9 cm | ~11.1 cm |
| 7 | ~7.9 mm | ~11.1 mm |
| **8 (new)** | **~0.79 mm** | **~1.11 mm** |

Note: The actual precision is still limited by the 32-bit `float` type used by NaviCon.DLL (~7 significant digits), but 8 decimal places ensures we capture all available precision.

## Testing the New Build

After building, test it:

```cmd
# Navigate to the project root (where AA3.trn is located)
cd "C:\Users\Main\Documents\webdev\git\condorServerUDPscraper"

# Test with St. Auban coordinates
extra\Condor3XY2LatLon.exe AA3 800934.75 95883.93
```

Expected output (with 8 decimal places):
```
5.99010000,44.05550000
```

## Deploying the New Executable

1. **Copy the new .exe to the project root:**
   ```cmd
   copy extra\Condor3XY2LatLon.exe Condor3XY2LatLon.exe
   ```

2. **Restart your Python sniffer** to use the new precision

3. **Verify in output:** You should now see coordinates with 8 decimal places in the telemetry output

## Troubleshooting

### Error: "cl is not recognized"
- Make sure you're using the **x86 Native Tools Command Prompt**
- Or run `vcvars32.bat` to set up the environment

### Error: "LINK : fatal error LNK1104: cannot open file 'advapi32.lib'"
- Ensure Windows SDK is installed with Visual Studio
- Try running from x86 Native Tools Command Prompt

### Error: "Could not call NaviConInit"
- Make sure Condor3 is installed and the registry key exists
- Ensure AA3.trn is in the project root directory

### Wrong Architecture (64-bit instead of 32-bit)
- Verify you're using **x86** tools, not x64
- Check with: `dumpbin /headers Condor3XY2LatLon.exe | findstr machine`
- Should show: `8664 machine (x86)`

## Clean Build

To clean up build artifacts:
```cmd
del Condor3XY2LatLon.obj
del Condor3XY2LatLon.exe
```

Then rebuild from scratch.
