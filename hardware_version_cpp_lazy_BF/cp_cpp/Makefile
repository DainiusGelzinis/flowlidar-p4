# Makefile — pure C++ control plane for hardware_version_cpp_lazy_BF.
#
# Targets two SDE flavours without modification:
#   - open-p4studio (simulator, SDE 9.13.4): paths under $SDE/install
#   - bf-sde-9.11.0 (p4switch2 hardware):   paths under $SDE/install
# Both expose $SDE / $SDE_INSTALL — the make uses those.
#
# Self-contained on the proto side: status.proto is shipped in proto/google/rpc/
# so we don't depend on the SDE's pkgsrc/ tree (which is missing on most
# binary-installed switches).

SDE          ?= $(error SDE not set; export SDE=/path/to/SDE first)
SDE_INSTALL  ?= $(SDE)/install

PROTOC       := $(SDE_INSTALL)/bin/protoc
GRPC_PLUGIN  := $(SDE_INSTALL)/bin/grpc_cpp_plugin

# Look for bfruntime.proto in known SDE locations.
BFRT_PROTO_CANDIDATES := \
    $(SDE_INSTALL)/share/bf_rt_shared/proto/bfruntime.proto \
    $(SDE_INSTALL)/share/bfsys/proto/bfruntime.proto \
    $(SDE)/pkgsrc/bf-drivers/bf_rt/proto/bfruntime.proto

BFRT_PROTO   := $(firstword $(wildcard $(BFRT_PROTO_CANDIDATES)))
ifeq ($(BFRT_PROTO),)
$(error bfruntime.proto not found; tried: $(BFRT_PROTO_CANDIDATES))
endif
BFRT_DIR     := $(dir $(BFRT_PROTO))

# Bundled deps so we don't need SDE pkgsrc (often absent on real hw).
LOCAL_PROTO  := proto

GEN_DIR      := build_gen
GEN_SRCS     := $(GEN_DIR)/bfruntime.pb.cc \
                $(GEN_DIR)/bfruntime.grpc.pb.cc \
                $(GEN_DIR)/google/rpc/status.pb.cc

CXX          := g++
CXXFLAGS     := -std=c++17 -O2 -Wall \
                -I$(SDE_INSTALL)/include \
                -I$(GEN_DIR)
PKGCONFIG    := PKG_CONFIG_PATH=$(SDE_INSTALL)/lib/pkgconfig pkg-config
LDFLAGS      := -L$(SDE_INSTALL)/lib \
                -Wl,-rpath,$(SDE_INSTALL)/lib \
                -Wl,--copy-dt-needed-entries

# Prefer pkg-config; fall back to a hand-rolled list if the SDE doesn't
# ship .pc files.
GRPC_LIBS    := $(shell $(PKGCONFIG) --libs grpc++ 2>/dev/null)
ifeq ($(strip $(GRPC_LIBS)),)
GRPC_LIBS    := -lgrpc++ -lgrpc -lgpr -labsl_synchronization
endif
LIBS         := $(GRPC_LIBS) -lgrpc++_reflection -lprotobuf -lpthread

TARGET       := lazy_bf_cp
SRCS         := main.cpp bfrt_client.cpp $(GEN_SRCS)

all: $(TARGET)

$(TARGET): $(SRCS) bfrt_client.hpp crc.hpp flow.hpp
	$(CXX) $(CXXFLAGS) -o $@ main.cpp bfrt_client.cpp $(GEN_SRCS) \
	    $(LDFLAGS) $(LIBS)

# Generate C++ bfruntime stubs. We pass both the proto's own dir and the
# bundled proto/ as include paths so the import "google/rpc/status.proto"
# resolves locally.
$(GEN_DIR)/bfruntime.pb.cc $(GEN_DIR)/bfruntime.grpc.pb.cc: \
        $(BFRT_PROTO) $(GEN_DIR)/google/rpc/status.pb.cc
	mkdir -p $(GEN_DIR)
	$(PROTOC) -I$(BFRT_DIR) -I$(LOCAL_PROTO) \
	          --cpp_out=$(GEN_DIR) \
	          --grpc_out=$(GEN_DIR) \
	          --plugin=protoc-gen-grpc=$(GRPC_PLUGIN) \
	          $(BFRT_PROTO)

$(GEN_DIR)/google/rpc/status.pb.cc: $(LOCAL_PROTO)/google/rpc/status.proto
	mkdir -p $(GEN_DIR)/google/rpc
	$(PROTOC) -I$(LOCAL_PROTO) --cpp_out=$(GEN_DIR) $(LOCAL_PROTO)/google/rpc/status.proto

# Print which versions / paths we resolved — useful when debugging on hw.
diag:
	@echo "SDE         = $(SDE)"
	@echo "SDE_INSTALL = $(SDE_INSTALL)"
	@echo "PROTOC      = $(PROTOC)"
	@echo "GRPC_PLUGIN = $(GRPC_PLUGIN)"
	@echo "BFRT_PROTO  = $(BFRT_PROTO)"
	@echo "GRPC_LIBS   = $(GRPC_LIBS)"

clean:
	rm -rf $(TARGET) $(GEN_DIR)

.PHONY: all clean diag
