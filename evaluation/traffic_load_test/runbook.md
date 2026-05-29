# Runbook — Traffic load sweep (E8)

Goal: at fixed lazy_bf2m / traditional_bf2m with CMS=64x1024, sweep the input traffic load and observe how coverage, accuracy, and solver-path distribution change as the BF and CMS get progressively stressed.

With bf2m the BF doesn't saturate as quickly as bf1m, so more flows stay visible at heavy loads — this drives the per-bucket solver pool higher, which pushes alg6 into firing across more load points. Combined with the now uncapped + OpenMP-parallel CP, alg6 should fire on most heavy-load runs at reasonable wallclock.

## Variants and loads

2 variants × 6 loads = **12 runs**:

| Variant | Type |
|---|---|
| `cpp_lazy_bf2m_cms64x1024` | Lazy BF |
| `cpp_traditional_bf2m_cms64x1024` | Standard BF |

| Load | Pcap | Truth | Notes |
|---|---|---|---|
| 1M  | `load_1000000_legacy.pcap`  | `load_1000000_truth.csv`  | baseline, easy regime |
| 2M  | `load_2000000_legacy.pcap`  | `load_2000000_truth.csv`  | |
| 4M  | `load_4000000_legacy.pcap`  | `load_4000000_truth.csv`  | alg6 may fire on traditional |
| 8M  | `load_8000000_legacy.pcap`  | `load_8000000_truth.csv`  | alg6 expected to fire on both |
| 16M | `load_16000000_legacy.pcap` | `load_16000000_truth.csv` | alg6 on both modes |
| 32M | `load_32000000_legacy.pcap` | `load_32000000_truth.csv` | heaviest |

Pcaps under `/home2/dgelzini/chunks/130000_loads/` on hotpot.

## Required CP / P4 builds on switch (first run only)

The `cpp_lazy_bf2m_cms64x1024` directory was renamed locally for naming consistency (was `lazy_bf2m`, now `lazy_bf2m_cms64x1024` throughout). The `cpp_traditional_bf2m_cms64x1024` variant is brand-new. Both need their P4 program built + installed on the switch in addition to the CP binary.

**From VM — scp the variant directories + updated common code:**

```bash
# updated common code (LSQR, OpenMP, no cap)
scp /home/student/Desktop/flowlidar/cpp_lazy_common/Makefile.core \
    /home/student/Desktop/flowlidar/cpp_lazy_common/main.cpp \
    /home/student/Desktop/flowlidar/cpp_lazy_common/solver.cpp \
    onie.two.hotpot:~/dainius/cpp_lazy_common/

scp /home/student/Desktop/flowlidar/cpp_traditional_common/Makefile.core \
    /home/student/Desktop/flowlidar/cpp_traditional_common/main.cpp \
    /home/student/Desktop/flowlidar/cpp_traditional_common/solver.cpp \
    onie.two.hotpot:~/dainius/cpp_traditional_common/

# the bf2m variant directories (CP + P4 + helper scripts)
scp -r /home/student/Desktop/flowlidar/cpp_lazy_bf2m_cms64x1024 \
    onie.two.hotpot:~/dainius/

scp -r /home/student/Desktop/flowlidar/cpp_traditional_bf2m_cms64x1024 \
    onie.two.hotpot:~/dainius/
```

**On switch — build P4 programs (~10-15 min each):**

```bash
ssh onie.two.hotpot

~/dainius/cpp_lazy_bf2m_cms64x1024/build.sh
~/dainius/cpp_traditional_bf2m_cms64x1024/build.sh
```

**Then rebuild CPs (~30 sec each):**

```bash
make -C ~/dainius/cpp_lazy_bf2m_cms64x1024 clean && make -C ~/dainius/cpp_lazy_bf2m_cms64x1024
make -C ~/dainius/cpp_traditional_bf2m_cms64x1024 clean && make -C ~/dainius/cpp_traditional_bf2m_cms64x1024
```

## Pre-flight on the switch

```bash
ssh onie.two.hotpot

# nothing foreign holding the switch?
ps -ef | grep bf_switchd | grep -v grep

# driver loaded?
lsmod | grep bf_kdrv || sudo $SDE/install/bin/bf_kdrv_mod_load $SDE/install

# both CPs and P4 .conf files present?
ls -lh ~/dainius/cpp_{lazy,traditional}_bf2m_cms64x1024/*_cp
ls ~/sde/bf-sde-9.11.0/install/share/p4/targets/tofino/lazy_bf2m_cms64x1024.conf \
   ~/sde/bf-sde-9.11.0/install/share/p4/targets/tofino/traditional_bf2m_cms64x1024.conf
```

