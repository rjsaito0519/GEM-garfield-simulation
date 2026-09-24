/**
 * Trace pure electrostatic field lines from a grid of seed points down
 * through a GEM hole, with no Monte Carlo transport/diffusion at all --
 * a diagnostic to separate "the field itself doesn't geometrically
 * connect the hole to the downstream gas" from "the field is fine but
 * microscopic diffusion/transport loses electrons anyway" (see
 * docs/debugging_notes.md).
 *
 * Integrates each line by simple small fixed-step Euler stepping along
 * -E/|E| (the direction an electron actually drifts: opposite to E, not
 * along it), starting just above the GEM foil and stepping downstream
 * until the point leaves the drift medium (ComponentElmer status != 0,
 * i.e. hit solid material or exited the mesh) or a maximum number of
 * steps is reached. Classifies each line's endpoint by z:
 *   - z > topCuZ - epsilon         : never really entered (shouldn't happen)
 *   - dielectricBottomZ..topCuZ    : stuck inside the foil (dielectric/Cu)
 *   - z < dielectricBottomZ - margin: reached the downstream gas
 *
 * Usage: trace_field_lines <mesh/result dir> <topCuZCm> <dielectricBottomZCm>
 *          <holeOuterRadiusCm> <nSeedsPerRing> <nRings> [stepCm] [maxSteps]
 *   topCuZCm/dielectricBottomZCm: z bounds of the GEM foil [cm] (e.g. the
 *     GEM_100UM single-foil test's +-59um/-59um, in cm) -- seeds start
 *     just below topCuZCm and lines are classified against these bounds.
 *   holeOuterRadiusCm: seeds are placed on nRings evenly-spaced radii from
 *     0 to this radius, nSeedsPerRing points per ring (except r=0, one
 *     point only).
 *   stepCm: Euler step size [cm], default 1e-6 (0.01 um) -- much smaller
 *     than the hole (tens of um), matching the real per-collision step
 *     scale found in the SetCollisionSteps=1 diagnostic.
 *   maxSteps: default 200000 (with the default step size, covers a few mm).
 */

#include <cmath>
#include <filesystem>
#include <iostream>
#include <map>
#include <string>

#include "Garfield/ComponentElmer.hh"
#include "Garfield/MediumMagboltz.hh"

#include "model_info.hh"

using namespace Garfield;

namespace {

enum class Outcome { Downstream, StuckInFoil, ExitedMeshOrOther, MaxStepsReached };

const char* ToString(Outcome o) {
  switch (o) {
    case Outcome::Downstream: return "downstream";
    case Outcome::StuckInFoil: return "stuck_in_foil";
    case Outcome::ExitedMeshOrOther: return "exited_mesh_or_other";
    case Outcome::MaxStepsReached: return "max_steps_reached";
  }
  return "?";
}

}  // namespace

int main(int argc, char* argv[]) {
  if (argc < 6) {
    std::cout << "Usage: trace_field_lines <mesh/result dir> <topCuZCm> "
                 "<dielectricBottomZCm> <holeOuterRadiusCm> <nSeedsPerRing> "
                 "<nRings> [stepCm] [maxSteps]\n";
    return 1;
  }
  const std::string meshDir = std::string(argv[1]) + "/";
  const std::string baseName = std::filesystem::path(argv[1]).filename().string();
  const gem::ModelGeometryInfo geo = gem::LoadModelGeometryInfo(argv[1], baseName);
  const double topCuZ = std::stod(argv[2]);
  const double dielectricBottomZ = std::stod(argv[3]);
  const double holeOuterRadiusCm = std::stod(argv[4]);
  const int nSeedsPerRing = std::atoi(argv[5]);
  const int nRings = argc > 6 ? std::atoi(argv[6]) : 4;
  const double stepCm = argc > 7 ? std::stod(argv[7]) : 1.0e-6;
  const int maxSteps = argc > 8 ? std::atoi(argv[8]) : 200000;

  MediumMagboltz gas;
  gas.SetComposition("ar", 90., "ch4", 10.);
  gas.SetTemperature(293.15);
  gas.SetPressure(760.);

  // geo.gas_material_index is read from the actual "Gas" physical group ID
  // the geometry builder wrote (model_info.hh), not hardcoded -- see that
  // struct's own comment and docs/pipeline_gotchas.md #8 (ComponentElmer
  // subtracts 1 from mesh.names' 1-based body ID) and GitHub issue #6 item 3.
  ComponentElmer elm(meshDir + "mesh.header", meshDir + "mesh.elements",
                      meshDir + "mesh.nodes", meshDir + "dielectrics.dat",
                      meshDir + baseName + ".result", "cm");
  elm.SetMedium(geo.gas_material_index, &gas);
  elm.DriftMedium(geo.gas_material_index);

  // Start just below the top Cu face, inside the drift gas above the hole.
  const double zStart = topCuZ - 1.0e-6;
  const double foilMargin = 5.0e-4;  // 5 um: how far past dielectricBottomZ counts as "genuinely downstream"

  std::map<std::string, int> outcomeCounts;
  int nSeeds = 0;
  for (int ring = 0; ring < nRings; ++ring) {
    const double r = nRings > 1 ? holeOuterRadiusCm * ring / (nRings - 1) : 0.0;
    const int nThisRing = (r == 0.0) ? 1 : nSeedsPerRing;
    for (int j = 0; j < nThisRing; ++j) {
      const double phi = 2.0 * M_PI * j / nThisRing;
      double x = r * std::cos(phi);
      double y = r * std::sin(phi);
      double z = zStart;
      ++nSeeds;

      Outcome outcome = Outcome::MaxStepsReached;
      for (int step = 0; step < maxSteps; ++step) {
        double ex, ey, ez, v;
        Medium* medium = nullptr;
        int status;
        elm.ElectricField(x, y, z, ex, ey, ez, v, medium, status);
        if (status != 0) {
          if (z < dielectricBottomZ - foilMargin) {
            outcome = Outcome::Downstream;
          } else if (z <= topCuZ + 1.0e-6 && z >= dielectricBottomZ - foilMargin) {
            outcome = Outcome::StuckInFoil;
          } else {
            outcome = Outcome::ExitedMeshOrOther;
          }
          break;
        }
        const double emag = std::sqrt(ex * ex + ey * ey + ez * ez);
        if (emag < 1.0e-9) {
          outcome = Outcome::ExitedMeshOrOther;  // field vanished -- shouldn't happen in a real drift region
          break;
        }
        // Electrons drift opposite to E.
        x += -stepCm * ex / emag;
        y += -stepCm * ey / emag;
        z += -stepCm * ez / emag;
      }
      outcomeCounts[ToString(outcome)]++;
    }
  }

  std::cout << "Traced " << nSeeds << " field lines from z=" << zStart
            << " cm, r in [0, " << holeOuterRadiusCm << "] cm:\n";
  for (const auto& [name, count] : outcomeCounts) {
    std::cout << "  " << name << ": " << count << " (" << (100.0 * count / nSeeds) << "%)\n";
  }
  return 0;
}
