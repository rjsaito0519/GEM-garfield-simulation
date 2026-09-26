/**
 * Export full per-point avalanche electron trajectories (not just start/end
 * points, unlike gem_avalanche.cpp's endpoint tree) to a ROOT TTree, for the
 * Python/PyVista visualization layer to overlay against geometry and field
 * maps.
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
 *          <yHalfCm> [e0_eV] [injectionRadiusCm] [output dir] [collisionSteps]
 *          [eventOffset] [seed] [avalancheSizeLimit]
 *   Same argument convention as gem_avalanche.cpp -- the numbers already
 *   used for a given model's gem_avalanche run can be reused here directly.
 *   collisionSteps: real collisions between recorded path points, default
 *     100. Set to 1 to record every single real collision (much bigger
 *     output, but shows the true per-collision step size -- e.g. near a
 *     hole wall, see docs/debugging_notes.md).
 *   eventOffset: added to every "event" branch value (default 0). Lets
 *     several parallel runs (e.g. LSF/bsub jobs, see batch/run_avalanche_batch.py
 *     and docs/pipeline_gotchas.md) each cover a distinct, non-overlapping
 *     slice of a larger total event count, so their "Trajectories" trees
 *     can be hadd'd together afterward without colliding (event,track)
 *     keys -- every downstream analysis script treats (event,track) as a
 *     globally unique identifier.
 *   avalancheSizeLimit: see gem_avalanche.cpp's usage docstring for why the
 *     default (2000) can significantly undercount transmission once
 *     Penning transfer is on -- same CLI-configurable cap here, same
 *     Garfield++ drop-without-recording behavior when hit.
 *
 * Output: "<baseName>_avalanche.root", tree "Trajectories", branches
 *   event,track,x,y,z,t,energy,status. Also writes a "RunInfoTrajectories"
 *   tree (see run_info.hh) recording this run's own conditions --
 *   gem_avalanche.cpp writes its own "RunInfoEndpoints" to the same file
 *   under a different tree name specifically so the two don't overwrite
 *   each other (a single shared "RunInfo" tree name would mean whichever
 *   macro runs last silently overwrites the other's metadata).
 * (one entry per recorded path point; "track" is a per-event index into
 * AvalancheMicroscopic::GetElectrons(), not a globally unique ID -- pair
 * (event,track) to identify one electron's full path). "status" is that
 * electron's final Garfield++ endpoint status (Electron::status, see
 * GarfieldConstants.hh), repeated on every row of the track for
 * convenience -- there is no separate per-track "track" index in
 * gem_avalanche.cpp's "Endpoints" tree to join against, so this is the
 * only way to classify a given trajectory's final fate. Opened in UPDATE
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
#include "Garfield/RandomEngineRoot.hh"
#include "Garfield/Sensor.hh"

#include "model_info.hh"
#include "run_info.hh"

using namespace Garfield;

int main(int argc, char* argv[]) {
  if (argc < 9) {
    std::cout << "Usage: export_avalanche_trajectories <mesh/result dir> <.gas file> "
                 "<n events> <zSensorMin> <zSensorMax> <zInjection> <xHalfCm> <yHalfCm> "
                 "[e0_eV] [injectionRadiusCm] [output dir] [collisionSteps] [eventOffset] "
                 "[seed] [avalancheSizeLimit]\n";
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
  const double xHalfCm = std::stod(argv[7]);
  const double yHalfCm = std::stod(argv[8]);
  const double e0 = argc > 9 ? std::stod(argv[9]) : 0.1;
  const double injectionRadiusCm = argc > 10 ? std::stod(argv[10]) : 0.0005;
  const std::string outDir = argc > 11 ? std::string(argv[11]) + "/" : "./";
  // How many real collisions between recorded path points (see the
  // EnableDriftLines() comment below) -- default 100 for normal use
  // (dense enough overlay plots without huge files), but 1 (every single
  // real collision) lets the true per-collision step size be inspected
  // directly near a hole wall, independent of any macroscopic-transport-
  // table question -- see docs/debugging_notes.md.
  const int collisionSteps = argc > 12 ? std::atoi(argv[12]) : 100;
  const int eventOffset = argc > 13 ? std::atoi(argv[13]) : 0;
  // Explicit RNG seed (default: none -- Garfield's own default engine,
  // Garfield::RandomEngineRoot, auto-seeds itself via ROOT's TRandom3::
  // SetSeed(0), which draws from time+PID and is independent per process;
  // verified empirically across a real multi-job bsub batch that this
  // already gives genuinely independent event sequences per job with no
  // explicit seeding). Pass an explicit seed for reproducibility (e.g.
  // batch/run_avalanche_batch.py derives one per job from a shared base
  // seed + job index) instead of relying on that auto-seeding -- see
  // docs/debugging_notes.md.
  const bool hasExplicitSeed = argc > 14;
  const unsigned int seed = hasExplicitSeed ? static_cast<unsigned int>(std::stoul(argv[14])) : 0;
  if (hasExplicitSeed) {
    // NOT RandomEngineRoot(seed) (the parameterized constructor) -- that
    // constructor has a real Garfield++ bug (confirmed in the installed
    // source, and isolated in a standalone reproducer): it calls SetSeed()
    // via the base RandomEngine<> constructor *before* the derived class's
    // own m_rng member is constructed, so the explicit seed is silently
    // clobbered when m_rng's default constructor then runs (TRandom3's own
    // fixed default seed, 4357) -- every seed value ends up producing the
    // exact same sequence. Default-construct (correctly self-seeds AND
    // properly constructs m_rng) then call SetSeed() as a separate step
    // instead.
    RandomEngineRoot engine;
    engine.SetSeed(seed);
    Random::SetEngine(engine);
  }
  std::cout << "RNG seed: " << (hasExplicitSeed ? std::to_string(seed) : "auto (process-default)")
            << "\n";
  // See the usage docstring above for why this default (2000) can
  // significantly undercount transmission once Penning transfer is on.
  const std::size_t avalancheSizeLimit = argc > 15 ? static_cast<std::size_t>(std::atoi(argv[15])) : 2000;

  MediumMagboltz gas;
  if (!gas.LoadGasFile(gasFile)) {
    std::cerr << "Failed to load gas file " << gasFile << "\n";
    return 1;
  }
  // Penning transfer is a runtime-only MediumGas property, not persisted in
  // .gas files -- see gem_avalanche.cpp's comment on the same call for the
  // full explanation and the literature source for this gas mixture's
  // parameters.
  const bool penningEnabled = gas.EnablePenningTransfer();
  if (!penningEnabled) {
    std::cerr << "WARNING: EnablePenningTransfer() failed for this gas "
                 "composition -- proceeding without Penning transfer.\n";
  }
  // See gem_avalanche.cpp's comment on the same pair of calls for why the
  // actual r/lambda are recorded, not just whether Penning was enabled.
  double penningR = 0., penningLambda = 0.;
  if (penningEnabled) {
    // See gem_avalanche.cpp's comment on the same call for why the
    // explicit MediumGas:: qualification is needed.
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

  AvalancheMicroscopic aval;
  aval.SetSensor(&sensor);
  aval.SetCollisionSteps(collisionSteps);
  // Must be explicitly enabled (default off): without it, path only ever
  // ends up with the seed point plus one final point regardless of how
  // long the drift line actually was (confirmed in the installed
  // Garfield++ source, AvalancheMicroscopic.cc -- the interior-point
  // recording is gated on m_storeDriftLines, separate from m_viewer/
  // EnablePlotting). SetCollisionSteps(100) above then controls how often
  // (every 100 collisions) an interior point gets recorded.
  aval.EnableDriftLines();
  // Same safety cap as gem_avalanche.cpp -- see its comment on the same
  // call, and this file's usage docstring, for why. Recorded per event
  // below so a scan that pushes gain high enough to actually hit this can
  // be detected instead of silently truncating -- routinely hit once
  // Penning transfer was enabled, hence this being CLI-configurable rather
  // than a fixed constant.
  const std::size_t kAvalancheSizeLimit = avalancheSizeLimit;
  aval.EnableAvalancheSizeLimit(kAvalancheSizeLimit);

  const std::string rootPath = outDir + baseName + "_avalanche.root";
  TFile* rootFile = TFile::Open(rootPath.c_str(), "UPDATE");
  rootFile->Delete("Trajectories;*");
  TTree trajectoriesTree("Trajectories", "Per-point avalanche electron trajectories");
  // Disable ROOT's automatic mid-run TTree autosave (default: every ~300MB
  // of TBasket data triggers an implicit Write(), leaving multiple
  // cumulative "cycles" of the same tree name in the file once the real,
  // explicit Write() below also runs). Each autosave cycle is complete and
  // correct on its own, and hadd already resolves to the latest one
  // correctly, but a heavy event's file (300MB+, e.g. with a large
  // avalanche_size_limit) can end up with a dozen-plus cycles, and that
  // specific multi-cycle key-table layout intermittently makes uproot fail
  // to read the file at all ("ValueError: read length must be non-negative
  // or -1") even though `rootls`/`hadd` read the same file fine -- this
  // project's batch merge validation is uproot-based, so that failure mode
  // matters here. One clean cycle per run avoids the whole class of issue;
  // a run either finishes and writes it, or gets killed and writes
  // nothing, which this project's batch tooling already treats as a
  // failed part either way (no partial-file fallback is expected).
  trajectoriesTree.SetAutoSave(0);
  int b_event;
  std::size_t b_track;
  double b_x, b_y, b_z, b_t, b_energy;
  int b_status;
  trajectoriesTree.Branch("event", &b_event);
  trajectoriesTree.Branch("track", &b_track);
  trajectoriesTree.Branch("x", &b_x);
  trajectoriesTree.Branch("y", &b_y);
  trajectoriesTree.Branch("z", &b_z);
  trajectoriesTree.Branch("t", &b_t);
  trajectoriesTree.Branch("energy", &b_energy);
  trajectoriesTree.Branch("status", &b_status);

  const double t0 = 0.;
  int nEventsAtCap = 0;
  for (int i = 0; i < nEvents; ++i) {
    // Same injection convention as gem_avalanche.cpp: direction (0,0,-1)
    // (downstream); r = R*sqrt(U), not r = R*U, for genuine uniform-in-area
    // sampling over the injection disk -- see gem_avalanche.cpp's comment
    // on the same pattern for the full reasoning.
    const double r = injectionRadiusCm * std::sqrt(RndmUniform());
    const double phi = 2. * M_PI * RndmUniform();
    const double x0 = r * std::cos(phi);
    const double y0 = r * std::sin(phi);
    aval.AvalancheElectron(x0, y0, zInjection, t0, e0, 0., 0., -1.);

    const auto& electrons = aval.GetElectrons();
    std::size_t nPoints = 0;
    for (std::size_t track = 0; track < electrons.size(); ++track) {
      b_status = electrons[track].status;
      for (const auto& p : electrons[track].path) {
        b_event = i + eventOffset;
        b_track = track;
        b_x = p.x; b_y = p.y; b_z = p.z; b_t = p.t; b_energy = p.energy;
        trajectoriesTree.Fill();
        ++nPoints;
      }
    }
    const bool atCap = electrons.size() >= kAvalancheSizeLimit;
    if (atCap) ++nEventsAtCap;
    std::cout << "Event " << i << "/" << nEvents << " (global event "
               << (i + eventOffset) << "): " << electrons.size()
               << " electron tracks, " << nPoints << " trajectory points"
               << (atCap ? " [AVALANCHE SIZE LIMIT HIT -- truncated, not a genuine final size]" : "")
               << "\n";
  }
  trajectoriesTree.Write();

  // Record the conditions this run actually used, alongside the data --
  // see run_info.hh.
  gem::WriteRunInfo(rootFile, "RunInfoTrajectories", {
      {"executable", "export_avalanche_trajectories"},
      {"git_commit_hash", GEM_GIT_COMMIT_HASH},
      {"mesh_dir", argv[1]},
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
      {"event_offset", std::to_string(eventOffset)},
      {"collision_steps", std::to_string(collisionSteps)},
      {"z_sensor_min_cm", std::to_string(zSensorMin)},
      {"z_sensor_max_cm", std::to_string(zSensorMax)},
      {"z_injection_cm", std::to_string(zInjection)},
      {"x_half_cm", std::to_string(xHalfCm)},
      {"y_half_cm", std::to_string(yHalfCm)},
      {"e0_ev", std::to_string(e0)},
      {"injection_radius_cm", std::to_string(injectionRadiusCm)},
      // See gem_avalanche.cpp's comment on the same entry.
      {"injection_direction", "0,0,-1"},
      {"avalanche_size_limit", std::to_string(kAvalancheSizeLimit)},
      {"n_events_at_avalanche_size_limit", std::to_string(nEventsAtCap)},
      {"rng_seed", hasExplicitSeed ? std::to_string(seed) : "auto (process-default)"},
      {"model_info_json", gem::LoadModelInfoJsonRaw(argv[1], baseName)},
  });

  rootFile->Close();
  std::cout << "Wrote " << rootPath << " (tree \"Trajectories\")\n";
  std::cout << "Avalanche size limit (" << kAvalancheSizeLimit << ") hit in " << nEventsAtCap
            << "/" << nEvents << " events"
            << (nEventsAtCap > 0
                    ? " -- those events' reported sizes are truncated, not genuine avalanche "
                      "sizes; raise EnableAvalancheSizeLimit if this matters for the current scan"
                    : "")
            << "\n";
  return 0;
}
