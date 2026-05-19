# cpp_lazy_bf262k_cms64x1024 — pure C++ control plane, lazy BF 262k

Pure-C++ FlowLiDAR control plane on real Tofino 1 (p4switch2). Doubled-BF
variant of `cpp_lazy_bf131k_cms64x1024`:

- **Data plane**: lazy BF (3 × **262144** × 1 bit, bit<18>) + sub-sketch
  CMS (3 × 65536 × 16-bit, 64 buckets × 1024 cols). CMS unchanged from
  the 131k variant — only the BF grew.
- **Control plane**: a single C++ binary (`./lazy_bf262k_cp`) built from
  the shared `../cpp_lazy_common/` sources. Same code as the 131k variant
  with BF_SIZE=262144 injected at compile time.

## File map

```
cpp_lazy_bf262k_cms64x1024/
├── lazy_bf262k.p4    P4 (lazy BF + sub-sketch CMS, 262k cells)
├── build.sh          compiles lazy_bf262k.p4 with bf-p4c
├── setup_table.py    bfshell one-shot — port enables, LPM, BF/CMS gates
├── print_ids.py      dumps bfrt register table IDs
├── test_packet.py    local 6-flow correctness probe
├── verify_crc.py     CRC parity check
├── Makefile          4-line stub: BF_SIZE=262144, P4_NAME=lazy_bf262k, BINARY=lazy_bf262k_cp
├── README.md         this file
└── results.md        measured numbers on real hardware
```

Shared sources live in `../cpp_lazy_common/`.

## Build

On the switch (with `$SDE` and `$SDE_INSTALL` exported):

```bash
cd ~/dainius/cpp_lazy_bf262k_cms64x1024
./build.sh                  # compiles lazy_bf262k.p4 with bf-p4c
make                        # builds ./lazy_bf262k_cp from ../cpp_lazy_common/
```

## Run

Three terminals (T1 + T2 on the switch, T3 sends traffic from hotpot):

### T1 — switchd
```bash
$SDE/run_switchd.sh -p lazy_bf262k
```

### T2 — one-shot setup, then C++ control plane
```bash
bfshell
> bfrt_python /home/onie/dainius/cpp_lazy_bf262k_cms64x1024/setup_table.py
> exit

/home/onie/dainius/cpp_lazy_bf262k_cms64x1024/lazy_bf262k_cp \
    --epoch 15 --pipe 1 \
    --bf-ids  <from print_ids.py> \
    --cms-ids <from print_ids.py>
```

### T3 — traffic from hotpot
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- ~/simple_pcap_replay.click
```

See `results.md` for the measured numbers — doubling the BF closes the
remaining coverage gap (~84% → ~100%) and drops per-flow inflation
(1.40× → 1.15×) vs the 131k variant.
