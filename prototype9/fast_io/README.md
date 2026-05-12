# fast_io — hybrid CP bulk register reader

`fast_io` is a small C++ tool that talks to bf_switchd's bfrt-gRPC service and
bulk-reads / bulk-clears the FlowLiDAR Prototype 9 register tables. It exists
to take the slow per-epoch register I/O off the Python control plane.

The Python `control_plane.py` keeps doing digest collection, the sub-sketch
solver and reporting. When invoked with `--fast-io`, it spawns this binary
at every epoch boundary instead of doing the (slow) bfrt_grpc Python reads
and per-cell clears.

## Build (open-p4studio simulator environment)

```bash
cd prototype9/fast_io
make            # generates gRPC stubs into build_gen/, builds ./fast_io
```

Requires `$SDE` to be set the same way as for the P4 build. Uses:
- `$SDE/install/bin/protoc` + `grpc_cpp_plugin`
- `$SDE/install/share/bf_rt_shared/proto/bfruntime.proto`
- `$SDE/pkgsrc/bf-drivers/third-party/google/rpc/status.proto`
- `$SDE/install/lib/libgrpc++*` and `libprotobuf`

## CLI

```
./fast_io snapshot          <out_dir> [--pipe N]
./fast_io clear                       [--pipe N]
./fast_io snapshot_and_clear <out_dir> [--pipe N]
```

`<out_dir>` will receive 6 binary files:
- `bf_0.bin` / `bf_1.bin` / `bf_2.bin` — `BF_SIZE` bytes each, 1 byte per cell
- `cms_0.bin` / `cms_1.bin` / `cms_2.bin` — `CMS_SIZE × 2` bytes each,
  little-endian uint16 per cell

The Python control plane reads these files and feeds them into the existing
sub-sketch solver. The on-disk format is intentionally trivial so the
reader is a one-liner (`open(...).read()` + `struct.unpack`).

## Use it from control_plane.py

```bash
python3 control_plane.py --epoch 30 \
    --fast-io ./fast_io/fast_io \
    --snapshot-dir /tmp/flowlidar_snapshot
```

Without `--fast-io`, the control plane stays on the original Python
bfrt_grpc path so this prototype is backward-compatible with the prototype 8
workflow.

## Sanity-test on the simulator

After building the P4 program and starting the model + switchd:

```bash
# in another terminal
./fast_io snapshot /tmp/snap
ls -la /tmp/snap/        # should print 6 files
```

Both should succeed in well under a second on the simulator with empty
registers.

## Notes / known gotchas

- The C++ JSON parsing of `bfrt_info` is intentionally minimal — it only
  extracts `(name, id)` pairs from the `tables` array. If the bfrt_info
  layout changes in a future SDE this scanner may need a real JSON library.
- `clear_register` issues a `MODIFY` of the default entry per register
  table. The SDE's behaviour is to zero all cells in that table, but this
  may differ on real hardware — verify with a known non-zero state before
  trusting it for correctness.
- Pipe id is 0 by default (matches the simulator). For real hardware
  (p4switch2) pass `--pipe 1` and the Python CP propagates this.
