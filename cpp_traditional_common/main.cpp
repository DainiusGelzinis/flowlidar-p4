// main.cpp — shared traditional-BF control plane for the
// cpp_traditional_bf*_cms64x1024 variants. The including Makefile
// (cpp_traditional_common/Makefile.core) injects TRAD_BF_SIZE and
// TRAD_P4_NAME at compile time so the same source builds against any
// (BF size, P4 program name) pair.
//
// What it does:
//   - Connects to bfrt-grpc on localhost:50052
//   - Subscribes + binds to the P4 program named by TRAD_P4_NAME
//   - Reads digests off the StreamChannel into a flow_table. Traditional BF
//     fires at most ONE digest per visible flow (the packet that first sets
//     any of the 3 BF bits) — so flow_table[k] is ~1 for every visible flow.
//   - Every --epoch seconds:
//       * Bulk-reads the 3 BF + 3 CMS register tables.
//       * For each visible flow runs the sub-sketch equation solver
//         (min(cms_rows) fallback when n > kColsPerRow).
//         Per-flow estimate = digest_count + solver/cms estimate.
//       * Prints a one-line summary (flows, digests, est. packets, max load).
//       * Bulk-clears all 6 register tables.
//
// Algorithms 4 / 5 are NOT applicable to a traditional BF: every packet
// flips all 3 BF rows, so a 1-pkt mouse and an N-pkt elephant leave
// identical BF state. We go straight to the solver / min-fallback path.

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <mutex>
#include <string>
#include <vector>

#include "bfrt_client.hpp"
#include "crc.hpp"
#include "flow.hpp"
#include "solver.hpp"

#include <array>
#include <unordered_map>

#ifndef TRAD_BF_SIZE
#error "TRAD_BF_SIZE must be defined at build time (e.g. -DTRAD_BF_SIZE=131072)"
#endif
#ifndef TRAD_P4_NAME
#error "TRAD_P4_NAME must be defined at build time (e.g. -DTRAD_P4_NAME=\"traditional_bf\")"
#endif
#ifndef TRAD_CMS_BUCKETS
#error "TRAD_CMS_BUCKETS must be defined at build time (e.g. -DTRAD_CMS_BUCKETS=64)"
#endif
#ifndef TRAD_CMS_COLS
#error "TRAD_CMS_COLS must be defined at build time (e.g. -DTRAD_CMS_COLS=1024)"
#endif

// Compile-time log2 for power-of-two values.
static constexpr uint32_t ilog2_pow2(uint32_t v) {
    return v <= 1 ? 0 : 1 + ilog2_pow2(v >> 1);
}

static constexpr const char* kAddr      = "localhost:50052";
static constexpr const char* kP4Name    = TRAD_P4_NAME;
static constexpr uint32_t    kDeviceId  = 0;
static constexpr uint32_t    kClientId  = 0;

static constexpr uint32_t    kBfSize      = TRAD_BF_SIZE;       // per-row BF cells
static constexpr uint32_t    kCmsBuckets  = TRAD_CMS_BUCKETS;   // sub-sketch count
static constexpr uint32_t    kColsPerRow  = TRAD_CMS_COLS;      // cols per sub-sketch
static constexpr uint32_t    kCmsSize     = kCmsBuckets * kColsPerRow;
static constexpr uint32_t    kBucketShift = ilog2_pow2(kColsPerRow);
static constexpr uint32_t    kCmsIndexMask = kCmsSize - 1;

static_assert((kColsPerRow & (kColsPerRow - 1)) == 0, "TRAD_CMS_COLS must be a power of 2");
static_assert((kCmsBuckets & (kCmsBuckets - 1)) == 0, "TRAD_CMS_BUCKETS must be a power of 2");

