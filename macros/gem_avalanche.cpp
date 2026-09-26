/**
 * Electron avalanche gain for a GEM field map -- single-GEM or the full
 * 3-GEM stack (this macro is geometry-agnostic; only the sensor bounds and
 * injection point need to match whichever model is being run). Injects
 * electrons near the hole axis, above the topmost GEM foil, in the drift
 * gas, and reports the resulting total gain (number of secondary
 * electrons) after passing through the whole field map. Also writes an
 * "Endpoints" TTree (event,xs,ys,zs,ts,es,xe,ye,ze,te,ee,status) to
 * "<baseName>_avalanche.root" in the output dir, so where each electron's
 * drift line actually ended can be examined directly, not just lumped into
 * the printed status tally. Opened in UPDATE mode and any existing
 * "Endpoints" cycles purged first, so re-running this macro replaces its
 * own tree without disturbing a sibling "Trajectories" tree that
 * export_avalanche_trajectories.cpp may have written to the same file.
 * Also writes a "RunInfoEndpoints" TTree recording the run's actual
 * conditions (gas file, geometry, RNG seed, git commit, full
 * model_info.json, ...) -- see run_info.hh (this macro's own tree name,
 * distinct from export_avalanche_trajectories.cpp's "RunInfoTrajectories",
 * so the two don't overwrite each other when run against the same output
 * file).
 *
 * The mesh/result base name is taken from the last path component of the
 * mesh directory (e.g. "single_gem_field" or "triple_gem_field"), matching
 * how geometry/build_*_field_mesh.py always names it.
 *
 * Usage: gem_avalanche <mesh/result dir> <.gas file> <n events>
 *                       <zSensorMin> <zSensorMax> <zInjection>
 *                       <xHalfCm> <yHalfCm> [e0_eV] [injectionRadiusCm]
 *                       [rootOutDir] [imgOutDir] [maxElectronEnergyEv] [seed]
 *                       [avalancheSizeLimit]
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
 *   rootOutDir/imgOutDir: where to write the .root file / the drift-lines
 *     PNG (e.g. results/root and results/img -- see docs/reference.md
 *     "出力ディレクトリ構成"). imgOutDir defaults to rootOutDir if omitted.
 *   maxElectronEnergyEv: pre-extend MediumMagboltz's collision-rate table
 *     to this energy up front, default 0 (= Magboltz's own auto-extension,
 *     which is slow when triggered many times -- see the comment where
 *     this is used).
 *   avalancheSizeLimit: EnableAvalancheSizeLimit() argument, default 2000.
 *     A capped event's still-unprocessed electrons are dropped with no
 *     endpoint recorded at all (confirmed in the installed Garfield++
 *     source, AvalancheMicroscopic::transportParticleStack: hitting the cut
 *     does `newParticles.clear(); break;`, not a graceful stop after
 *     finishing the current generation) -- so a run that hits this cap
 *     often has a downward bias on any measured transmission/collection
 *     fraction, not just a capped "gain" number. Found to be hit in the
 *     majority of events once Penning transfer was enabled, at the default
 *     2000; raise this for a run where that bias matters.
 */

#include <cmath>
#include <filesystem>
#include <iostream>
#include <map>
#include <string>
#include <vector>

#include <TApplication.h>
#include <TCanvas.h>
#include <TFile.h>
#include <TROOT.h>
#include <TTree.h>

#include "Garfield/AvalancheMicroscopic.hh"
#include "Garfield/ComponentElmer.hh"
#include "Garfield/MediumMagboltz.hh"
#include "Garfield/Random.hh"
#include "Garfield/RandomEngineRoot.hh"
#include "Garfield/Sensor.hh"
#include "Garfield/ViewDrift.hh"

#include "model_info.hh"
#include "run_info.hh"

using namespace Garfield;

