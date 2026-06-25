// solver.hpp — sub-sketch CMS equation solver.

#pragma once

#include <array>
#include <cstdint>
#include <utility>
#include <vector>

#include "flow.hpp"

enum class SolverPath : uint8_t {
    Exact      = 0,
    Algorithm6 = 1,
    Skipped    = 2,
};

struct SolverResult {
    std::vector<uint64_t> cms_estimate;
    SolverPath            path = SolverPath::Skipped;
    bool                  exact = false;
};

SolverResult solve_bucket(
    const std::vector<FlowKey>& flows,
    const std::vector<std::array<std::pair<int, uint32_t>, 3>>& flow_cells,
    const std::array<std::vector<uint64_t>, 3>& cms_rows);
