/**
 * Simple utility to call NaviCon.DLL from a Condor3 (https://www.condorsoaring.com/) installation.
 * Arguments:
 *   Name of scenery, e.g. "AA3"
 *   X value corresponding to the Longitude you want, e.g. 807440.44
 *   Y value corresponding to the Latitude you want, e.g. 100150.11
 * 
 * Returns two floating point numbers, comma-separated, for the Longitude,Latitude.
 * Output precision: 8 decimal places (sub-meter accuracy: ~0.79-1.11 cm at 45° latitude)
 * 
 * Example:
 *   Condor3XY2LatLon AA3 800934.75 95883.93
 *   5.99010000,44.05550000
 * ...which is St. Auban airport in France
 * 
 * This must be compiled with 32-bit MSVC as of 2025/09/27, because Condor3 is a 32-bit app.
 * Compilation is a simple matter of running "cl Condor3XY2LatLon.cpp advapi32.lib"
 * 
 */

 #include <iostream>
 #include <iomanip>
 #include <string>
 #include <windows.h>
 #include <winreg.h>
 
 typedef int (__stdcall *f_funci)(const char *);
 typedef float (__stdcall *f_funcf)(float, float);
 
 int main(int argc, char **argv)
 {
     if (argc != 4) {
         std::cout << "Wrong!  I need exactly three arguments." << std::endl
                  << "Usage (scenery name):" << std::endl
                  << "   Condor3XY2LatLon AA3 807440.44 100150.11" << std::endl
                  << std::endl
                  << "Or pass a full .trn path (e.g., local AA3.trn in current directory):" << std::endl
                  << "   Condor3XY2LatLon C:\\path\\to\\AA3.trn 807440.44 100150.11" << std::endl
                  << std::endl
                  << "...and make it clean.  I could not be arsed to do much error checking :-)" << std::endl;
         return EXIT_FAILURE;
     }
 
     char buffer[821]; // Anyone installing in a path deeper than 821 characters can rot!
     DWORD buffer_size = 821;
     std::string path = "Software\\Condor3";
     std::string value = "InstallDir";
     LSTATUS rc = RegGetValueA(HKEY_CURRENT_USER, path.c_str(), value.c_str(), RRF_RT_REG_SZ, NULL, buffer, &buffer_size);
     if (rc != ERROR_SUCCESS) {
         std::cout << "Gross.  I couldn't determine where Condor3 was installed.  Was it?" << std::endl;
         return EXIT_FAILURE;
     }
     std::string root_dir = std::string(buffer, buffer_size-1);
     // std::cout << "I think Condor3 is installed at " << root_dir << std::endl;
 
     std::string dll_name = "NaviCon.dll";
    std::string input1 = argv[1];
    float x = std::stof(argv[2]);
    float y = std::stof(argv[3]);
    std::string dll_path = root_dir + "\\" + dll_name;
 
     HINSTANCE hGetProcIDDLL = LoadLibraryA(dll_path.c_str());
     if (!hGetProcIDDLL) {
         std::cout << "could not load the " <<dll_name << " dynamic library" << std::endl;
         return EXIT_FAILURE;
     }
 
     f_funci f_init = (f_funci)GetProcAddress(hGetProcIDDLL, "NaviConInit");
    // Determine if argv[1] is a full .trn path or a scenery name
    bool is_trn_path = (input1.find(".trn") != std::string::npos) ||
                       (input1.find('\\') != std::string::npos) ||
                       (input1.find('/') != std::string::npos);
    std::string trn_name;
    if (is_trn_path) {
        trn_name = input1; // Use the provided full path
    } else {
        std::string scenery = input1;
        trn_name = root_dir + "\\Landscapes\\" + scenery + "\\" + scenery + ".trn";
    }
    int init_ret = f_init(trn_name.c_str());
    if (!init_ret) {
        std::cout << "Could not call NaviConInit(" << trn_name << ")" << std::endl;
        return EXIT_FAILURE;
    }

    f_funcf f_xy2lon = (f_funcf)GetProcAddress(hGetProcIDDLL, "XYToLon");
    float lon = f_xy2lon(x, y);
    f_funcf f_xy2lat = (f_funcf)GetProcAddress(hGetProcIDDLL, "XYToLat");
    float lat = f_xy2lat(x, y);
    
    // Output with high precision: 8 decimal places for sub-meter accuracy
    // At 45° latitude: 0.00000001° ≈ 0.79-1.11 mm, so 8 decimals ≈ 0.79-1.11 cm
    std::cout << std::fixed << std::setprecision(8) << lon << "," << lat;

    return EXIT_SUCCESS;
}