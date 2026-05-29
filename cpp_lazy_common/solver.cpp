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

// LSQR (Paige & Saunders 1982) for the over-determined least-squares
// problem: minimize ||M · x - b||_2 where M is m_rows x k_cols (row-major).
// Iterative bidiagonalization-based solver. Each iteration costs two
// matrix-vector products and a few O(k) vector ops, so total cost is
// O(iter * m_rows * k_cols) without forming M^T M. Converges in at most
// rank iterations for well-conditioned systems; typically far fewer.
//
// Returns x of size k_cols. Stops at max_iter or when the residual estimate
// stops changing meaningfully (relative tolerance tol on phi_bar / beta0).
std::vector<double> lsqr(const std::vector<double>& M, int m_rows, int k_cols,
                          const std::vector<double>& b,
                          int max_iter, double tol) {
    std::vector<double> x(k_cols, 0.0);
    if (k_cols == 0 || m_rows == 0) return x;

    // Initialize: u = b / ||b||, beta0 = ||b||
    std::vector<double> u = b;
    double beta = 0.0;
    for (double v : u) beta += v * v;
    beta = std::sqrt(beta);
    if (beta < 1e-30) return x;            // b is zero -> trivial solution
    const double beta0 = beta;
    for (auto& uu : u) uu /= beta;

    // v = M^T * u, alpha = ||v||, v /= alpha
    std::vector<double> v(k_cols, 0.0);
    for (int c = 0; c < k_cols; ++c) {
        double s = 0.0;
        for (int i = 0; i < m_rows; ++i) s += M[i * k_cols + c] * u[i];
        v[c] = s;
    }
    double alpha = 0.0;
    for (double a : v) alpha += a * a;
    alpha = std::sqrt(alpha);
    if (alpha < 1e-30) return x;
    for (auto& a : v) a /= alpha;

    std::vector<double> w = v;
    double phi_bar = beta;
    double rho_bar = alpha;

    std::vector<double> Mv(m_rows, 0.0);
    std::vector<double> Mtu(k_cols, 0.0);

    for (int iter = 0; iter < max_iter; ++iter) {
        // Bidiagonalization step:
        //   u_new = M*v - alpha*u, beta = ||u_new||, u = u_new / beta
        for (int i = 0; i < m_rows; ++i) {
            double s = 0.0;
            for (int c = 0; c < k_cols; ++c) s += M[i * k_cols + c] * v[c];
            Mv[i] = s;
        }
        beta = 0.0;
        for (int i = 0; i < m_rows; ++i) {
            u[i] = Mv[i] - alpha * u[i];
            beta += u[i] * u[i];
        }
        beta = std::sqrt(beta);
        if (beta < 1e-30) break;            // converged
        for (auto& uu : u) uu /= beta;

        //   v_new = M^T*u - beta*v, alpha = ||v_new||, v = v_new / alpha
        for (int c = 0; c < k_cols; ++c) {
            double s = 0.0;
            for (int i = 0; i < m_rows; ++i) s += M[i * k_cols + c] * u[i];
            Mtu[c] = s;
        }
        alpha = 0.0;
        for (int c = 0; c < k_cols; ++c) {
            v[c] = Mtu[c] - beta * v[c];
            alpha += v[c] * v[c];
        }
        alpha = std::sqrt(alpha);
        if (alpha < 1e-30) break;
        for (auto& a : v) a /= alpha;

        // Givens rotation to maintain the QR factorisation implicitly
        double rho = std::sqrt(rho_bar * rho_bar + beta * beta);
        double cs = rho_bar / rho;
        double sn = beta / rho;
        double theta = sn * alpha;
        rho_bar = -cs * alpha;
        double phi = cs * phi_bar;
        phi_bar = sn * phi_bar;

        // x += (phi/rho) * w;  w = v - (theta/rho) * w
        double phi_over_rho   = phi / rho;
        double theta_over_rho = theta / rho;
        for (int c = 0; c < k_cols; ++c) {
            x[c] += phi_over_rho * w[c];
            w[c]  = v[c] - theta_over_rho * w[c];
        }

        // Relative residual estimate: |phi_bar| approximates ||M*x - b||.
        if (std::fabs(phi_bar) < tol * beta0) break;
    }

    return x;
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
//     Subtract the fixed columns' contributions from b, then solve the
//     reduced system A_red * x_sub = b_red via LSQR. LSQR converges to
//     the same minimum-residual solution as the normal equations
//     (A_red^T A_red) x_sub = A_red^T b_red, but without forming A^T A
//     explicitly. This saves O(k^2 * m) on the matrix product and avoids
//     the O(k^3) dense Gauss-Jordan; typical convergence is in far fewer
//     than k iterations for well-conditioned reduced systems.
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

    // Solve the reduced system via LSQR. max_iter capped at the rank bound
    // min(m, k); the relative-residual stop catches convergence earlier in
    // practice.
    const int    lsqr_max_iter = std::min(m, k) + 20;
    const double lsqr_tol      = 1e-8;
    std::vector<double> x_sub = lsqr(Ar, m, k, b_red, lsqr_max_iter, lsqr_tol);

    for (int c = 0; c < k; ++c) x[unfixed[c]] = x_sub[c];
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

    // Exact path: rank(A) == n means the system has a unique solution.
    // For m == n the matrix is square and the pivots give it directly.
    // For m > n the extra equations either reduce to 0 = 0 (consistent,
    // redundant) or to 0 = residual (inconsistent due to hidden-flow
    // contamination of the CMS cells). In both cases reading the pivot
    // rows gives a well-defined value; under contamination it may be
    // inflated, but main.cpp clamps the per-flow estimate to
    // min(cms_rows) afterwards, which matches the paper's worst-case
    // bound (Section 3.4.2).
    if (rank == n) {
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
