# Archive: results before uncapped+parallel rebuild

Snapshot taken 2026-05-27 morning. These results are from earlier CP
versions; preserved here for reference / comparison once the fresh
sweep with the uncapped + OpenMP-parallel CP is done.

## Contents

### Light loads (cap=2000, sequential — first runs from May 26)
- `est_load_1000000.csv`  — 1M lazy, single-CPU sequential, no alg6 firing (exact regime)
- `est_load_2000000.csv`  — 2M lazy, same config
- `est_load_4000000.csv`  — 4M lazy, same config

### 8M lazy comparison set (three different solver configurations)
- `est_load_8000000.csv`               — cap=5000, max_iter=3050, sequential. 3-hour run. ALG6 fired on all 64 buckets. Best-quality alg6 reference.
- `est_load_8000000_cap5k_15min.csv`   — cap=5000, 15-min wall-time gate, sequential. ~16-min run. Only 5/64 buckets got alg6, rest timed out to min. Essentially mirrors min-fallback.
- `est_load_8000000_minfallback.csv`   — cap=3000 (alg6 skips entirely), sequential. ~5-min run. All 64 buckets used min(cms_rows). Pure standard-CMS baseline.

## CP code versions

These files were produced by CPs at various commits between commit
1e4a1e8 (paper-aligned dispatch) and the addition of OpenMP
parallelisation. The exact commit each came from is the one current
at the file's mtime.

## When to use these vs the fresh sweep

Fresh sweep results (in the parent directory after rerun) will be from
the uncapped + parallel CP. Compare:
- Fresh 8M lazy   vs `est_load_8000000.csv`  → should match within precision; new version is just much faster
- Fresh 8M lazy   vs `est_load_8000000_minfallback.csv` → shows what alg6 gets you over the pure-min baseline
