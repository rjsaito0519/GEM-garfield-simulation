/**
 * Electron avalanche gain for a GEM field map -- single-GEM or the full
 * 3-GEM stack (this macro is geometry-agnostic; only the sensor bounds and
 * injection point need to match whichever model is being run). Injects
 * electrons near the hole axis, above the topmost GEM foil, in the drift
 * gas, and reports the resulting total gain (number of secondary
 * electrons) after passing through the whole field map. Also writes a
 * per-electron-endpoint CSV ("<baseName>_avalanche_endpoints.csv" in the
 * output dir: event,xs,ys,zs,ts,es,xe,ye,ze,te,ee,status) so where each
 * electron's drift line actually ended can be examined directly, not just
 * lumped into the printed status tally.
 *
 * The mesh/result base name is taken from the last path component of the
 * mesh directory (e.g. "single_gem_field" or "triple_gem_field"), matching
 * how geometry/build_*_field_mesh.py always names it.
 *
 * Usage: gem_avalanche <mesh/result dir> <.gas file> <n events>
 *                       <zSensorMin> <zSensorMax> <zInjection>
 *                       <xHalfCm> <yHalfCm> [e0_eV] [injectionRadiusCm] [output dir]
 *   zSensorMin/Max: the sensor's z bounds [cm], from the induction/transfer
 *     plane at the bottom to the drift plane at the top (see the model's
 *     printed electrode potentials, or its mesh cross-section plot, for
 *     the actual numbers).
 *   zInjection: where to start each electron [cm], just above the topmost
 *     GEM foil's top copper surface, inside the drift gas.
 *   xHalfCm/yHalfCm: the built model's x/y half-extent [cm] -- pitch/2 and
 *     pitch*sqrt(3)/2 for a single unit cell, or n_cells_x/y times that for
 *     a tiled model (see geometry/triple_gem_field_model.py).
 *   e0_eV: initial electron energy [eV], default 0.1 (roughly thermal).
 *   injectionRadiusCm: each electron's (x, y) is offset from the hole axis
 *     by a random radius in [0, injectionRadiusCm], default 0.0005 cm (5 um).
 */

#include <cmath>
#include <filesystem>
#include <iostream>
#include <map>
#include <string>
#include <vector>

#include <TApplication.h>
#include <TCanvas.h>
#include <TROOT.h>

#include "Garfield/AvalancheMicroscopic.hh"
#include "Garfield/ComponentElmer.hh"
#include "Garfield/MediumMagboltz.hh"
#include "Garfield/Random.hh"
#include "Garfield/Sensor.hh"
#include "Garfield/ViewDrift.hh"

using namespace Garfield;

