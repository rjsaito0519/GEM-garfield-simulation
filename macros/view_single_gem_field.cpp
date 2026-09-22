/**
 * Milestone 2 (Garfield++ step): load the Elmer field map for the standalone
 * single-GEM test and plot the potential, as an end-to-end check that
 * Garfield++ can actually read what our Gmsh + Elmer pipeline produced.
 *
 * Usage: view_single_gem_field <path to geometry/output/single_gem_field/>
 */

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
  if (argc != 2) {
    std::cout << "Usage: view_single_gem_field <mesh/result directory>\n";
    return 1;
  }
  const std::string meshDir = std::string(argv[1]) + "/";

  TApplication app("app", &argc, argv);
  gROOT->SetBatch(kTRUE);  // headless: only ever save canvases to files, never show them

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
                      meshDir + "single_gem_field.result", "cm");
  // Body ID 1 = "Gas" in mesh.names (see geometry/single_gem_field_model.py),
  // but ComponentElmer internally subtracts 1 from every body ID it reads
  // from mesh.elements before using it as an array index (confirmed in
  // ComponentElmer.cc: "int imat = ReadInteger(token, ...) - 1;"), so the
  // matching SetMedium/DriftMedium index here is 0, not 1. Passing 1 here
  // silently attaches the gas medium to material index 1, which is actually
  // the *Dielectric* body -- see elmer/write_sif.py's write_dielectrics_dat
  // docstring for the same off-by-one, and the pipeline gotchas memory note.
  elm.SetMedium(0, &gas);
  // SetMedium() alone does *not* mark a material as a drift medium (it only
  // records which Medium* to use); without this, ElectricField()'s status
  // output is -5 ("inside mesh but not in an active medium") everywhere in
  // the gas, even though the field values themselves are already correct.
  elm.DriftMedium(0);

  ViewField vf;
  vf.SetComponent(&elm);
  vf.SetNumberOfContours(50);
  vf.SetPlaneXZ();

  // Pitch of the GEM hole pattern, hardcoded here to match gem_params.GEM_50UM
  // (pitch = 140 um = 0.014 cm). If that parameter ever changes, this must
  // change with it -- there is no automatic link between the two right now.
  const double pitchCm = 0.014;

  TCanvas fullViewCanvas("full_view", "Potential, full drift-GEM-transfer range", 700, 900);
  vf.SetCanvas(&fullViewCanvas);
  vf.SetArea(-2.0 * pitchCm, -0.25, 2.0 * pitchCm, 0.45);
  vf.PlotContour();
  fullViewCanvas.SaveAs("single_gem_field_potential_full.png");

  TCanvas holeZoomCanvas("hole_zoom", "Potential, zoomed on the GEM hole", 700, 700);
  vf.SetCanvas(&holeZoomCanvas);
  vf.SetArea(-1.5 * pitchCm, -0.01, 1.5 * pitchCm, 0.01);
  vf.PlotContour();
  holeZoomCanvas.SaveAs("single_gem_field_potential_hole_zoom.png");

  std::cout << "Wrote single_gem_field_potential_full.png and "
               "single_gem_field_potential_hole_zoom.png\n";
  return 0;
}
