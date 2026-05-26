# Runbook — lazy vs traditional BF sweep (10 variants, chunk 0)

CMS fixed at 256×1024×3 (16-bit). BF size swept across 131k / 262k / 524k / 1M / 2M bits per row in both lazy and traditional modes. One epoch per variant on chunk 0 of CAIDA 130000.

This runbook assumes:
- CP changes from commit 1e4a1e8 (paper-aligned dispatch) and 68723a4 (traditional alg5) are on the switch.
- All 10 variant CPs have been rebuilt on the switch.
- Hotpot DPDK hugepages are allocated (otherwise click won't start).
- Switch driver `bf_kdrv` is loaded and no other `bf_switchd` is holding port 9999.

## Pre-flight on the switch

```bash
ssh onie.two.hotpot

# nothing else holding the switch?
ps -ef | grep bf_switchd | grep -v grep
# if a foreign one is running, coordinate with its owner before killing

# driver loaded?
lsmod | grep bf_kdrv || sudo $SDE/install/bin/bf_kdrv_mod_load $SDE/install

# all 10 binaries present and fresh?
ls -lh ~/dainius/cpp_{lazy,traditional}_bf*_cms256x1024/*_cp
```

## Common setup on hotpot (once per shell)

```bash
ssh dgelzini@hotpot.win.tue.nl

# point at the LEGACY-pcap version of the chunk (Click can't read pcapng)
PCAP=/home2/dgelzini/chunks/130000_chunk5M/chunk_00000_legacy.pcap
RATE=2Gbps
```

**One-shot pcapng → legacy pcap conversion** (only needed once per chunk, or skip if the `_legacy.pcap` file already exists):

```bash
editcap -F pcap \
  /home2/dgelzini/chunks/130000_chunk5M/chunk_00000_20190117140000.pcap \
  /home2/dgelzini/chunks/130000_chunk5M/chunk_00000_legacy.pcap
```

Sanity check:
```bash
capinfos -c $PCAP    # expect "Number of packets: 5,000 k"
# A pcapng file shows "Packet size limit: inferred:..."; a legacy pcap shows a fixed snaplen.
```

Replay command (identical for every variant). The script's variable names are `trace` (NOT `PCAP`) and `replay_count` (NOT `LIMIT`). There is no `LIMIT` variable; only `replay_count=1` stops the script after one pass through the pcap. Without it the script loops forever on its hardcoded default pcap.

```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=$PCAP RATE=$RATE replay_count=1
```

Click reports `SENT PKTS: 5000000` and `SEND RATE: <bps>` when finished. The actual send rate is typically higher than `$RATE` (e.g. ~3.3 Gbps was observed for `RATE=2Gbps`), so the replay completes in ~2-3 s rather than the 20 s the rate would suggest. The `--epoch 20` on the CP is still the right value: it just gives the CP enough wallclock to digest the burst plus a margin.

## Known IDs

All 10 variants (both lazy and traditional, all 5 BF sizes) share the same register IDs:
- `BF_IDS=2338372543,2333775667,2347111112`
- `CMS_IDS=2346354927,2339499036,2335880110`

Confirmed empirically by running `print_ids.py` on lazy_bf2m, lazy_bf1m, lazy_bf524k, and traditional_bf131k — all four returned identical IDs. The register names in the P4 (`SwitchIngress.bf_0`, `cms_0`, etc.) are the same across variants, and `bf-p4c` assigns IDs from those names, so the IDs are stable.

If a future variant returns different IDs, just rerun `print_ids.py` for that one.

## Stop switchd: Ctrl+\ (SIGQUIT), not Ctrl+C

Ctrl+C can leave a zombie `bf_switchd` holding port 9999. Use Ctrl+\ to stop cleanly. If a zombie is stuck, `sudo killall bf_switchd` (but check whose process it is first on the shared switch).

## Sanity check after each CP exit

```bash
grep -E "Resolved by Alg|Sub-sketch buckets|cms_[012] :" /tmp/$VARIANT.log
```

Expected on a clean run:
- `cms_0 / cms_1 / cms_2` row sums all roughly equal (within counter-saturation noise on the heaviest variant). Wildly unequal sums (e.g. one row much lower) usually means the replay sent more packets than expected and counter saturation hit cms_0 only.
- `exact:` buckets should be 256 / 256 for the lazy variants at this load factor. Alg6 firing means the bucket load went above the paper's `c* = 0.918` threshold (won't happen at 256 buckets / 5M packets).
- `Resolved by Alg5` should be in the tens of percent for lazy and similar for traditional; if it's ~0%, the new dispatch isn't running (binary on the switch is stale — `make clean && make` and redeploy).

