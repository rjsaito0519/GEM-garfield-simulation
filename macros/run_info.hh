/**
 * Write a "RunInfo" ROOT TTree (one (key, value) string pair per entry) to
 * a simulation output file, recording the conditions actually used for that
 * run -- so an output file is self-describing and analysis code doesn't
 * have to trust that its own re-derived config still matches whatever
 * simulation produced the file (see GitHub issue #6, items 1-3).
 *
 * A flexible key/value schema is used deliberately, not a fixed branch per
 * field: single-GEM and triple-GEM model_info.json have different
 * "geometry" shapes (see model_info.hh's LoadModelInfoJsonRaw), and a fixed
 * schema would either need separate trees per geometry type or silently
 * drop fields when the JSON shape changes -- both worse than one flexible
 * tree that analysis code looks up by key. The full model_info.json content
 * is included verbatim under the "model_info_json" key so every geometry/
 * material/voltage value the geometry builder wrote (including the
 * "Gas" -> Garfield material index mapping, physical_group_ids) is
 * available without re-deriving it; the remaining keys are runtime-only
 * parameters (gas file, RNG seed, avalanche size limit, ...) that the
 * geometry JSON has no way to know about.
 */

#pragma once

#include <string>
#include <utility>
#include <vector>

#include <TFile.h>
#include <TTree.h>

namespace gem {

using RunInfoEntry = std::pair<std::string, std::string>;

// Opened in UPDATE mode by the caller (same convention as the "Endpoints"/
// "Trajectories" trees, see export_avalanche_trajectories.cpp) -- any
// existing "RunInfo" cycles are purged first so re-running a macro against
// the same output file replaces its RunInfo instead of accumulating stale
// cycles.
inline void WriteRunInfo(TFile* file, const std::vector<RunInfoEntry>& entries) {
  file->cd();
  file->Delete("RunInfo;*");
  TTree tree("RunInfo", "Simulation run conditions (key, value string pairs) -- see GitHub issue #6 item 1");
  std::string key, value;
  tree.Branch("key", &key);
  tree.Branch("value", &value);
  for (const auto& entry : entries) {
    key = entry.first;
    value = entry.second;
    tree.Fill();
  }
  tree.Write();
}

}  // namespace gem
