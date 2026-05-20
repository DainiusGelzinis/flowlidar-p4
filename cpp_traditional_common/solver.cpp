// solver.cpp — Gauss-Jordan exact solver + Algorithm 6 approximate fallback.

#include "solver.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <map>
#include <numeric>

namespace {

inline uint64_t to_count(double v) {
    if (v < 0.5) return 0;
    return (uint64_t)std::llround(v);
}

// Row-reduce [A | b] in place (m equations, n unknowns; matrix row-major
// of width n+1). Returns the rank. After reduction, leading variables can
// be read directly from the rightmost column of the rows that were
// assigned a pivot (caller scans for them).
int gauss_jordan(std::vector<double>& aug, int m, int n) {
    int rank = 0;
    int col  = 0;
    for (int row = 0; row < m && col < n; ) {
        int    best_r = -1;
        double best_v = 1e-9;
        for (int r = row; r < m; ++r) {
            double v = std::fabs(aug[r * (n + 1) + col]);
            if (v > best_v) { best_v = v; best_r = r; }
        }
        if (best_r < 0) { ++col; continue; }
        if (best_r != row) {
            for (int c = col; c <= n; ++c)
                std::swap(aug[row * (n + 1) + c], aug[best_r * (n + 1) + c]);
        }
        double pv = aug[row * (n + 1) + col];
        for (int c = col; c <= n; ++c) aug[row * (n + 1) + c] /= pv;
        for (int r = 0; r < m; ++r) {
            if (r == row) continue;
            double f = aug[r * (n + 1) + col];
            if (std::fabs(f) < 1e-12) continue;
            for (int c = col; c <= n; ++c)
                aug[r * (n + 1) + c] -= f * aug[row * (n + 1) + c];
        }
        ++rank;
        ++row;
        ++col;
    }
    return rank;
}

// Algorithm 6 from the FlowLiDAR paper.
//
// `A` is m x n (row-major), `b` is m. `n_rank` is the rank of A.
// Returns x of size n: per-flow CMS contribution.
//
// Step A (heuristic / pinning):
//     Sort the m equations by b ascending. For each equation in order, if
//     `free_remaining > 0`, find the columns j with A[eq, j] == 1 that are
//     still unfixed. Assign each such column the value b[eq] / k where k
//     is the number of unfixed columns; mark them fixed. Stop when
//     free_remaining == 0 (we've fixed n - rank columns, so the residual
//     system can be uniquely solved).
//
// Step B (least-squares on the reduced system):
//     Subtract the fixed columns' contributions from b. Solve the reduced
//     system A_red · x_sub = b_red via the normal equations
//     (A_red^T A_red) x_sub = A_red^T b_red, using Gauss-Jordan.
std::vector<double> algorithm6(const std::vector<double>& A,
                                const std::vector<double>& b,
                                int m, int n, int n_rank) {
    std::vector<double> x(n, 0.0);
    std::vector<bool>   fixed(n, false);
    int free_remaining = n - n_rank;
    if (free_remaining < 0) free_remaining = 0;

    // Step A: process equations smallest-b first.
    std::vector<int> order(m);
    std::iota(order.begin(), order.end(), 0);
    std::sort(order.begin(), order.end(),
              [&](int a, int c) { return b[a] < b[c]; });

    for (int eq_i : order) {
        if (free_remaining <= 0) break;
        std::vector<int> cols;
        cols.reserve(8);
        for (int j = 0; j < n; ++j) {
            if (A[eq_i * n + j] > 0.5 && !fixed[j]) cols.push_back(j);
        }
        if (cols.empty()) continue;
        double val = b[eq_i] / (double)cols.size();
        for (int j : cols) {
            x[j]     = val;
            fixed[j] = true;
        }
        free_remaining -= (int)cols.size();
    }

    // Step B: solve the reduced system for unfixed columns.
    std::vector<int> unfixed;
    for (int j = 0; j < n; ++j) if (!fixed[j]) unfixed.push_back(j);
    int k = (int)unfixed.size();
    if (k == 0) return x;

    // b_red = b - A_fixed · x_fixed
    std::vector<double> b_red(m);
    for (int i = 0; i < m; ++i) {
        double v = b[i];
        for (int j = 0; j < n; ++j)
            if (fixed[j] && A[i * n + j] > 0.5) v -= x[j];
        b_red[i] = v;
    }

    // Build A_red as m x k (only unfixed columns).
    std::vector<double> Ar((size_t)m * k);
    for (int i = 0; i < m; ++i)
        for (int c = 0; c < k; ++c)
            Ar[i * k + c] = A[i * n + unfixed[c]];

    // Normal equations: AtA = Ar^T Ar  (k x k),  Atb = Ar^T b_red  (k).
    std::vector<double> AtA((size_t)k * k, 0.0);
    std::vector<double> Atb(k, 0.0);
    for (int c1 = 0; c1 < k; ++c1) {
        for (int c2 = 0; c2 < k; ++c2) {
            double s = 0.0;
            for (int i = 0; i < m; ++i) s += Ar[i * k + c1] * Ar[i * k + c2];
            AtA[c1 * k + c2] = s;
        }
        double s = 0.0;
        for (int i = 0; i < m; ++i) s += Ar[i * k + c1] * b_red[i];
        Atb[c1] = s;
    }

    // Solve AtA · x_sub = Atb via Gauss-Jordan on [AtA | Atb].
    std::vector<double> aug2((size_t)k * (k + 1), 0.0);
    for (int r = 0; r < k; ++r) {
        for (int c = 0; c < k; ++c) aug2[r * (k + 1) + c] = AtA[r * k + c];
        aug2[r * (k + 1) + k] = Atb[r];
    }
    int sub_rank = gauss_jordan(aug2, k, k);
    (void)sub_rank;  // for normal equations on a full-rank reduced system this == k

    // Read x_sub.  Each row's pivot column gives one variable's value.
    for (int r = 0; r < k; ++r) {
        for (int c = 0; c < k; ++c) {
            if (std::fabs(aug2[r * (k + 1) + c] - 1.0) < 1e-9) {
                bool only_pivot = true;
                for (int rr = 0; rr < k && only_pivot; ++rr) {
                    if (rr == r) continue;
                    if (std::fabs(aug2[rr * (k + 1) + c]) > 1e-9) only_pivot = false;
                }
                if (only_pivot) {
                    x[unfixed[c]] = aug2[r * (k + 1) + k];
                    break;
                }
            }
        }
    }
    return x;
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

    // Build (row, cell) -> equation_index map.
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

    // Build A (m x n) and b (m).
    std::vector<double> A((size_t)m * n, 0.0);
    std::vector<double> b(m, 0.0);
    for (const auto& kv : cell_to_eq) {
        int eq_i = kv.second;
        int row  = kv.first.first;
        uint32_t cell = kv.first.second;
        b[eq_i] = (double)cms_rows[row][cell];
    }
    for (int j = 0; j < n; ++j) {
        for (const auto& rc : flow_cells[j]) {
            int eq_i = cell_to_eq[rc];
            A[eq_i * n + j] = 1.0;
        }
    }

    // Step 1: try exact solve via Gauss-Jordan on a copy of [A | b].
    std::vector<double> aug((size_t)m * (n + 1), 0.0);
    for (int i = 0; i < m; ++i) {
        for (int j = 0; j < n; ++j) aug[i * (n + 1) + j] = A[i * n + j];
        aug[i * (n + 1) + n] = b[i];
    }
    int rank = gauss_jordan(aug, m, n);

    // Exact path is correct only for a SQUARE full-rank system (m == n,
    // rank == n). With m > n the system is over-determined: in noise-free
    // conditions the leading n rows give the true solution and the
    // remaining m - n equations are redundant, but with hidden-flow
    // contamination of the CMS cells those extra equations make the
    // system inconsistent. Reading the pivot solution then produces
    // negative residuals on some flows which to_count() clamps to 0,
    // grossly inflating the total. For m > n we therefore route through
    // Algorithm 6 step B, which uses least squares via the normal
    // equations and distributes the residual properly across all flows.
    if (rank == n && m == n) {
        // Exact: read solution from the row-reduced augmented matrix.
        for (int r = 0; r < m && r < n; ++r) {
            int pcol = -1;
            for (int c = 0; c < n; ++c) {
                if (std::fabs(aug[r * (n + 1) + c] - 1.0) < 1e-9) {
                    bool only = true;
                    for (int rr = 0; rr < m && only; ++rr) {
                        if (rr == r) continue;
                        if (std::fabs(aug[rr * (n + 1) + c]) > 1e-9) only = false;
                    }
                    if (only) { pcol = c; break; }
                }
            }
            if (pcol >= 0) out.cms_estimate[pcol] = to_count(aug[r * (n + 1) + n]);
        }
        out.path  = SolverPath::Exact;
        out.exact = true;
        return out;
    }

    // Step 2: under-determined (rank < n) OR over-determined (m > n) —
    // Algorithm 6 approximate. When rank == n it pins zero vars in
    // step A and runs least squares in step B on all n flows.
    std::vector<double> x_approx = algorithm6(A, b, m, n, rank);
    for (int j = 0; j < n; ++j) out.cms_estimate[j] = to_count(x_approx[j]);
    out.path  = SolverPath::Algorithm6;
    out.exact = false;
    return out;
}
