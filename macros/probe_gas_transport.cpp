/**
 * Query MediumMagboltz's transport parameters (drift velocity, diffusion
 * coefficients, Townsend coefficient) at one or more explicit electric
 * field magnitudes -- for a back-of-envelope sanity check of whether the
 * GEM1 hole neck's own transverse diffusion length can plausibly explain
 * the near-total electron loss found there (see docs/debugging_notes.md),
 * independent of any code bug.
 *
 * CAVEAT (unresolved): against the currently
 * checked-in resources/ar_ch4_90_10.gas, ElectronVelocity() and
 * ElectronTownsend() both return false (no usable table), and
 * ElectronDiffusion() returns the exact same value for both DL and DT at
 * every field tested -- suspicious, since real DL/DT should differ,
 * especially at high field. AvalancheMicroscopic itself does not use any
 * of these three macroscopic tables (it samples real collisions directly
 * from cross-section data), so this is unrelated to whether the actual
 * avalanche simulation is correct -- but it does mean the numbers this
 * tool currently prints should not yet be trusted for the diffusion-vs-
 * hole-size estimate; regenerating the .gas file with explicit velocity/
 * Townsend/anisotropic-diffusion table requests (see gen_gas_table.cpp)
 * would need to happen first.
 *
 * Usage: probe_gas_transport <.gas file> <E1_V_per_cm> [E2 ...]
 */

#include <cmath>
#include <iostream>
#include <string>

#include "Garfield/MediumMagboltz.hh"

using namespace Garfield;

int main(int argc, char* argv[]) {
  if (argc < 3) {
    std::cout << "Usage: probe_gas_transport <.gas file> <E1_V_per_cm> [E2 ...]\n";
    return 1;
  }
  MediumMagboltz gas;
  gas.SetComposition("ar", 90., "ch4", 10.);
  gas.SetTemperature(293.15);
  gas.SetPressure(760.);
  if (!gas.LoadGasFile(argv[1])) {
    std::cerr << "Failed to load gas file " << argv[1] << "\n";
    return 1;
  }

  for (int i = 2; i < argc; ++i) {
    const double e = std::stod(argv[i]);
    double vx, vy, vz;
    const bool okV = gas.ElectronVelocity(0., 0., -e, 0., 0., 0., vx, vy, vz);
    double dl = 0., dt = 0.;
    const bool okD = gas.ElectronDiffusion(0., 0., -e, 0., 0., 0., dl, dt);
    double alpha = 0.;
    const bool okA = gas.ElectronTownsend(0., 0., -e, 0., 0., 0., alpha);
    const double vmag = std::sqrt(vx * vx + vy * vy + vz * vz);
    // vmag is cm/ns; 1 cm/ns = 1e4 cm/us.
    std::cout << "E=" << e << " V/cm: vdrift=" << vmag * 1.0e4 << " cm/us (ok=" << okV
               << "), DL=" << dl << " DT=" << dt << " cm^1/2 (ok=" << okD
               << "), alpha=" << alpha << " /cm (ok=" << okA << ")\n";
  }
  return 0;
}
