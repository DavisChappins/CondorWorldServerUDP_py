/**
 * Persistent version of Condor3XY2LatLon - keeps NaviCon.dll loaded and reads from stdin
 * 
 * This version loads the DLL once and then enters a loop reading X,Y coordinates from stdin
 * and writing Lon,Lat to stdout. This eliminates the process startup overhead.
 * 
 * Protocol:
 *   Input (stdin):  "X Y\n" (e.g., "807440.44 100150.11\n")
 *   Output (stdout): "LON,LAT\n" (e.g., "5.99010000,44.05550000\n")
 *   Special: "EXIT\n" to quit
 * 
 * Usage:
 *   Condor3XY2LatLon_persistent.exe <scenery_or_trn_path>
 * 
 * Example:
 *   Condor3XY2LatLon_persistent.exe AA3
 *   (then send "807440.44 100150.11\n" via stdin)
 * 
 * Compile with 32-bit MSVC:
 *   cl /O2 Condor3XY2LatLon_persistent.cpp advapi32.lib
 */

#include <iostream>
#include <iomanip>
#include <string>
#include <sstream>
#include <windows.h>
#include <winreg.h>

typedef int (__stdcall *f_funci)(const char *);
typedef float (__stdcall *f_funcf)(float, float);

int main(int argc, char **argv)
{
    if (argc != 2) {
        std::cerr << "Usage: Condor3XY2LatLon_persistent.exe <scenery_or_trn_path>" << std::endl;
        std::cerr << "Example: Condor3XY2LatLon_persistent.exe AA3" << std::endl;
        std::cerr << "Or: Condor3XY2LatLon_persistent.exe C:\\path\\to\\AA3.trn" << std::endl;
        return EXIT_FAILURE;
    }

    // Get Condor3 install directory
    char buffer[821];
    DWORD buffer_size = 821;
    std::string path = "Software\\Condor3";
    std::string value = "InstallDir";
    LSTATUS rc = RegGetValueA(HKEY_CURRENT_USER, path.c_str(), value.c_str(), RRF_RT_REG_SZ, NULL, buffer, &buffer_size);
    if (rc != ERROR_SUCCESS) {
        std::cerr << "ERROR: Could not find Condor3 installation directory in registry" << std::endl;
        return EXIT_FAILURE;
    }
    std::string root_dir = std::string(buffer, buffer_size-1);

    // Load NaviCon.dll
    std::string dll_name = "NaviCon.dll";
    std::string dll_path = root_dir + "\\" + dll_name;
    HINSTANCE hGetProcIDDLL = LoadLibraryA(dll_path.c_str());
    if (!hGetProcIDDLL) {
        std::cerr << "ERROR: Could not load " << dll_path << std::endl;
        return EXIT_FAILURE;
    }

    // Get function pointers
    f_funci f_init = (f_funci)GetProcAddress(hGetProcIDDLL, "NaviConInit");
    f_funcf f_xy2lon = (f_funcf)GetProcAddress(hGetProcIDDLL, "XYToLon");
    f_funcf f_xy2lat = (f_funcf)GetProcAddress(hGetProcIDDLL, "XYToLat");
    
    if (!f_init || !f_xy2lon || !f_xy2lat) {
        std::cerr << "ERROR: Could not get NaviCon.dll function pointers" << std::endl;
        return EXIT_FAILURE;
    }

    // Determine TRN path
    std::string input1 = argv[1];
    bool is_trn_path = (input1.find(".trn") != std::string::npos) ||
                       (input1.find('\\') != std::string::npos) ||
                       (input1.find('/') != std::string::npos);
    std::string trn_name;
    if (is_trn_path) {
        trn_name = input1;
    } else {
        std::string scenery = input1;
        trn_name = root_dir + "\\Landscapes\\" + scenery + "\\" + scenery + ".trn";
    }

    // Initialize NaviCon with TRN file (ONCE)
    int init_ret = f_init(trn_name.c_str());
    if (!init_ret) {
        std::cerr << "ERROR: NaviConInit failed for " << trn_name << std::endl;
        return EXIT_FAILURE;
    }

    // Signal ready
    std::cout << "READY" << std::endl;
    std::cout.flush();

    // Main loop: read X Y from stdin, write LON,LAT to stdout
    std::string line;
    while (std::getline(std::cin, line)) {
        // Trim whitespace
        line.erase(0, line.find_first_not_of(" \t\r\n"));
        line.erase(line.find_last_not_of(" \t\r\n") + 1);
        
        if (line.empty()) {
            continue;
        }
        
        if (line == "EXIT") {
            break;
        }

        // Parse "X Y"
        std::istringstream iss(line);
        float x, y;
        if (!(iss >> x >> y)) {
            std::cout << "ERROR: Invalid input format" << std::endl;
            std::cout.flush();
            continue;
        }

        // Convert
        float lon = f_xy2lon(x, y);
        float lat = f_xy2lat(x, y);

        // Output with high precision
        std::cout << std::fixed << std::setprecision(8) << lon << "," << lat << std::endl;
        std::cout.flush();
    }

    return EXIT_SUCCESS;
}
