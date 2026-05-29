# Remaining experiments — prioritized

After E8 (traffic load sweep) finishes, here's what's left and how to prioritise.

## Tier 1: free or near-free (do these first)

### §6.6 Per-class error breakdown ⭐

- Uses your **existing** E8 and lazy_vs_traditional CSVs
- Compute per-flow-size-class AAE/ARE: 1pkt, 2pkt, 3pkt, 4-10, 11-100, 101+
- The `compare.py` output already has these columns (`AAE_1pkt`, `ARE_101plus`, etc.)
- **Plotting only — zero new switch runs**
- Tells the story "alg4 catches mice with zero error; elephants are where alg6 helps"
- ~2 hours of Python plotting

### §6.7 Tofino resources table ⭐

- Parse `/tmp/build_<name>/<name>/tofino/pipe/logs/resources.json` for each compiled variant on the switch
- Extract: SRAM blocks per stage, total SRAM, MAU stages used, hash distribution units
- **Zero new runs — just data extraction**
- Tells the deployment story: "fits in ~14% of one Tofino 1 pipe"
- ~1 hour of script writing

## Tier 2: small cost, distinct value

### §6.5 CMS bucket sweep at fixed memory ⭐

- 3 runs at lazy_bf1m_cms256x1024 (already have!), cms128x2048 (need build), cms64x4096 (have)
- All same total CMS memory (~786K cells)
- Tests: "given fixed memory budget, does layout matter?"
- Probably 2-3 hours including the missing build
- New story angle: separates "memory budget" from "layout choice"

### Multi-chunk variance ⭐

- Rerun the E8 sweep (or just the most-interesting 3-4 loads) on chunks 1 and 2 of CAIDA 130000 (chunks already exist on hotpot)
- Adds error bars / variance to claims
- 4-6 hours of switch time
- Big credibility boost — reviewers love variance

## Tier 3: medium cost, supports specific claims

### §6.4 CMS column sweep at fixed buckets

- cms64x1024, cms64x2048, cms64x4096 (need build) at lazy_bf1m
- Tests: "more cols per row at fixed buckets = how much better?"
- 3 runs + 1 build
- **Mostly redundant with §6.5 — pick one or the other**

### Alg6 over-counting fix

- The bug we identified — step A doesn't subtract pinned contributions before computing `b/n`
- ~10 lines in `solver.cpp` to fix (see `project_alg6_overcounting.md` in memory)
- Re-run heaviest E8 points to validate (e.g. 16M, 32M lazy + trad)
- Adds a "we improved on paper's alg6 by fixing the pinning over-count" finding
- 1 hour code + 4-6 hours rerun

### Counter saturation analysis

- Currently your CMS cells are 16-bit (max 65535). At 32M load, do any cells saturate?
- Count cells at value 65535 in the bulk-read summary
- Affects elephant accuracy (alg4/alg6 can't recover saturated cells)
- Zero new runs; just analysis script on existing CSVs
- 1 hour

## Tier 4: high cost, key thesis claim

### §6.2 Python vs C++ CP comparison

- Supports "we built a C++ CP because Python can't keep up"
- Requires the Python CP to actually work end-to-end
- 7 speeds × 2 CPs × 3 reps = 42 runs
- 5+ hours of switch time + port work
- Critical for the C++ implementation chapter justification

## Tier 5: nice-to-have, low impact

### Cross-trace reproduction (paper-style)

- Run on equinix-nyc 13:30:00 or 14:00:00 (different traces)
- Would let you show "our results hold across traces, not just the 13:00 one"
- 4-6 hours per trace

### k=4 P4 variant

- Match paper's k=4 exactly
- Requires P4 stage redesign + new BF/CMS row
- 1-2 days of work
- Probably not worth it for BEP

---

## Recommended order of operations

Given E8 finishes today/tomorrow:

1. **Per-class breakdown** (free, ~2hrs) — solidifies chapter
2. **Resources table** (free, ~1hr) — solidifies chapter
3. **Multi-chunk for E8** (4-6hrs switch, big credibility) — IF time permits
4. **Alg6 over-counting fix + rerun heavy loads** (~5hrs) — addresses a real finding
5. **§6.5 CMS layout sweep** (~3hrs) — adds design-space dimension

**Skip §6.2, §6.4, cross-trace, k=4** for BEP scope unless you have weeks.

## What the eval chapter looks like after items 1–3

- **C3**: Lazy vs Standard BF sweep (done — lazy_vs_traditional_bf)
- **E8**: Traffic load scaling (almost done — traffic_load_test)
- **T4**: Per-class breakdown (free — from existing CSVs)
- **T5**: Tofino resources (free — from compile outputs)
- **Variance bars** on E8 (if multi-chunk done)

That's a solid BEP-scope evaluation chapter — 4-5 figures + 2 tables, all defensible.