int main(int argc, char* argv[]) {
  if (argc < 9) {
    std::cout << "Usage: gem_avalanche <mesh/result dir> <.gas file> <n events> "
                 "<zSensorMin> <zSensorMax> <zInjection> <xHalfCm> <yHalfCm> "
                 "[e0_eV] [injectionRadiusCm] [rootOutDir] [imgOutDir] "
                 "[maxElectronEnergyEv] [seed] [avalancheSizeLimit]\n";
    return 1;
  }
  // Captured once here, before TApplication is constructed below: its
  // constructor is documented to strip any argv entries it recognizes as
  // its own options, which can shift/mutate argv -- confirmed directly: a
  // *second* argv[1] read after that point returned a different, wrong
  // value even though this first read (and everything else in this
  // function) uses the same argv[1] and worked fine. Every later use of
  // "the mesh dir path as given on the command line" must go through this
  // variable, not argv[1] directly.
  const std::string meshDirArg = argv[1];
  const std::string meshDir = meshDirArg + "/";
  const std::string baseName = std::filesystem::path(meshDirArg).filename().string();
  const gem::ModelGeometryInfo geo = gem::LoadModelGeometryInfo(meshDirArg, baseName);
  const std::string gasFile = argv[2];
  const int nEvents = std::atoi(argv[3]);
  const double zSensorMin = std::stod(argv[4]);
  const double zSensorMax = std::stod(argv[5]);
  const double zInjection = std::stod(argv[6]);
  const double xHalfCm = std::stod(argv[7]);
  const double yHalfCm = std::stod(argv[8]);
  const double e0 = argc > 9 ? std::stod(argv[9]) : 0.1;
  const double injectionRadiusCm = argc > 10 ? std::stod(argv[10]) : 0.0005;
  // Two separate output dirs since this macro writes both a ROOT file and
  // a PNG (results/root/ and results/img/ respectively -- see
  // docs/reference.md "出力ディレクトリ構成"); imgOutDir falls back to
  // rootOutDir if not given, so old single-output-dir invocations still work.
  const std::string rootOutDir = argc > 11 ? std::string(argv[11]) + "/" : "./";
  const std::string imgOutDir = argc > 12 ? std::string(argv[12]) + "/" : rootOutDir;
  // Optional: pre-extend MediumMagboltz's electron-collision-rate table up
  // front instead of letting it auto-extend in many small increments
  // during the run (seen testing a diagnostic with a much higher applied
  // GEM voltage: electron energies routinely exceeded the table's default
  // range, and each "Rate at X eV is not included... Increasing energy
  // range" step is expensive when it happens hundreds of times over a run
  // -- see docs/debugging_notes.md). 0 (default) leaves Magboltz's own
  // auto-extension behavior untouched.
  const double maxElectronEnergyEv = argc > 13 ? std::stod(argv[13]) : 0.0;
  // Explicit RNG seed, same convention as export_avalanche_trajectories.cpp
  // -- see that macro's comment for why.
  const bool hasExplicitSeed = argc > 14;
  const unsigned int seed = hasExplicitSeed ? static_cast<unsigned int>(std::stoul(argv[14])) : 0;
  if (hasExplicitSeed) {
    // NOT RandomEngineRoot(seed) -- see export_avalanche_trajectories.cpp's
    // comment on the same pattern for the Garfield++ constructor bug this
    // works around.
    RandomEngineRoot engine;
    engine.SetSeed(seed);
    Random::SetEngine(engine);
  }
  // See the usage docstring above for why this default (2000) can
  // significantly undercount transmission once Penning transfer is on.
  const int avalancheSizeLimit = argc > 15 ? std::atoi(argv[15]) : 2000;
  std::cout << "RNG seed: " << (hasExplicitSeed ? std::to_string(seed) : "auto (process-default)")
            << "\n";

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
  if (maxElectronEnergyEv > 0.) {
    gas.SetMaxElectronEnergy(maxElectronEnergyEv);
  }
  // Penning transfer is NOT part of what .gas files persist (confirmed in
  // the installed Garfield++ source, MediumGas::WriteGasFile/LoadGasFile --
  // it's a runtime-only property of the MediumGas object), so every macro
  // that runs an avalanche must (re-)enable it itself, same as every other
  // LoadGasFile() call. The no-arg overload uses Garfield's own built-in,
  // literature-sourced parameterization for this exact Ar/CH4 mixture at
  // our pressure (doi:10.1088/1748-0221/5/05/P05002; confirmed in source,
  // MediumGas::EnablePenningTransfer(), gives r~0.222, lambda=0 for 90/10
  // Ar/CH4 at 1 atm) rather than an arbitrary guess. Note: absolute gain
  // numbers computed without Penning transfer enabled are not directly
  // comparable to gain numbers computed with it on.
  const bool penningEnabled = gas.EnablePenningTransfer();
  if (!penningEnabled) {
    std::cerr << "WARNING: EnablePenningTransfer() failed for this gas "
                 "composition -- proceeding without Penning transfer.\n";
  }
  // The actual r/lambda values used, not just the enabled/disabled flag:
  // these came from Garfield++'s own built-in parameterization
  // (EnablePenningTransfer()'s no-arg overload), which could in principle
  // change with a future Garfield++ version even though our gas
  // composition doesn't, so recording the value actually used each run
  // (not just "Penning was on") matters for reproducibility.
  double penningR = 0., penningLambda = 0.;
  if (penningEnabled) {
    // MediumMagboltz declares its own GetPenningTransfer(size_t, ...)
    // (per-excitation-level) that hides MediumGas's GetPenningTransfer(
    // const std::string&, ...) (the global per-gas-component value
    // EnablePenningTransfer() actually set) -- explicit base-class
    // qualification needed to reach the one we want.
    gas.MediumGas::GetPenningTransfer("Ar", penningR, penningLambda);
  }

  // geo.gas_material_index is read from the actual "Gas" physical group ID
  // the geometry builder wrote (model_info.hh), not hardcoded -- see that
  // struct's own comment and docs/pipeline_gotchas.md #8 (ComponentElmer
  // subtracts 1 from mesh.names' 1-based body ID).
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
  // Safety cap: a run with 150 events at the default settings was killed
  // after 25+ minutes and 3.5+ GB RSS with no sign of finishing -- almost
  // certainly one event's avalanche growing pathologically large (or stuck)
  // rather than genuinely needing that much computation. Bound it so a
  // single bad event cannot hang the whole run; GetAvalancheSize() still
  // reports whatever size it reached when cut off -- meaning that reported
  // "gain" is a truncated lower bound, not a genuine final size, for any
  // event that hits this (tracked and flagged below; CLI-configurable, see
  // this file's usage docstring -- default unchanged at 2000 for backward
  // compatibility, but it turned out to be hit far more often once Penning
  // transfer was enabled).
  const int kAvalancheSizeLimit = avalancheSizeLimit;
  aval.EnableAvalancheSizeLimit(kAvalancheSizeLimit);

  const double t0 = 0.;

  // Per-electron-endpoint TTree: which (x,y,z) each secondary electron's
  // drift line actually ended at, not just its status code -- needed to
  // tell "hit the hole wall partway down" apart from "hit the bottom
  // copper" apart from "made it into the transfer gap but got lost later",
  // all of which show up as the same StatusLeftDriftMedium(-5) in the
  // tally below. See docs/debugging_notes.md.
  const std::string rootPath = rootOutDir + baseName + "_avalanche.root";
  TFile* rootFile = TFile::Open(rootPath.c_str(), "UPDATE");
  rootFile->Delete("Endpoints;*");
  TTree endpointsTree("Endpoints", "Per-electron-endpoint avalanche data");
  // Disable ROOT's automatic mid-run TTree autosave -- see the identical
  // call in export_avalanche_trajectories.cpp for why (multi-cycle files
  // intermittently unreadable by uproot). Endpoints is much smaller
  // per-event than Trajectories so less likely to hit the autosave
  // threshold in practice, but there is no reason to risk it here either.
  endpointsTree.SetAutoSave(0);
  int b_event, b_status;
  double b_xs, b_ys, b_zs, b_ts, b_es, b_xe, b_ye, b_ze, b_te, b_ee;
  endpointsTree.Branch("event", &b_event);
  endpointsTree.Branch("xs", &b_xs);
  endpointsTree.Branch("ys", &b_ys);
  endpointsTree.Branch("zs", &b_zs);
  endpointsTree.Branch("ts", &b_ts);
  endpointsTree.Branch("es", &b_es);
  endpointsTree.Branch("xe", &b_xe);
  endpointsTree.Branch("ye", &b_ye);
  endpointsTree.Branch("ze", &b_ze);
  endpointsTree.Branch("te", &b_te);
  endpointsTree.Branch("ee", &b_ee);
  endpointsTree.Branch("status", &b_status);

  std::vector<int> gains;
  std::map<int, int> endpointStatusCounts;
  gains.reserve(nEvents);
  int nEventsAtCap = 0;
  for (int i = 0; i < nEvents; ++i) {
    // r = R*sqrt(U) for genuine uniform-in-area sampling over the
    // injection disk -- r = R*U (a naive-looking alternative) is biased
    // toward the center and would undercount collection efficiency for
    // anything but a near-axis injection radius. Because of that bias,
    // injectionRadiusCm was historically kept tiny to approximate
    // near-axis injection; a result using a wider injectionRadiusCm
    // together with the R*U formula would be wrong. See also the
    // injection *direction* comment below (still intentionally
    // simplified, not meant to reproduce a real post-drift-diffusion
    // angular distribution).
    const double r = injectionRadiusCm * std::sqrt(RndmUniform());
    const double phi = 2. * M_PI * RndmUniform();
    const double x0 = r * std::cos(phi);
    const double y0 = r * std::sin(phi);

    // Initial direction (0, 0, -1): pointing "downstream" (toward the pad
    // plane, i.e. decreasing z), matching a real drift electron's net
    // motion. Passing (0, 0, 0) instead makes Garfield sample a *random*
    // initial direction (see AvalancheElectron's doc comment), which shows
    // up as most secondary electrons hitting the hole wall almost
    // immediately: close injection with a random start, or distant
    // injection giving diffusion more time to act, are both worse than
    // injecting close with the correct drift direction.
    aval.AvalancheElectron(x0, y0, zInjection, t0, e0, 0., 0., -1.);
    int ne = 0, ni = 0;
    aval.GetAvalancheSize(ne, ni);
    gains.push_back(ne);
    const bool atCap = ne >= kAvalancheSizeLimit;
    if (atCap) ++nEventsAtCap;
    std::cout << "Event " << i << "/" << nEvents << ": gain = " << ne
               << (atCap ? " [AVALANCHE SIZE LIMIT HIT -- truncated]" : "") << "\n";

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
      b_event = i;
      b_xs = xs; b_ys = ys; b_zs = zs; b_ts = ts; b_es = es;
      b_xe = xe; b_ye = ye; b_ze = ze; b_te = te; b_ee = ee;
      b_status = status;
      endpointsTree.Fill();
    }
  }
  endpointsTree.Write();

  // Record the conditions this run actually used, alongside the data --
  // see run_info.hh.
  gem::WriteRunInfo(rootFile, "RunInfoEndpoints", {
      {"executable", "gem_avalanche"},
      {"git_commit_hash", GEM_GIT_COMMIT_HASH},
      {"mesh_dir", meshDirArg},
      {"geometry_type", baseName},
      {"gas_file", gasFile},
      {"gas_temperature_k", std::to_string(gas.GetTemperature())},
      {"gas_pressure_torr", std::to_string(gas.GetPressure())},
      {"gas_material_index", std::to_string(geo.gas_material_index)},
      {"penning_transfer_enabled", penningEnabled ? "true" : "false"},
      {"penning_r", std::to_string(penningR)},
      {"penning_lambda_cm", std::to_string(penningLambda)},
      {"git_dirty", GEM_GIT_DIRTY},
      {"n_events", std::to_string(nEvents)},
      {"z_sensor_min_cm", std::to_string(zSensorMin)},
      {"z_sensor_max_cm", std::to_string(zSensorMax)},
      {"z_injection_cm", std::to_string(zInjection)},
      {"x_half_cm", std::to_string(xHalfCm)},
      {"y_half_cm", std::to_string(yHalfCm)},
      {"e0_ev", std::to_string(e0)},
      {"injection_radius_cm", std::to_string(injectionRadiusCm)},
      // Not a CLI parameter (hardcoded downstream); recorded alongside
      // position/radius so the run's actual injection direction is
      // captured in RunInfo too -- (0,0,-1) matches AvalancheElectron()'s
      // call below.
      {"injection_direction", "0,0,-1"},
      {"max_electron_energy_ev", std::to_string(maxElectronEnergyEv)},
      {"avalanche_size_limit", std::to_string(kAvalancheSizeLimit)},
      {"n_events_at_avalanche_size_limit", std::to_string(nEventsAtCap)},
      {"rng_seed", hasExplicitSeed ? std::to_string(seed) : "auto (process-default)"},
      {"model_info_json", gem::LoadModelInfoJsonRaw(meshDirArg, baseName)},
  });

  rootFile->Close();
  std::cout << "Wrote per-endpoint data to " << rootPath << " (tree \"Endpoints\")\n";

  std::cout << "Electron endpoint status tally (StatusLeftDriftArea=-1, "
               "StatusLeftDriftMedium=-5, StatusOutsideMesh=-6, other=see "
               "GarfieldConstants.hh):\n";
  for (const auto& [status, count] : endpointStatusCounts) {
    std::cout << "  status " << status << ": " << count << "\n";
  }

  // "gains" here is GetAvalancheSize()'s ne: the total number of electrons
  // produced within one primary event's avalanche tree (including ones
  // later absorbed by a wall/electrode), NOT a detector "effective gain"
  // (electrons actually reaching the readout/next stage) -- that has to be
  // computed separately from genuine plane crossings (see
  // geometry/analyze_plane_crossings.py and docs/debugging_notes.md).
  // Printed as "avalanche size" below, not "gain", to avoid conflating the
  // two.
  double sum = 0., sumSq = 0.;
  for (const int g : gains) {
    sum += g;
    sumSq += double(g) * g;
  }
  const double mean = sum / gains.size();
  const double variance = sumSq / gains.size() - mean * mean;
  const double rms = std::sqrt(std::max(0., variance));
  // RMS (event-to-event spread) and the standard error on the mean
  // (RMS/sqrt(N), how precisely the mean itself is known) are different
  // quantities -- printing "mean +/- sqrt(variance)" alone would conflate
  // them, reading like an uncertainty on the mean when it is actually the
  // distribution width.
  const double meanStdErr = rms / std::sqrt(static_cast<double>(gains.size()));
  std::cout << "Mean avalanche size = " << mean << ", RMS = " << rms
            << ", standard error on the mean = " << meanStdErr
            << " (n = " << gains.size() << " events, " << nEventsAtCap
            << " hit the avalanche size limit)\n";

  TCanvas canvas("c", "Drift lines", 800, 800);
  driftView.SetCanvas(&canvas);
  driftView.Plot();
  const std::string plotPath = imgOutDir + baseName + "_avalanche_drift_lines.png";
  canvas.SaveAs(plotPath.c_str());
  std::cout << "Wrote " << plotPath << "\n";

  return 0;
}
