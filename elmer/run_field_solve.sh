#!/bin/bash
# Elmer step: mesh -> ElmerGrid -> .sif -> ElmerSolver, for either the
# standalone single-GEM electrostatics test or the full 3-GEM stack.
#
# Usage: run_field_solve.sh [mesh_name]
#   mesh_name defaults to single_gem_field; pass triple_gem_field for the
#   3-GEM stack. Assumes geometry/build_<mesh_name>.py has already been run
#   (it writes geometry/output/<mesh_name>.msh and *_model_info.json).
#
# Elmer's env vars are set here explicitly rather than relying on ~/.bashrc,
# which no longer exports them by default (see README.md "実行環境").
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/../geometry/output"
MESH_NAME="${1:-single_gem_field}"

export ELMER_HOME="$HOME/elmer"
export PATH="$ELMER_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$ELMER_HOME/lib:${LD_LIBRARY_PATH:-}"
export ELMER_SOLVER_HOME="$ELMER_HOME/share/elmersolver"

cd "$OUTPUT_DIR"

echo "[1/3] Converting Gmsh mesh to Elmer format with ElmerGrid..."
rm -rf "$MESH_NAME"
ElmerGrid 14 2 "$MESH_NAME.msh" -autoclean

echo "[2/3] Writing $MESH_NAME.sif from mesh.names + model info..."
python3 "$SCRIPT_DIR/write_sif.py" "$MESH_NAME"

echo "[3/3] Running ElmerSolver..."
ElmerSolver "$MESH_NAME.sif"

echo "Done. Result: $OUTPUT_DIR/$MESH_NAME/$MESH_NAME.result"
echo "       ParaView-readable field map: $OUTPUT_DIR/$MESH_NAME.vtu"
