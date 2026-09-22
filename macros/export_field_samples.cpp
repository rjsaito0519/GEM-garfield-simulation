/**
 * Sample the single-GEM Elmer field map on regular grids and dump the
 * results to JSON, for the interactive 3D viewer
 * (macros/output/field_viewer.html) to render as vector arrows and as
 * color-mapped slice planes.
 *
 * Two versions of each are written: a coarse "full" grid spanning the whole
 * drift-GEM-transfer stack (context), and a fine "zoom" grid restricted to
 * a thin slab around the GEM foil (where the field actually funnels through
 * the hole -- a uniform grid over the full range would barely resolve it).
 *
 * Usage: export_field_samples <mesh/result directory> <output directory>
 */

#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "Garfield/ComponentElmer.hh"
#include "Garfield/MediumMagboltz.hh"

using namespace Garfield;

namespace {

// Same caveat as view_single_gem_field.cpp: hardcoded to match
// gem_params.GEM_50UM (pitch = 140 um = 0.014 cm), not read from a shared
// source of truth.
constexpr double kPitchCm = 0.014;
// The solved domain is exactly one hexagonal unit cell (see
// gem_unit_cell.py's _hole_centers / single_gem_field_model.py's
// _add_gas_box): half-width pitch/2 in x, pitch*sqrt(3)/2 in y. Sampling
// outside this returns status -6 ("outside the mesh") -- there is no field
// map beyond the single cell that was actually meshed and solved. Shrunk by
// 2% to stay clear of the boundary, where point-location can be flaky.
constexpr double kHalfXCm = 0.98 * kPitchCm / 2.0;
constexpr double kHalfYCm = 0.98 * kPitchCm * 0.8660254037844387;  // sqrt(3)/2
constexpr double kFullZMinCm = -0.21;   // just past the transfer plane
constexpr double kFullZMaxCm = 0.43;    // just past the drift plane
constexpr double kZoomZCm = 0.006;      // +/- range around the GEM foil (z=0)

struct FieldSample {
  double x, y, z;
  double ex, ey, ez, v;
  int status;
};

std::vector<FieldSample> SampleGrid(ComponentElmer& component, double xMin,
                                     double xMax, int nx, double yMin,
                                     double yMax, int ny, double zMin,
                                     double zMax, int nz) {
  std::vector<FieldSample> samples;
  samples.reserve(nx * ny * nz);
  for (int ix = 0; ix < nx; ++ix) {
    const double x = nx == 1 ? xMin : xMin + (xMax - xMin) * ix / (nx - 1);
    for (int iy = 0; iy < ny; ++iy) {
      const double y = ny == 1 ? yMin : yMin + (yMax - yMin) * iy / (ny - 1);
      for (int iz = 0; iz < nz; ++iz) {
        const double z = nz == 1 ? zMin : zMin + (zMax - zMin) * iz / (nz - 1);
        FieldSample s{x, y, z, 0, 0, 0, 0, 0};
        Medium* medium = nullptr;
        component.ElectricField(x, y, z, s.ex, s.ey, s.ez, s.v, medium, s.status);
        samples.push_back(s);
      }
    }
  }
  return samples;
}

// Writes {"nx":.., "ny":.., "nz":.., "samples":[...]} -- the shape lets the
// viewer reshape the flat sample list back into an (nx, ny, nz) grid (needed
// e.g. to build a Plotly Surface for the slice views) without having to
// infer it from floating-point coordinates in JavaScript.
void WriteSamplesJson(const std::vector<FieldSample>& samples, int nx, int ny,
                       int nz, const std::string& path) {
  std::ofstream out(path);
  out << "{\"nx\":" << nx << ",\"ny\":" << ny << ",\"nz\":" << nz
      << ",\"samples\":[";
  for (size_t i = 0; i < samples.size(); ++i) {
    const auto& s = samples[i];
    if (i > 0) out << ",";
    out << "{\"x\":" << s.x << ",\"y\":" << s.y << ",\"z\":" << s.z
        << ",\"ex\":" << s.ex << ",\"ey\":" << s.ey << ",\"ez\":" << s.ez
        << ",\"v\":" << s.v << ",\"status\":" << s.status << "}";
  }
  out << "]}";
  std::cout << "Wrote " << samples.size() << " samples to " << path << "\n";
}

}  // namespace

int main(int argc, char* argv[]) {
  if (argc != 3) {
    std::cout << "Usage: export_field_samples <mesh/result directory> "
                 "<output directory>\n";
    return 1;
  }
  const std::string meshDir = std::string(argv[1]) + "/";
  const std::string outDir = std::string(argv[2]) + "/";

  MediumMagboltz gas;
  gas.SetComposition("ar", 90., "ch4", 10.);
  gas.SetTemperature(293.15);
  gas.SetPressure(760.);

  ComponentElmer elm(meshDir + "mesh.header", meshDir + "mesh.elements",
                      meshDir + "mesh.nodes", meshDir + "dielectrics.dat",
                      meshDir + "single_gem_field.result", "cm");
  // Index 0, not body ID 1: see view_single_gem_field.cpp's comment on the
  // same call for why (ComponentElmer subtracts 1 from every body ID before
  // using it as an array index).
  elm.SetMedium(0, &gas);
  // SetMedium() alone does not flag material 0 as a drift medium, which
  // would leave every sample's "status" at -5.
  elm.DriftMedium(0);

  // Vector-arrow grids: kept coarse since each point becomes a visible arrow.
  {
    const int nx = 6, ny = 5, nz = 24;
    WriteSamplesJson(
        SampleGrid(elm, -kHalfXCm, kHalfXCm, nx, -kHalfYCm, kHalfYCm, ny,
                   kFullZMinCm, kFullZMaxCm, nz),
        nx, ny, nz, outDir + "field_vectors_full.json");
  }
  {
    const int nx = 12, ny = 9, nz = 16;
    WriteSamplesJson(
        SampleGrid(elm, -kHalfXCm, kHalfXCm, nx, -kHalfYCm, kHalfYCm, ny,
                   -kZoomZCm, kZoomZCm, nz),
        nx, ny, nz, outDir + "field_vectors_zoom.json");
  }

  // Slice grids (y=0 plane): denser, since these render as a smooth color map.
  {
    const int nx = 60, nz = 240;
    WriteSamplesJson(
        SampleGrid(elm, -kHalfXCm, kHalfXCm, nx, 0.0, 0.0, 1,
                   kFullZMinCm, kFullZMaxCm, nz),
        nx, 1, nz, outDir + "field_slice_full.json");
  }
  {
    const int nx = 80, nz = 80;
    WriteSamplesJson(
        SampleGrid(elm, -kHalfXCm, kHalfXCm, nx, 0.0, 0.0, 1,
                   -kZoomZCm, kZoomZCm, nz),
        nx, 1, nz, outDir + "field_slice_zoom.json");
  }

  return 0;
}
