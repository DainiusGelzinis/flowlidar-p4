// solver.hpp — sub-sketch CMS equation solver.
//
// For each master-hash sub-sketch bucket the FlowLiDAR control plane has a
// set of visible flows that all hash into that bucket's columns. Each flow
// uses 3 CMS cells (one per row). We can build a linear system
//
//     A · x = b
//
// where:
//   - x is the n-vector of per-flow CMS contributions (= packets - digests)
//   - b is the m-vector of CMS counter values for the cells used by the
//     bucket's flows (one equation per unique (row, cell) tuple)
//   - A is m × n binary (1 if flow j touches that (row, cell), else 0)
//
// Strategy:
//   1. If rank(A) == n  (well-determined or over-determined): solve exactly
//      via Gauss-Jordan on the augmented matrix [A | b].
//   2. Otherwise (under-determined, i.e. more flows than independent cells):
//      fall back to per-flow min(cms_rows). Algorithm 6's "small-equation
//      first" heuristic from the Python CP can be added later.
//
// Per-flow integer count returned by the solver gets clamped to >= 0 and
// rounded to the nearest integer.

#pragma once

#include <cstdint>
#include <map>
#include <utility>
#include <vector>

#include "flow.hpp"

struct SolverResult {
    // Per-flow CMS contribution count (NOT including the digest count).
    // Same indexing as the input `flows` vector.
    std::vector<uint64_t> cms_estimate;
    bool                  exact = false;
};

// Solve one sub-sketch bucket.
// `flows`           : the bucket's visible flows
// `flow_cells`      : for each flow, the 3 (row, cell) tuples it touches.
//                     row is 0/1/2 for cms_0/cms_1/cms_2, cell is 0..65535.
// `cms_rows`        : the 3 fully-read CMS rows (each indexed 0..65535).
//
// Returns per-flow CMS contribution and a flag for whether the system was
// fully determined.
SolverResult solve_bucket(
    const std::vector<FlowKey>& flows,
    const std::vector<std::array<std::pair<int, uint32_t>, 3>>& flow_cells,
    const std::array<std::vector<uint64_t>, 3>& cms_rows);
