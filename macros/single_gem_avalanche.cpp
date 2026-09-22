/**
 * Electron avalanche gain for the standalone single-GEM (GEM1 conditions)
 * field map. Injects electrons just above the GEM hole, in the drift gas,
 * and reports the resulting gain (number of secondary electrons) -- the
 * first real physics check that the corrected field map (see
 * gmsh_elmer_garfield_pipeline_gotchas notes: the hole-gas volume and the
 * SetMedium/DriftMedium off-by-one) actually produces multiplication, not
 * just a plausible-looking potential plot.
 *
 * Usage: single_gem_avalanche <mesh/result dir> <.gas file> <n events> [output dir]
 */

#include <cmath>
#include <iostream>
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

namespace {

// Same values as geometry/gem_params.GEM_50UM / single_gem_field_model.py --
// hardcoded here rather than read from a shared source of truth (same
// caveat as the other macros).
constexpr double kHalfXCm = 0.0068;    // slightly inside pitch/2 = 0.007
constexpr double kHalfYCm = 0.0117;    // slightly inside pitch*sqrt(3)/2 = 0.0121
constexpr double kZTransferPlaneCm = -0.2029;
constexpr double kZDriftPlaneCm = 0.4229;
constexpr double kGemTopCu = 0.0029;   // top of the top copper layer

}  // namespace

int main(int argc, char* argv[]) {
  if (argc < 4) {
    std::cout << "Usage: single_gem_avalanche <mesh/result dir> <.gas file> "
                 "<n events> [output dir]\n";
    return 1;
  }
  const std::string meshDir = std::string(argv[1]) + "/";
  const std::string gasFile = argv[2];
  const int nEvents = std::atoi(argv[3]);
  const std::string outDir = argc > 4 ? std::string(argv[4]) + "/" : "./";

  TApplication app("app", &argc, argv);
  gROOT->SetBatch(kTRUE);

  MediumMagboltz gas;
  if (!gas.LoadGasFile(gasFile)) {
    std::cerr << "Failed to load gas file " << gasFile << "\n";
    return 1;
  }

  // Material ID 0 = "Gas" (body ID 1 in mesh.names, minus 1 -- see
  // gmsh_elmer_garfield_pipeline_gotchas memory note / the comment in
  // view_single_gem_field.cpp for why it is 0 and not 1).
  ComponentElmer elm(meshDir + "mesh.header", meshDir + "mesh.elements",
                      meshDir + "mesh.nodes", meshDir + "dielectrics.dat",
                      meshDir + "single_gem_field.result", "cm");
  elm.SetMedium(0, &gas);
  elm.DriftMedium(0);

  Sensor sensor;
  sensor.AddComponent(&elm);
  sensor.SetArea(-kHalfXCm, -kHalfYCm, kZTransferPlaneCm,
                 kHalfXCm, kHalfYCm, kZDriftPlaneCm);

  ViewDrift driftView;
  driftView.SetArea(-kHalfXCm, -kHalfYCm, -0.01, kHalfXCm, kHalfYCm, 0.02);

  AvalancheMicroscopic aval;
  aval.SetSensor(&sensor);
  aval.EnablePlotting(&driftView);
  aval.SetCollisionSteps(100);

  // Start just above the GEM's top copper surface, well inside the drift
  // gas: close enough to the hole that the simulation does not spend most
  // of its time on the (physically uneventful, uniform-field) drift
  // through the rest of the 4.2 mm drift gap.
  const double z0 = kGemTopCu + 0.003;  // 30 um above the copper
  const double e0 = 0.1;                // initial electron energy [eV]
  const double t0 = 0.;

  std::vector<int> gains;
  gains.reserve(nEvents);
  for (int i = 0; i < nEvents; ++i) {
    // Small random offset around the hole axis, matching the
    // now-deleted prototype's convention (test/gem_simulation/gem_avalanche.C).
    const double r = 0.0005 * RndmUniform();
    const double phi = 2. * M_PI * RndmUniform();
    const double x0 = r * std::cos(phi);
    const double y0 = r * std::sin(phi);

    aval.AvalancheElectron(x0, y0, z0, t0, e0, 0., 0., 0.);
    int ne = 0, ni = 0;
    aval.GetAvalancheSize(ne, ni);
    gains.push_back(ne);
    std::cout << "Event " << i << "/" << nEvents << ": gain = " << ne << "\n";
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
  const std::string plotPath = outDir + "single_gem_avalanche_drift_lines.png";
  canvas.SaveAs(plotPath.c_str());
  std::cout << "Wrote " << plotPath << "\n";

  return 0;
}
