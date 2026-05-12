#!/usr/bin/env bash
# =============================================================================
# build.sh — Build script for FlowLiDAR hardware_version3 (real Tofino 1)
# Run this on p4switch2, not on the local VM.
# =============================================================================

set -euo pipefail

PROGRAM_NAME="prototype7"
P4_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/prototype7.p4"
BUILD_DIR="/tmp/build_${PROGRAM_NAME}"

if [[ -z "${SDE:-}" ]]; then
    echo "[ERROR] \$SDE is not set."
    exit 1
fi

SDE_INSTALL="${SDE}/install"
P4C_BIN="${SDE_INSTALL}/bin/bf-p4c"

if [[ ! -x "$P4C_BIN" ]]; then
    echo "[ERROR] P4 compiler not found at: $P4C_BIN"
    exit 1
fi

echo "============================================================"
echo "  Building FlowLiDAR Prototype 7 (hardware_version3 — BF doubled)"
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
echo "  To run on real hardware (terminal 1):"
echo "    sudo -E \$SDE/run_switchd.sh -p $PROGRAM_NAME"
echo ""
echo "  Then in bfshell (terminal 2):"
echo "    bfrt_python ~/dainius/hardware_version3/setup_table.py"
echo ""
echo "  Then run control plane (terminal 2):"
echo "    python3 ~/dainius/hardware_version3/control_plane.py --epoch 30"
echo ""
echo "  Then send packets FROM hotpot (separate machine):"
echo "    /opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- ~/single_flow.click"
echo "============================================================"
