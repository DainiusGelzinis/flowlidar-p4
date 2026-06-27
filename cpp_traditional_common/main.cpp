// main.cpp — shared traditional-BF control plane for the

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>

#include <arpa/inet.h>

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

static constexpr uint32_t    kBfSize      = TRAD_BF_SIZE;
static constexpr uint32_t    kCmsBuckets  = TRAD_CMS_BUCKETS;
static constexpr uint32_t    kColsPerRow  = TRAD_CMS_COLS;
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
    uint32_t pipe_id       = 1;
    std::vector<uint32_t> bf_ids_override;
    std::vector<uint32_t> cms_ids_override;
    std::string csv_out;
    uint32_t    max_epochs = 0;
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
        else if (a == "--csv-out" && i + 1 < argc) c.csv_out  = argv[++i];
        else if (a == "--epochs"  && i + 1 < argc) c.max_epochs = (uint32_t)std::atoi(argv[++i]);
        else if (a == "--help" || a == "-h") {
            std::cout << "usage: " << argv[0]
                      << " [--epoch SECS] [--pipe N]"
                      << " [--bf-ids id0,id1,id2] [--cms-ids id0,id1,id2]"
                      << " [--csv-out FILE] [--epochs N]\n";
            std::exit(0);
        }
    }
    return c;
}

// CMS index helpers (mirror Python control_plane.py exactly).
static uint32_t master_bucket(const std::vector<uint8_t>& bytes) {
    uint32_t h32 = polys::master.compute(bytes.data(), bytes.size());
    uint32_t h   = h32 & kCmsIndexMask;
    return h >> kBucketShift;
}
// (Traditional BF doesn't need per-flow BF indices for classification —
static uint32_t cms_col(const Crc32& fn, const std::vector<uint8_t>& bytes) {
    return fn.compute(bytes.data(), bytes.size()) & (kColsPerRow - 1);
}

