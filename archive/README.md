# archive/

All early prototype iterations (P4 + Python control plane) live here for
reference. Active work lives in the top-level `cpp_*` directories.

## What's in here

| Subdir | What it was |
|--------|-------------|
| `prototype1/` | Build-pipeline check + IPv4 LPM forwarding |
| `prototype2/` | Standard Bloom Filter (k=3, m=128K) + digest |
| `prototype3/` | BF + Count-Min Sketch (k=3, m=1024, 16-bit) + epoch report |
| `prototype4/` | Lazy-update BF (Algorithm 2) + conditional CMS |
| `prototype5/` | Control-plane equation solver (§3.4 from the paper) |
| `prototype6/` | Master-hash sub-sketch CMS |
| `prototype7/` | Doubled, then 4×-grown BF + distinct hash poly per row |
| `prototype8/` | Traditional BF baseline (single digest per visible flow) |
| `prototype9/` | Hybrid Python+C++ CP attempt — abandoned because bfrt-grpc only allows one client per P4 |
| `hardware_version{,2,3,4}/` | Real-Tofino-1 ports of prototypes 5/6/7/8 with SDE 9.11.0 paths and `pipe_id=1` |

Each subdir has its own `results.md` (where applicable) and notes.

## Why these were retired

All used the Python `bfrt_grpc.client`, which drops digests under sustained
backbone-rate load. Coverage numbers in their `results.md` files
*understate* what the data plane actually delivers — see
`../cpp_lazy_bf131k_cms64x1024/results.md` for the corrected story.

## P4 includes

The P4 files in here used to use `#include "../common/headers.p4"`. After
moving to `archive/`, the includes were updated to
`"../../common/headers.p4"` so they still build from the archived location.

## Naming convention going forward

New prototype directories at the repo root use:

```
cpp_<bf_type>_bf<bf_size>_cms<sub_sketches>x<cols_per_sub_sketch>
```

e.g. `cpp_lazy_bf131k_cms64x1024`, `cpp_traditional_bf524k_cms32x2048`, etc.
