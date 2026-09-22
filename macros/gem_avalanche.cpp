/**
 * Electron avalanche gain for a GEM field map -- single-GEM or the full
 * 3-GEM stack (this macro is geometry-agnostic; only the sensor bounds and
 * injection point need to match whichever model is being run). Injects
 * electrons near the hole axis, above the topmost GEM foil, in the drift
 * gas, and reports the resulting total gain (number of secondary
 * electrons) after passing through the whole field map.
 *
 * The mesh/result base name is taken from the last path component of the
 * mesh directory (e.g. "single_gem_field" or "triple_gem_field"), matching
 * how geometry/build_*_field_mesh.py always names it.
 *
 * Usage: gem_avalanche <mesh/result dir> <.gas file> <n events>
 *                       <zSensorMin> <zSensorMax> <zInjection>
 *                       <xHalfCm> <yHalfCm> [output dir]
 *   zSensorMin/Max: the sensor's z bounds [cm], from the induction/transfer
 *     plane at the bottom to the drift plane at the top (see the model's
 *     printed electrode potentials, or its mesh cross-section plot, for
 *     the actual numbers).
 *   zInjection: where to start each electron [cm], just above the topmost
 *     GEM foil's top copper surface, inside the drift gas.
 *   xHalfCm/yHalfCm: the built model's x/y half-extent [cm] -- pitch/2 and
 *     pitch*sqrt(3)/2 for a single unit cell, or n_cells_x/y times that for
 *     a tiled model (see geometry/triple_gem_field_model.py).
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
  const std::string outDir = argc > 9 ? std::string(argv[9]) + "/" : "./";

  TApplication app("app", &argc, argv);
  gROOT->SetBatch(kTRUE);

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

  const double e0 = 0.1;  // initial electron energy [eV]
  const double t0 = 0.;

  std::vector<int> gains;
  std::map<int, int> endpointStatusCounts;
  gains.reserve(nEvents);
  for (int i = 0; i < nEvents; ++i) {
    // Small random offset around the hole axis, matching the now-deleted
    // prototype's convention (test/gem_simulation/gem_avalanche.C).
    const double r = 0.0005 * RndmUniform();
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
    }
  }

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
