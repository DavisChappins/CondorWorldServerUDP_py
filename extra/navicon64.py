# navicon64.py
# Pure-Python reimplementation of the observed NaviCon.dll behavior (x64-safe)

import struct
from dataclasses import dataclass

@dataclass
class NaviConState:
    width: int
    height: int
    north: float
    south: float
    east_like: float  # header’s third float; not used directly
    maxX: float
    maxY: float
    lon_min: float
    lon_max: float
    y_down: bool = True  # set False if your Y increases upward

_state: NaviConState | None = None

def _read_header(trn_path: str) -> NaviConState:
    with open(trn_path, "rb") as f:
        hdr = f.read(64)  # first 64 bytes are enough for the discovered fields
    # Interpret as little-endian
    # First 2 uint32: width, height
    width, height = struct.unpack_from("<II", hdr, 0)
    # Next 3 float32: 90.0, -90.0, 90.0
    north, south, east_like = struct.unpack_from("<fff", hdr, 8)
    # Next 2 float32: maxX, maxY
    maxX, maxY = struct.unpack_from("<ff", hdr, 20)
    # Next 2 uint32: 32, 78  (we interpret these as lon_min, lon_max)
    lon_min, lon_max = struct.unpack_from("<II", hdr, 28)

    # Sanity checks / fallbacks
    if not (-90.0 <= south <= 0.0 and 0.0 <= north <= 90.0):
        # If header is different than expected, you can adjust here.
        pass

    return NaviConState(
        width=width,
        height=height,
        north=float(north),
        south=float(south),
        east_like=float(east_like),
        maxX=float(maxX),
        maxY=float(maxY),
        lon_min=float(lon_min),
        lon_max=float(lon_max),
        y_down=True,  # typical image coords grow downward; flip if needed
    )

# Public API mirroring the DLL’s naming

def NaviConInit(trn_path: str) -> None:
    """Load calibration from the .trn file header."""
    global _state
    _state = _read_header(trn_path)

def GetMaxX() -> float:
    if _state is None:
        raise RuntimeError("NaviConInit() must be called first")
    return _state.maxX

def GetMaxY() -> float:
    if _state is None:
        raise RuntimeError("NaviConInit() must be called first")
    return _state.maxY

def XYToLat(x: float, y: float) -> float:
    """Convert XY to latitude in degrees. Assumes linear georeference."""
    if _state is None:
        raise RuntimeError("NaviConInit() must be called first")
    st = _state
    # Map y to [0..1] top→bottom or bottom→top depending on y_down
    if st.y_down:
        ny = (st.maxY - y) / st.maxY
    else:
        ny = y / st.maxY
    # Lat spans south..north (−90..+90 from header)
    lat = st.south + ny * (st.north - st.south)
    return lat

def XYToLon(x: float, y: float | None = None) -> float:
    """Convert X to longitude in degrees. Y not required for lon in a linear model."""
    if _state is None:
        raise RuntimeError("NaviConInit() must be called first")
    st = _state
    nx = x / st.maxX
    lon = st.lon_min + nx * (st.lon_max - st.lon_min)
    return lon

# Convenience: a single call that returns (lat, lon)
def XYToLatLon(x: float, y: float) -> tuple[float, float]:
    return XYToLat(x, y), XYToLon(x, y)

if __name__ == "__main__":
    # Example usage:
    # Update the path to your .trn file
    trn = r"AA3.trn"
    NaviConInit(trn)
    print("MaxX:", GetMaxX())
    print("MaxY:", GetMaxY())
    # Sample point (center of the domain)
    cx, cy = GetMaxX()/2, GetMaxY()/2
    lat, lon = XYToLatLon(cx, cy)
    print("Center →", lat, lon)
