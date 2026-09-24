/**
 * Write a per-macro ROOT TTree (one (key, value) string pair per entry) to
 * a simulation output file, recording the conditions actually used for that
 * run -- so an output file is self-describing and analysis code doesn't
 * have to trust that its own re-derived config still matches whatever
 * simulation produced the file (see GitHub issue #6, items 1-3).
 *
 * Tree name is caller-supplied ("RunInfoEndpoints" for gem_avalanche.cpp,
 * "RunInfoTrajectories" for export_avalanche_trajectories.cpp) rather than
 * one shared "RunInfo" name -- the original single shared name meant
 * whichever of those two macros ran most recently against a given output
 * file silently overwrote the other's metadata (last-writer-wins), even
 * though their sibling data trees ("Endpoints"/"Trajectories") coexist
 * fine. See GitHub issue #11 item 1.
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
// existing cycles of this exact tree_name are purged first so re-running a
// macro against the same output file replaces its own RunInfo tree instead
// of accumulating stale cycles, without touching any other macro's
// same-file RunInfo* tree (see tree_name discussion above).
inline void WriteRunInfo(TFile* file, const std::string& tree_name,
                          const std::vector<RunInfoEntry>& entries) {
  file->cd();
  file->Delete((tree_name + ";*").c_str());
  TTree tree(tree_name.c_str(),
             "Simulation run conditions (key, value string pairs) -- see GitHub issue #6 item 1, "
             "#11 item 1");
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