## Common setup on hotpot (once per shell)

```bash
ssh dgelzini@hotpot.win.tue.nl
RATE=2Gbps
PCAP_DIR=/home2/dgelzini/chunks/130000_loads

# verify all 6 pcaps + truths exist
ls $PCAP_DIR/load_{1000000,2000000,4000000,8000000,16000000,32000000}_legacy.pcap
ls $PCAP_DIR/load_{1000000,2000000,4000000,8000000,16000000,32000000}_truth.csv
```

Replay template (run on hotpot, change PCAP for each load):
```bash
PCAP=$PCAP_DIR/load_${LOAD}_legacy.pcap
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=$PCAP RATE=$RATE replay_count=1
```

## Known IDs

All 4 register tables share the same IDs across all 64x1024 variants (verified via `print_ids.py`). Use these directly:
```bash
export BF_IDS=2338372543,2333775667,2347111112
export CMS_IDS=2346354927,2339499036,2335880110
```

(If they ever differ on a future variant, run `python3 /home/onie/dainius/cpp_<variant>/print_ids.py` after switchd + setup_table to get the live values.)

## Stop switchd

Ctrl+\ (SIGQUIT). Ctrl+C can leave a zombie holding port 9999. `sudo killall bf_switchd` if stuck (verify whose process first on the shared switch).

## Per-load epoch length

Set `--epoch` high enough that replay finishes inside the window. Click's actual rate is ~3.3 Gbps even with `RATE=2Gbps`.

| Load | Replay duration | `--epoch` |
|---|---:|---:|
| 1M  | ~1.5 s | 20 |
| 2M  | ~3 s   | 20 |
| 4M  | ~6 s   | 20 |
| 8M  | ~12 s  | 30 |
| 16M | ~24 s  | 45 |
| 32M | ~48 s  | 75 |

Postprocessing (LSQR alg6) runs *after* the epoch timer expires, so `--epoch` only needs to cover replay. With OpenMP parallelism on the switch's 8 cores, alg6 step adds ~5-10 min per heavy run on top of the epoch+bulk-read.

---

## Variant A — `lazy_bf2m_cms64x1024` (6 runs)

For each load, run this ritual. Restart switchd between loads to clear per-epoch state.

**Terminal A (switch) — start switchd:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms64x1024
```

**Terminal B (switch) — setup tables (once per switchd start):**
```bash
bfshell
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms64x1024/setup_table.py
# Ctrl+D
```

**Terminal B — run CP for the current LOAD (change per load):**
```bash
LOAD=1000000   # change to 2000000, 4000000, 8000000, 16000000, 32000000 per run
EPOCH=20       # change to 20, 20, 20, 30, 45, 75 per load

mkdir -p ~/results_traffic_load_test/lazy_bf2m_cms64x1024
export BF_IDS=2338372543,2333775667,2347111112
export CMS_IDS=2346354927,2339499036,2335880110

~/dainius/cpp_lazy_bf2m_cms64x1024/lazy_bf2m_cms64x1024_cp \
  --epoch $EPOCH --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/lazy_bf2m_cms64x1024/est_load_${LOAD}.csv 2>&1 \
  | tee /tmp/lazy_bf2m_cms64x1024_load${LOAD}.log
```

**Hotpot — replay (when CP is listening):**
```bash
PCAP=$PCAP_DIR/load_${LOAD}_legacy.pcap
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=$PCAP RATE=$RATE replay_count=1
```

After CP exits, **Ctrl+\\ switchd in A, then restart switchd** and repeat for the next load.

**Sanity check after each run:**
```bash
grep -E "Resolved by Alg|Sub-sketch buckets|cms_[012] :" /tmp/lazy_bf2m_cms64x1024_load${LOAD}.log
```

Expected pattern: `Sub-sketch buckets used: 64 / 64  (exact: X, Alg6 approx: Y, skipped: 0)`. At 1-4M loads, X=64 / Y=0. At 8M+ loads, Y starts growing as buckets cross the alg6 threshold; at 16M/32M, Y should dominate.

---

## Variant B — `traditional_bf2m_cms64x1024` (6 runs)

Identical ritual, just substitute the variant name.

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms64x1024
```

**Terminal B — setup:**
```bash
bfshell
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms64x1024/setup_table.py
# Ctrl+D
```

