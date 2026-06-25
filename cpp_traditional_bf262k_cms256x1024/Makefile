# Build the C++ control plane for the traditional 262k / 256x1024 CMS variant.
BF_SIZE     := 262144
CMS_BUCKETS := 256
CMS_COLS    := 1024
P4_NAME     := traditional_bf262k_cms256x1024
BINARY      := traditional_bf262k_cms256x1024_cp
include ../cpp_traditional_common/Makefile.core

# Paper Algorithm 1: every packet in the CMS -> estimate = CMS value only.
CXXFLAGS += -DTRAD_CMS_UNGATED