---

## Block 1 — lazy_bf131k_cms256x1024

**Terminal A (switch):**
```bash
$SDE/run_switchd.sh -p lazy_bf131k_cms256x1024
```

**Terminal B (switch):**
```bash
bfshell
bfrt_python /home/onie/dainius/cpp_lazy_bf131k_cms256x1024/setup_table.py
# Ctrl+D

mkdir -p ~/results_lazy_vs_traditional_bf/lazy_bf131k_cms256x1024
export BF_IDS=2338372543,2333775667,2347111112
export CMS_IDS=2346354927,2339499036,2335880110

~/dainius/cpp_lazy_bf131k_cms256x1024/lazy_bf131k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/lazy_bf131k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/lazy_bf131k.log
```

**Hotpot:** run the replay command.

After CP exits, Ctrl+\ switchd in A.

---

## Block 2 — lazy_bf262k_cms256x1024

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf262k_cms256x1024
```

**Terminal B:**
```bash
bfshell
bfrt_python /home/onie/dainius/cpp_lazy_bf262k_cms256x1024/setup_table.py
# Ctrl+D

mkdir -p ~/results_lazy_vs_traditional_bf/lazy_bf262k_cms256x1024
export BF_IDS=2338372543,2333775667,2347111112
export CMS_IDS=2346354927,2339499036,2335880110

~/dainius/cpp_lazy_bf262k_cms256x1024/lazy_bf262k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/lazy_bf262k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/lazy_bf262k.log
```

**Hotpot:** replay. Ctrl+\ switchd in A.

---

## Block 3 — lazy_bf524k_cms256x1024

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf524k_cms256x1024
```

**Terminal B:**
```bash
bfshell
bfrt_python /home/onie/dainius/cpp_lazy_bf524k_cms256x1024/setup_table.py
# Ctrl+D

mkdir -p ~/results_lazy_vs_traditional_bf/lazy_bf524k_cms256x1024
export BF_IDS=2338372543,2333775667,2347111112
export CMS_IDS=2346354927,2339499036,2335880110

~/dainius/cpp_lazy_bf524k_cms256x1024/lazy_bf524k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/lazy_bf524k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/lazy_bf524k.log
```

**Hotpot:** replay. Ctrl+\ switchd.

---

## Block 4 — lazy_bf1m_cms256x1024

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf1m_cms256x1024
```

**Terminal B:**
```bash
bfshell
bfrt_python /home/onie/dainius/cpp_lazy_bf1m_cms256x1024/setup_table.py
# Ctrl+D

mkdir -p ~/results_lazy_vs_traditional_bf/lazy_bf1m_cms256x1024
export BF_IDS=2338372543,2333775667,2347111112
export CMS_IDS=2346354927,2339499036,2335880110

~/dainius/cpp_lazy_bf1m_cms256x1024/lazy_bf1m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/lazy_bf1m_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/lazy_bf1m.log
```

**Hotpot:** replay. Ctrl+\ switchd.

---

## Block 5 — lazy_bf2m_cms256x1024

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
# Ctrl+D

mkdir -p ~/results_lazy_vs_traditional_bf/lazy_bf2m_cms256x1024
export BF_IDS=2338372543,2333775667,2347111112
export CMS_IDS=2346354927,2339499036,2335880110

~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/lazy_bf2m_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/lazy_bf2m.log
```

**Hotpot:** replay. Ctrl+\ switchd.

---

## Block 6 — traditional_bf131k_cms256x1024

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf131k_cms256x1024
```

**Terminal B:**
```bash
bfshell
bfrt_python /home/onie/dainius/cpp_traditional_bf131k_cms256x1024/setup_table.py
# Ctrl+D

mkdir -p ~/results_lazy_vs_traditional_bf/traditional_bf131k_cms256x1024
export BF_IDS=2338372543,2333775667,2347111112
export CMS_IDS=2346354927,2339499036,2335880110

~/dainius/cpp_traditional_bf131k_cms256x1024/traditional_bf131k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/traditional_bf131k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/traditional_bf131k.log
```

**Hotpot:** replay. Ctrl+\ switchd.

---

## Block 7 — traditional_bf262k_cms256x1024

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf262k_cms256x1024
```

