# cpp_lazy_common/ — shared C++ control plane for the lazy-BF variants

Single source-of-truth for the pure-C++ FlowLiDAR control plane used by
every `cpp_lazy_bf*_cms64x1024/` variant. Variant directories never copy
this code — they include `Makefile.core` and pass three Make variables.

## File map

```
cpp_lazy_common/
├── Makefile.core      shared build rules (proto stub, gRPC stubs, link)
├── main.cpp           entrypoint + per-epoch loop + Algs 4/5 + solver dispatch
├── bfrt_client.{hpp,cpp}  gRPC wrapper: subscribe/BIND, register I/O, digests
├── crc.hpp            CRC-32 family (bf0/1/2, master, cms0/1/2)
├── flow.hpp           5-tuple FlowKey + byte packer
├── solver.{hpp,cpp}   sub-sketch equation solver (Exact / Algorithm 6 / Skipped)
└── README.md          this file
```

## How a variant uses it

The variant's `Makefile` is a 4-line stub:

```make
BF_SIZE := 131072
P4_NAME := lazy_bf
BINARY  := lazy_bf_cp
include ../cpp_lazy_common/Makefile.core
```

`Makefile.core` then:
- Compiles `main.cpp` with `-DLAZY_BF_SIZE=$(BF_SIZE) -DLAZY_P4_NAME=\"$(P4_NAME)\"`.
- Inline-generates the `google.rpc.Status` proto stub into
  `build_gen/proto/google/rpc/status.proto`.
- Generates `bfruntime.pb.cc` / `bfruntime.grpc.pb.cc` next to it.
- Links the binary into the variant directory.

So a fresh variant for, say, 524 K BF cells is a 6-line directory:

```
cpp_lazy_bf524k_cms64x1024/
├── lazy_bf524k.p4
├── build.sh
├── setup_table.py
└── Makefile        (BF_SIZE := 524288 / P4_NAME := lazy_bf524k / BINARY := lazy_bf524k_cp)
```

## Why a separate `cpp_traditional_common/`

Traditional BF can't run Algs 4/5 (every packet flips all 3 BF rows, so
BF state alone can't distinguish a 1-pkt mouse from an N-pkt elephant).
Rather than `#ifdef` the per-flow loop, the two cores live as separate
trees with their own `main.cpp`. They share the proto stub, CRCs, and
solver pattern in spirit but each compiles independently.
