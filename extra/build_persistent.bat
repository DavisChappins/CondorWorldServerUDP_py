@echo off
REM Build script for Condor3XY2LatLon_persistent.exe
REM Requires 32-bit MSVC compiler (Visual Studio with x86 tools)

echo Building Condor3XY2LatLon_persistent.exe...
echo.
echo NOTE: This must be compiled with 32-bit MSVC because NaviCon.dll is 32-bit
echo.
echo If you don't have MSVC installed, you need:
echo   1. Visual Studio (Community Edition is free)
echo   2. C++ Desktop Development workload
echo   3. Open "x86 Native Tools Command Prompt for VS"
echo   4. Run this script from that prompt
echo.

REM Try to find vcvarsall.bat to set up 32-bit environment
if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" (
    call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x86
) else if exist "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat" (
    call "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat" x86
) else (
    echo WARNING: Could not find vcvarsall.bat
    echo Please run this from "x86 Native Tools Command Prompt for VS"
    echo.
)

REM Compile with optimizations
cl /O2 /EHsc Condor3XY2LatLon_persistent.cpp advapi32.lib

if %ERRORLEVEL% EQU 0 (
    echo.
    echo SUCCESS! Condor3XY2LatLon_persistent.exe built successfully
    echo.
    echo The sniffer will now use the persistent process for 10-20x faster coordinate conversion
) else (
    echo.
    echo BUILD FAILED!
    echo Make sure you're running from "x86 Native Tools Command Prompt for VS"
)

pause
