# FlowLiDAR on Intel Tofino 1

P4 implementation and hardware evaluation of **FlowLiDAR** (Monterubbiano et al.,
ACM SIGMETRICS 2023) on an Intel Tofino 1 switch, with a parallel C++ control
plane. This README is the single guide for running everything: syncing to the
switch, building, cutting datasets, running the data plane, filling tables,
sending traffic, and comparing results.

---

## 1. Repository structure

```
flowlidar/
├── README.md                       # this file
├── common/                         # shared P4 headers (#include "../common/...")
├── cpp_lazy_common/                # shared C++ control plane for LAZY variants
├── cpp_traditional_common/         # shared C++ control plane for STANDARD variants
│
├── cpp_lazy_bf<SIZE>_cms<G>/        # one dir per compiled P4 program (data plane)
├── cpp_traditional_bf<SIZE>_cms<G>/ #   "
│       <name>.p4          # the data plane
│       setup_table.py     # enable ports + LPM (+ lazy gates)
│       print_ids.py       # dump register-table IDs for the control plane
│       build.sh           # cmake + make + install ON THE SWITCH
│       Makefile           # builds the control-plane binary <name>_cp
│       <name>_cp          # control-plane binary (after `make`)
│
├── evaluation/harness/             # dataset + scoring tools
│       split_pcaps.sh  truth_csv.sh  compare.py  aggregate.py
├── evaluation/traffic_load_test/   # load-sweep cut scripts (phase1/phase2)
├── traffic_gen/                    # Click/DPDK replay configs (run on the server)
├── results/                        # experiment outputs + plot scripts
└── docs/                           # paper, survey, notes
```

**Variants used in the experiments (6 lazy + 6 standard):**
`bf{131k,262k,524k,1m,2m}_cms256x1024` and `bf2m_cms64x1024`, for each of
`lazy` and `traditional`.

- **lazy** = lazy-update Bloom Filter (FlowLiDAR).
- **traditional** = standard Bloom Filter, paper Algorithm 1 (every packet
  counted in the CMS). The control plane is built with `-DTRAD_CMS_UNGATED`.
- Naming: `bf<N>` = Bloom-filter bits per row (131k…2m = 2^17…2^21);
  `cms<B>x<C>` = B sub-sketches × C columns.

---

## 2. Hosts and environment

| Role | How to reach | Notes |
|---|---|---|
| Switch (Tofino 1) | `ssh <switch>` | SDE 9.11.0; code lives under `~/flowlidar/` |
| Traffic server | `ssh <user>@<server>` | replays pcaps via Click + DPDK |

On the switch, set the SDE env if a non-login shell doesn't have it:
```bash
export SDE=/home/onie/sde/bf-sde-9.11.0
export SDE_INSTALL=$SDE/install
```

---

## 3. Sync the code to the switch

