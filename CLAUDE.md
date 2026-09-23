# GEM-garfield-simulation: agent entrypoint

Project-specific guidance for AI agents working in this repository. The
user's own global rules (understand-first workflow, minimal/conservative
changes, physics-integrity checks, etc.) still apply and take precedence
where they conflict with anything here — this file only adds project-local
context on top of them.

## What this project is

A Gmsh(OCC) → Elmer → Garfield++ pipeline simulating the J-PARC E72
(HypTPC) 3-GEM stack's electrostatics and electron avalanche, with a
Python-based (PyVista/matplotlib) visualization layer on top. See
`README.md` for the physical device and design.

## Read these first, in this order

1. `README.md` — device, pipeline overview, environment table, status log
2. `docs/reference.md` — how to actually run each pipeline stage, the
   `results/` output directory convention, ROOT tree schemas
3. `docs/pipeline_gotchas.md` — real bugs/gotchas already hit in this
   Gmsh/Elmer/Garfield++/ROOT/Python stack; check before touching similar
   code, since several of them fail silently (plausible-looking wrong
   output, not a crash)
4. `docs/debugging_notes.md` — the ongoing GEM1→GEM2 electron transmission
   investigation (GitHub issue #2), if working on that specific problem

## Project-specific conventions

- **Single source of truth for geometry constants.** GEM pitch, hole
  radii, domain z-bounds, etc. must not be hardcoded independently in both
  Python and C++. Python's `geometry/build_*_field_mesh.py` writes them
  into `results/json/<baseName>_model_info.json`; C++ macros read that
  same file via `macros/model_info.hh`. Add a new geometry parameter there
  if a macro needs it, don't hardcode it locally.
- **Output goes under `results/`, organized by file type**
  (`mesh/root/img/html/json`), not scattered per-subsystem `output/`
  directories. See `docs/reference.md` §3 for exactly what belongs where.
  `results/img/*.png` is the only part of `results/` tracked in git (as
  verification evidence); everything else is regenerable.
- **Prefer ROOT (TTree) over CSV/JSON for numeric simulation output**
  (per-electron endpoints, avalanche trajectories) — this is a ROOT/
  Garfield++ project, and ROOT is the idiomatic format here. Read ROOT
  files from Python with `uproot` (no PyROOT / no need to match ROOT's own
  Python binding to the `work` conda env's Python — see
  `docs/pipeline_gotchas.md` point 17 for why that env is kept separate).
  JSON remains fine for small structured metadata (`model_info.json`,
  mesh surface exports) and geometry/field sample grids consumed by the
  Plotly/PyVista viewers.
- **`GEM_Garfield/` (the sibling reference repo) is read-only.** It is an
  architecture reference (Korea Univ. HANUL group's code), never something
  to edit or extend directly.
- **Units**: lengths in cm, energies in eV, times in ns, fields in V/cm —
  matching Garfield++'s own convention — throughout the whole pipeline
  (Gmsh geometry, Elmer `.sif`, Garfield++ macros, ROOT trees, Python
  loaders). Don't introduce a different unit convention in new code.
- **Physics/geometry decisions require the user's confirmation** (this
  echoes the user's own global rules but is worth restating given how
  often this project's parameters get revisited): GEM stacking order,
  voltages, gap sizes, hole geometry, gas composition. Several of these
  already deliberately diverge from the source paper (Kim et al. 2020) —
  see README.md's status log for what and why — don't silently "correct"
  them back to the paper's numbers.

## Environment quirks worth knowing before debugging something that looks broken

- `python3` is normally an envfs-cached copy of the `work` conda env for
  fast startup; it can lag behind a fresh `pip install` until
  `~/local/bin/envfs.sh repack work` is rerun (see
  `docs/pipeline_gotchas.md` point 17, and `~/local/envfs_README.md`
  outside this repo for the full mechanism).
- ROOT/TApplication-using macros can crash at process exit *after*
  completing and writing all real output correctly (see
  `docs/pipeline_gotchas.md` point 13) — check the output file's actual
  contents before assuming a non-zero exit code means something is wrong.