**Terminal B:**
```bash
bfshell
bfrt_python /home/onie/dainius/cpp_traditional_bf262k_cms256x1024/setup_table.py
# Ctrl+D

mkdir -p ~/results_lazy_vs_traditional_bf/traditional_bf262k_cms256x1024
export BF_IDS=2338372543,2333775667,2347111112
export CMS_IDS=2346354927,2339499036,2335880110

~/dainius/cpp_traditional_bf262k_cms256x1024/traditional_bf262k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/traditional_bf262k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/traditional_bf262k.log
```

**Hotpot:** replay. Ctrl+\ switchd.

---

## Block 8 — traditional_bf524k_cms256x1024

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf524k_cms256x1024
```

**Terminal B:**
```bash
bfshell
bfrt_python /home/onie/dainius/cpp_traditional_bf524k_cms256x1024/setup_table.py
# Ctrl+D

mkdir -p ~/results_lazy_vs_traditional_bf/traditional_bf524k_cms256x1024
export BF_IDS=2338372543,2333775667,2347111112
export CMS_IDS=2346354927,2339499036,2335880110

~/dainius/cpp_traditional_bf524k_cms256x1024/traditional_bf524k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/traditional_bf524k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/traditional_bf524k.log
```

**Hotpot:** replay. Ctrl+\ switchd.

---

## Block 9 — traditional_bf1m_cms256x1024

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf1m_cms256x1024
```

**Terminal B:**
```bash
bfshell
bfrt_python /home/onie/dainius/cpp_traditional_bf1m_cms256x1024/setup_table.py
# Ctrl+D

mkdir -p ~/results_lazy_vs_traditional_bf/traditional_bf1m_cms256x1024
export BF_IDS=2338372543,2333775667,2347111112
export CMS_IDS=2346354927,2339499036,2335880110

~/dainius/cpp_traditional_bf1m_cms256x1024/traditional_bf1m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/traditional_bf1m_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/traditional_bf1m.log
```

**Hotpot:** replay. Ctrl+\ switchd.

---

## Block 10 — traditional_bf2m_cms256x1024

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
# Ctrl+D

mkdir -p ~/results_lazy_vs_traditional_bf/traditional_bf2m_cms256x1024
export BF_IDS=2338372543,2333775667,2347111112
export CMS_IDS=2346354927,2339499036,2335880110

~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/traditional_bf2m_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/traditional_bf2m.log
```

**Hotpot:** replay. Ctrl+\ switchd.

---

## After all 10 — pull, summarise, plot (on VM)

```bash
# pull CSVs
for v in lazy_bf{131k,262k,524k,1m,2m}_cms256x1024 \
         traditional_bf{131k,262k,524k,1m,2m}_cms256x1024; do
    mkdir -p /home/student/Desktop/flowlidar/results/lazy_vs_traditional_bf/$v
    scp onie.two.hotpot:~/results_lazy_vs_traditional_bf/$v/est_chunk_00000.csv \
        /home/student/Desktop/flowlidar/results/lazy_vs_traditional_bf/$v/
done

# build summary  (compare.py uses POSITIONAL args: truth, estimate, summary)
cd /home/student/Desktop/flowlidar
cp results/6_3/chunk0_truth.csv results/lazy_vs_traditional_bf/
> results/lazy_vs_traditional_bf/summary_chunk0.csv
for v in lazy_bf{131k,262k,524k,1m,2m}_cms256x1024 \
         traditional_bf{131k,262k,524k,1m,2m}_cms256x1024; do
    python3 evaluation/harness/compare.py \
      results/lazy_vs_traditional_bf/chunk0_truth.csv \
      results/lazy_vs_traditional_bf/$v/est_chunk_00000.csv \
      results/lazy_vs_traditional_bf/summary_chunk0.csv \
      --meta variant=$v,pcap=130000,chunk=00000
done

# side-by-side old vs new
echo "=== old commit 8b86bc8 ==="
awk -F',' 'NR>=2 {printf "%-45s ARE=%.4f cov=%.4f exact=%.4f\n", $1, $14, $9, $15}' \
  results/6_3/summary_chunk0.csv | sort
echo "=== new ==="
awk -F',' 'NR>=2 {printf "%-45s ARE=%.4f cov=%.4f exact=%.4f\n", $1, $14, $9, $15}' \
  results/lazy_vs_traditional_bf/summary_chunk0.csv | sort

# plots
cp results/6_3/plot_lazy_vs_trad.py results/lazy_vs_traditional_bf/
python3 results/lazy_vs_traditional_bf/plot_lazy_vs_trad.py
ls -lh results/lazy_vs_traditional_bf/plots/
```
