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
//   1. If rank(A) == n (well-determined or over-determined): solve exactly
//      via Gauss-Jordan on the augmented matrix [A | b].
//   2. If rank(A) < n (under-determined): run Algorithm 6 from the paper.
//      The heuristic part processes equations in ascending b order and
//      distributes b among the still-unfixed flows touching that cell;
//      remaining unfixed flows get values from least-squares on the
//      reduced normal equations.
//   3. The caller can also skip the solver entirely (for buckets where
//      n > columns_per_row) and fall back to per-flow min(cms_rows).
//
// Per-flow integer count returned by the solver gets clamped to >= 0 and
// rounded to the nearest integer.

#pragma once

#include <array>
#include <cstdint>
#include <utility>
#include <vector>

#include "flow.hpp"

enum class SolverPath : uint8_t {
    Exact      = 0,   // Gauss-Jordan, rank == n
    Algorithm6 = 1,   // approximate, rank < n
    Skipped    = 2,   // caller short-circuited; cms_estimate not populated
};

struct SolverResult {
    std::vector<uint64_t> cms_estimate;     // per-flow CMS contribution
    SolverPath            path = SolverPath::Skipped;
    bool                  exact = false;    // convenience: path == Exact
};

SolverResult solve_bucket(
    const std::vector<FlowKey>& flows,
    const std::vector<std::array<std::pair<int, uint32_t>, 3>>& flow_cells,
    const std::array<std::vector<uint64_t>, 3>& cms_rows);
