# cpp_lazy_bf262k_cms64x2048 — lazy BF 262k + wider CMS

Pure-C++ FlowLiDAR control plane on real Tofino 1 (p4switch2). Same lazy
BF size as `cpp_lazy_bf262k_cms64x1024` but with **double the CMS
columns per sub-sketch**.

- **Data plane**: lazy BF (3 × 262144 × 1 bit, bit<18>) + sub-sketch CMS
  (3 × **131072** × 16-bit, **64 buckets × 2048 cols**).
- **Control plane**: `./lazy_bf262k_cms2048_cp`, built from the shared
  `../cpp_lazy_common/` sources with `LAZY_CMS_COLS=2048` injected at
  compile time.

## Why this variant exists

In the 262k / 64×1024 run, all 64 sub-sketch buckets had `n > 1024` flows
(`max bucket = 3842`). The Gauss-Jordan exact solver and Algorithm 6
never fired — every solver-eligible flow fell back to `min(cms_rows)`,
leaving ~15% per-flow inflation. Doubling the column count drops the
per-bucket threshold, so many buckets are expected to fall under
`n ≤ kColsPerRow=2048` and run the exact solver.

## File map

```
cpp_lazy_bf262k_cms64x2048/
├── lazy_bf262k_cms2048.p4   P4 (lazy BF 262k + sub-sketch CMS 64×2048)
├── build.sh                 compiles the P4 with bf-p4c
├── setup_table.py           bfshell one-shot — ports, LPM, BF/CMS gates
├── print_ids.py             dumps bfrt register table IDs
├── test_packet.py           local 6-flow correctness probe
├── verify_crc.py            CRC parity check
├── Makefile                 5-line stub: BF_SIZE=262144, CMS_COLS=2048, ...
└── README.md                this file
```

Shared sources live in `../cpp_lazy_common/`.

## Build

On the switch:

```bash
cd ~/dainius/cpp_lazy_bf262k_cms64x2048
./build.sh                  # compiles lazy_bf262k_cms2048.p4 with bf-p4c
make                        # builds ./lazy_bf262k_cms2048_cp
```

## Run

```bash
# T1 — switchd
$SDE/run_switchd.sh -p lazy_bf262k_cms2048

# T2 — setup + CP
bfshell
> bfrt_python /home/onie/dainius/cpp_lazy_bf262k_cms64x2048/setup_table.py
> exit
python3 /home/onie/dainius/cpp_lazy_bf262k_cms64x2048/print_ids.py
/home/onie/dainius/cpp_lazy_bf262k_cms64x2048/lazy_bf262k_cms2048_cp \
    --epoch 15 --pipe 1 \
    --bf-ids  <from print_ids.py> \
    --cms-ids <from print_ids.py>

# T3 — traffic from hotpot
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- ~/simple_pcap_replay.click
```

## Expected vs 64×1024 baseline

- **Max sub-sketch load** drops from ~3.75 to ~1.9 (max bucket 3842 / 1024
  → 3842 / 2048).
- **Exact solver** should fire on the majority of buckets instead of zero.
- **Per-flow inflation** should drop below 1.15× (best case ~1.0× if every
  bucket fits the exact solver).
