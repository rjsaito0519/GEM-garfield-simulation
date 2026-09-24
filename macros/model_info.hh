/**
 * Read the "geometry" block written by geometry/build_*_field_mesh.py into
 * "<baseName>_model_info.json" -- the single source of truth for values
 * like the GEM hole pitch and the solved domain's extent, so individual
 * macros stop re-hardcoding them (see docs/debugging_notes.md for why that
 * duplication was a problem).
 *
 * Under this project's results/ layout (see docs/reference.md), the mesh/
 * result directory macros take as argv[1] is results/mesh/<baseName>/, and
 * the model info JSON is a *sibling subdirectory* of that: results/json/
 * <baseName>_model_info.json. Both are two levels below the mesh dir's
 * parent (results/mesh/<baseName> -> results/mesh -> results), so this
 * goes up two levels then down into json/, not just one -- that tripped
 * this exact function up once already when results/ didn't exist yet and
 * model info sat directly next to the mesh dir (one level up); keep this
 * comment in sync if that layout ever changes again.
 */

#pragma once

#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>

#include "third_party/nlohmann/json.hpp"

namespace gem {

struct ModelGeometryInfo {
  double pitch_cm;
  double half_extent_x_cm;
  double half_extent_y_cm;
  double z_domain_min_cm;
  double z_domain_max_cm;
  // ComponentElmer material index for the "Gas" physical group (see
  // docs/pipeline_gotchas.md #8: ComponentElmer subtracts 1 from
  // mesh.names' 1-based body ID). Every macro used to hardcode this as the
  // literal 0, relying on "Gas" always being the first addPhysicalGroup()
  // call in geometry/*_field_model.py -- a real but silent fragility (see
  // GitHub issue #6 item 3): reordering those calls would make every
  // SetMedium(0, ...)/DriftMedium(0) call silently wrong (gotcha #8 again:
  // this specific mistake doesn't crash, only the drift-medium status
  // determination quietly breaks while raw field values stay correct).
  // Read from the actual physical_group_ids the geometry builder wrote
  // instead of assuming it.
  int gas_material_index;
};

// meshDirArg is the raw mesh/result directory path as passed on the command
// line (argv[1], no trailing slash needed/assumed); baseName is its last
// path component, exactly as every macro already derives it via
// std::filesystem::path(argv[1]).filename().string().
inline ModelGeometryInfo LoadModelGeometryInfo(const std::string& meshDirArg,
                                                const std::string& baseName) {
  const std::filesystem::path resultsDir =
      std::filesystem::path(meshDirArg).parent_path().parent_path();
  const std::filesystem::path path =
      resultsDir / "json" / (baseName + "_model_info.json");
  std::ifstream in(path);
  if (!in) {
    throw std::runtime_error("Could not open model info file: " + path.string());
  }
  nlohmann::json j;
  in >> j;
  const auto& g = j.at("geometry");
  const int gasMaterialIndex = j.at("physical_group_ids").at("Gas").get<int>() - 1;
  return ModelGeometryInfo{
      g.at("pitch_cm").get<double>(),
      g.at("half_extent_x_cm").get<double>(),
      g.at("half_extent_y_cm").get<double>(),
      g.at("z_domain_min_cm").get<double>(),
      g.at("z_domain_max_cm").get<double>(),
      gasMaterialIndex,
  };
}

}  // namespace gem
