# fit_bilinear_plus_y2.py
# Fits lat,lon = (1, x, y, x*y, y^2) · params using your 4 corners + 1 interior point.

from dataclasses import dataclass
from math import cos, radians, sqrt
from typing import List, Tuple
import numpy as np

# ---- Controls: your 4 corners + 1 interior ground-truth ----
CONTROLS: List[Tuple[str, float, float, float, float]] = [
    # name,                x,         y,         lat,       lon
    ("bottom_right",     7293.6,     9426.2,    43.1142,   15.7923),
    ("bottom_left",    909896.4,    13351.9,    43.2716,    4.6869),
    ("top_right",       12750.9,   567946.2,    48.1079,   16.3506),
    ("top_left",       911547.1,   564612.7,    48.2158,    4.2654),
    ("interior_1",     460800.0,   288000.0,    45.8175,   10.2749),  # your known inside point
]

# Optional extra XY tests to predict (no refs needed)
EXTRA_TESTS: List[Tuple[str, float, float]] = [
    ("centerish", 460_800.0, 288_000.0),  # same as interior_1, should now be ~exact
]

def approx_dist_m(lat_deg: float, dlat_deg: float, dlon_deg: float) -> float:
    m_per_deg_lat = 111_132.92
    m_per_deg_lon = 111_412.84 * cos(radians(lat_deg))
    return ((dlat_deg*m_per_deg_lat)**2 + (dlon_deg*m_per_deg_lon)**2) ** 0.5

@dataclass
class QuadYCal:
    # lat = a0 + a1*x + a2*y + a3*x*y + a4*y^2
    # lon = b0 + b1*x + b2*y + b3*x*y + b4*y^2
    a: np.ndarray  # shape (5,)
    b: np.ndarray  # shape (5,)

    def predict(self, x: float, y: float) -> Tuple[float, float]:
        phi = np.array([1.0, x, y, x*y, y*y], dtype=float)
        lat = float(phi @ self.a)
        lon = float(phi @ self.b)
        return lat, lon

def fit_quady(pts) -> QuadYCal:
    # Design matrix with columns [1, x, y, x*y, y^2]
    A = np.array([[1.0, x, y, x*y, y*y] for _, x, y, _, _ in pts], dtype=float)
    lat_vec = np.array([lat for _, _, _, lat, _ in pts], dtype=float)
    lon_vec = np.array([lon for _, _, _, _, lon in pts], dtype=float)

    # Solve (exact if 5 pts; least-squares if >5)
    a_params, *_ = np.linalg.lstsq(A, lat_vec, rcond=None)
    b_params, *_ = np.linalg.lstsq(A, lon_vec, rcond=None)
    return QuadYCal(a_params, b_params)

def main():
    cal = fit_quady(CONTROLS)

    # Report control residuals
    print("Control point residuals:")
    errs = []
    for name, x, y, lat_ref, lon_ref in CONTROLS:
        lat_p, lon_p = cal.predict(x, y)
        dlat = lat_p - lat_ref
        dlon = lon_p - lon_ref
        dist = approx_dist_m(lat_ref, dlat, dlon)
        errs.append(dist)
        print(f"  {name:12s} XY=({x:10.1f},{y:10.1f})  "
              f"pred=({lat_p:9.6f},{lon_p:10.6f})  "
              f"ref=({lat_ref:9.6f},{lon_ref:10.6f})  "
              f"Δ=({dlat:+.6f}°, {dlon:+.6f}°)  ~{dist:8.3f} m")
    print(f"\nSummary residuals: mean={np.mean(errs):.3f} m, "
          f"max={np.max(errs):.3f} m, min={np.min(errs):.3f} m\n")

    # ADD THIS SECTION
    print("\n" + "="*60)
    print("COPY THE CODE BLOCK BELOW AND PASTE IT INTO 'aa3_converter.py'")
    print("="*60)
    print("    a_params = np.array([", end="")
    print(*[f"{v: .8e}" for v in cal.a], sep=", ", end="])\n")
    print("    b_params = np.array([", end="")
    print(*[f"{v: .8e}" for v in cal.b], sep=", ", end="])")
    print("="*60 + "\n")

    # Extra predictions
    if EXTRA_TESTS:
        print("Extra predictions:")
        for name, x, y in EXTRA_TESTS:
            lat_p, lon_p = cal.predict(x, y)
            print(f"  {name:12s} XY=({x:10.1f},{y:10.1f}) → lat={lat_p:9.6f}, lon={lon_p:10.6f}")

if __name__ == "__main__":
    main()
