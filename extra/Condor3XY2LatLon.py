import sys
import os.path
from ctypes import WinDLL, c_char_p, c_int, c_float

condor_base = sys.argv[1]
landscape = sys.argv[2]
dll_path = os.path.join(condor_base, "NaviCon.dll")
trn_path = os.path.join(condor_base, "Landscapes", landscape, landscape + ".trn").encode("utf-8")
x = float(sys.argv[3])
y = float(sys.argv[4])
nav = WinDLL(dll_path)
NaviConInit = nav.NaviConInit
NaviConInit.argtypes = [c_char_p]
NaviConInit.restype = c_int
ret = NaviConInit(trn_path)

XYToLat = nav.XYToLat
XYToLat.argtypes = [c_float, c_float]
XYToLat.restype = c_float
XYToLon = nav.XYToLon
XYToLon.argtypes = [c_float, c_float]
XYToLon.restype = c_float

lat = XYToLat(x, y)
lon = XYToLon(x, y)
print(lat)
print(lon)