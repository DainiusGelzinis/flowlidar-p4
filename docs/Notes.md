# This is the document for user to be prepare for the next thesis meeting and save some details

Your supervisor is pointing at a concrete technical challenge that sits between the
  data plane and the equation solver. Let me break it down.

  ---
  What needs to be queried

  At epoch end, the control plane needs two things from the data plane:

  ┌────────────────────────────────┬────────────────────────────────────────────────┐
  │              What              │                      Why                       │
  ├────────────────────────────────┼────────────────────────────────────────────────┤
  │ BF register arrays             │ BF preprocessing: check if a flow was fully    │
  │ (bf_0..bf_3)                   │ inserted or not                                │
  ├────────────────────────────────┼────────────────────────────────────────────────┤
  │ CMS register arrays (all       │ Build the vector b for the equation solver Ax  │
  │ counter rows)                  │ = b                                            │
  └────────────────────────────────┴────────────────────────────────────────────────┘

  ---
  Why it's non-trivial — the hash replication problem

  In the data plane, the BF and CMS use hardware CRC hash units to compute which
  register index a flow maps to. For example:

  Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly0) hash0;
  bit<17> idx = hash0.get({src_ip, dst_ip, proto, sport, dport});
  bf_0[idx]  // this is what gets set/read

  To query the BF or build matrix A for the solver, the control plane Python code must
  compute the exact same hash values for a given 5-tuple — otherwise you read the wrong
  register indices.

  This means you need to:

  1. Replicate each CRC32 polynomial in Python with matching parameters (same
  polynomial, same init value, same XOR, same bit-reversal settings)
  2. Feed the same 5-tuple field ordering and bit widths
  3. Get the same 17-bit result

  Python's crcmod library can do this, but the parameters must match exactly what was
  compiled into the P4.

  ---
  How to read registers via bfrt

  Two patterns — depending on what you need:

  Read a specific index (e.g. query one flow against the BF):

# In bfrt_python or via gRPC

  resp = p4.SwitchIngress.bf_0.entry_get(
      [bf_0.make_key([gc.KeyTuple('$REGISTER_INDEX', idx)])],
      {'from_hw': True}
  )

  Dump the entire array (e.g. read all CMS counters at epoch end):
  for entry, _in p4.SwitchIngress.cms_row0.entry_get(
          [], flags={'from_hw': True}):
      data = entry.to_dict()
      counters[data['$REGISTER_INDEX']] = data['cms_row0.f1']

  The from_hw: True flag is important — it reads from hardware registers, not the cached
   software copy.

  ---
  The atomicity / timing concern

  Registers are read entry-by-entry over gRPC. While you're reading, packets are still
  arriving and updating counters. This means your snapshot may be inconsistent — some
  counters read before a packet arrived, some after.

  Options to handle this:

- Pause traffic (only realistic in simulation/testing)
- Read fast enough that the inconsistency is negligible
- Two-phase epoch: stop updating CMS first (swap to a new epoch in hardware), then
  read the old one — the paper uses epoch reset for this

  ---
  In summary — what your supervisor likely wants you to know

  1. What you query: BF register arrays (for BF preprocessing) and CMS register arrays
  (for the equation solver)
  2. How you query it: bfrt register reads via entry_get with from_hw: True
  3. The hash replication problem: you must reproduce the P4 CRC hashes in Python to
  know which indices to read for a given flow
  4. When you query: at epoch boundary, ideally after stopping updates to the structure
  being read

  The hash replication is the part most likely to cause bugs — it's easy to get subtly
  wrong (field ordering, endianness, bit width truncation) and produce silently
  incorrect results.
