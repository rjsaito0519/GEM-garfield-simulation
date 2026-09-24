#!/bin/bash
# Elmer step: mesh -> ElmerGrid -> .sif -> ElmerSolver, for either the
# standalone single-GEM electrostatics test or the full 3-GEM stack.
#
# Usage: run_field_solve.sh [mesh_name] [preconditioner] [max_iterations]
#   mesh_name defaults to single_gem_field; pass triple_gem_field for the
#   3-GEM stack. Assumes geometry/build_<mesh_name>.py has already been run
#   (it writes results/mesh/<mesh_name>.msh and results/json/*_model_info.json
#   -- see docs/reference.md "出力ディレクトリ構成"). preconditioner/
#   max_iterations are forwarded to write_sif.py (default ILU2/20000) -- see
#   that script's own usage message for why/when to override (large-mesh
#   ILU2 integer overflow, docs/debugging_notes.md 2026-09-24).
#
# Elmer's env vars are set here explicitly rather than relying on ~/.bashrc,
# which no longer exports them by default (see README.md "実行環境").
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/../results/mesh"
MESH_NAME="${1:-single_gem_field}"
PRECONDITIONER="${2:-ILU2}"
MAX_ITERATIONS="${3:-20000}"

export ELMER_HOME="$HOME/elmer"
export PATH="$ELMER_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$ELMER_HOME/lib:${LD_LIBRARY_PATH:-}"
export ELMER_SOLVER_HOME="$ELMER_HOME/share/elmersolver"

cd "$OUTPUT_DIR"

echo "[1/3] Converting Gmsh mesh to Elmer format with ElmerGrid..."
rm -rf "$MESH_NAME"
ElmerGrid 14 2 "$MESH_NAME.msh" -autoclean

echo "[2/3] Writing $MESH_NAME.sif from mesh.names + model info (preconditioner=$PRECONDITIONER, max_iterations=$MAX_ITERATIONS)..."
python3 "$SCRIPT_DIR/write_sif.py" "$MESH_NAME" "$PRECONDITIONER" "$MAX_ITERATIONS"

echo "[3/3] Running ElmerSolver..."
ElmerSolver "$MESH_NAME.sif"

echo "Done. Result: $OUTPUT_DIR/$MESH_NAME/$MESH_NAME.result"
echo "       ParaView-readable field map: $OUTPUT_DIR/$MESH_NAME.vtu"
