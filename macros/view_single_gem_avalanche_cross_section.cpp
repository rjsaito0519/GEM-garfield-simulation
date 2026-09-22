/**
 * Cross-section (x-z plane) view of a few electron avalanches overlaid on
 * the GEM foil outline, using ViewFEMesh + ViewDrift -- much easier to read
 * than the tangled 3D drift-line plot from single_gem_avalanche.cpp, since
 * everything is projected onto one plane through the hole axis.
 *
 * Runs only a handful of events on purpose: overlaying 100 avalanches on
 * one 2D plot would just be a solid blob.
 *
 * Usage: view_single_gem_avalanche_cross_section <mesh/result dir> <.gas file> <n events> [output dir]
 */

#include <cmath>
#include <iostream>
#include <string>

#include <TApplication.h>
#include <TCanvas.h>
#include <TROOT.h>

#include "Garfield/AvalancheMicroscopic.hh"
#include "Garfield/ComponentElmer.hh"
#include "Garfield/MediumMagboltz.hh"
#include "Garfield/Random.hh"
#include "Garfield/Sensor.hh"
#include "Garfield/ViewDrift.hh"
#include "Garfield/ViewFEMesh.hh"

using namespace Garfield;

namespace {
constexpr double kHalfXCm = 0.0068;
constexpr double kHalfYCm = 0.0117;
constexpr double kZTransferPlaneCm = -0.2029;
constexpr double kZDriftPlaneCm = 0.4229;
constexpr double kGemTopCu = 0.0029;
}  // namespace

int main(int argc, char* argv[]) {
  if (argc < 4) {
    std::cout << "Usage: view_single_gem_avalanche_cross_section "
                 "<mesh/result dir> <.gas file> <n events> [output dir]\n";
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

  // Material index 0 = Gas -- see single_gem_avalanche.cpp's comment on the
  // same call for why it is 0 and not the mesh.names body ID (1).
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
  driftView.SetArea(-kHalfXCm, -kHalfYCm, -0.02, kHalfXCm, kHalfYCm, 0.01);

  AvalancheMicroscopic aval;
  aval.SetSensor(&sensor);
  aval.EnablePlotting(&driftView);
  aval.SetCollisionSteps(100);

  const double z0 = kGemTopCu + 0.003;
  const double e0 = 0.1;
  for (int i = 0; i < nEvents; ++i) {
    const double r = 0.0005 * RndmUniform();
    const double phi = 2. * M_PI * RndmUniform();
    const double x0 = r * std::cos(phi);
    const double y0 = r * std::sin(phi);
    aval.AvalancheElectron(x0, y0, z0, 0., e0, 0., 0., 0.);
    int ne = 0, ni = 0;
    aval.GetAvalancheSize(ne, ni);
    std::cout << "Event " << i << "/" << nEvents << ": gain = " << ne << "\n";
  }

  ViewFEMesh meshView;
  meshView.SetComponent(&elm);
  meshView.SetPlaneXZ();
  meshView.SetFillMesh(true);
  // ROOT color indices; material 0 = Gas is left uncolored (default) so the
  // drift lines stand out against a plain background.
  meshView.SetColor(1, kYellow + 1);  // Dielectric (polyimide)
  meshView.SetColor(2, kOrange + 7);  // Copper
  meshView.SetViewDrift(&driftView);
  meshView.EnableAxes();

  TCanvas canvas("c", "Avalanche cross section", 900, 900);
  meshView.SetCanvas(&canvas);
  meshView.SetArea(-kHalfXCm, -0.02, kHalfXCm, 0.01);
  meshView.Plot();

  const std::string plotPath = outDir + "single_gem_avalanche_cross_section.png";
  canvas.SaveAs(plotPath.c_str());
  std::cout << "Wrote " << plotPath << "\n";
  return 0;
}
