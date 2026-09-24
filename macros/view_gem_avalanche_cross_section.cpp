/**
 * Cross-section (x-z plane) view of a few electron avalanches overlaid on
 * the GEM foil outline(s), using ViewFEMesh + ViewDrift -- much easier to
 * read than a tangled 3D drift-line plot, since everything is projected
 * onto one plane through the hole axis. Geometry-agnostic: works for the
 * single-GEM model or the full 3-GEM stack.
 *
 * Runs only a handful of events on purpose: overlaying 100 avalanches on
 * one 2D plot would just be a solid blob.
 *
 * Usage: view_gem_avalanche_cross_section <mesh/result dir> <.gas file>
 *          <n events> <zSensorMin> <zSensorMax> <zInjection>
 *          <zPlotMin> <zPlotMax> <xHalfCm> <yHalfCm> [output dir]
 *   zSensorMin/Max: full sensor bounds (same meaning as in gem_avalanche.cpp).
 *   zPlotMin/Max: the (usually much narrower) z range actually drawn, e.g.
 *     zoomed on just the GEM foil the electrons were injected above.
 *   xHalfCm/yHalfCm: see gem_avalanche.cpp -- the built model's x/y
 *     half-extent; also used directly as the plot's x range.
 */

#include <cmath>
#include <filesystem>
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

#include "model_info.hh"

using namespace Garfield;

int main(int argc, char* argv[]) {
  if (argc < 11) {
    std::cout << "Usage: view_gem_avalanche_cross_section <mesh/result dir> "
                 "<.gas file> <n events> <zSensorMin> <zSensorMax> "
                 "<zInjection> <zPlotMin> <zPlotMax> <xHalfCm> <yHalfCm> "
                 "[output dir]\n";
    return 1;
  }
  const std::string meshDir = std::string(argv[1]) + "/";
  const std::string baseName = std::filesystem::path(argv[1]).filename().string();
  const gem::ModelGeometryInfo geo = gem::LoadModelGeometryInfo(argv[1], baseName);
  const std::string gasFile = argv[2];
  const int nEvents = std::atoi(argv[3]);
  const double zSensorMin = std::stod(argv[4]);
  const double zSensorMax = std::stod(argv[5]);
  const double zInjection = std::stod(argv[6]);
  const double zPlotMin = std::stod(argv[7]);
  const double zPlotMax = std::stod(argv[8]);
  const double xHalfCm = std::stod(argv[9]);
  const double yHalfCm = std::stod(argv[10]);
  const std::string outDir = argc > 11 ? std::string(argv[11]) + "/" : "./";

  // Must come before constructing TApplication -- see gem_avalanche.cpp's
  // comment on the same lines for why (avoids a possible hang trying to
  // reach an unreachable $DISPLAY).
  gROOT->SetBatch(kTRUE);
  TApplication app("app", &argc, argv);

  MediumMagboltz gas;
  if (!gas.LoadGasFile(gasFile)) {
    std::cerr << "Failed to load gas file " << gasFile << "\n";
    return 1;
  }

  // geo.gas_material_index is read from the actual "Gas" physical group ID
  // the geometry builder wrote (model_info.hh), not hardcoded -- see that
  // struct's own comment and docs/pipeline_gotchas.md #8 (ComponentElmer
  // subtracts 1 from mesh.names' 1-based body ID) and GitHub issue #6 item 3.
  ComponentElmer elm(meshDir + "mesh.header", meshDir + "mesh.elements",
                      meshDir + "mesh.nodes", meshDir + "dielectrics.dat",
                      meshDir + baseName + ".result", "cm");
  elm.SetMedium(geo.gas_material_index, &gas);
  elm.DriftMedium(geo.gas_material_index);

  Sensor sensor;
  sensor.AddComponent(&elm);
  sensor.SetArea(-xHalfCm, -yHalfCm, zSensorMin, xHalfCm, yHalfCm, zSensorMax);

  ViewDrift driftView;
  driftView.SetArea(-xHalfCm, -yHalfCm, zSensorMin, xHalfCm, yHalfCm, zSensorMax);

  AvalancheMicroscopic aval;
  aval.SetSensor(&sensor);
  aval.EnablePlotting(&driftView);
  aval.SetCollisionSteps(100);

  const double e0 = 0.1;
  for (int i = 0; i < nEvents; ++i) {
    const double r = 0.0005 * RndmUniform();
    const double phi = 2. * M_PI * RndmUniform();
    const double x0 = r * std::cos(phi);
    const double y0 = r * std::sin(phi);
    aval.AvalancheElectron(x0, y0, zInjection, 0., e0, 0., 0., -1.);
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
  meshView.SetArea(-xHalfCm, zPlotMin, xHalfCm, zPlotMax);
  meshView.Plot();

  const std::string plotPath = outDir + baseName + "_avalanche_cross_section.png";
  canvas.SaveAs(plotPath.c_str());
  std::cout << "Wrote " << plotPath << "\n";
  return 0;
}
