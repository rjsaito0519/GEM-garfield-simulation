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
#include <sstream>
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
  // mesh.names' 1-based body ID). Hardcoding this as the literal 0 and
  // relying on "Gas" always being the first addPhysicalGroup() call in
  // geometry/*_field_model.py would be a real but silent fragility:
  // reordering those calls would make every SetMedium(0, ...)/
  // DriftMedium(0) call silently wrong (gotcha #8 again: this specific
  // mistake doesn't crash, only the drift-medium status determination
  // quietly breaks while raw field values stay correct).
  //
  // Read from model_info.json's "garfield_material_indices" block, written
  // by elmer/write_sif.py *after* ElmerGrid has run, from mesh.names'
  // actual (post-renumbering) body IDs -- NOT derived here from
  // "physical_group_ids" (the pre-ElmerGrid Gmsh tags model_info.json also
  // carries). Deriving it from those Gmsh tags directly would happen to
  // agree with mesh.names in every case seen so far but is not guaranteed
  // to (ElmerGrid is documented, in write_sif.py's own module docstring,
  // to renumber boundary physical groups into a compact range -- the same
  // could happen to body groups). mesh.names, not the Gmsh-side tags, is
  // this project's one authoritative source for post-ElmerGrid IDs
  // everywhere else (write_sif.py's own Target Body/Boundary indices), so
  // this field follows that same rule.
  int gas_material_index;
};

// meshDirArg is the raw mesh/result directory path as passed on the command
// line (argv[1], no trailing slash needed/assumed); baseName is its last
// path component, exactly as every macro already derives it via
// std::filesystem::path(argv[1]).filename().string().
inline std::filesystem::path ResolveModelInfoJsonPath(const std::string& meshDirArg,
                                                        const std::string& baseName) {
  const std::filesystem::path resultsDir =
      std::filesystem::path(meshDirArg).parent_path().parent_path();
  return resultsDir / "json" / (baseName + "_model_info.json");
}

inline ModelGeometryInfo LoadModelGeometryInfo(const std::string& meshDirArg,
                                                const std::string& baseName) {
  const std::filesystem::path path = ResolveModelInfoJsonPath(meshDirArg, baseName);
  std::ifstream in(path);
  if (!in) {
    throw std::runtime_error("Could not open model info file: " + path.string());
  }
  nlohmann::json j;
  in >> j;
  const auto& g = j.at("geometry");
  if (!j.contains("garfield_material_indices")) {
    throw std::runtime_error(
        "model_info.json at " + path.string() +
        " has no \"garfield_material_indices\" block -- it was produced by an older "
        "elmer/write_sif.py, or write_sif.py has not been (re-)run against this mesh since. Re-run "
        "write_sif.py (or the full geometry->Elmer pipeline) for this mesh; the gas material "
        "index is no longer derived from the pre-ElmerGrid Gmsh physical_group_ids here.");
  }
  const int gasMaterialIndex = j.at("garfield_material_indices").at("Gas").get<int>();
  return ModelGeometryInfo{
      g.at("pitch_cm").get<double>(),
      g.at("half_extent_x_cm").get<double>(),
      g.at("half_extent_y_cm").get<double>(),
      g.at("z_domain_min_cm").get<double>(),
      g.at("z_domain_max_cm").get<double>(),
      gasMaterialIndex,
  };
}

// The full, unparsed model_info.json content, for embedding verbatim into a
// simulation output's RunInfo tree (see run_info.hh) -- kept as one opaque
// blob rather than flattened into individual RunInfo keys because
// single-GEM and triple-GEM model_info.json have different
// "geometry" shapes (e.g. only the latter has a "layers" list), and a fixed
// RunInfo schema would either need per-geometry-type branches or silently
// drop fields. This is the single source of truth (this same file) already
// read by LoadModelGeometryInfo, just not parsed down to individual fields.
inline std::string LoadModelInfoJsonRaw(const std::string& meshDirArg,
                                         const std::string& baseName) {
  const std::filesystem::path path = ResolveModelInfoJsonPath(meshDirArg, baseName);
  std::ifstream in(path);
  if (!in) {
    throw std::runtime_error("Could not open model info file: " + path.string());
  }
  std::ostringstream buf;
  buf << in.rdbuf();
  return buf.str();
}

}  // namespace gem
