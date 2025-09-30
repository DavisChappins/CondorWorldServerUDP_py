"""
navicon_bridge.py

Out-of-process bridge for calling the 32-bit NaviCon.dll from 64-bit Python.
Uses the helper executable Condor3XY2LatLon.exe and an AA3.trn file.

- Preferred usage here: put AA3.trn in the same directory as this script.
- The helper EXE can accept either a scenery name (uses registry), or a full .trn path.
  We pass the full .trn path to ensure we use the local AA3.trn.

Public API:
- xy_to_latlon_default(x: float, y: float, timeout: float=0.5) -> tuple[float, float]
  Uses AA3.trn in the project root and calls the helper EXE. Returns (lat, lon).

- xy_to_latlon_trn(trn_path: str, x: float, y: float, timeout: float=0.5) -> tuple[float, float]
  Same as above but with an explicit .trn path.
"""
from __future__ import annotations

import os
import subprocess
from typing import Tuple


def _project_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _default_trn_path() -> str:
    trn = os.path.join(_project_root(), "AA3.trn")
    if not os.path.exists(trn):
        raise FileNotFoundError(f"AA3.trn not found at: {trn}")
    return trn


def _helper_exe_path() -> str:
    exe = os.path.join(_project_root(), "Condor3XY2LatLon.exe")
    if not os.path.exists(exe):
        raise FileNotFoundError(
            f"Helper not found: {exe}. Build it from Condor3XY2LatLon.cpp with 32-bit MSVC (x86)."
        )
    return exe


def _run_helper(trn_path: str, x: float, y: float, timeout: float) -> Tuple[float, float]:
    exe = _helper_exe_path()
    cmd = [exe, trn_path, str(float(x)), str(float(y))]
    # On Windows, hide the helper's console window to prevent flashing when called frequently.
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            # 0 = SW_HIDE
            si.wShowWindow = 0  # type: ignore[attr-defined]
            startupinfo = si
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                creationflags |= subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        except Exception:
            # If anything goes wrong, fall back to default behavior
            startupinfo = None
            creationflags = 0

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
        raise RuntimeError(
            f"Helper failed (rc={res.returncode}). STDOUT: {stdout} STDERR: {stderr}"
        )

    # Helper prints "lon,lat" (no newline or with), we return (lat, lon)
    out = (res.stdout or "").strip()
    # Be robust to extra lines (shouldn't happen): take last non-empty line
    line = next((ln for ln in (ln.strip() for ln in out.splitlines()) if ln), "")
    if not line:
        raise ValueError("Empty output from helper")

    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 2:
        raise ValueError(f"Unexpected helper output: {line}")

    lon = float(parts[0])
    lat = float(parts[1])
    return lat, lon


def xy_to_latlon_trn(trn_path: str, x: float, y: float, timeout: float = 0.5) -> Tuple[float, float]:
    """Call helper with an explicit .trn path. Returns (lat, lon)."""
    return _run_helper(trn_path, x, y, timeout)


def xy_to_latlon_default(x: float, y: float, timeout: float = 0.5) -> Tuple[float, float]:
    """Call helper using the local AA3.trn in this project. Returns (lat, lon)."""
    return _run_helper(_default_trn_path(), x, y, timeout)


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