**Terminal B — CP for current LOAD:**
```bash
LOAD=1000000
EPOCH=20

mkdir -p ~/results_traffic_load_test/traditional_bf2m_cms64x1024
export BF_IDS=2338372543,2333775667,2347111112
export CMS_IDS=2346354927,2339499036,2335880110

~/dainius/cpp_traditional_bf2m_cms64x1024/traditional_bf2m_cms64x1024_cp \
  --epoch $EPOCH --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/traditional_bf2m_cms64x1024/est_load_${LOAD}.csv 2>&1 \
  | tee /tmp/traditional_bf2m_cms64x1024_load${LOAD}.log
```

**Hotpot — replay** (same as Variant A, with the LOAD pcap).

**Sanity check** same grep, just substitute the variant name in the log file path.

For traditional, alg6 is expected to fire from 4M onwards (per-bucket loads cross the alg6 threshold earlier than lazy because no alg4 catches mice).

---

## After all 12 runs — pull to VM and summarise

```bash
# on VM — pull all 12 estimate CSVs
for v in lazy_bf2m_cms64x1024 traditional_bf2m_cms64x1024; do
    for n in 1000000 2000000 4000000 8000000 16000000 32000000; do
        mkdir -p /home/student/Desktop/flowlidar/results/traffic_load_test/$v
        scp onie.two.hotpot:~/results_traffic_load_test/$v/est_load_${n}.csv \
            /home/student/Desktop/flowlidar/results/traffic_load_test/$v/
    done
done

# pull the 6 truth CSVs (from hotpot — different machine)
for n in 1000000 2000000 4000000 8000000 16000000 32000000; do
    scp dgelzini@hotpot.win.tue.nl:/home2/dgelzini/chunks/130000_loads/load_${n}_truth.csv \
        /home/student/Desktop/flowlidar/results/traffic_load_test/
done

# build summary (compare.py uses positional args: truth, estimate, summary)
cd /home/student/Desktop/flowlidar
> results/traffic_load_test/summary.csv
for v in lazy_bf2m_cms64x1024 traditional_bf2m_cms64x1024; do
    for n in 1000000 2000000 4000000 8000000 16000000 32000000; do
        python3 evaluation/harness/compare.py \
          results/traffic_load_test/load_${n}_truth.csv \
          results/traffic_load_test/$v/est_load_${n}.csv \
          results/traffic_load_test/summary.csv \
          --meta variant=$v,load=$n
    done
done

# headline table (sorted by variant then load)
awk -F',' 'NR>=2 {
    split($1, parts, ",");
    printf "%-35s load=%-9s  cov=%.4f  ARE=%.4f  exact=%.4f  alg4=%.3f alg5=%.3f exactpath=%.3f alg6=%.3f min=%.3f\n",
           parts[1], substr(parts[2], 6), $7, $12, $13, $14, $15, $16, $17, $18
}' results/traffic_load_test/summary.csv | sort
```

(Column indices in summary.csv: `coverage=7, packet_acc=10, AAE=11, ARE=12, pct_exact=13, alg4_pct=14, alg5_pct=15, exact_pct=16, alg6_pct=17, min_pct=18`.)

## Plots

Adapt `results/lazy_vs_traditional_bf/plot_lazy_vs_standard.py`. Key changes:
- x-axis = load (packets) on log2 scale: 1M, 2M, 4M, 8M, 16M, 32M
- Same two lines (Lazy BF, Standard BF) per metric
- 5 figures: coverage, ARE, AAE, exact rate, **alg6 share** (proves alg6 actually firing at heavy loads)

Plot scaffold:
```python
LOADS = {"1M": 1000000, "2M": 2000000, "4M": 4000000,
         "8M": 8000000, "16M": 16000000, "32M": 32000000}
# collect points per mode (lazy / standard) using load as x
# alg6_pct chart shows the new dispatch behaviour explicitly
```

## Estimated wall time

| Phase | Time |
|---|---|
| First-time builds (lazy + trad bf2m): 2× build.sh @ 15 min each | 30 min |
| First-time CP rebuilds: 2× make @ 30 sec | 1 min |
| Per run: switchd boot 3 min + setup 30 s + epoch + bulk + alg6 + scp | 5-15 min |
| 6 light runs (1-4M lazy, 1-2M trad): ~5 min each | 30 min |
| 6 heavy runs (4-32M trad, 4-32M lazy alg6): ~10-15 min each | 60-90 min |
| **Total**: builds + 12 runs | **~2.5 - 3 hours** |
