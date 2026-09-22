/**
 * Read the "geometry" block written by geometry/build_*_field_mesh.py into
 * "<baseName>_model_info.json" -- the single source of truth for values
 * like the GEM hole pitch and the solved domain's extent, so individual
 * macros stop re-hardcoding them (see docs/debugging_notes.md for why that
 * duplication was a problem).
 *
 * That file lives one directory *above* the mesh/result directory the
 * macros take as argv[1] (e.g. geometry/output/triple_gem_field_model_info.json
 * next to the geometry/output/triple_gem_field/ mesh dir, both written by
 * geometry/build_triple_gem_field_mesh.py) -- not inside it, since ElmerGrid
 * owns the contents of the mesh/result directory itself.
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
};

// meshDirArg is the raw mesh/result directory path as passed on the command
// line (argv[1], no trailing slash needed/assumed); baseName is its last
// path component, exactly as every macro already derives it via
// std::filesystem::path(argv[1]).filename().string().
inline ModelGeometryInfo LoadModelGeometryInfo(const std::string& meshDirArg,
                                                const std::string& baseName) {
  const std::filesystem::path path =
      std::filesystem::path(meshDirArg).parent_path() / (baseName + "_model_info.json");
  std::ifstream in(path);
  if (!in) {
    throw std::runtime_error("Could not open model info file: " + path.string());
  }
  nlohmann::json j;
  in >> j;
  const auto& g = j.at("geometry");
  return ModelGeometryInfo{
      g.at("pitch_cm").get<double>(),
      g.at("half_extent_x_cm").get<double>(),
      g.at("half_extent_y_cm").get<double>(),
      g.at("z_domain_min_cm").get<double>(),
      g.at("z_domain_max_cm").get<double>(),
  };
}

}  // namespace gem
