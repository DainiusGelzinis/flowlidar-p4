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
std::vector<double> lsqr(const std::vector<double>& M, int m_rows, int k_cols,
                          const std::vector<double>& b,
                          int max_iter, double tol) {
    std::vector<double> x(k_cols, 0.0);
    if (k_cols == 0 || m_rows == 0) return x;

    std::vector<double> u = b;
    double beta = 0.0;
    for (double v : u) beta += v * v;
    beta = std::sqrt(beta);
    if (beta < 1e-30) return x;
    const double beta0 = beta;
    for (auto& uu : u) uu /= beta;

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
        if (beta < 1e-30) break;
        for (auto& uu : u) uu /= beta;

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

        double rho = std::sqrt(rho_bar * rho_bar + beta * beta);
        double cs = rho_bar / rho;
        double sn = beta / rho;
        double theta = sn * alpha;
        rho_bar = -cs * alpha;
        double phi = cs * phi_bar;
        phi_bar = sn * phi_bar;

        double phi_over_rho   = phi / rho;
        double theta_over_rho = theta / rho;
        for (int c = 0; c < k_cols; ++c) {
            x[c] += phi_over_rho * w[c];
            w[c]  = v[c] - theta_over_rho * w[c];
        }

        if (std::fabs(phi_bar) < tol * beta0) break;
    }

    return x;
}

// Algorithm 6 from the FlowLiDAR paper.
std::vector<double> algorithm6(const std::vector<double>& A,
                                const std::vector<double>& b,
                                int m, int n, int n_rank) {
    std::vector<double> x(n, 0.0);
    std::vector<bool>   fixed(n, false);
    int free_remaining = n - n_rank;
    if (free_remaining < 0) free_remaining = 0;

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

    std::vector<int> unfixed;
    for (int j = 0; j < n; ++j) if (!fixed[j]) unfixed.push_back(j);
    int k = (int)unfixed.size();
    if (k == 0) return x;

    std::vector<double> b_red(m);
    for (int i = 0; i < m; ++i) {
        double v = b[i];
        for (int j = 0; j < n; ++j)
            if (fixed[j] && A[i * n + j] > 0.5) v -= x[j];
        b_red[i] = v;
    }

    std::vector<double> Ar((size_t)m * k);
    for (int i = 0; i < m; ++i)
        for (int c = 0; c < k; ++c)
            Ar[i * k + c] = A[i * n + unfixed[c]];

    const int    lsqr_max_iter = std::min(m, k) + 20;
    const double lsqr_tol      = 1e-8;
    std::vector<double> x_sub = lsqr(Ar, m, k, b_red, lsqr_max_iter, lsqr_tol);

    for (int c = 0; c < k; ++c) x[unfixed[c]] = x_sub[c];
    return x;
}

}

SolverResult solve_bucket(
    const std::vector<FlowKey>& flows,
    const std::vector<std::array<std::pair<int, uint32_t>, 3>>& flow_cells,
    const std::array<std::vector<uint64_t>, 3>& cms_rows) {

    SolverResult out;
    int n = (int)flows.size();
    out.cms_estimate.assign(n, 0);
    if (n == 0) return out;

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

    std::vector<double> aug((size_t)m * (n + 1), 0.0);
    for (int i = 0; i < m; ++i) {
        for (int j = 0; j < n; ++j) aug[i * (n + 1) + j] = A[i * n + j];
        aug[i * (n + 1) + n] = b[i];
    }
    int rank = gauss_jordan(aug, m, n);

    if (rank == n) {
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

    std::vector<double> x_approx = algorithm6(A, b, m, n, rank);
    for (int j = 0; j < n; ++j) out.cms_estimate[j] = to_count(x_approx[j]);
    out.path  = SolverPath::Algorithm6;
    out.exact = false;
    return out;
}