static const std::vector<std::string> kBfNames = {
    "pipe.SwitchIngress.bf_0",
    "pipe.SwitchIngress.bf_1",
    "pipe.SwitchIngress.bf_2"
};
static const std::vector<std::string> kCmsNames = {
    "pipe.SwitchIngress.cms_0",
    "pipe.SwitchIngress.cms_1",
    "pipe.SwitchIngress.cms_2"
};

static std::atomic<bool> g_quit{false};
static void on_sigint(int) { g_quit.store(true); }

struct Config {
    double   epoch_seconds = 30.0;
    uint32_t pipe_id       = 1;        // p4switch2 default
    // Optional explicit overrides — comma-separated 3-ids each. If unset
    // we resolve via the JSON parser in BfrtClient (which sometimes misses
    // cms_2 because of an adjacent "id" field in the bfrt_info JSON).
    std::vector<uint32_t> bf_ids_override;
    std::vector<uint32_t> cms_ids_override;
};

static std::vector<uint32_t> parse_id_csv(const std::string& s) {
    std::vector<uint32_t> out;
    size_t i = 0;
    while (i < s.size()) {
        size_t j = s.find(',', i);
        if (j == std::string::npos) j = s.size();
        out.push_back((uint32_t)std::strtoul(s.substr(i, j - i).c_str(), nullptr, 10));
        i = j + 1;
    }
    return out;
}

static Config parse_args(int argc, char** argv) {
    Config c;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if      (a == "--epoch" && i + 1 < argc) c.epoch_seconds = std::stod(argv[++i]);
        else if (a == "--pipe"  && i + 1 < argc) c.pipe_id = std::atoi(argv[++i]);
        else if (a == "--bf-ids"  && i + 1 < argc) c.bf_ids_override  = parse_id_csv(argv[++i]);
        else if (a == "--cms-ids" && i + 1 < argc) c.cms_ids_override = parse_id_csv(argv[++i]);
        else if (a == "--help" || a == "-h") {
            std::cout << "usage: " << argv[0]
                      << " [--epoch SECS] [--pipe N]"
                      << " [--bf-ids id0,id1,id2] [--cms-ids id0,id1,id2]\n";
            std::exit(0);
        }
    }
    return c;
}

// CMS index helpers (mirror Python control_plane.py exactly).
static uint32_t master_bucket(const std::vector<uint8_t>& bytes) {
    uint32_t h32 = polys::master.compute(bytes.data(), bytes.size());
    uint32_t h   = h32 & kCmsIndexMask;     // truncate to CMS index width
    return h >> kBucketShift;               // upper log2(kCmsBuckets) bits
}
// (Traditional BF doesn't need per-flow BF indices for classification —
// every visible flow goes straight to the solver.)
static uint32_t cms_col(const Crc32& fn, const std::vector<uint8_t>& bytes) {
    return fn.compute(bytes.data(), bytes.size()) & (kColsPerRow - 1);
}

