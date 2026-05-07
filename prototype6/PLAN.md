# Prototype 6 — Sub-sketch CMS

Adds the paper's master-hash sub-sketch (sketchlet) partitioning. BF unchanged
from prototype5; CMS goes from 3×1024 cells to 3×65536 cells (64 sub-sketches
of 1024 columns each).

## Stage allocation (Tofino 1, 12 stages)

| Stage | What's there |
|-------|--------------|
| 0–2   | BF hash 0/1/2 (one per stage, unchanged from prototype5) |
| 3–5   | BF register check-and-set (lazy chained, unchanged) |
| 6     | master_hash → sketchlet_offset (Hash<bit<16>> & 0xFC00) |
| 7     | 3 column hashes — one table per hash (avoids 32-bit pathway limit) |
| 8     | 3 cms_idx adds — one table per add (avoids 48-bit pathway limit) |
| 9–11  | CMS register increment (one per row, register is now 65536 cells) |

All 12 stages used. No spare.

## Why so many tables?

Tofino 1's "immediate pathway" (data flowing from Hash/RNG into actions) is
limited to 32 bits per stage. We hit that limit twice:

1. **3 × bit<10> column hashes = 30 bits in one action** failed (compiler
   reported 40 bits, possibly due to cross-stage folding). Splitting into
   3 single-hash tables made the compiler happy.

2. **3 × bit<16> cms_idx adds = 48 bits** definitely fails. Splitting into
   3 single-add tables works.

Each split table is `size=1` with a `default_action` — they're effectively
constants from the data plane's perspective.

## Hash polynomials

Master hash uses **0xF4ACFB13** (CRC32-BZIP2 reflected variant), distinct
from all 6 polynomials used for BF and column hashes.

The hash output is `bit<16>` and we mask with `0xFC00` so the bucket id ends
up in bits [15:10] of `sketchlet_offset` — pre-shifted, ready to add to the
column hash.

## Final CMS index

`cms_idx_i = sketchlet_offset + (bit<16>)col_hash_i`

Since sketchlet_offset has zeros in [9:0] and col_hash fits in [9:0] without
overflow (max 1023), addition is equivalent to bitwise OR — clean bucket
separation, no carries.

## Control plane changes

- New `_master_fn` CRC function in Python
- `master_idx(flow_key)` returns 0..63
- `cms_indices(flow_key)` returns 16-bit indices: `(bucket << 10) | col_hash`
- `solve_cms_system` partitions C_final by master bucket and runs the solver
  64 times (once per non-empty bucket) — each system is small and almost
  certainly full-rank under realistic load

## Expected behavior

At 1 Gbps (our overload point in prototype5):
- Per-bucket flows: ~600 (vs 38K total in prototype5)
- Per-bucket load: 0.6 (vs 37 in prototype5)
- Solver: full-rank exact solutions, no Algorithm 6 fallback

## Build

```
SDE=/home/student/Desktop/open-p4studio bash build.sh
```

Compiles cleanly into 12 stages.
