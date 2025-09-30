@echo off
REM Build script for Condor3XY2LatLon.exe (32-bit)
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

REM Compile
echo Compiling Condor3XY2LatLon.cpp...
cl /EHsc /O2 Condor3XY2LatLon.cpp advapi32.lib

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Compilation failed!
    pause
    exit /b 1
)

REM Clean up intermediate files
if exist Condor3XY2LatLon.obj del Condor3XY2LatLon.obj

echo.
echo ========================================
echo Build successful!
echo ========================================
echo.
echo Executable: %CD%\Condor3XY2LatLon.exe
echo.

REM Test if Condor3 is installed
reg query "HKCU\Software\Condor3" /v InstallDir >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo Condor3 installation detected.
    echo.
    echo To test, run:
    echo   Condor3XY2LatLon.exe AA3 800934.75 95883.93
    echo.
    echo Expected output (8 decimal places):
    echo   5.99010000,44.05550000
) else (
    echo WARNING: Condor3 installation not found in registry.
    echo The executable may not work without Condor3 installed.
)

echo.
echo To deploy, copy to project root:
echo   copy Condor3XY2LatLon.exe ..\Condor3XY2LatLon.exe
echo.
pause
