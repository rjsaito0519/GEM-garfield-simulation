/**
 * Print the field/potential at one or more explicit (x, y, z) points --
 * a quick diagnostic tool for questions like "which way does E point right
 * here", without having to build a whole visualization.
 *
 * Usage: probe_field <mesh/result dir> x1,y1,z1 [x2,y2,z2 ...]
 *   Coordinates in cm.
 */

#include <cmath>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "Garfield/ComponentElmer.hh"
#include "Garfield/MediumMagboltz.hh"

using namespace Garfield;

namespace {
std::array<double, 3> ParsePoint(const std::string& arg) {
  std::array<double, 3> p{};
  std::stringstream ss(arg);
  std::string token;
  for (int i = 0; i < 3; ++i) {
    std::getline(ss, token, ',');
    p[i] = std::stod(token);
  }
  return p;
}
}  // namespace

int main(int argc, char* argv[]) {
  if (argc < 3) {
    std::cout << "Usage: probe_field <mesh/result dir> x1,y1,z1 [x2,y2,z2 ...]\n";
    return 1;
  }
  const std::string meshDir = std::string(argv[1]) + "/";
  const std::string baseName = std::filesystem::path(argv[1]).filename().string();

  MediumMagboltz gas;
  gas.SetComposition("ar", 90., "ch4", 10.);
  gas.SetTemperature(293.15);
  gas.SetPressure(760.);

  ComponentElmer elm(meshDir + "mesh.header", meshDir + "mesh.elements",
                      meshDir + "mesh.nodes", meshDir + "dielectrics.dat",
                      meshDir + baseName + ".result", "cm");
  elm.SetMedium(0, &gas);
  elm.DriftMedium(0);

  for (int i = 2; i < argc; ++i) {
    const auto p = ParsePoint(argv[i]);
    double ex, ey, ez, v;
    Medium* medium = nullptr;
    int status;
    elm.ElectricField(p[0], p[1], p[2], ex, ey, ez, v, medium, status);
    std::cout << "(" << p[0] << ", " << p[1] << ", " << p[2] << "): "
              << "E=(" << ex << ", " << ey << ", " << ez << ") V/cm, "
              << "|E|=" << std::sqrt(ex * ex + ey * ey + ez * ez) << " V/cm, "
              << "V=" << v << " V, status=" << status << "\n";
  }
  return 0;
}
