# fit_affine_navicon.py
# Calibrate XY -> (lat, lon) from control points using an affine model.
# Then report calibration quality and test extra points.

from dataclasses import dataclass
from math import cos, radians, sqrt
from typing import List, Tuple
import numpy as np

# ---- Your FOUR control points (lat/lon in decimal degrees) ----
# Names are just for readable output.
CONTROL_POINTS = [
    # name,                x,         y,         lat,       lon
    ("bottom_right",     7293.6,    9426.2,    43.1142,   15.7923),
    ("bottom_left",    909896.4,   13351.9,    43.2716,    4.6869),
    ("top_right",       12750.9,  567946.2,    48.1079,   16.3506),
    ("top_left",       911547.1,  564612.7,    48.2158,    4.2654),
]

# Optional extra tests (XY you want to predict)
EXTRA_TESTS: List[Tuple[str, float, float]] = [
    ("sample_xy", 460_800.0, 288_000.0),  # toggle/comment as you like
]

# ---------------------------------------------------------------

@dataclass
class AffineCal:
    # lat = a0 + a1*x + a2*y
    # lon = b0 + b1*x + b2*y
    a0: float; a1: float; a2: float
    b0: float; b1: float; b2: float

    def predict(self, x: float, y: float) -> Tuple[float, float]:
        lat = self.a0 + self.a1 * x + self.a2 * y
        lon = self.b0 + self.b1 * x + self.b2 * y
        return lat, lon

def approx_dist_m(lat_deg: float, dlat_deg: float, dlon_deg: float) -> float:
    """Approximate great-circle distance using local meters/deg at given latitude."""
    m_per_deg_lat = 111_132.92
    m_per_deg_lon = 111_412.84 * cos(radians(lat_deg))
    return sqrt((dlat_deg * m_per_deg_lat) ** 2 + (dlon_deg * m_per_deg_lon) ** 2)

def fit_affine(points: List[Tuple[str, float, float, float, float]]) -> AffineCal:
    # Build design matrix A = [1, x, y]
    A = np.array([[1.0, x, y] for _, x, y, _, _ in points], dtype=float)
    lat_vec = np.array([lat for _, _, _, lat, _ in points], dtype=float)
    lon_vec = np.array([lon for _, _, _, _, lon in points], dtype=float)

    # Least-squares solve for lat and lon separately
    a_params, *_ = np.linalg.lstsq(A, lat_vec, rcond=None)  # a0,a1,a2
    b_params, *_ = np.linalg.lstsq(A, lon_vec, rcond=None)  # b0,b1,b2
    return AffineCal(*a_params, *b_params)

def main():
    print("Fitting affine model from control points (lat = a0+a1*x+a2*y; lon = b0+b1*x+b2*y)\n")

    cal = fit_affine(CONTROL_POINTS)

    print("Calibration parameters:")
    print(f"  LAT: a0={cal.a0:.10f}, a1={cal.a1:.10e}, a2={cal.a2:.10e}")
    print(f"  LON: b0={cal.b0:.10f}, b1={cal.b1:.10e}, b2={cal.b2:.10e}\n")

    # Evaluate fit on the control points (in-sample residuals)
    print("Control point residuals:")
    errs_m = []
    for name, x, y, lat_ref, lon_ref in CONTROL_POINTS:
        lat_p, lon_p = cal.predict(x, y)
        dlat = lat_p - lat_ref
        dlon = lon_p - lon_ref
        dist_m = approx_dist_m(lat_ref, dlat, dlon)
        errs_m.append(dist_m)
        print(f"  {name:12s} XY=({x:10.1f},{y:10.1f})  "
              f"pred(lat,lon)=({lat_p:9.5f},{lon_p:10.5f})  "
              f"ref=({lat_ref:9.5f},{lon_ref:10.5f})  "
              f"Δ=({dlat:+.6f}°, {dlon:+.6f}°)  ~{dist_m:8.3f} m")

    if errs_m:
        print(f"\nSummary residuals on controls: mean={np.mean(errs_m):.3f} m, "
              f"max={np.max(errs_m):.3f} m, min={np.min(errs_m):.3f} m\n")

    # Optional extra predictions
    if EXTRA_TESTS:
        print("Extra test predictions:")
        for name, x, y in EXTRA_TESTS:
            lat_p, lon_p = cal.predict(x, y)
            print(f"  {name:12s} XY=({x:10.1f},{y:10.1f})  →  "
                  f"lat={lat_p:9.5f}, lon={lon_p:10.5f}")

if __name__ == "__main__":
    main()
