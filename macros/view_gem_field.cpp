/**
 * Load an Elmer field map (single-GEM or the full 3-GEM stack -- this macro
 * is geometry-agnostic) and plot the potential, as an end-to-end check that
 * Garfield++ can actually read what the Gmsh + Elmer pipeline produced.
 *
 * The mesh/result base name (e.g. "single_gem_field" or "triple_gem_field")
 * is taken from the last path component of the mesh directory, since that
 * is how geometry/build_*_field_mesh.py always names it -- no separate
 * argument needed for it.
 *
 * Usage: view_gem_field <mesh/result directory> [zMinCm] [zMaxCm]
 *   zMinCm/zMaxCm bound the "full range" plot; default to the single-GEM
 *   stack's extent. Pass the 3-GEM stack's actual range for that model
 *   (see build_triple_gem_field_mesh.py's printed electrode potentials /
 *   the mesh cross-section plot for the numbers).
 */

#include <filesystem>
#include <iostream>
#include <string>

#include <TApplication.h>
#include <TCanvas.h>
#include <TROOT.h>

#include "Garfield/ComponentElmer.hh"
#include "Garfield/MediumMagboltz.hh"
#include "Garfield/ViewField.hh"

using namespace Garfield;

int main(int argc, char* argv[]) {
  if (argc < 2) {
    std::cout << "Usage: view_gem_field <mesh/result directory> [zMinCm] [zMaxCm]\n";
    return 1;
  }
  const std::string meshDir = std::string(argv[1]) + "/";
  const std::string baseName = std::filesystem::path(argv[1]).filename().string();
  const double zMin = argc > 2 ? std::stod(argv[2]) : -0.25;
  const double zMax = argc > 3 ? std::stod(argv[3]) : 0.45;

  // Must come before constructing TApplication -- see gem_avalanche.cpp's
  // comment on the same lines for why (avoids a possible hang trying to
  // reach an unreachable $DISPLAY).
  gROOT->SetBatch(kTRUE);  // headless: only ever save canvases to files, never show them
  TApplication app("app", &argc, argv);

  // The gas composition only needs to be set (not Initialise()'d with a full
  // Magboltz table) to view the field map: transport tables are only needed
  // once we start drifting/avalanching electrons, not for plotting E or V.
  MediumMagboltz gas;
  gas.SetComposition("ar", 90., "ch4", 10.);
  gas.SetTemperature(293.15);
  gas.SetPressure(760.);

  // NOTE: the 4th argument is the *materials* file (dielectrics.dat, written
  // by elmer/write_sif.py), not mesh.boundary -- see ComponentElmer.hh:
  // ComponentElmer(header, elist, nlist, mplist, volt, unit).
  ComponentElmer elm(meshDir + "mesh.header", meshDir + "mesh.elements",
                      meshDir + "mesh.nodes", meshDir + "dielectrics.dat",
                      meshDir + baseName + ".result", "cm");
  // Body ID 1 = "Gas" in mesh.names, but ComponentElmer subtracts 1 from
  // every body ID it reads from mesh.elements before using it as an array
  // index (confirmed in ComponentElmer.cc: "int imat = ReadInteger(...) -
  // 1;"), so the matching SetMedium/DriftMedium index here is 0, not 1 --
  // see the gmsh_elmer_garfield_pipeline_gotchas memory note.
  elm.SetMedium(0, &gas);
  elm.DriftMedium(0);

  ViewField vf;
  vf.SetComponent(&elm);
  vf.SetNumberOfContours(50);
  vf.SetPlaneXZ();

  // Pitch of the GEM hole pattern, hardcoded here to match
  // gem_params.GEM_50UM/GEM_100UM (both use pitch = 140 um = 0.014 cm). If
  // that ever changes, this must change with it -- there is no automatic
  // link between the two right now.
  const double pitchCm = 0.014;

  TCanvas fullViewCanvas("full_view", "Potential, full stack", 700, 900);
  vf.SetCanvas(&fullViewCanvas);
  vf.SetArea(-2.0 * pitchCm, zMin, 2.0 * pitchCm, zMax);
  vf.PlotContour();
  const std::string fullPath = baseName + "_potential_full.png";
  fullViewCanvas.SaveAs(fullPath.c_str());

  TCanvas holeZoomCanvas("hole_zoom", "Potential, zoomed on a GEM hole", 700, 700);
  vf.SetCanvas(&holeZoomCanvas);
  vf.SetArea(-1.5 * pitchCm, -0.01, 1.5 * pitchCm, 0.01);
  vf.PlotContour();
  const std::string zoomPath = baseName + "_potential_hole_zoom.png";
  holeZoomCanvas.SaveAs(zoomPath.c_str());

  std::cout << "Wrote " << fullPath << " and " << zoomPath << "\n";
  return 0;
}
