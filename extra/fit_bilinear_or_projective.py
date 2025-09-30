# fit_bilinear_or_projective.py
# Fit XY -> (lat, lon) using (A) bilinear and (B) optional projective models.

from dataclasses import dataclass
from math import cos, radians, sqrt
from typing import List, Tuple
import numpy as np

# ---- Your 4 controls (decimal degrees) ----
CONTROLS = [
    # name,                x,         y,         lat,       lon
    ("bottom_right",     7293.6,    9426.2,    43.1142,   15.7923),
    ("bottom_left",    909896.4,   13351.9,    43.2716,    4.6869),
    ("top_right",       12750.9,  567946.2,    48.1079,   16.3506),
    ("top_left",       911547.1,  564612.7,    48.2158,    4.2654),
]

# Extra test XYs to predict (add more as needed)
EXTRA_TESTS = [
    ("sample_xy", 460_800.0, 288_000.0),
]

def approx_dist_m(lat_deg: float, dlat_deg: float, dlon_deg: float) -> float:
    m_per_deg_lat = 111_132.92
    m_per_deg_lon = 111_412.84 * cos(radians(lat_deg))
    return ( (dlat_deg*m_per_deg_lat)**2 + (dlon_deg*m_per_deg_lon)**2 ) ** 0.5

# ---------- (A) Bilinear fit ----------
@dataclass
class BilinearCal:
    # lat = a0 + a1*x + a2*y + a3*x*y
    # lon = b0 + b1*x + b2*y + b3*x*y
    a0: float; a1: float; a2: float; a3: float
    b0: float; b1: float; b2: float; b3: float

    def predict(self, x: float, y: float) -> Tuple[float, float]:
        lat = self.a0 + self.a1*x + self.a2*y + self.a3*x*y
        lon = self.b0 + self.b1*x + self.b2*y + self.b3*x*y
        return lat, lon

def fit_bilinear(pts) -> BilinearCal:
    # Build matrix for [1, x, y, x*y]
    A = np.array([[1.0, x, y, x*y] for _, x, y, _, _ in pts], dtype=float)
    lat_vec = np.array([lat for _, _, _, lat, _ in pts], dtype=float)
    lon_vec = np.array([lon for _, _, _, _, lon in pts], dtype=float)

    a_params, *_ = np.linalg.lstsq(A, lat_vec, rcond=None)
    b_params, *_ = np.linalg.lstsq(A, lon_vec, rcond=None)
    return BilinearCal(*a_params, *b_params)

# ---------- (B) Projective (Homography) optional ----------
@dataclass
class HomogCal:
    # Maps (x,y,1) via 3x3 H_l and H_phi to (lon, lat)
    Hl: np.ndarray  # for longitude
    Hp: np.ndarray  # for latitude

    def predict(self, x: float, y: float) -> Tuple[float, float]:
        v = np.array([x, y, 1.0])
        lon_h = self.Hl @ v
        lat_h = self.Hp @ v
        lon = lon_h[0] / lon_h[2]
        lat = lat_h[0] / lat_h[2]
        return lat, lon

def _fit_homography(src_pts, dst_vals):
    """
    Solve 8-parameter homography mapping (x,y,1) -> (u,w) with u/w = target
    Using 4 point correspondences.
    dst_vals is the scalar target (e.g., lon or lat).
    """
    # Build linear system for H with entries h11..h33, but fix h33=1 to remove scale DOF.
    # We solve for [h11,h12,h13,h21,h22,h23,h31,h32] per standard DLT for scalar mapping.
    # For each point (x,y) and value t: (h11 x + h12 y + h13) / (h31 x + h32 y + 1) = t
    # => (h11 x + h12 y + h13) - t*(h31 x + h32 y + 1) = 0
    A = []
    b = []
    for (_, x, y, _, _), t in zip(CONTROLS, dst_vals):
        A.append([x, y, 1,   0, 0, 0,   -t*x, -t*y])
        b.append(t)
    A = np.array(A, dtype=float)
    b = np.array(b, dtype=float)
    # Solve A * p = b, where p = [h11,h12,h13,h21,h22,h23,h31,h32], but we set h21.. to zero for scalar?:
    # To keep it simple, we actually fit two separate homographies in "1D" form by setting row2 equal to row1
    # which reduces to rational function per coordinate; this is a pragmatic approach for 4 points.
    p, *_ = np.linalg.lstsq(A, b, rcond=None)
    # Construct H as [[h11,h12,h13],[0,0,1],[h31,h32,1]]
    H = np.array([[p[0], p[1], p[2]],
                  [0.0,  0.0,  1.0],
                  [p[6], p[7], 1.0 ]], dtype=float)
    return H

def fit_projective(pts) -> HomogCal:
    lons = [lon for _, _, _, _, lon in pts]
    lats = [lat for _, _, _, lat, _ in pts]
    Hl = _fit_homography(pts, lons)
    Hp = _fit_homography(pts, lats)
    return HomogCal(Hl, Hp)

# ----------------- Runner -----------------
def report_fit(name: str, model, predict_fn):
    print(f"\n{name} residuals on control points:")
    errs = []
    for nm, x, y, lat_ref, lon_ref in CONTROLS:
        lat_p, lon_p = predict_fn(model, x, y)
        dlat = lat_p - lat_ref
        dlon = lon_p - lon_ref
        dist = approx_dist_m(lat_ref, dlat, dlon)
        errs.append(dist)
        print(f"  {nm:12s} XY=({x:10.1f},{y:10.1f})  "
              f"pred=({lat_p:9.5f},{lon_p:10.5f})  "
              f"ref=({lat_ref:9.5f},{lon_ref:10.5f})  "
              f"Δ=({dlat:+.6f}°, {dlon:+.6f}°)  ~{dist:8.3f} m")
    print(f"  -> mean={np.mean(errs):.2f} m, max={np.max(errs):.2f} m, min={np.min(errs):.2f} m")

    if EXTRA_TESTS:
        print("\nExtra test predictions:")
        for nm, x, y in EXTRA_TESTS:
            lat_p, lon_p = predict_fn(model, x, y)
            print(f"  {nm:12s} XY=({x:10.1f},{y:10.1f}) → lat={lat_p:9.5f}, lon={lon_p:10.5f}")

def main():
    # (A) Bilinear
    bil = fit_bilinear(CONTROLS)
    def bil_pred(m,x,y): return m.predict(x,y)
    report_fit("Bilinear", bil, bil_pred)

    # (B) Projective (optional; uncomment if you want to compare)
    # proj = fit_projective(CONTROLS)
    # def proj_pred(m,x,y): return m.predict(x,y)
    # report_fit("Projective", proj, proj_pred)

if __name__ == "__main__":
    main()