A new person copies the repo to the switch's `~/flowlidar/`. From this machine:
```bash
scp -r cpp_lazy_common cpp_traditional_common common \
       cpp_lazy_bf2m_cms256x1024 cpp_traditional_bf2m_cms256x1024 \
       <switch>:~/flowlidar/
```
Sync whichever variant dirs you need (each is self-contained but needs
`common/` and its policy's `cpp_*_common/`). To sync everything:
```bash
rsync -av --exclude build_gen --exclude '*_cp' ./ <switch>:~/flowlidar/
```

---

## 4. Cut datasets (on the server)

Click needs **legacy pcap** (not pcapng). Two cutters:

**Fixed 5M-packet chunks** (Bloom-filter size sweep):
```bash
bash split_pcaps.sh 5 <PCAP_DIR> <OUT_DIR>     # from evaluation/harness/
```

**Load slices 1M…16M** (traffic-load sweep):
```bash
bash phase1_cut_pcaps.sh 130000 130100 130200  # from evaluation/traffic_load_test/
# -> ~/chunks/<trace>_loads/load_<N>_legacy.pcap
```

One-off pcapng → legacy conversion if needed:
```bash
editcap -F pcap in_pcapng.pcap out_legacy.pcap
capinfos -c out_legacy.pcap        # sanity: packet count
```

**Ground-truth CSV** for a chunk (per-flow true counts, matches the P4 5-tuple):
```bash
bash truth_csv.sh <chunk_legacy.pcap> truth.csv   # from evaluation/harness/
#   columns: src_ip,dst_ip,proto,src_port,dst_port,true_pkts
```

---

## 5. Build (on the switch)

Per variant (`<V>` = variant name) — `build.sh` runs cmake + the P4 compiler +
install, then `make` builds the control plane:
```bash
ssh <switch>
cd ~/flowlidar/cpp_<V>     # e.g. cpp_traditional_bf2m_cms256x1024
./build.sh        # compiles + installs the P4 program (tofino.bin, context.json)
make              # builds the control-plane binary  <V>_cp
```
`build.sh` needs `$SDE` set (see §2). Expect `Build SUCCESS` and `0 errors`.

---

## 6. Run FlowLiDAR (per variant)

Use `<V>` = variant name, e.g. `traditional_bf2m_cms256x1024`.

**Terminal 1 (switch) — start the data plane**
```bash
sudo -E $SDE/run_switchd.sh -p <V>
# wait for the bf-sde> prompt;  stop later with Ctrl-\
```

**Terminal 2 (switch) — fill tables, get IDs, run the control plane**
```bash
# (a) enable ports + LPM  — ABSOLUTE path; ~ is not expanded inside bfrt_python
bfshell
bfshell> bfrt_python /home/<user>/flowlidar/cpp_<V>/setup_table.py
bfshell> exit
#   expect: "Ports enabled: 1/0 (D_P=132) and 2/0 (D_P=140)" + LPM entries

# (b) register-table IDs (no other control plane bound while this runs)
python3 ~/flowlidar/cpp_<V>/print_ids.py
#   prints:  --bf-ids a,b,c   --cms-ids d,e,f

# (c) run the control plane (one epoch sized to the replay window)
cd ~/flowlidar/cpp_<V>
./<V>_cp --pipe 1 --epoch 30 --epochs 1 \
         --bf-ids a,b,c --cms-ids d,e,f \
         --csv-out estimates.csv
#   wait for "waiting for packets..."
```
- `--epoch` is **seconds**; make it ≥ replay time + register read (use 60 for big chunks).
- `--epochs 1` runs one epoch and exits (omit to loop until Ctrl-C).
- Always pass `--bf-ids`/`--cms-ids` (don't rely on auto-resolve).

> **Register IDs are stable across all variants** (same P4 register names →
> same bf-p4c IDs):
> `--bf-ids 2338372543,2333775667,2347111112`
> `--cms-ids 2346354927,2339499036,2335880110`
> If a new variant differs, rerun `print_ids.py`.

---

## 7. Send traffic (on the server)

Start the replay **inside** the control plane's epoch window:
```bash
ssh <user>@<server>
PCAP=~/chunks/130000_loads/load_4000000_legacy.pcap
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
   ~/simple_pcap_replay.click trace=$PCAP RATE=2Gbps replay_count=1
```
- `trace=` the legacy pcap; `replay_count=1` stops after one pass (without it,
  it loops on its default pcap).
- Click prints `SENT PKTS:` / `SEND RATE:`. Actual rate is usually higher than
  `RATE` (e.g. ~3.3 Gbps), so a 5M chunk drains in ~2–3 s.
- Traffic enters on port 2/0 (D_P 140), exits on port 1/0 (D_P 132).

At epoch end the control plane snapshots + clears registers, solves, and writes
`estimates.csv`:
```
src_ip,dst_ip,proto,src_port,dst_port,digest_count,estimated_packets,solver_path
```

---

## 8. Compare results

Join estimate vs truth, compute metrics, append a row to a summary CSV:
```bash
python3 evaluation/harness/compare.py truth.csv estimates.csv summary.csv \
        --meta variant=traditional_bf2m_cms256x1024 load=4000000 trace=130000
```
`compare.py` reports hidden share, coverage, packet accuracy, AAE, ARE,
`pct_exact`, the solver-path mix, and per-size-class errors.

Collapse multiple chunks/traces into per-group mean ± std:
```bash
python3 evaluation/harness/aggregate.py summary.csv --group-by variant,load
```
Plot scripts that produced the report figures live in `results/*/plot_*.py`.

> Note: the CMS row sum (total packets) will exceed `estimated_packets` by the
> hidden-flow packet mass — that's expected. Judge accuracy against `truth.csv`
> (ARE / exact rate), not against the CMS total.

---

## 9. General runbook — all variants

The procedure is identical for every variant; only `<V>` changes. To build a set:
```bash
# switch
for V in lazy_bf131k_cms256x1024 traditional_bf131k_cms256x1024 \
         lazy_bf2m_cms256x1024  traditional_bf2m_cms256x1024 \
         lazy_bf2m_cms64x1024   traditional_bf2m_cms64x1024 ; do
  ( cd ~/flowlidar/cpp_$V && ./build.sh && make )
done
```
Then, per variant: start switchd (`-p <V>`) → `setup_table.py` →
`print_ids.py` → run `<V>_cp` → replay the chosen chunk on the server →
`compare.py truth.csv estimates.csv summary.csv --meta variant=<V> ...`.
Stop switchd (`Ctrl-\`) between variants — each `-p` loads a different program.
Register IDs are shared, so you can reuse the ones in §6.

**Checklist per run:** ports enabled · CP echoes the right IDs · digest count
climbs during replay · `EPOCH 1 END` shows non-zero flows · `estimates.csv`
populated · `compare.py` row looks sane.
