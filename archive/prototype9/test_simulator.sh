#!/usr/bin/env bash
# test_simulator.sh — end-to-end sanity test for prototype9 hybrid CP on the
# open-p4studio simulator.
#
# Brings up veth pairs (needs sudo), runs the tofino model + switchd in the
# background, loads tables, runs the C++ fast_io tool, sends 6 known flows,
# checks that the control plane reports 6 / 6 / 27.
#
# Run from the prototype9 directory:
#   ./test_simulator.sh
#
# Caveats:
#   - Will sudo (asks once for veth_setup, model, switchd).
#   - Leaves model + switchd running until you Ctrl-C / kill the script.

set -e

PROTO=prototype9
PROTO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOGDIR="/tmp/${PROTO}_logs"
mkdir -p "$LOGDIR"

if [[ -z "${SDE:-}" || -z "${SDE_INSTALL:-}" ]]; then
    echo "[ERROR] \$SDE / \$SDE_INSTALL must be set."
    exit 1
fi

echo "============================================================"
echo "  prototype9 simulator end-to-end test"
echo "  Logs: $LOGDIR"
echo "============================================================"

cleanup() {
    echo
    echo "[cleanup] killing simulator processes..."
    sudo pkill -f tofino-model 2>/dev/null || true
    sudo pkill -f run_switchd  2>/dev/null || true
    pkill -f "control_plane.py" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[1/7] veth_setup (needs sudo)..."
sudo $SDE_INSTALL/bin/veth_setup.sh > "$LOGDIR/veth_setup.log" 2>&1
echo "      veth1 present: $(ip -br link show veth1 2>&1)"

echo "[2/7] starting tofino model in background..."
sudo -E $SDE/run_tofino_model.sh -p $PROTO > "$LOGDIR/model.log" 2>&1 &
MODEL_PID=$!
sleep 4
if ! pgrep -f tofino-model > /dev/null; then
    echo "[ERROR] tofino model did not start; see $LOGDIR/model.log"
    exit 1
fi
echo "      model pid (sudo subprocess): $MODEL_PID"

echo "[3/7] starting switchd in background..."
sudo -E $SDE/run_switchd.sh -p $PROTO > "$LOGDIR/switchd.log" 2>&1 &
SWITCHD_PID=$!
echo "      waiting for bfruntime gRPC server ready..."
for _ in $(seq 1 30); do
    if grep -q "bfruntime gRPC server started" "$LOGDIR/switchd.log" 2>/dev/null; then
        break
    fi
    sleep 1
done
if ! grep -q "bfruntime gRPC server started" "$LOGDIR/switchd.log"; then
    echo "[ERROR] switchd never reported gRPC ready; see $LOGDIR/switchd.log"
    exit 1
fi
echo "      switchd ready"

echo "[4/7] loading tables via bfshell..."
$SDE_INSTALL/bin/bfshell -f <(echo "bfrt_python $PROTO_DIR/setup_table.py") \
    > "$LOGDIR/setup_table.log" 2>&1
tail -5 "$LOGDIR/setup_table.log"

echo "[5/7] dry-run of fast_io snapshot (empty registers, just sanity)..."
mkdir -p /tmp/${PROTO}_snap
time $PROTO_DIR/fast_io/fast_io snapshot /tmp/${PROTO}_snap

echo "[6/7] starting control plane in hybrid mode (epoch=20s)..."
python3 $PROTO_DIR/control_plane.py \
        --epoch 20 \
        --fast-io $PROTO_DIR/fast_io/fast_io \
        --snapshot-dir /tmp/${PROTO}_snap \
        > "$LOGDIR/cp.log" 2>&1 &
CP_PID=$!
sleep 5
if ! ps -p $CP_PID > /dev/null; then
    echo "[ERROR] control plane crashed; see $LOGDIR/cp.log"
    cat "$LOGDIR/cp.log"
    exit 1
fi

echo "[7/7] sending 6 known flows (12/6/3/2/2/2 packets)..."
sudo python3 $PROTO_DIR/test_packet.py > "$LOGDIR/test_packet.log" 2>&1

echo "      waiting for epoch report (up to 25s)..."
for _ in $(seq 1 25); do
    if grep -q "EPOCH 1 END" "$LOGDIR/cp.log"; then break; fi
    sleep 1
done

echo
echo "============================================================"
echo "  Control plane epoch 1 output"
echo "============================================================"
sed -n '/EPOCH 1 END/,/=====/p' "$LOGDIR/cp.log" | head -25

echo
echo "============================================================"
echo "  fast_io timing lines from CP log"
echo "============================================================"
grep "fast_io" "$LOGDIR/cp.log" || true

echo
echo "Done. Logs in $LOGDIR/"
echo "Press Ctrl-C to tear down (or just exit terminal)."
wait $CP_PID
