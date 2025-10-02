"""
navicon_bridge.py

Out-of-process bridge for calling the 32-bit NaviCon.dll from 64-bit Python.
Uses a persistent helper process (Condor3XY2LatLon_persistent.exe) that keeps
the DLL loaded and communicates via stdin/stdout for maximum performance.

Public API:
- xy_to_latlon_default(x: float, y: float, timeout: float=0.5) -> tuple[float, float]
  Uses AA3.trn in the project root. Returns (lat, lon).

- xy_to_latlon_trn(trn_path: str, x: float, y: float, timeout: float=0.5) -> tuple[float, float]
  Same as above but with an explicit .trn path.

- shutdown() -> None
  Gracefully shut down the persistent process. Called automatically at exit.
"""
from __future__ import annotations

import os
import subprocess
import atexit
import threading
from typing import Tuple, Optional


def _project_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _default_trn_path() -> str:
    trn = os.path.join(_project_root(), "AA3.trn")
    if not os.path.exists(trn):
        raise FileNotFoundError(f"AA3.trn not found at: {trn}")
    return trn


# Global persistent process management
_process: Optional[subprocess.Popen] = None
_process_trn: Optional[str] = None
_process_lock = threading.Lock()


def _helper_exe_path() -> str:
    # Try persistent version first, fall back to original
    exe_persistent = os.path.join(_project_root(), "Condor3XY2LatLon_persistent.exe")
    if os.path.exists(exe_persistent):
        return exe_persistent
    
    exe = os.path.join(_project_root(), "Condor3XY2LatLon.exe")
    if not os.path.exists(exe):
        raise FileNotFoundError(
            f"Helper not found. Need either:\n"
            f"  {exe_persistent} (preferred, compile from Condor3XY2LatLon_persistent.cpp)\n"
            f"  {exe} (fallback, compile from Condor3XY2LatLon.cpp)"
        )
    return exe


def _is_persistent_exe(exe_path: str) -> bool:
    """Check if the exe is the persistent version."""
    return "persistent" in os.path.basename(exe_path).lower()


def _start_persistent_process(trn_path: str) -> subprocess.Popen:
    """Start the persistent helper process."""
    exe = _helper_exe_path()
    
    if not _is_persistent_exe(exe):
        raise RuntimeError("Persistent exe not available, cannot start persistent process")
    
    # Hide console window on Windows
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE
            startupinfo = si
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                creationflags |= subprocess.CREATE_NO_WINDOW
        except Exception:
            pass
    
    proc = subprocess.Popen(
        [exe, trn_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,  # Line buffered
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    
    # Wait for READY signal
    ready_line = proc.stdout.readline().strip()
    if ready_line != "READY":
        stderr_output = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"Helper failed to start. Output: {ready_line}, Stderr: {stderr_output}")
    
    return proc


def _get_or_start_process(trn_path: str) -> subprocess.Popen:
    """Get the persistent process, starting it if necessary."""
    global _process, _process_trn
    
    with _process_lock:
        # Check if we need to restart (different TRN or dead process)
        if _process is not None:
            if _process_trn != trn_path or _process.poll() is not None:
                # Process died or wrong TRN, restart
                shutdown()
        
        if _process is None:
            _process = _start_persistent_process(trn_path)
            _process_trn = trn_path
        
        return _process


def _query_persistent_process(proc: subprocess.Popen, x: float, y: float, timeout: float) -> Tuple[float, float]:
    """Query the persistent process for a coordinate conversion."""
    with _process_lock:
        # Send query
        query = f"{x} {y}\n"
        proc.stdin.write(query)
        proc.stdin.flush()
        
        # Read response
        response = proc.stdout.readline().strip()
        
        if response.startswith("ERROR"):
            raise RuntimeError(f"Helper returned error: {response}")
        
        # Parse "lon,lat"
        parts = [p.strip() for p in response.split(",")]
        if len(parts) != 2:
            raise ValueError(f"Unexpected helper output: {response}")
        
        lon = float(parts[0])
        lat = float(parts[1])
        return lat, lon


def _run_helper_oneshot(trn_path: str, x: float, y: float, timeout: float) -> Tuple[float, float]:
    """Fallback: run the original one-shot helper (for non-persistent exe)."""
    exe = _helper_exe_path()
    cmd = [exe, trn_path, str(float(x)), str(float(y))]
    
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            startupinfo = si
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                creationflags |= subprocess.CREATE_NO_WINDOW
        except Exception:
            pass

    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    
    if res.returncode != 0:
        stdout = (res.stdout or "").strip()
        stderr = (res.stderr or "").strip()
        raise RuntimeError(f"Helper failed (rc={res.returncode}). STDOUT: {stdout} STDERR: {stderr}")

    out = (res.stdout or "").strip()
    line = next((ln for ln in (ln.strip() for ln in out.splitlines()) if ln), "")
    if not line:
        raise ValueError("Empty output from helper")

    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 2:
        raise ValueError(f"Unexpected helper output: {line}")

    lon = float(parts[0])
    lat = float(parts[1])
    return lat, lon


def _run_helper(trn_path: str, x: float, y: float, timeout: float) -> Tuple[float, float]:
    """Run helper - uses persistent process if available, otherwise one-shot."""
    exe = _helper_exe_path()
    
    if _is_persistent_exe(exe):
        # Use persistent process
        proc = _get_or_start_process(trn_path)
        return _query_persistent_process(proc, x, y, timeout)
    else:
        # Fall back to one-shot
        return _run_helper_oneshot(trn_path, x, y, timeout)


def xy_to_latlon_trn(trn_path: str, x: float, y: float, timeout: float = 0.5) -> Tuple[float, float]:
    """Call helper with an explicit .trn path. Returns (lat, lon)."""
    return _run_helper(trn_path, x, y, timeout)


def xy_to_latlon_default(x: float, y: float, timeout: float = 0.5) -> Tuple[float, float]:
    """Call helper using the local AA3.trn in this project. Returns (lat, lon)."""
    return _run_helper(_default_trn_path(), x, y, timeout)


def shutdown() -> None:
    """Gracefully shut down the persistent process."""
    global _process, _process_trn
    
    with _process_lock:
        if _process is not None:
            try:
                # Send EXIT command
                _process.stdin.write("EXIT\n")
                _process.stdin.flush()
                # Wait for process to exit
                _process.wait(timeout=1.0)
            except Exception:
                # Force kill if graceful shutdown fails
                _process.kill()
            finally:
                _process = None
                _process_trn = None


# Register shutdown handler
atexit.register(shutdown)


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 3:
        # Use default AA3.trn
        x_val = float(sys.argv[1])
        y_val = float(sys.argv[2])
        lat, lon = xy_to_latlon_default(x_val, y_val)
        print(f"{lat:.6f},{lon:.6f}")
    elif len(sys.argv) == 4:
        trn = sys.argv[1]
        x_val = float(sys.argv[2])
        y_val = float(sys.argv[3])
        lat, lon = xy_to_latlon_trn(trn, x_val, y_val)
        print(f"{lat:.6f},{lon:.6f}")
    else:
        print(
            "Usage:\n"
            "  python navicon_bridge.py <x> <y>\n"
            "  python navicon_bridge.py <path\\to\\AA3.trn> <x> <y>\n"
        )