int main(int argc, char** argv) {
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

    std::cerr << "Waiting for packets...\n";
    auto epoch_dur = std::chrono::milliseconds((int64_t)(cfg.epoch_seconds * 1000.0));
    uint32_t epoch_num = 1;

    while (!g_quit.load()) {
        std::this_thread::sleep_for(epoch_dur);

        FlowTable snap;
        {
            std::lock_guard<std::mutex> lk(flow_mu);
            snap.swap(flow_table);
        }

        std::cerr << "=== EPOCH " << epoch_num << " END ===\n";

        if (snap.empty()) {
            ++epoch_num;
            continue;
        }

        std::vector<std::vector<uint64_t>> bf(3), cms(3);
        for (size_t i = 0; i < 3; ++i) {
            if (!client.read_register(bf_ids[i],  kBfSize,  bf[i]))  return 1;
            if (!client.read_register(cms_ids[i], kCmsSize, cms[i])) return 1;
        }

        std::array<std::vector<FlowKey>, kCmsBuckets>                    buckets;
        std::array<std::vector<std::array<std::pair<int,uint32_t>,3>>, kCmsBuckets> bucket_cells;
        std::array<std::vector<uint64_t>, 3> cms_arr{cms[0], cms[1], cms[2]};

        uint64_t epoch_packets = 0;

        std::unordered_map<FlowKey, std::pair<uint64_t, const char*>, FlowKeyHash> per_flow;
        per_flow.reserve(snap.size());

        for (const auto& kv : snap) {
            const FlowKey& k = kv.first;
            uint32_t       dc = kv.second;

            auto bytes = pack_5tuple(k.src_ip, k.dst_ip, k.proto,
                                      k.src_port, k.dst_port);

            uint32_t bucket = master_bucket(bytes);
            uint32_t off    = bucket << kBucketShift;
            std::array<std::pair<int,uint32_t>,3> cells = {{
                {0, off | cms_col(polys::cms0, bytes)},
                {1, off | cms_col(polys::cms1, bytes)},
                {2, off | cms_col(polys::cms2, bytes)},
            }};

            uint64_t cmin = std::min({cms[0][cells[0].second],
                                       cms[1][cells[1].second],
                                       cms[2][cells[2].second]});
            if (cmin == 0) {
                epoch_packets += dc;
                per_flow[k] = {dc, "alg5"};
                continue;
            }

            buckets[bucket].push_back(k);
            bucket_cells[bucket].push_back(cells);
        }

        std::vector<SolverResult> bucket_results(kCmsBuckets);
        #pragma omp parallel for schedule(dynamic, 1)
        for (size_t b = 0; b < kCmsBuckets; ++b) {
            if (buckets[b].empty()) continue;
            bucket_results[b] = solve_bucket(buckets[b], bucket_cells[b], cms_arr);
        }

        for (size_t b = 0; b < kCmsBuckets; ++b) {
            if (buckets[b].empty()) continue;
            const SolverResult& r = bucket_results[b];
            const char* path_tag = (r.path == SolverPath::Skipped)    ? "min"
                                 : (r.path == SolverPath::Exact)      ? "exact"
                                 : (r.path == SolverPath::Algorithm6) ? "alg6"
                                 :                                       "min";
            for (size_t j = 0; j < buckets[b].size(); ++j) {
                uint64_t v;
                auto& cells = bucket_cells[b][j];
                uint64_t cms_min = std::min({cms[0][cells[0].second],
                                             cms[1][cells[1].second],
                                             cms[2][cells[2].second]});
                if (r.path == SolverPath::Skipped) {
                    v = cms_min;
                } else {
                    v = std::min(r.cms_estimate[j], cms_min);
                }
                auto it = snap.find(buckets[b][j]);
#ifdef TRAD_CMS_UNGATED
                uint64_t est = v;
#else
                uint64_t est = it->second + v;
#endif
                epoch_packets += est;
                per_flow[buckets[b][j]] = {est, path_tag};
            }
        }
        std::cerr << "  Estimated flows: " << snap.size()
                  << "   estimated packets: " << epoch_packets << "\n";

        for (size_t i = 0; i < 3; ++i) {
            std::vector<uint32_t> nz;
            nz.reserve(bf[i].size() / 16);
            for (uint32_t k = 0; k < bf[i].size(); ++k)
                if (bf[i][k]) nz.push_back(k);
            client.clear_register_indices(bf_ids[i], nz, 1);
        }
        for (size_t i = 0; i < 3; ++i) {
            std::vector<uint32_t> nz;
            nz.reserve(cms[i].size() / 16);
            for (uint32_t k = 0; k < cms[i].size(); ++k)
                if (cms[i][k]) nz.push_back(k);
            client.clear_register_indices(cms_ids[i], nz, 2);
        }

        if (!cfg.csv_out.empty()) {
            std::ofstream out(cfg.csv_out);
            if (!out) {
                std::cerr << "[main] WARN: cannot open --csv-out file: "
                          << cfg.csv_out << "\n";
            } else {
                out << "src_ip,dst_ip,proto,src_port,dst_port,"
                       "digest_count,estimated_packets,solver_path\n";
                char ipbuf_s[INET_ADDRSTRLEN], ipbuf_d[INET_ADDRSTRLEN];
                for (const auto& kv : snap) {
                    const FlowKey& k = kv.first;
                    uint32_t       dc = kv.second;
                    in_addr a; a.s_addr = htonl(k.src_ip);
                    inet_ntop(AF_INET, &a, ipbuf_s, sizeof(ipbuf_s));
                    a.s_addr = htonl(k.dst_ip);
                    inet_ntop(AF_INET, &a, ipbuf_d, sizeof(ipbuf_d));
                    auto it = per_flow.find(k);
                    uint64_t est = it != per_flow.end() ? it->second.first  : (uint64_t)dc;
                    const char* path = it != per_flow.end() ? it->second.second : "min";
                    out << ipbuf_s << "," << ipbuf_d << ","
                        << (unsigned)k.proto << ","
                        << k.src_port << "," << k.dst_port << ","
                        << dc << "," << est << "," << path << "\n";
                }
                std::cerr << "  CSV saved: " << cfg.csv_out << "\n";
            }
        }

        ++epoch_num;

        if (cfg.max_epochs && (epoch_num - 1) >= cfg.max_epochs) {
            break;
        }
    }

    client.stop_digest_stream();
    std::cerr << "Finished successfully\n";
    return 0;
}
