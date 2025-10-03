@echo off
REM Build script for Condor3XY2LatLon.exe (32-bit one-shot version)
REM This must be run from an x86 Native Tools Command Prompt for VS 2022

echo ========================================
echo Building Condor3XY2LatLon.exe (32-bit)
echo ========================================
echo.

REM Check if cl.exe is available
where cl.exe >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: cl.exe not found!
    echo.
    echo Please run this script from:
    echo   "x86 Native Tools Command Prompt for VS 2022"
    echo.
    echo Or run this first:
    echo   "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat"
    echo.
    pause
    exit /b 1
)

REM Clean old build artifacts
if exist Condor3XY2LatLon.obj del Condor3XY2LatLon.obj
if exist Condor3XY2LatLon.exe del Condor3XY2LatLon.exe

REM Copy source from extra folder
copy extra\Condor3XY2LatLon.cpp Condor3XY2LatLon.cpp

REM Compile
echo Compiling Condor3XY2LatLon.cpp...
cl /EHsc /O2 Condor3XY2LatLon.cpp advapi32.lib

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Compilation failed!
    del Condor3XY2LatLon.cpp
    pause
    exit /b 1
)

REM Clean up intermediate files
if exist Condor3XY2LatLon.obj del Condor3XY2LatLon.obj
del Condor3XY2LatLon.cpp

echo.
echo ========================================
echo Build successful!
echo ========================================
echo.
echo Executable: %CD%\Condor3XY2LatLon.exe
echo.
echo This is the ONE-SHOT version for batch conversion.
echo It will be used automatically by tasksConvert.py
echo.
pause
