#!/usr/bin/env bash
# =============================================================================
# build.sh — Build script for FlowLiDAR Prototype 2
# =============================================================================

set -euo pipefail

PROGRAM_NAME="prototype2"
P4_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/prototype2.p4"
BUILD_DIR="/tmp/build_${PROGRAM_NAME}"

if [[ -z "${SDE:-}" ]]; then
    echo "[ERROR] \$SDE is not set."
    exit 1
fi

SDE_INSTALL="${SDE}/install"
P4C_BIN="${SDE_INSTALL}/bin/p4c"

if [[ ! -x "$P4C_BIN" ]]; then
    echo "[ERROR] P4 compiler not found at: $P4C_BIN"
    exit 1
fi

echo "============================================================"
echo "  Building FlowLiDAR Prototype 2"
echo "  SDE         : $SDE"
echo "  SDE_INSTALL : $SDE_INSTALL"
echo "  P4C         : $P4C_BIN"
echo "  P4 file     : $P4_FILE"
echo "  Build dir   : $BUILD_DIR"
echo "============================================================"

echo ""
echo "[1/3] Running cmake..."
rm -rf "$BUILD_DIR"
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
