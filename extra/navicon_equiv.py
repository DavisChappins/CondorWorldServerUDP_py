# navicon_equiv.py
# 64-bit Python reimplementation with calibration from control points.
# API mirrors the DLL: NaviConInit(), GetMaxX(), GetMaxY(), XYToLat(), XYToLon()

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Optional
import json
import numpy as np

# ---- Model: lat,lon = (1, x, y, x*y, y^2) · params ----
@dataclass
class _Cal:
    # a: params for lat, b: params for lon (each shape (5,))
    a: np.ndarray
    b: np.ndarray
    maxX: float
    maxY: float

    def predict(self, x: float, y: float) -> Tuple[float, float]:
        phi = np.array([1.0, x, y, x*y, y*y], dtype=float)
        lat = float(phi @ self.a)
        lon = float(phi @ self.b)
        return lat, lon

_state: Optional[_Cal] = None

def _fit_quady(controls: List[Tuple[float,float,float,float]]) -> Tuple[np.ndarray, np.ndarray]:
    """
    controls: list of (x, y, lat_deg, lon_deg)
    returns (a_params for lat, b_params for lon), each length 5
    """
    A = np.array([[1.0, x, y, x*y, y*y] for (x, y, _, _) in controls], dtype=float)
    lat_vec = np.array([lat for (_, _, lat, _) in controls], dtype=float)
    lon_vec = np.array([lon for (_, _, _, lon) in controls], dtype=float)
    a_params, *_ = np.linalg.lstsq(A, lat_vec, rcond=None)
    b_params, *_ = np.linalg.lstsq(A, lon_vec, rcond=None)
    return a_params, b_params

# ------------- Public API (DLL-like) -------------

def NaviConInit_from_controls(controls: List[Tuple[float,float,float,float]]) -> None:
    """
    Initialize from control points.
    controls = [(x, y, lat_deg, lon_deg), ...]
    Requires ≥ 5 points for an exact solve of the model; works with >5 via least squares.
    """
    global _state
    if len(controls) < 5:
        raise ValueError("Need at least 5 control points (4 corners + ≥1 interior) for this model.")
    a, b = _fit_quady(controls)
    # Derive maxX,maxY from extents of provided XY (or set explicitly later)
    xs = [x for (x, *_rest) in controls]
    ys = [y for (_x, y, *_rest) in controls]
    _state = _Cal(a=a, b=b, maxX=max(xs), maxY=max(ys))

def NaviConInit_from_json(path: str) -> None:
    """
    JSON schema:
    {
      "controls": [
        {"x":..., "y":..., "lat":..., "lon":...},
        ...
      ],
      "maxX": <optional>, "maxY": <optional>
    }
    """
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    controls = [(c["x"], c["y"], c["lat"], c["lon"]) for c in cfg["controls"]]
    NaviConInit_from_controls(controls)
    # Optional explicit maxX/maxY override
    global _state
    if "maxX" in cfg and "maxY" in cfg:
        _state.maxX = float(cfg["maxX"])
        _state.maxY = float(cfg["maxY"])

def GetMaxX() -> float:
    if _state is None: raise RuntimeError("Call NaviConInit_*() first")
    return _state.maxX

def GetMaxY() -> float:
    if _state is None: raise RuntimeError("Call NaviConInit_*() first")
    return _state.maxY

def XYToLat(x: float, y: float) -> float:
    if _state is None: raise RuntimeError("Call NaviConInit_*() first")
    lat, _ = _state.predict(x, y)
    return lat

def XYToLon(x: float, y: float) -> float:
    if _state is None: raise RuntimeError("Call NaviConInit_*() first")
    _, lon = _state.predict(x, y)
    return lon
