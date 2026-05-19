# Makefile — pure C++ control plane for hardware_version_cpp_lazy_BF.
#
# Targets two SDE flavours without modification:
#   - open-p4studio (simulator, SDE 9.13.4): paths under $SDE/install
#   - bf-sde-9.11.0 (p4switch2 hardware):   paths under $SDE/install
# Both expose $SDE / $SDE_INSTALL — the make uses those.
#
# Self-contained on the proto side: a minimal google.rpc.Status proto
# stub is generated inline (see STATUS_PROTO rule below) so we don't
# depend on the SDE's pkgsrc/ tree (which is missing on most binary-
# installed switches) and don't need to vendor a third-party file.

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

# Inline-generated minimal stub for google.rpc.Status — bfruntime.proto
# imports it but the SDE often doesn't ship it. We write a 12-line
# proto3 stub at build time so there is nothing to vendor in this tree.
GEN_DIR      := build_gen
STUB_PROTO_DIR := $(GEN_DIR)/proto
STATUS_PROTO   := $(STUB_PROTO_DIR)/google/rpc/status.proto

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

TARGET       := traditional_bf_cp
SRCS         := main.cpp bfrt_client.cpp solver.cpp $(GEN_SRCS)

all: $(TARGET)

$(TARGET): $(SRCS) bfrt_client.hpp crc.hpp flow.hpp solver.hpp
	$(CXX) $(CXXFLAGS) -o $@ main.cpp bfrt_client.cpp solver.cpp $(GEN_SRCS) \
	    $(LDFLAGS) $(LIBS)

# Generate C++ bfruntime stubs. The inline-generated status.proto stub
# in $(STUB_PROTO_DIR) lets the `import "google/rpc/status.proto"` in
# bfruntime.proto resolve without a vendored file in this tree.
$(GEN_DIR)/bfruntime.pb.cc $(GEN_DIR)/bfruntime.grpc.pb.cc: \
        $(BFRT_PROTO) $(GEN_DIR)/google/rpc/status.pb.cc
	mkdir -p $(GEN_DIR)
	$(PROTOC) -I$(BFRT_DIR) -I$(STUB_PROTO_DIR) \
	          --cpp_out=$(GEN_DIR) \
	          --grpc_out=$(GEN_DIR) \
	          --plugin=protoc-gen-grpc=$(GRPC_PLUGIN) \
	          $(BFRT_PROTO)

$(GEN_DIR)/google/rpc/status.pb.cc: $(STATUS_PROTO)
	mkdir -p $(GEN_DIR)/google/rpc
	$(PROTOC) -I$(STUB_PROTO_DIR) --cpp_out=$(GEN_DIR) $(STATUS_PROTO)

# Inline stub — only the Status message itself is load-bearing; the
# rest of the upstream file is licence headers / java options / docs.
# bfruntime.proto only uses `.google.rpc.Status` as a field type.
$(STATUS_PROTO):
	@mkdir -p $(dir $@)
	@printf '%s\n' \
	    'syntax = "proto3";' \
	    'package google.rpc;' \
	    'import "google/protobuf/any.proto";' \
	    'message Status {' \
	    '  int32 code = 1;' \
	    '  string message = 2;' \
	    '  repeated google.protobuf.Any details = 3;' \
	    '}' > $@

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
