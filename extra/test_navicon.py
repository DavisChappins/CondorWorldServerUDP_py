# test_navicon.py
from math import cos, radians, sqrt
import navicon64 as nc

TRN_PATH = r"AA3.trn"

# Your test point (XY from your system)
x_test = 460_800
y_test = 288_000

# Your reference (lon, lat) in decimal degrees
lon_ref = 10.2749
lat_ref = 45.8175

def approx_meters(lat_deg, dlat_deg, dlon_deg):
    # Rough local conversion to meters at given latitude
    m_per_deg_lat = 111_132.92
    m_per_deg_lon = 111_412.84 * cos(radians(lat_deg))
    return sqrt((dlat_deg * m_per_deg_lat) ** 2 + (dlon_deg * m_per_deg_lon) ** 2)

def run(y_down_flag):
    print(f"\n=== Testing with y_down={y_down_flag} ===")
    # Load/initialize
    nc.NaviConInit(TRN_PATH)
    # Flip behavior at runtime
    nc._state.y_down = y_down_flag  # safe tweak for testing

    # Do the conversion
    lat_pred = nc.XYToLat(x_test, y_test)
    lon_pred = nc.XYToLon(x_test, y_test)

    # Errors
    dlat = lat_pred - lat_ref
    dlon = lon_pred - lon_ref
    dist_m = approx_meters(lat_ref, dlat, dlon)

    print(f"XY: ({x_test}, {y_test})")
    print(f"Predicted: lat={lat_pred:.6f}, lon={lon_pred:.6f}")
    print(f"Reference: lat={lat_ref:.6f}, lon={lon_ref:.6f}")
    print(f"Error: Δlat={dlat:+.6f}°, Δlon={dlon:+.6f}°  (~{dist_m:.1f} m)")

if __name__ == "__main__":
    run(True)   # typical screen/image coords
    run(False)  # if your system's Y increases upward
