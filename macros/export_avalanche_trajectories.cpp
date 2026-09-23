/**
 * Export full per-point avalanche electron trajectories (not just start/end
 * points, unlike gem_avalanche.cpp's endpoint tree) to a ROOT TTree, for the
 * Python/PyVista visualization layer to overlay against geometry and field
 * maps (see GitHub issue #3).
 *
 * Needs no ROOT graphics at all: AvalancheMicroscopic::GetElectrons()[i].path
 * is populated unconditionally (confirmed in the installed Garfield++
 * source, AvalancheMicroscopic.cc: the path point is recorded every step
 * regardless of whether EnablePlotting()/ViewDrift is in use), so this
 * macro never constructs a TApplication/TCanvas -- also sidesteps the
 * pre-existing double-free/segfault-at-exit quirk noted in
 * docs/debugging_notes.md for the macros that do use ROOT graphics.
 *
 * Runs only a handful of events on purpose, like
 * view_gem_avalanche_cross_section.cpp: exporting the full path of every
 * electron in a 100-event run would produce a huge file for no
 * visualization benefit (a plot of that many overlaid avalanches would
 * already be an unreadable blob).
 *
 * Usage: export_avalanche_trajectories <mesh/result dir> <.gas file>
 *          <n events> <zSensorMin> <zSensorMax> <zInjection> <xHalfCm>
 *          <yHalfCm> [e0_eV] [injectionRadiusCm] [output dir]
 *   Same argument convention as gem_avalanche.cpp -- the numbers already
 *   used for a given model's gem_avalanche run can be reused here directly.
 *
 * Output: "<baseName>_avalanche.root", tree "Trajectories", branches
 *   event,track,x,y,z,t,energy
 * (one entry per recorded path point; "track" is a per-event index into
 * AvalancheMicroscopic::GetElectrons(), not a globally unique ID -- pair
 * (event,track) to identify one electron's full path). Opened in UPDATE
 * mode and any existing "Trajectories" cycles purged first, so re-running
 * this macro replaces its own tree without disturbing a sibling
 * "Endpoints" tree that gem_avalanche.cpp may have written to the same
 * file.
 */

#include <cmath>
#include <filesystem>
#include <iostream>
#include <string>

#include <TFile.h>
#include <TTree.h>

#include "Garfield/AvalancheMicroscopic.hh"
#include "Garfield/ComponentElmer.hh"
#include "Garfield/MediumMagboltz.hh"
#include "Garfield/Random.hh"
#include "Garfield/Sensor.hh"

using namespace Garfield;

int main(int argc, char* argv[]) {
  if (argc < 9) {
    std::cout << "Usage: export_avalanche_trajectories <mesh/result dir> <.gas file> "
                 "<n events> <zSensorMin> <zSensorMax> <zInjection> <xHalfCm> <yHalfCm> "
                 "[e0_eV] [injectionRadiusCm] [output dir]\n";
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

  MediumMagboltz gas;
  if (!gas.LoadGasFile(gasFile)) {
    std::cerr << "Failed to load gas file " << gasFile << "\n";
    return 1;
  }

  // Material index 0 = Gas -- see gem_avalanche.cpp's comment on the same
  // call for why.
  ComponentElmer elm(meshDir + "mesh.header", meshDir + "mesh.elements",
                      meshDir + "mesh.nodes", meshDir + "dielectrics.dat",
                      meshDir + baseName + ".result", "cm");
  elm.SetMedium(0, &gas);
  elm.DriftMedium(0);

  Sensor sensor;
  sensor.AddComponent(&elm);
  sensor.SetArea(-xHalfCm, -yHalfCm, zSensorMin, xHalfCm, yHalfCm, zSensorMax);

  AvalancheMicroscopic aval;
  aval.SetSensor(&sensor);
  aval.SetCollisionSteps(100);
  // Must be explicitly enabled (default off): without it, path only ever
  // ends up with the seed point plus one final point regardless of how
  // long the drift line actually was (confirmed in the installed
  // Garfield++ source, AvalancheMicroscopic.cc -- the interior-point
  // recording is gated on m_storeDriftLines, separate from m_viewer/
  // EnablePlotting). SetCollisionSteps(100) above then controls how often
  // (every 100 collisions) an interior point gets recorded.
  aval.EnableDriftLines();
  // Same safety cap as gem_avalanche.cpp -- see its comment on the same
  // call for why.
  aval.EnableAvalancheSizeLimit(2000);

  const std::string rootPath = outDir + baseName + "_avalanche.root";
  TFile* rootFile = TFile::Open(rootPath.c_str(), "UPDATE");
  rootFile->Delete("Trajectories;*");
  TTree trajectoriesTree("Trajectories", "Per-point avalanche electron trajectories");
  int b_event;
  std::size_t b_track;
  double b_x, b_y, b_z, b_t, b_energy;
  trajectoriesTree.Branch("event", &b_event);
  trajectoriesTree.Branch("track", &b_track);
  trajectoriesTree.Branch("x", &b_x);
  trajectoriesTree.Branch("y", &b_y);
  trajectoriesTree.Branch("z", &b_z);
  trajectoriesTree.Branch("t", &b_t);
  trajectoriesTree.Branch("energy", &b_energy);

  const double t0 = 0.;
  for (int i = 0; i < nEvents; ++i) {
    // Same injection convention as gem_avalanche.cpp: small random offset
    // around the hole axis, direction (0,0,-1) (downstream).
    const double r = injectionRadiusCm * RndmUniform();
    const double phi = 2. * M_PI * RndmUniform();
    const double x0 = r * std::cos(phi);
    const double y0 = r * std::sin(phi);
    aval.AvalancheElectron(x0, y0, zInjection, t0, e0, 0., 0., -1.);

    const auto& electrons = aval.GetElectrons();
    std::size_t nPoints = 0;
    for (std::size_t track = 0; track < electrons.size(); ++track) {
      for (const auto& p : electrons[track].path) {
        b_event = i;
        b_track = track;
        b_x = p.x; b_y = p.y; b_z = p.z; b_t = p.t; b_energy = p.energy;
        trajectoriesTree.Fill();
        ++nPoints;
      }
    }
    std::cout << "Event " << i << "/" << nEvents << ": " << electrons.size()
               << " electron tracks, " << nPoints << " trajectory points\n";
  }
  trajectoriesTree.Write();
  rootFile->Close();
  std::cout << "Wrote " << rootPath << " (tree \"Trajectories\")\n";
  return 0;
}
