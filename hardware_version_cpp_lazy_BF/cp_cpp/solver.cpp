// solver.cpp — Gauss-Jordan implementation for sub-sketch CMS systems.

#include "solver.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>

namespace {

// Round and clamp to non-negative integer.
inline uint64_t to_count(double v) {
    if (v < 0.5) return 0;
    return (uint64_t)std::llround(v);
}

// Row-reduce [A | b] in place (m equations, n unknowns; matrix is row-major
// of width n+1). Returns the rank. After reduction, leading variables can
// be read directly from the rightmost column of the rows that were assigned
// a pivot.
int gauss_jordan(std::vector<double>& aug, int m, int n) {
    int rank = 0;
    std::vector<int> pivot_col_of_row(m, -1);
    int col = 0;
    for (int row = 0; row < m && col < n; ) {
        // Find largest pivot in this column at or below `row`.
        int    best_r = -1;
        double best_v = 1e-9;
        for (int r = row; r < m; ++r) {
            double v = std::fabs(aug[r * (n + 1) + col]);
            if (v > best_v) { best_v = v; best_r = r; }
        }
        if (best_r < 0) { ++col; continue; }   // column is all zero, skip
        if (best_r != row) {
            for (int c = col; c <= n; ++c)
                std::swap(aug[row * (n + 1) + c], aug[best_r * (n + 1) + c]);
        }
        // Normalise pivot row.
        double pv = aug[row * (n + 1) + col];
        for (int c = col; c <= n; ++c) aug[row * (n + 1) + c] /= pv;
        // Eliminate in every other row.
        for (int r = 0; r < m; ++r) {
            if (r == row) continue;
            double f = aug[r * (n + 1) + col];
            if (std::fabs(f) < 1e-12) continue;
            for (int c = col; c <= n; ++c)
                aug[r * (n + 1) + c] -= f * aug[row * (n + 1) + c];
        }
        pivot_col_of_row[row] = col;
        ++rank;
        ++row;
        ++col;
    }
    return rank;
}

}  // namespace

SolverResult solve_bucket(
    const std::vector<FlowKey>& flows,
    const std::vector<std::array<std::pair<int, uint32_t>, 3>>& flow_cells,
    const std::array<std::vector<uint64_t>, 3>& cms_rows) {

    SolverResult out;
    int n = (int)flows.size();
    out.cms_estimate.assign(n, 0);
    if (n == 0) return out;

    // Step 1: collect the unique (row, cell) -> equation_index mapping.
    std::map<std::pair<int, uint32_t>, int> cell_to_eq;
    for (const auto& cells : flow_cells) {
        for (const auto& rc : cells) {
            if (cell_to_eq.find(rc) == cell_to_eq.end()) {
                int idx = (int)cell_to_eq.size();
                cell_to_eq[rc] = idx;
            }
        }
    }
    int m = (int)cell_to_eq.size();

    // Step 2: build augmented matrix [A | b] in row-major form, width n+1.
    std::vector<double> aug((size_t)m * (n + 1), 0.0);
    for (const auto& kv : cell_to_eq) {
        int eq_i = kv.second;
        int row  = kv.first.first;
        uint32_t cell = kv.first.second;
        aug[eq_i * (n + 1) + n] = (double)cms_rows[row][cell];
    }
    for (int j = 0; j < n; ++j) {
        for (const auto& rc : flow_cells[j]) {
            int eq_i = cell_to_eq[rc];
            aug[eq_i * (n + 1) + j] = 1.0;
        }
    }

    // Step 3: Gauss-Jordan reduce.
    int rank = gauss_jordan(aug, m, n);

    if (rank == n) {
        // Well-determined — read solution from each pivot row.
        // After Gauss-Jordan with row j's pivot in column j, x[j] = rhs of row j.
        // (Pivot column may not equal row index, so re-scan for the pivot col.)
        for (int r = 0; r < m && r < n; ++r) {
            // Find the column containing this row's pivot (= 1 entry).
            int pcol = -1;
            for (int c = 0; c < n; ++c) {
                if (std::fabs(aug[r * (n + 1) + c] - 1.0) < 1e-9) {
                    bool is_only = true;
                    for (int rr = 0; rr < m && is_only; ++rr) {
                        if (rr == r) continue;
                        if (std::fabs(aug[rr * (n + 1) + c]) > 1e-9) is_only = false;
                    }
                    if (is_only) { pcol = c; break; }
                }
            }
            if (pcol >= 0) out.cms_estimate[pcol] = to_count(aug[r * (n + 1) + n]);
        }
        out.exact = true;
    } else {
        // Under-determined — caller falls back to min(rows) per flow.
        out.exact = false;
    }
    return out;
}
