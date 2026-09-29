#!/bin/bash
# Stable-baseline smoke test: runs the real Gmsh -> ElmerGrid -> ElmerSolver
# -> Garfield++ pipeline end-to-end against the single_gem_field model,
# with a small event count. NOT part of `python3 -m unittest discover
# -s tests` -- unlike everything else under tests/, this needs a real Elmer/
# Garfield++/ROOT install and takes about a minute (mesh ~10s, Elmer solve
# ~1min, avalanche ~10s), so it's kept as its own opt-in script per issue
# #17 item 7/6's explicit split (fast metadata/logic tests can run in CI;
# a full-stack solver run can't and shouldn't gate every commit).
#
# This does NOT check any physical quantity for correctness (that's
# issue #18's job) -- only that every stage completes and produces the
# expected non-empty output, i.e. "the pipeline itself still works",
# which is what silently breaks first after an unrelated refactor.
#
# Usage: bash tests/smoke_single_gem.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
N_EVENTS=3

echo "[1/3] Building single_gem_field mesh..."
(cd "$REPO_ROOT/geometry" && python3 build_single_gem_field_mesh.py > /dev/null)

echo "[2/3] Solving the field map with Elmer..."
(cd "$REPO_ROOT/elmer" && bash run_field_solve.sh single_gem_field > /dev/null)

echo "[3/3] Running a $N_EVENTS-event Garfield++ avalanche..."
# gem_avalanche (like other ROOT/TApplication-using macros here) can crash
# during process teardown *after* it has already written all real output
# correctly -- a known, harmless pattern (docs/pipeline_gotchas.md #13), not
# something this smoke test should fail on. The Python check right below,
# not this exit code, is what actually decides pass/fail.
set +e
(cd "$REPO_ROOT/macros/build" && ./gem_avalanche \
    "$REPO_ROOT/results/mesh/single_gem_field" \
    "$REPO_ROOT/resources/ar_ch4_90_10.gas" \
    "$N_EVENTS" -0.62 0.42 0.362 0.007 0.01212435565298214 0.1 0.0005 \
    "$REPO_ROOT/results/root" "$REPO_ROOT/results/img" > /dev/null)
set -e

echo "Verifying output..."
python3 - "$REPO_ROOT/results/root/single_gem_field_avalanche.root" "$N_EVENTS" <<'EOF'
import sys
import uproot

root_path, n_events = sys.argv[1], int(sys.argv[2])
with uproot.open(root_path) as f:
    if "Endpoints" not in f:
        sys.exit(f"FAIL: {root_path} has no Endpoints tree")
    tree = f["Endpoints"]
    if tree.num_entries != n_events:
        sys.exit(f"FAIL: Endpoints has {tree.num_entries} entries, expected {n_events}")
print(f"OK: {root_path}'s Endpoints tree has {n_events} entries as expected.")
EOF

echo "Smoke test passed."
