#!/usr/bin/env bash
# =============================================================================
# build.sh — Build script for FlowLiDAR Prototype 1
#
# Usage:  ./build.sh
#
# Requires:
#   $SDE  — path to the Barefoot SDE root (e.g. /home/student/Desktop/open-p4studio)
# =============================================================================

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────

PROGRAM_NAME="prototype1"
P4_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/prototype1.p4"
BUILD_DIR="/tmp/build_${PROGRAM_NAME}"

# ── Checks ────────────────────────────────────────────────────────────────────

if [[ -z "${SDE:-}" ]]; then
    echo "[ERROR] \$SDE is not set."
    echo "        Export it first, e.g.:"
    echo "          export SDE=/home/student/Desktop/open-p4studio"
    exit 1
fi

if [[ ! -d "$SDE" ]]; then
    echo "[ERROR] \$SDE directory does not exist: $SDE"
    exit 1
fi

if [[ ! -f "$P4_FILE" ]]; then
    echo "[ERROR] P4 source file not found: $P4_FILE"
    exit 1
fi

SDE_INSTALL="${SDE}/install"

# The p4studio CMakeLists.txt calls find_program(P4C bf-p4c ...) but the SDE
# installs the compiler as plain "p4c" (no bf- prefix).  Pass the path
# explicitly so cmake doesn't report P4C-NOTFOUND.
P4C_BIN="${SDE_INSTALL}/bin/p4c"

if [[ ! -x "$P4C_BIN" ]]; then
    echo "[ERROR] P4 compiler not found at: $P4C_BIN"
    exit 1
fi

echo "============================================================"
echo "  Building FlowLiDAR Prototype 1"
echo "  SDE         : $SDE"
echo "  SDE_INSTALL : $SDE_INSTALL"
echo "  P4C         : $P4C_BIN"
echo "  P4 file     : $P4_FILE"
echo "  Build dir   : $BUILD_DIR"
echo "============================================================"

# ── Build ─────────────────────────────────────────────────────────────────────

echo ""
echo "[1/3] Running cmake..."
mkdir -p "$BUILD_DIR"
cmake "$SDE/p4studio/" \
    -DCMAKE_INSTALL_PREFIX="$SDE_INSTALL" \
    -DCMAKE_MODULE_PATH="$SDE/cmake" \
    -DP4_NAME="$PROGRAM_NAME" \
    -DP4_PATH="$P4_FILE" \
    -DP4C="$P4C_BIN" \
    -B "$BUILD_DIR" \
    2>&1

echo ""
echo "[2/3] Compiling..."
make -C "$BUILD_DIR" "$PROGRAM_NAME" 2>&1

echo ""
echo "[3/3] Installing..."
make -C "$BUILD_DIR" install 2>&1

echo ""
echo "============================================================"
echo "  Build SUCCESS"
echo ""
echo "  To run the Tofino model (terminal 1):"
echo "    \$SDE/run_tofino_model.sh -p $PROGRAM_NAME"
echo ""
echo "  To run switchd (terminal 2):"
echo "    \$SDE/run_switchd.sh -p $PROGRAM_NAME"
echo "============================================================"