int main(int argc, char* argv[]) {
  if (argc < 9) {
    std::cout << "Usage: gem_avalanche <mesh/result dir> <.gas file> <n events> "
                 "<zSensorMin> <zSensorMax> <zInjection> <xHalfCm> <yHalfCm> "
                 "[output dir]\n";
    return 1;
  }
  const std::string meshDir = std::string(argv[1]) + "/";
  const std::string baseName = std::filesystem::path(argv[1]).filename().string();
  const std::string gasFile = argv[2];
  const int nEvents = std::atoi(argv[3]);
  const double zSensorMin = std::stod(argv[4]);
  const double zSensorMax = std::stod(argv[5]);
  const double zInjection = std::stod(argv[6]);
  const double xHalfCm = std::stod(argv[7]);
  const double yHalfCm = std::stod(argv[8]);
  const double e0 = argc > 9 ? std::stod(argv[9]) : 0.1;
  const double injectionRadiusCm = argc > 10 ? std::stod(argv[10]) : 0.0005;
  const std::string outDir = argc > 11 ? std::string(argv[11]) + "/" : "./";

  // Must come *before* constructing TApplication: otherwise TApplication's
  // own construction tries to connect to the X11 display named by $DISPLAY,
  // which on this cluster is set but not actually reachable (SSH X11
  // forwarding isn't really working here) -- that connection attempt can
  // hang for a very long time (seen directly: one run sat at ~0% CPU
  // producing no output at all). Setting batch mode first heads it off.
  gROOT->SetBatch(kTRUE);
  TApplication app("app", &argc, argv);

  MediumMagboltz gas;
  if (!gas.LoadGasFile(gasFile)) {
    std::cerr << "Failed to load gas file " << gasFile << "\n";
    return 1;
  }

  // Material index 0 = Gas -- see gmsh_elmer_garfield_pipeline_gotchas
  // memory note / view_gem_field.cpp's comment on the same call for why.
  ComponentElmer elm(meshDir + "mesh.header", meshDir + "mesh.elements",
                      meshDir + "mesh.nodes", meshDir + "dielectrics.dat",
                      meshDir + baseName + ".result", "cm");
  elm.SetMedium(0, &gas);
  elm.DriftMedium(0);

  Sensor sensor;
  sensor.AddComponent(&elm);
  sensor.SetArea(-xHalfCm, -yHalfCm, zSensorMin, xHalfCm, yHalfCm, zSensorMax);

  ViewDrift driftView;
  driftView.SetArea(-xHalfCm, -yHalfCm, zSensorMin, xHalfCm, yHalfCm, zSensorMax);

  AvalancheMicroscopic aval;
  aval.SetSensor(&sensor);
  aval.EnablePlotting(&driftView);
  aval.SetCollisionSteps(100);
  // Safety cap: a run with 150 events at the default settings was killed
  // after 25+ minutes and 3.5+ GB RSS with no sign of finishing -- almost
  // certainly one event's avalanche growing pathologically large (or stuck)
  // rather than genuinely needing that much computation. Bound it so a
  // single bad event cannot hang the whole run; GetAvalancheSize() still
  // reports whatever size it reached when cut off.
  aval.EnableAvalancheSizeLimit(2000);

  const double t0 = 0.;

  // Per-electron-endpoint CSV: which (x,y,z) each secondary electron's
  // drift line actually ended at, not just its status code -- needed to
  // tell "hit the hole wall partway down" apart from "hit the bottom
  // copper" apart from "made it into the transfer gap but got lost later",
  // all of which show up as the same StatusLeftDriftMedium(-5) in the
  // tally below. See docs/debugging_notes.md.
  const std::string endpointsPath = outDir + baseName + "_avalanche_endpoints.csv";
  std::ofstream endpointsCsv(endpointsPath);
  endpointsCsv << "event,xs,ys,zs,ts,es,xe,ye,ze,te,ee,status\n";

  std::vector<int> gains;
  std::map<int, int> endpointStatusCounts;
  gains.reserve(nEvents);
  for (int i = 0; i < nEvents; ++i) {
    // Small random offset around the hole axis, matching the now-deleted
    // prototype's convention (test/gem_simulation/gem_avalanche.C).
    const double r = injectionRadiusCm * RndmUniform();
    const double phi = 2. * M_PI * RndmUniform();
    const double x0 = r * std::cos(phi);
    const double y0 = r * std::sin(phi);

    // Initial direction (0, 0, -1): pointing "downstream" (toward the pad
    // plane, i.e. decreasing z), matching a real drift electron's net
    // motion. Passing (0, 0, 0) here -- as an earlier version of this macro
    // did -- makes Garfield sample a *random* initial direction instead
    // (see AvalancheElectron's doc comment), which showed up as most
    // secondary electrons hitting the hole wall almost immediately: close
    // injection with a random start, or distant injection giving diffusion
    // more time to act, were both worse than injecting close with the
    // correct drift direction.
    aval.AvalancheElectron(x0, y0, zInjection, t0, e0, 0., 0., -1.);
    int ne = 0, ni = 0;
    aval.GetAvalancheSize(ne, ni);
    gains.push_back(ne);
    std::cout << "Event " << i << "/" << nEvents << ": gain = " << ne << "\n";

    // Tally why each secondary electron's drift line ended (see
    // GarfieldConstants.hh): e.g. StatusLeftDriftMedium (-5, hit solid
    // copper/dielectric) vs. StatusLeftDriftArea (-1, exited the sensor's
    // bounding box laterally -- likely an artifact of simulating only one
    // hex unit cell with no periodic boundary, not real GEM physics).
    const std::size_t np = aval.GetNumberOfElectronEndpoints();
    for (std::size_t j = 0; j < np; ++j) {
      double xs, ys, zs, ts, es, xe, ye, ze, te, ee;
      int status;
      aval.GetElectronEndpoint(j, xs, ys, zs, ts, es, xe, ye, ze, te, ee, status);
      endpointStatusCounts[status]++;
      endpointsCsv << i << "," << xs << "," << ys << "," << zs << "," << ts << ","
                   << es << "," << xe << "," << ye << "," << ze << "," << te << ","
                   << ee << "," << status << "\n";
    }
  }
  endpointsCsv.close();
  std::cout << "Wrote per-endpoint data to " << endpointsPath << "\n";

  std::cout << "Electron endpoint status tally (StatusLeftDriftArea=-1, "
               "StatusLeftDriftMedium=-5, StatusOutsideMesh=-6, other=see "
               "GarfieldConstants.hh):\n";
  for (const auto& [status, count] : endpointStatusCounts) {
    std::cout << "  status " << status << ": " << count << "\n";
  }

  double sum = 0., sumSq = 0.;
  for (const int g : gains) {
    sum += g;
    sumSq += double(g) * g;
  }
  const double mean = sum / gains.size();
  const double variance = sumSq / gains.size() - mean * mean;
  std::cout << "Mean gain = " << mean << " +/- " << std::sqrt(std::max(0., variance))
            << " (n = " << gains.size() << " events)\n";

  TCanvas canvas("c", "Drift lines", 800, 800);
  driftView.SetCanvas(&canvas);
  driftView.Plot();
  const std::string plotPath = outDir + baseName + "_avalanche_drift_lines.png";
  canvas.SaveAs(plotPath.c_str());
  std::cout << "Wrote " << plotPath << "\n";

  return 0;
}
