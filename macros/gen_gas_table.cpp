/**
 * Generate the P10 (Ar 90% + CH4 10%) gas transport table with Magboltz and
 * cache it to a .gas file. This is a separate, one-off step from the
 * avalanche macro because it takes several minutes to compute and never
 * changes unless the gas composition/temperature/pressure does -- every
 * other macro should LoadGasFile() the cached result instead of
 * regenerating it.
 *
 * Usage: gen_gas_table <output .gas file path>
 */

#include <iostream>
#include <string>

#include "Garfield/MediumMagboltz.hh"

using namespace Garfield;

int main(int argc, char* argv[]) {
  if (argc != 2) {
    std::cout << "Usage: gen_gas_table <output .gas file path>\n";
    return 1;
  }
  const std::string outputPath = argv[1];

  MediumMagboltz gas;
  gas.SetComposition("ar", 90., "ch4", 10.);
  gas.SetTemperature(293.15);
  gas.SetPressure(760.);
  // The electric field range covered by the table must include everything
  // the field map actually reaches. The strongest field in the model is
  // deep inside the GEM hole itself (tens of kV/cm); use a wide log-spaced
  // grid so Magboltz has table points to interpolate between out there too.
  gas.SetFieldGrid(100., 100000., 20, true);

  std::cout << "Generating Magboltz transport tables for P10 (Ar 90% + CH4 "
               "10%)... this takes a few minutes.\n";
  const bool ok = gas.Initialise(true);
  if (!ok) {
    std::cerr << "MediumMagboltz::Initialise failed.\n";
    return 1;
  }
  gas.WriteGasFile(outputPath);
  std::cout << "Wrote " << outputPath << "\n";
  return 0;
}
