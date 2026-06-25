// bfrt_client.hpp — minimal bfrt-grpc client wrapping subscribe + bind +
#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <thread>
#include <vector>
#include <mutex>

#include <grpcpp/grpcpp.h>
#include "bfruntime.pb.h"
#include "bfruntime.grpc.pb.h"

#include "flow.hpp"

namespace bf = bfrt_proto;

class BfrtClient {
public:
    BfrtClient(std::string addr, std::string p4_name,
               uint32_t device_id, uint32_t client_id, uint32_t pipe_id);
    ~BfrtClient();

    bool connect_and_bind();

    bool resolve_table_id(const std::string& full_name, uint32_t& out_id);

    // Bulk read. Returns one entry per cell in `out` (index 0..size-1).
    bool read_register(uint32_t table_id, uint32_t expected_size,
                        std::vector<uint64_t>& out);

    // Targeted clear: write 0 to each given index of `table_id`. We don't
    bool clear_register_indices(uint32_t table_id,
                                const std::vector<uint32_t>& indices,
                                uint32_t value_bytes );

    void start_digest_stream(std::function<void(const FlowKey&)> cb);
    void stop_digest_stream();

private:
    bool load_bfrt_info();
    bool parse_table_ids(const std::string& info);
    static uint32_t extract_register_index(const bf::TableEntry& te);
    static uint64_t extract_register_value(const bf::TableEntry& te);

    std::string addr_, p4_name_;
    uint32_t device_id_, client_id_, pipe_id_;

    std::shared_ptr<grpc::Channel>             channel_;
    std::unique_ptr<bf::BfRuntime::Stub>       stub_;
    std::unique_ptr<grpc::ClientContext>       stream_ctx_;
    std::unique_ptr<grpc::ClientReaderWriter<bf::StreamMessageRequest,
                                              bf::StreamMessageResponse>> stream_;

    std::map<std::string, uint32_t>            table_id_;

    struct FieldIds { uint32_t key_fid = 0; uint32_t data_fid = 0; };
    std::map<uint32_t, FieldIds>               field_ids_;

    std::thread                                 digest_thread_;
    std::atomic<bool>                           stop_digests_{false};
};