int main(int argc, char** argv) {
    // Self-test mode: compute CRC of "123456789" for every config and print
    // hex output. Standard CRC test vectors say (from RevEng catalog):
    //   CRC-32       (poly 0x04C11DB7, refl, init=FFFF.., xor=FFFF..) -> 0xCBF43926
    //   CRC-32/BZIP2 (poly 0x04C11DB7, !refl, init=FFFF.., xor=FFFF..) -> 0xFC891918
    //   CRC-32C      (poly 0x1EDC6F41, refl, init=FFFF.., xor=FFFF..) -> 0xE3069283
    //   CRC-32D      (poly 0xA833982B, refl, init=FFFF.., xor=FFFF..) -> 0x87315576
    if (argc >= 2 && std::string(argv[1]) == "--selftest") {
        const char* s = "123456789";
        std::vector<uint8_t> b(s, s + 9);
        auto test = [&](const char* name, const Crc32& fn, uint32_t want) {
            uint32_t got = fn.compute(b.data(), b.size());
            std::printf("  %-12s got=0x%08x  want=0x%08x  %s\n",
                        name, got, want, got == want ? "OK" : "DIFFERS");
        };
        Crc32 crc32_std   {0x104C11DB7ULL, true,  0xFFFFFFFF, 0xFFFFFFFF};
        Crc32 crc32_bzip2 {0x104C11DB7ULL, false, 0xFFFFFFFF, 0xFFFFFFFF};
        Crc32 crc32c      {0x11EDC6F41ULL, true,  0xFFFFFFFF, 0xFFFFFFFF};
        Crc32 crc32d      {0x1A833982BULL, true,  0xFFFFFFFF, 0xFFFFFFFF};
        std::puts("Self-test: CRC of \"123456789\"");
        test("CRC-32",       crc32_std,   0xCBF43926);
        test("CRC-32/BZIP2", crc32_bzip2, 0xFC891918);
        test("CRC-32C",      crc32c,      0xE3069283);
        test("CRC-32D",      crc32d,      0x87315576);
        return 0;
    }

    Config cfg = parse_args(argc, argv);
    std::signal(SIGINT, on_sigint);

    std::cerr << "============================================================\n"
              << "  cpp_traditional_common — pure C++ control plane (P4: "
              << kP4Name << ")\n"
              << "  bfrt-gRPC        : " << kAddr << "\n"
              << "  P4 program       : " << kP4Name << "\n"
              << "  Device / Pipe    : " << kDeviceId << " / " << cfg.pipe_id << "\n"
              << "  Epoch length     : " << cfg.epoch_seconds << " s\n"
              << "  BF cells per row : " << kBfSize << "\n"
              << "  CMS cells per row: " << kCmsSize
              << " (" << kCmsBuckets << " buckets * " << kColsPerRow << " cols)\n"
              << "============================================================\n";

    BfrtClient client(kAddr, kP4Name, kDeviceId, kClientId, cfg.pipe_id);
    if (!client.connect_and_bind()) return 1;

    uint32_t bf_ids[3], cms_ids[3];
    for (size_t i = 0; i < 3; ++i) {
        if (cfg.bf_ids_override.size() == 3) {
            bf_ids[i] = cfg.bf_ids_override[i];
        } else if (!client.resolve_table_id(kBfNames[i], bf_ids[i])) {
            std::cerr << "[main] cannot resolve " << kBfNames[i] << "\n"; return 1;
        }
        if (cfg.cms_ids_override.size() == 3) {
            cms_ids[i] = cfg.cms_ids_override[i];
        } else if (!client.resolve_table_id(kCmsNames[i], cms_ids[i])) {
            std::cerr << "[main] cannot resolve " << kCmsNames[i] << "\n"; return 1;
        }
    }
    std::cerr << "[main] BF  table ids : "
              << bf_ids[0] << " " << bf_ids[1] << " " << bf_ids[2] << "\n";
    std::cerr << "[main] CMS table ids : "
              << cms_ids[0] << " " << cms_ids[1] << " " << cms_ids[2] << "\n";

    FlowTable             flow_table;
    std::mutex            flow_mu;
    std::atomic<uint64_t> total_digests{0};

    client.start_digest_stream([&](const FlowKey& k) {
        std::lock_guard<std::mutex> lk(flow_mu);
        flow_table[k] += 1;
        uint64_t t = ++total_digests;
        if (t % 50000 == 0) {
            std::cerr << "  [" << t << " digests received, "
                      << flow_table.size() << " unique flows]\n";
        }
    });

    std::cerr << "[main] connected. waiting for packets...\n";
    auto epoch_dur = std::chrono::milliseconds((int64_t)(cfg.epoch_seconds * 1000.0));
    uint32_t epoch_num = 1;

    while (!g_quit.load()) {
        std::this_thread::sleep_for(epoch_dur);

        // Snapshot (and detach) the current flow_table so digest collection
        // continues into the next epoch's table while we process this one.
        FlowTable snap;
        {
            std::lock_guard<std::mutex> lk(flow_mu);
            snap.swap(flow_table);
        }

        std::cerr << "\n========================================================================\n"
                  << "  EPOCH " << epoch_num << " END  -  "
                  << snap.size() << " flows detected by BF\n"
                  << "========================================================================\n";

        if (snap.empty()) {
            std::cerr << "  (no flows this epoch — skipping snapshot/clear)\n";
            ++epoch_num;
            continue;
        }

        auto t0 = std::chrono::steady_clock::now();

        std::vector<std::vector<uint64_t>> bf(3), cms(3);
        for (size_t i = 0; i < 3; ++i) {
            if (!client.read_register(bf_ids[i],  kBfSize,  bf[i]))  return 1;
            if (!client.read_register(cms_ids[i], kCmsSize, cms[i])) return 1;
        }

        auto t1 = std::chrono::steady_clock::now();
        double read_secs = std::chrono::duration<double>(t1 - t0).count();
        std::cerr << "  bulk read time         : " << read_secs << " s\n";

        // Diagnostic: how many cells are non-zero per row, and what's the sum?
        for (size_t i = 0; i < 3; ++i) {
            uint64_t sum = 0, nz = 0;
            for (auto v : bf[i])  { if (v) { sum += v; ++nz; } }
            std::cerr << "    bf_"  << i << " : " << nz
                      << " non-zero cells, sum=" << sum << "\n";
        }
        for (size_t i = 0; i < 3; ++i) {
            uint64_t sum = 0, nz = 0;
            for (auto v : cms[i]) { if (v) { sum += v; ++nz; } }
            std::cerr << "    cms_" << i << " : " << nz
                      << " non-zero cells, sum=" << sum << "\n";
        }

        // (Per-flow CRC/index diagnostic removed — was useful for the 6-flow
        // probe but spams the terminal at line-rate scale. Re-enable it
        // behind a flag if you ever need to debug index computation again.)

        // Traditional BF: every visible flow goes straight to the sub-sketch
        // equation solver (with min(cms_rows) fallback when n > kColsPerRow).
        // Algorithms 4 / 5 are NOT applicable — BF state after the epoch can't
        // distinguish a 1-pkt mouse from an N-pkt elephant because every
        // packet flips all 3 BF rows.
        std::array<std::vector<FlowKey>, kCmsBuckets>                    buckets;
        std::array<std::vector<std::array<std::pair<int,uint32_t>,3>>, kCmsBuckets> bucket_cells;
        std::array<std::vector<uint64_t>, 3> cms_arr{cms[0], cms[1], cms[2]};

        uint64_t epoch_digests = 0, epoch_packets = 0;
        size_t   solver_input_count = 0;

        for (const auto& kv : snap) {
            const FlowKey& k = kv.first;
            uint32_t       dc = kv.second;
            epoch_digests += dc;

            auto bytes = pack_5tuple(k.src_ip, k.dst_ip, k.proto,
                                      k.src_port, k.dst_port);

            uint32_t bucket = master_bucket(bytes);
            uint32_t off    = bucket << kBucketShift;
            std::array<std::pair<int,uint32_t>,3> cells = {{
                {0, off | cms_col(polys::cms0, bytes)},
                {1, off | cms_col(polys::cms1, bytes)},
                {2, off | cms_col(polys::cms2, bytes)},
            }};

            buckets[bucket].push_back(k);
            bucket_cells[bucket].push_back(cells);
            ++solver_input_count;
        }

        // Sub-sketch equation solver on the remaining flows.
        size_t   exact_buckets = 0, alg6_buckets = 0, skipped_buckets = 0;
        size_t   total_used_buckets = 0;
        uint64_t max_bucket_flows = 0;
        std::unordered_map<const FlowKey*, uint64_t> per_flow_cms;
        for (size_t b = 0; b < kCmsBuckets; ++b) {
            if (buckets[b].empty()) continue;
            ++total_used_buckets;
            if (buckets[b].size() > max_bucket_flows) max_bucket_flows = buckets[b].size();

            SolverResult r;
            // Skip criteria, in order:
            //   1. n > 3c: information-theoretic limit; no possible exact solve.
            //   2. n > kSlowSolverCap: Algorithm 6 step B (LSQ via normal
            //      equations) is O(n^2 * m) per bucket, which blows out
            //      runtime at large n. Cap at 500 to keep solver wall-time
            //      under a few seconds. Beyond cap -> min(cms_rows) fallback.
            constexpr uint32_t kSlowSolverCap = 500;
            if (buckets[b].size() > 3 * kColsPerRow ||
                buckets[b].size() > kSlowSolverCap) {
                r.path = SolverPath::Skipped;
                ++skipped_buckets;
            } else {
                r = solve_bucket(buckets[b], bucket_cells[b], cms_arr);
                if (r.path == SolverPath::Exact)           ++exact_buckets;
                else if (r.path == SolverPath::Algorithm6) ++alg6_buckets;
            }
            for (size_t j = 0; j < buckets[b].size(); ++j) {
                uint64_t v;
                if (r.path == SolverPath::Skipped) {
                    auto& cells = bucket_cells[b][j];
                    v = std::min({cms[0][cells[0].second],
                                  cms[1][cells[1].second],
                                  cms[2][cells[2].second]});
                } else {
                    v = r.cms_estimate[j];
                }
                auto it = snap.find(buckets[b][j]);
                if (it != snap.end()) per_flow_cms[&(it->first)] = v;
                epoch_packets += it->second + v;
            }
        }
        double max_load = (double)max_bucket_flows / kColsPerRow;

        size_t total_flows = snap.size();
        auto pct = [&](size_t v) -> double {
            return total_flows ? 100.0 * v / total_flows : 0.0;
        };
        std::cerr << "  Total flows            : " << total_flows << "\n"
                  << "  Epoch digests          : " << epoch_digests << "\n"
                  << "  Estimated packets      : " << epoch_packets << "\n"
                  << "  Equation solver / min fallback  : " << solver_input_count
                  << "  (" << pct(solver_input_count) << "%)\n"
                  << "  Sub-sketch buckets used: " << total_used_buckets
                  << " / " << kCmsBuckets << "  (exact: " << exact_buckets
                  << ", Alg6 approx: " << alg6_buckets
                  << ", skipped: " << skipped_buckets << ")\n"
                  << "  Max sub-sketch load    : " << max_load
                  << "  (max bucket = " << max_bucket_flows << " flows / "
                  << kColsPerRow << " cols)\n";

        std::cerr << "  Clearing BF + CMS registers (targeted, non-zero only)...\n";
        auto t2 = std::chrono::steady_clock::now();
        for (size_t i = 0; i < 3; ++i) {
            std::vector<uint32_t> nz;
            nz.reserve(bf[i].size() / 16);
            for (uint32_t k = 0; k < bf[i].size(); ++k)
                if (bf[i][k]) nz.push_back(k);
            client.clear_register_indices(bf_ids[i], nz, /*value_bytes=*/1);
        }
        for (size_t i = 0; i < 3; ++i) {
            std::vector<uint32_t> nz;
            nz.reserve(cms[i].size() / 16);
            for (uint32_t k = 0; k < cms[i].size(); ++k)
                if (cms[i][k]) nz.push_back(k);
            client.clear_register_indices(cms_ids[i], nz, /*value_bytes=*/2);
        }
        auto t3 = std::chrono::steady_clock::now();
        std::cerr << "  bulk clear time        : "
                  << std::chrono::duration<double>(t3 - t2).count() << " s\n";

        std::cerr << "========================================================================\n";
        ++epoch_num;
    }

    std::cerr << "[main] shutting down\n";
    client.stop_digest_stream();
    return 0;
}
