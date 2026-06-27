#!/usr/bin/env bash
# =============================================================================
# build.sh — Build script for cpp_traditional_bf524k_cms256x1024
# Run this on p4switch2, not on the local VM.
# =============================================================================

set -euo pipefail

PROGRAM_NAME="traditional_bf524k_cms256x1024"
P4_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/traditional_bf524k_cms256x1024.p4"
BUILD_DIR="/tmp/build_${PROGRAM_NAME}"

if [[ -z "${SDE:-}" ]]; then
    echo "[ERROR] \$SDE is not set."
    exit 1
fi

SDE_INSTALL="${SDE}/install"
P4C_BIN=""
for cand in "${SDE_INSTALL}/bin/bf-p4c" "${SDE_INSTALL}/bin/p4c"; do
    if [[ -x "$cand" ]]; then
        P4C_BIN="$cand"
        break
    fi
done
if [[ -z "$P4C_BIN" ]]; then
    echo "[ERROR] P4 compiler not found in ${SDE_INSTALL}/bin/ (tried bf-p4c and p4c)"
    exit 1
fi

echo "============================================================"
echo "  Building FlowLiDAR Traditional BF (C++ CP variant)"
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
echo "============================================================"
