# cpp_traditional_common/ — shared C++ control plane for traditional-BF variants

Single source-of-truth for the pure-C++ FlowLiDAR control plane used by
every `cpp_traditional_bf*_cms64x1024/` variant. Variant directories
never copy this code — they include `Makefile.core` and pass three Make
variables.

## File map

```
cpp_traditional_common/
├── Makefile.core      shared build rules (proto stub, gRPC stubs, link)
├── main.cpp           entrypoint + per-epoch loop + solver dispatch (no Algs 4/5)
├── bfrt_client.{hpp,cpp}  gRPC wrapper
├── crc.hpp            CRC-32 family
├── flow.hpp           5-tuple FlowKey + byte packer
├── solver.{hpp,cpp}   sub-sketch equation solver (Exact / Algorithm 6 / Skipped)
└── README.md          this file
```

## How a variant uses it

```make
BF_SIZE := 131072
P4_NAME := traditional_bf
BINARY  := traditional_bf_cp
include ../cpp_traditional_common/Makefile.core
```

`Makefile.core` compiles with `-DTRAD_BF_SIZE=$(BF_SIZE)` and
`-DTRAD_P4_NAME=\"$(P4_NAME)\"`.

## Why separate from `cpp_lazy_common/`

Traditional BF can't run Algorithms 4/5: every packet flips all 3 BF
rows, so a 1-pkt mouse leaves identical BF state to an N-pkt elephant.
Every visible flow goes straight to the sub-sketch equation solver
(with `min(cms_rows)` fallback when `n > kColsPerRow`). Rather than
`#ifdef` the per-flow loop in a unified main.cpp, the two cores live as
separate trees that share the build pattern in spirit but compile
independently.

The lazy variants live under `../cpp_lazy_common/`.
