/**
 * Sample an Elmer field map (single-GEM or the full 3-GEM stack -- this
 * macro is geometry-agnostic) on regular grids and dump the results to
 * JSON, for visualization/plot_triple_gem.py to render as vector arrows
 * and as color-mapped slice planes.
 *
 * Two versions of each are written: a coarse "full" grid spanning the whole
 * solved domain (context), and a fine "zoom" grid restricted to a thin slab
 * around z=0 (where the field actually funnels through a hole -- a uniform
 * grid over the full range would barely resolve it).
 *
 * The mesh/result base name and the pitch/domain-extent values are all
 * taken from "<mesh dir>/<baseName>_model_info.json" (written by
 * geometry/build_*_field_mesh.py), not hardcoded here -- see model_info.hh.
 *
 * Output: "<outDir>/<baseName>_field_{vectors,slice}_{full,zoom}.json"
 * (baseName-prefixed, like every other macro's output in this project --
 * see docs/debugging_notes.md. Without the prefix, switching models
 * without re-running this macro would silently feed a stale/mismatched
 * model's field data into the visualization).
 *
 * Usage: export_field_samples <mesh/result directory> <output directory>
 */

#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "Garfield/ComponentElmer.hh"
#include "Garfield/MediumMagboltz.hh"

#include "model_info.hh"

using namespace Garfield;

namespace {

// Half-range of the "zoom" grid around z=0 -- purely a display choice (how
// closely to zoom in on a GEM foil), not a physical parameter that can get
// out of sync between Python and C++, so it stays a local constant.
constexpr double kZoomZCm = 0.006;

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
  const std::string baseName = std::filesystem::path(argv[1]).filename().string();
  const std::string outDir = std::string(argv[2]) + "/";

  const gem::ModelGeometryInfo geo = gem::LoadModelGeometryInfo(argv[1], baseName);
  // Shrunk by 2% to stay clear of the domain boundary, where point-location
  // can be flaky (samples right on the edge can spuriously read back
  // status -6, "outside the mesh").
  const double halfXCm = 0.98 * geo.half_extent_x_cm;
  const double halfYCm = 0.98 * geo.half_extent_y_cm;

  MediumMagboltz gas;
  gas.SetComposition("ar", 90., "ch4", 10.);
  gas.SetTemperature(293.15);
  gas.SetPressure(760.);

  ComponentElmer elm(meshDir + "mesh.header", meshDir + "mesh.elements",
                      meshDir + "mesh.nodes", meshDir + "dielectrics.dat",
                      meshDir + baseName + ".result", "cm");
  // geo.gas_material_index is read from the actual "Gas" physical group ID
  // the geometry builder wrote (model_info.hh), not hardcoded -- see that
  // struct's own comment and docs/pipeline_gotchas.md #8 (ComponentElmer
  // subtracts 1 from mesh.names' 1-based body ID).
  elm.SetMedium(geo.gas_material_index, &gas);
  // SetMedium() alone does not flag this material as a drift medium, which
  // would leave every sample's "status" at -5.
  elm.DriftMedium(geo.gas_material_index);

  // Vector-arrow grids: kept coarse since each point becomes a visible arrow.
  {
    const int nx = 6, ny = 5, nz = 24;
    WriteSamplesJson(
        SampleGrid(elm, -halfXCm, halfXCm, nx, -halfYCm, halfYCm, ny,
                   geo.z_domain_min_cm, geo.z_domain_max_cm, nz),
        nx, ny, nz, outDir + baseName + "_field_vectors_full.json");
  }
  {
    const int nx = 12, ny = 9, nz = 16;
    WriteSamplesJson(
        SampleGrid(elm, -halfXCm, halfXCm, nx, -halfYCm, halfYCm, ny,
                   -kZoomZCm, kZoomZCm, nz),
        nx, ny, nz, outDir + baseName + "_field_vectors_zoom.json");
  }

  // Slice grids (y=0 plane): denser, since these render as a smooth color map.
  {
    const int nx = 60, nz = 240;
    WriteSamplesJson(
        SampleGrid(elm, -halfXCm, halfXCm, nx, 0.0, 0.0, 1,
                   geo.z_domain_min_cm, geo.z_domain_max_cm, nz),
        nx, 1, nz, outDir + baseName + "_field_slice_full.json");
  }
  {
    const int nx = 80, nz = 80;
    WriteSamplesJson(
        SampleGrid(elm, -halfXCm, halfXCm, nx, 0.0, 0.0, 1,
                   -kZoomZCm, kZoomZCm, nz),
        nx, 1, nz, outDir + baseName + "_field_slice_zoom.json");
  }

  return 0;
}
