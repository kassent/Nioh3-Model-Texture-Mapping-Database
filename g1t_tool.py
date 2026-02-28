#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
G1T/G1TS Texture Tool
=====================
Export G1T/G1TS textures to DDS files and import DDS files back.

Usage:
  python g1t_tool.py export <input.g1t_or_dir> [output_dir]
  python g1t_tool.py import <input_dir> [output_dir]
  python g1t_tool.py info <input.g1t_or_dir>

Supports both traditional G1T (v56) and streaming G1TS (v66) formats.
"""

from __future__ import print_function
import struct
import sys
import os
import zlib
import math
import argparse
import re

# ============================================================================
# Constants
# ============================================================================

G1T_MAGIC = 0x47315447  # "GT1G"
ZLIB_MAGIC = 0x30303030  # "0000"
DDS_MAGIC = 0x20534444   # "DDS "
DX10_FOURCC = 0x30315844  # "DX10"
DDSCAPS2_CUBEMAP = 0x200
DDS_RESOURCE_MISC_TEXTURECUBE = 0x4
PLATFORM_WIN_DX12 = 0x0E

G1T_TO_DXGI = {
    0x00: (28, 29), 0x01: (87, 91), 0x02: (41, 0), 0x03: (10, 0),
    0x04: (2, 0), 0x05: (45, 0), 0x06: (71, 72), 0x07: (74, 75),
    0x08: (77, 78), 0x09: (28, 29), 0x0A: (87, 91), 0x0B: (41, 0),
    0x0C: (10, 0), 0x0D: (2, 0), 0x0F: (65, 0), 0x10: (71, 72),
    0x11: (74, 75), 0x12: (77, 78), 0x14: (56, 0), 0x18: (65, 0),
    0x19: (85, 0), 0x1A: (86, 0), 0x21: (88, 92), 0x23: (35, 0),
    0x2A: (61, 0), 0x40: (24, 0), 0x41: (11, 0), 0x46: (49, 0),
    0x4C: (16, 0), 0x4E: (41, 0),
    0x59: (71, 72), 0x5A: (74, 75), 0x5B: (77, 78), 0x5C: (80, 0),
    0x5D: (83, 0), 0x5E: (95, 0), 0x5F: (98, 99),
    0x60: (71, 72), 0x61: (74, 75), 0x62: (77, 78), 0x63: (80, 0),
    0x64: (83, 0), 0x65: (95, 0), 0x66: (98, 99),
    0x67: (30, 0), 0x68: (50, 0), 0x69: (34, 0), 0x6A: (54, 0),
    0x6B: (26, 0), 0x72: (61, 0), 0x73: (49, 0), 0x74: (30, 0),
    0x75: (50, 0), 0x76: (34, 0), 0x77: (54, 0), 0x78: (26, 0),
}

DXGI_TO_G1T = {}
_PREFERRED = {71: 0x59, 74: 0x5A, 77: 0x5B, 80: 0x5C, 83: 0x5D, 95: 0x5E, 98: 0x5F}
for _g, (_d, _ds) in G1T_TO_DXGI.items():
    if _d and _d not in DXGI_TO_G1T:
        DXGI_TO_G1T[_d] = _g
    if _ds and _ds not in DXGI_TO_G1T:
        DXGI_TO_G1T[_ds] = _g
for _d, _g in _PREFERRED.items():
    DXGI_TO_G1T[_d] = _g

POINT_SIZES = [
    32, 32, 32, 64, 128, 32, 4, 8, 8, 32, 32, 32, 64, 128, 0, 8,
    4, 8, 8, 32, 16, 16, 16, 16, 8, 16, 16, 16, 16, 16, 16, 32,
    32, 32, 32, 32, 0, 0, 0, 0, 0, 0, 8, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    32, 64, 32, 64, 0, 0, 16, 0, 0, 0, 0, 0, 64, 64, 32, 32,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 8, 8, 4, 8, 8, 8,
    4, 8, 8, 4, 8, 8, 8, 32, 16, 32, 16, 32, 64, 0, 0, 0,
    0, 0, 8, 16, 32, 16, 32, 16, 32, 0, 0, 0, 0,
]

DXGI_NAMES = {
    2: "R32G32B32A32_FLOAT", 10: "R16G16B16A16_FLOAT", 11: "R16G16B16A16_UNORM",
    16: "R32G32_FLOAT", 24: "R10G10B10A2_UNORM", 26: "R11G11B10_FLOAT",
    28: "R8G8B8A8_UNORM", 29: "R8G8B8A8_UNORM_SRGB", 30: "R8G8B8A8_UINT",
    34: "R16G16_FLOAT", 35: "R16G16_UNORM", 41: "R32_FLOAT",
    45: "R24_UNORM_X8_TYPELESS", 49: "R8G8_UNORM", 50: "R8G8_UINT",
    54: "R16_FLOAT", 56: "R16_UNORM", 61: "R8_UNORM", 65: "A8_UNORM",
    71: "BC1_UNORM", 72: "BC1_UNORM_SRGB", 74: "BC2_UNORM", 75: "BC2_UNORM_SRGB",
    77: "BC3_UNORM", 78: "BC3_UNORM_SRGB", 80: "BC4_UNORM", 83: "BC5_UNORM",
    85: "B5G6R5_UNORM", 86: "B5G5R5A1_UNORM", 87: "B8G8R8A8_UNORM",
    88: "B8G8R8X8_UNORM", 91: "B8G8R8A8_UNORM_SRGB", 92: "B8G8R8X8_UNORM_SRGB",
    95: "BC6H_UF16", 98: "BC7_UNORM", 99: "BC7_UNORM_SRGB",
}


# ============================================================================
# Utility Functions
# ============================================================================

def is_block_compressed(fmt):
    """Check if a G1T format is block-compressed."""
    if fmt >= len(POINT_SIZES):
        return False
    ps = POINT_SIZES[fmt]
    return 0 < ps < 32


def calc_mip_size(fmt, w, h):
    """Calculate the byte size of a single mip level."""
    if fmt >= len(POINT_SIZES):
        return 0
    ps = POINT_SIZES[fmt]
    if ps == 0:
        return 0
    if ps >= 32:
        block_size = ps // 8
    else:
        block_size = ps * 16 // 8
    size = w * h * ps // 8
    return max(size, block_size)


def calc_total_size(fmt, w, h, mips):
    """Calculate total byte size for all mip levels."""
    total = 0
    m = max(mips, 1)
    for i in range(m):
        total += calc_mip_size(fmt, max(1, w >> i), max(1, h >> i))
    return total


def dxgi_format_name(dxgi):
    return DXGI_NAMES.get(dxgi, "UNKNOWN_%d" % dxgi)


def format_extension(dxgi):
    """Get a descriptive file extension based on DXGI format."""
    ext_map = {
        87: ".rgba", 71: ".dxt1", 74: ".dxt3", 77: ".dxt5",
        80: ".bc4", 83: ".bc5", 95: ".bc6h", 98: ".bc7",
    }
    return ext_map.get(dxgi, "")


def _is_g1t_file(path):
    lower = path.lower()
    return lower.endswith(".g1t") or lower.endswith(".g1ts")


def _collect_g1t_files(path):
    """Collect .g1t/.g1ts files from a file or directory path."""
    if os.path.isfile(path):
        return [path] if _is_g1t_file(path) else []
    if not os.path.isdir(path):
        return []

    files = []
    for root, _dirs, names in os.walk(path):
        for name in names:
            if _is_g1t_file(name):
                files.append(os.path.join(root, name))
    files.sort()
    return files


def _collect_dds_files(path, recursive=True):
    """Collect .dds files from a file or directory path."""
    if os.path.isfile(path):
        return [path] if path.lower().endswith(".dds") else []
    if not os.path.isdir(path):
        return []

    files = []
    if recursive:
        for root, _dirs, names in os.walk(path):
            for name in names:
                if name.lower().endswith(".dds"):
                    files.append(os.path.join(root, name))
    else:
        for name in os.listdir(path):
            full = os.path.join(path, name)
            if os.path.isfile(full) and name.lower().endswith(".dds"):
                files.append(full)
    files.sort()
    return files


def _read_magic_u32(path):
    """Read first 4 bytes as little-endian uint32. Returns None on failure."""
    try:
        with open(path, "rb") as f:
            head = f.read(4)
        if len(head) < 4:
            return None
        return struct.unpack("<I", head)[0]
    except Exception:
        return None


def _is_gt1g_magic(path):
    magic = _read_magic_u32(path)
    if magic is None:
        return False, "cannot read 4-byte magic"
    if magic != G1T_MAGIC:
        return False, "magic=0x%08X" % magic
    return True, ""


def _split_magic_valid_g1t(paths):
    """Split paths into valid GT1G files and non-GT1G entries."""
    valid = []
    invalid = []  # (path, reason)
    for p in paths:
        ok, reason = _is_gt1g_magic(p)
        if ok:
            valid.append(p)
        else:
            invalid.append((p, reason))
    return valid, invalid


def _print_magic_skip_summary(invalid_items, root_dir):
    if not invalid_items:
        return
    print("Skipped %d non-GT1G .g1t/.g1ts file(s) by magic check." % len(invalid_items))
    show_n = 10
    for p, reason in invalid_items[:show_n]:
        try:
            rel = os.path.relpath(p, root_dir)
        except Exception:
            rel = p
        print("  - %s (%s)" % (rel, reason))
    if len(invalid_items) > show_n:
        print("  ... %d more" % (len(invalid_items) - show_n))


def _strip_all_extensions(path_or_name):
    """Strip all extensions, e.g. 0xABC.bc7.dds -> 0xABC."""
    name = os.path.basename(path_or_name)
    while True:
        stem, ext = os.path.splitext(name)
        if not ext:
            return stem
        name = stem


def _match_key_from_g1t(path_or_name):
    return os.path.splitext(os.path.basename(path_or_name))[0].lower()


def _match_key_from_dds(path_or_name):
    return _strip_all_extensions(path_or_name).lower()


def _extract_tex_index(filename):
    """Extract texture index from DDS filename, e.g. 0xABC.TEX2.bc7.dds -> 2."""
    fn = os.path.basename(filename)
    if fn.lower().endswith(".dds"):
        core = fn[:-4]
    else:
        core = os.path.splitext(fn)[0]

    # Preferred new style: "<base>.TEX<idx>.<fmt>.dds"
    m = re.search(r"(?:^|[._\-\s])TEX(?:TURE)?\s*[_\-]?\s*(\d+)(?:$|[._\-\s])", core, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Legacy styles
    m = re.search(r"(?:Tex|Arr)\s*[_\-]?\s*(\d+)", core, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Fallback: plain numeric stem
    tmp = core
    while "." in tmp:
        tmp = os.path.splitext(tmp)[0]
    m = re.match(r"^(\d+)$", tmp.strip())
    if m:
        return int(m.group(1))

    return None


def _find_matching_dds_for_g1t(g1t_path):
    """Find DDS files for one g1t/g1ts in sibling dir or same-name subdir."""
    g1t_dir = os.path.dirname(g1t_path) or "."
    base = os.path.splitext(os.path.basename(g1t_path))[0]
    base_lower = base.lower()

    matches = []
    seen = set()

    def _add(path):
        norm = os.path.normcase(os.path.abspath(path))
        if norm in seen:
            return
        seen.add(norm)
        matches.append(path)

    def _name_matches_base(fn):
        lower = fn.lower()
        if lower.startswith(base_lower + ".") or lower.startswith(base_lower + "_"):
            return True
        return _match_key_from_dds(fn) == base_lower

    # 1) Directly under g1t directory
    for dds_path in _collect_dds_files(g1t_dir, recursive=False):
        if _name_matches_base(os.path.basename(dds_path)):
            _add(dds_path)

    # 2) Same-name subdir under g1t directory
    subdir = os.path.join(g1t_dir, base)
    if not os.path.isdir(subdir):
        subdir = None
        for name in os.listdir(g1t_dir):
            full = os.path.join(g1t_dir, name)
            if os.path.isdir(full) and name.lower() == base_lower:
                subdir = full
                break

    if subdir and os.path.isdir(subdir):
        for dds_path in _collect_dds_files(subdir, recursive=True):
            fn = os.path.basename(dds_path)
            if _name_matches_base(fn) or _extract_tex_index(fn) is not None:
                _add(dds_path)

    return matches


def parse_version(ver_bytes):
    """Parse ASCII version string like b'5600' to integer 56."""
    try:
        return int(ver_bytes.decode("ascii")[:2])
    except (ValueError, UnicodeDecodeError):
        return 0


def _parse_extra_info(tex):
    """Return (ex_faces, ex_array) from extra header."""
    if tex.extra_header_version > 0 and len(tex.extra_header_raw) >= 10:
        ex_info = struct.unpack_from("<H", tex.extra_header_raw, 8)[0]
        return ex_info & 0xF, ex_info >> 4
    return 0, 0


def _texture_array_size(tex):
    """Get logical array size for the texture."""
    _ex_faces, ex_array = _parse_extra_info(tex)
    if tex.load_type in (3, 4):  # PLANE_ARRAY / CUBE_ARRAY
        return max(1, ex_array)
    if tex.load_type == 2:  # VOLUME
        return max(1, 1 << ex_array)
    return 1


def _texture_is_cube(tex):
    return tex.load_type in (1, 4)  # CUBE / CUBE_ARRAY


def _texture_slice_count(tex):
    """Get number of 2D slices represented by image_data."""
    count = _texture_array_size(tex)
    if _texture_is_cube(tex):
        count *= 6
    return max(1, count)


def _mip_level_sizes(fmt, width, height, mips, depth=1):
    """Get per-mip byte sizes for one slice (including depth for volume textures)."""
    sizes = []
    curr_d = max(1, depth)
    for i in range(max(1, mips)):
        mw = max(1, width >> i)
        mh = max(1, height >> i)
        sizes.append(calc_mip_size(fmt, mw, mh) * curr_d)
        curr_d = max(1, curr_d >> 1)
    return sizes


def _mip_major_to_slice_major(raw_data, mip_sizes, slice_count):
    """Convert data layout: [mip][slice] -> [slice][mip]."""
    expected = sum(mip_sizes) * slice_count
    if len(raw_data) < expected:
        raise ValueError("Raw texture data too small: %d < %d" % (len(raw_data), expected))

    pos = 0
    slices = [bytearray() for _ in range(slice_count)]
    for sz in mip_sizes:
        for s in range(slice_count):
            slices[s] += raw_data[pos:pos + sz]
            pos += sz

    return b"".join(bytes(s) for s in slices), raw_data[expected:]


def _slice_major_to_mip_major(raw_data, mip_sizes, slice_count):
    """Convert data layout: [slice][mip] -> [mip][slice]."""
    per_slice = sum(mip_sizes)
    expected = per_slice * slice_count
    if len(raw_data) < expected:
        raise ValueError("DDS pixel data too small: %d < %d" % (len(raw_data), expected))

    slice_offsets = [i * per_slice for i in range(slice_count)]
    out = bytearray()
    for sz in mip_sizes:
        for s in range(slice_count):
            start = slice_offsets[s]
            out += raw_data[start:start + sz]
            slice_offsets[s] += sz

    return bytes(out), raw_data[expected:]


def _truncate_slice_major_mips(raw_data, mip_sizes, slice_count, keep_mips):
    """Truncate slice-major texture data to first keep_mips mips."""
    keep_sizes = mip_sizes[:keep_mips]
    per_slice = sum(mip_sizes)
    keep_per_slice = sum(keep_sizes)
    expected = per_slice * slice_count
    if len(raw_data) < expected:
        raise ValueError("DDS pixel data too small: %d < %d" % (len(raw_data), expected))

    out = bytearray()
    for s in range(slice_count):
        base = s * per_slice
        out += raw_data[base:base + keep_per_slice]

    return bytes(out), keep_sizes


def _platform_mip_alignment(platform):
    """Platform-specific mip alignment used by some KOEI targets."""
    if platform == 0x0B:  # PS4
        return 1024
    if platform == PLATFORM_WIN_DX12:
        return 4096
    return 0


def _mip_level_sizes_platform(fmt, width, height, mips, depth=1, platform=0x0A):
    """Per-mip sizes with platform alignment rules (as used in RDBExplorer)."""
    sizes = []
    curr_d = max(1, depth)
    align = _platform_mip_alignment(platform)
    for i in range(max(1, mips)):
        mw = max(1, width >> i)
        mh = max(1, height >> i)
        one_layer = calc_mip_size(fmt, mw, mh)
        if align > 0:
            one_layer = (one_layer + align - 1) & ~(align - 1)
        sizes.append(one_layer * curr_d)
        curr_d = max(1, curr_d >> 1)
    return sizes


def _bytes_per_bc_block(fmt):
    """Get bytes per BC block (8 or 16), 0 for non-BC formats."""
    if not is_block_compressed(fmt):
        return 0
    ps = POINT_SIZES[fmt] if fmt < len(POINT_SIZES) else 0
    if ps == 4:
        return 8
    if ps == 8:
        return 16
    return 0


def _deswizzle_d3d12_64kb_bc(src, width, height, fmt):
    """Convert D3D12 64KB tiled BC data to linear row-major layout."""
    bpb = _bytes_per_bc_block(fmt)
    if bpb == 0:
        return src

    block_w = (width + 3) // 4
    block_h = (height + 3) // 4
    dst = bytearray(len(src))

    tile_size = 64 * 1024
    tile_row_bytes = 1024
    tile_width = tile_row_bytes // bpb
    tile_height = 64

    tiles_x = (block_w + tile_width - 1) // tile_width
    tiles_y = (block_h + tile_height - 1) // tile_height

    for ty in range(tiles_y):
        for tx in range(tiles_x):
            tile_index = ty * tiles_x + tx
            tile_base = tile_index * tile_size

            for row in range(tile_height):
                y = ty * tile_height + row
                if y >= block_h:
                    continue

                src_row_off = tile_base + row * tile_row_bytes
                dst_row_off = y * block_w * bpb
                x_off = tx * tile_width
                if x_off >= block_w:
                    continue

                copy_blocks = min(tile_width, block_w - x_off)
                copy_bytes = copy_blocks * bpb
                dst_off = dst_row_off + x_off * bpb

                if src_row_off + copy_bytes <= len(src) and dst_off + copy_bytes <= len(dst):
                    dst[dst_off:dst_off + copy_bytes] = src[src_row_off:src_row_off + copy_bytes]

    return bytes(dst)


def _swizzle_d3d12_64kb_bc(src, width, height, fmt):
    """Convert linear row-major BC data back to D3D12 64KB tiled layout."""
    bpb = _bytes_per_bc_block(fmt)
    if bpb == 0:
        return src

    block_w = (width + 3) // 4
    block_h = (height + 3) // 4
    dst = bytearray(len(src))

    tile_size = 64 * 1024
    tile_row_bytes = 1024
    tile_width = tile_row_bytes // bpb
    tile_height = 64

    tiles_x = (block_w + tile_width - 1) // tile_width
    tiles_y = (block_h + tile_height - 1) // tile_height

    for ty in range(tiles_y):
        for tx in range(tiles_x):
            tile_index = ty * tiles_x + tx
            tile_base = tile_index * tile_size

            for row in range(tile_height):
                y = ty * tile_height + row
                if y >= block_h:
                    continue

                dst_row_off = tile_base + row * tile_row_bytes
                src_row_off = y * block_w * bpb
                x_off = tx * tile_width
                if x_off >= block_w:
                    continue

                copy_blocks = min(tile_width, block_w - x_off)
                copy_bytes = copy_blocks * bpb
                src_off = src_row_off + x_off * bpb

                if src_off + copy_bytes <= len(src) and dst_row_off + copy_bytes <= len(dst):
                    dst[dst_row_off:dst_row_off + copy_bytes] = src[src_off:src_off + copy_bytes]

    return bytes(dst)


def _apply_d3d12_tiling_transform(tex, pixel_data, platform, to_linear):
    """Apply D3D12 64KB BC (de)swizzle per mip/layer in mip-major order."""
    if tex.depth > 1:
        # 3D texture swizzle layout is not handled yet.
        return pixel_data

    mips = tex.mip_count if tex.mip_count > 0 else 1
    slice_count = _texture_slice_count(tex)
    mip_sizes = _mip_level_sizes_platform(tex.format, tex.width, tex.height, mips, tex.depth, platform)

    expected = sum(mip_sizes) * slice_count
    if expected > len(pixel_data):
        return pixel_data

    out = bytearray()
    pos = 0
    for i, sz in enumerate(mip_sizes):
        mw = max(1, tex.width >> i)
        mh = max(1, tex.height >> i)
        for _slice_idx in range(slice_count):
            chunk = pixel_data[pos:pos + sz]
            pos += sz

            if sz > 65536:
                if to_linear:
                    chunk = _deswizzle_d3d12_64kb_bc(chunk, mw, mh, tex.format)
                else:
                    chunk = _swizzle_d3d12_64kb_bc(chunk, mw, mh, tex.format)

            out += chunk

    if pos < len(pixel_data):
        out += pixel_data[pos:]

    return bytes(out)


# ============================================================================
# G1T Data Structures
# ============================================================================

class G1THeader(object):
    def __init__(self):
        self.magic = G1T_MAGIC
        self.version = b"5600"
        self.file_size = 0
        self.table_offset = 0
        self.num_textures = 0
        self.platform = 0x0A
        self.metadata_size = 0
        self.global_metadata = b""
        self.normal_flags = []
        # Raw bytes between fixed header (0x20) and offset table start.
        # Preserved to keep unknown/variant layout details during save.
        self.pre_table_raw = b""
        # Raw bytes between offset table end and the first texture entry.
        self.post_table_raw = b""
        # Raw bytes physically present after declared file_size.
        self.trailing_raw = b""
        self.first_texture_offset = 0
        self.original_physical_size = 0


class G1TTexture(object):
    def __init__(self):
        self.mip_count = 0
        self.load_type = 0
        self.format = 0
        self.width = 0
        self.height = 0
        self.depth = 1
        self.packed_dxdy = None
        self.packed_depth_ex = None
        self.metadata = b"\x00\x00\x00"
        self.extra_header_version = 0
        self.extra_header_raw = b""
        self.swizzle_type = 0
        # Whether this texture should use D3D12 64KB BC tiled layout on disk.
        self.d3d12_tiled = False
        self.normal_flags = 0
        self.image_data = b""  # raw pixel data (all mips)
        # Streaming (G1TS) metadata - preserved for round-trip fidelity
        self.streaming_unk08 = 0x80
        self.streaming_window_size = 65536
        self.streaming_meta1_count = 0  # header value (not multiplied by stride)
        self.streaming_meta2_count = 0
        self.streaming_meta1_raw = b""  # raw meta1 bytes (meta1_count * metaStride * 16)
        self.streaming_meta2_raw = b""  # raw meta2 bytes (meta2_count * metaStride * 16)
        self.streaming_decode_failed = False
        self.streaming_decode_error = ""


class G1TFile(object):
    def __init__(self):
        self.header = G1THeader()
        self.textures = []
        self.is_streaming = False  # True if v66 with ZLIB


# ============================================================================
# G1T Parser
# ============================================================================

def load_g1t(path):
    """Load a G1T or G1TS file and return a G1TFile object."""
    with open(path, "rb") as f:
        data = f.read()
    return parse_g1t(data)


def parse_g1t(data):
    """Parse G1T/G1TS binary data."""
    g = G1TFile()
    h = g.header

    # Reverse-validated logical header size.
    header_size = 0x1C
    if len(data) < header_size:
        raise ValueError("File too small for G1T header")

    h.magic = struct.unpack_from("<I", data, 0)[0]
    if h.magic != G1T_MAGIC:
        raise ValueError("Invalid G1T magic: 0x%08X" % h.magic)

    h.version = data[4:8]
    ver = parse_version(h.version)
    h.file_size = struct.unpack_from("<I", data, 8)[0]
    h.original_physical_size = len(data)
    h.table_offset = struct.unpack_from("<I", data, 0xC)[0]
    h.num_textures = struct.unpack_from("<I", data, 0x10)[0]
    h.platform = struct.unpack_from("<I", data, 0x14)[0]
    h.metadata_size = struct.unpack_from("<I", data, 0x18)[0]

    expected_table_offset = header_size + h.num_textures * 4
    if h.table_offset < header_size or h.table_offset > len(data):
        raise ValueError("Invalid table_offset: 0x%X" % h.table_offset)
    if h.table_offset != expected_table_offset:
        raise ValueError(
            "Unexpected table_offset for this parser: got 0x%X, expected 0x%X" % (
                h.table_offset, expected_table_offset))
    h.pre_table_raw = b""

    # NormalFlags starts immediately after logical header.
    pos = header_size
    h.normal_flags = []
    for i in range(h.num_textures):
        if pos + 4 <= len(data):
            h.normal_flags.append(struct.unpack_from("<I", data, pos)[0])
        else:
            h.normal_flags.append(0)
        pos += 4

    # Read offset table
    pos = h.table_offset
    if pos + h.num_textures * 4 > len(data):
        raise ValueError("Offset table out of range")
    offsets = []
    for i in range(h.num_textures):
        offsets.append(struct.unpack_from("<I", data, pos)[0])
        pos += 4

    table_end = h.table_offset + h.num_textures * 4
    if offsets:
        first_tex_pos = min(h.table_offset + off for off in offsets)
        if first_tex_pos < table_end:
            first_tex_pos = table_end
        if first_tex_pos > len(data):
            first_tex_pos = len(data)
    else:
        first_tex_pos = min(len(data), table_end + h.metadata_size)

    # Metadata is physically located after the offset table.
    meta_start = table_end
    meta_end = min(meta_start + h.metadata_size, len(data))
    if meta_end > first_tex_pos:
        raise ValueError(
            "Invalid metadata placement: metadata end 0x%X exceeds first texture at 0x%X" % (
                meta_end, first_tex_pos))
    h.global_metadata = data[meta_start:meta_end]
    h.first_texture_offset = max(0, first_tex_pos - h.table_offset)
    h.post_table_raw = data[table_end:first_tex_pos]

    declared_end = h.file_size
    if declared_end > len(data):
        declared_end = len(data)
    max_payload_end = declared_end

    # Parse each texture
    for i in range(h.num_textures):
        tex_pos = h.table_offset + offsets[i]
        if tex_pos + 8 > len(data):
            raise ValueError("Texture %d header out of range" % i)
        tex = G1TTexture()
        tex.normal_flags = h.normal_flags[i] if i < len(h.normal_flags) else 0

        mip_sys = data[tex_pos]
        tex.mip_count = mip_sys >> 4
        tex.load_type = mip_sys & 0x0F
        tex.format = data[tex_pos + 1]
        dxdy = data[tex_pos + 2]
        tex.packed_dxdy = dxdy
        tex.width = 1 << (dxdy & 0x0F)
        tex.height = 1 << (dxdy >> 4)
        d_ex = data[tex_pos + 3]
        tex.packed_depth_ex = d_ex
        tex.depth = 1 << (d_ex & 0x0F)
        tex.metadata = data[tex_pos + 4:tex_pos + 7]
        tex.extra_header_version = data[tex_pos + 7]

        data_start = tex_pos + 8

        if tex.extra_header_version > 0:
            ex_size = struct.unpack_from("<I", data, data_start)[0]
            tex.extra_header_raw = data[data_start:data_start + ex_size]
            if len(tex.extra_header_raw) > 10:
                tex.swizzle_type = tex.extra_header_raw[10]
            if ex_size >= 0x10:
                tex.width = struct.unpack_from("<I", tex.extra_header_raw, 0x0C)[0]
            if ex_size >= 0x14:
                tex.height = struct.unpack_from("<I", tex.extra_header_raw, 0x10)[0]
            data_start += ex_size

        # Texture payload range (used by both streaming and non-streaming paths).
        if i < h.num_textures - 1:
            next_pos = h.table_offset + offsets[i + 1]
        else:
            next_pos = declared_end
        if next_pos > len(data):
            next_pos = len(data)
        if next_pos < data_start:
            next_pos = data_start
        if next_pos > max_payload_end:
            max_payload_end = next_pos

        # Follow RDBExplorer behavior:
        # treat streaming ZLIB or WinDX12 textures as tiled BC candidates.
        tex.d3d12_tiled = ((tex.swizzle_type == 0x03) or (h.platform == PLATFORM_WIN_DX12))

        # Check for ZLIB streaming header
        if tex.swizzle_type == 0x03 and data_start + 4 <= len(data):
            check = struct.unpack_from("<I", data, data_start)[0]
            if check == ZLIB_MAGIC:
                g.is_streaming = True
                # Calculate totalLayers and faces for metaStride
                array_size = 1
                ex_faces = 0
                if tex.extra_header_version > 0 and len(tex.extra_header_raw) >= 10:
                    ex_info = struct.unpack_from("<H", tex.extra_header_raw, 8)[0]
                    ex_faces = ex_info & 0xF
                    ex_array = ex_info >> 4
                    if tex.load_type in (3, 4):  # PLANE_ARRAY or CUBE_ARRAY
                        array_size = ex_array
                    elif tex.load_type == 2:  # VOLUME
                        array_size = 1 << ex_array
                total_layers = max(1, array_size)
                if tex.load_type in (1, 4):  # CUBE or CUBE_ARRAY
                    total_layers *= 6
                faces = ex_faces if (tex.extra_header_version > 0 and ex_faces != 0) else 1
                try:
                    tex.image_data, sinfo = _decompress_zlib_texture(
                        data, data_start, tex.depth, total_layers, faces)
                    tex.streaming_unk08 = sinfo["unk08"]
                    tex.streaming_window_size = sinfo["window_size"]
                    tex.streaming_meta1_count = sinfo["meta1_count"]
                    tex.streaming_meta2_count = sinfo["meta2_count"]
                    tex.streaming_meta1_raw = sinfo["meta1_raw"]
                    tex.streaming_meta2_raw = sinfo["meta2_raw"]
                    if tex.d3d12_tiled:
                        tex.image_data = _apply_d3d12_tiling_transform(
                            tex, tex.image_data, h.platform, to_linear=True)
                    tex.streaming_decode_failed = False
                    tex.streaming_decode_error = ""
                except Exception as e:
                    # Some files use streaming-table variants this parser cannot decode yet.
                    # Keep raw blob so unmodified files still round-trip losslessly.
                    tex.image_data = b""
                    tex.streaming_decode_failed = True
                    tex.streaming_decode_error = str(e)
                g.textures.append(tex)
                continue

        # Regular (non-compressed) texture data
        tex_data_size = next_pos - data_start
        if tex_data_size < 0:
            tex_data_size = 0
        tex.image_data = data[data_start:data_start + tex_data_size]
        if tex.d3d12_tiled:
            tex.image_data = _apply_d3d12_tiling_transform(
                tex, tex.image_data, h.platform, to_linear=True)
        g.textures.append(tex)

    h.trailing_raw = data[max_payload_end:] if max_payload_end < len(data) else b""
    return g


def _decompress_zlib_texture(data, base, depth, total_layers, faces):
    """Decompress ZLIB-compressed texture data (G1TS format).

    Returns (decompressed_bytes, streaming_info_dict).
    """
    pos = base
    _magic = struct.unpack_from("<I", data, pos)[0]  # "0000"
    _table_size = struct.unpack_from("<I", data, pos + 4)[0]
    unk08 = struct.unpack_from("<I", data, pos + 8)[0]
    window_size = struct.unpack_from("<I", data, pos + 0xC)[0]
    meta1_count = struct.unpack_from("<I", data, pos + 0x10)[0]
    chunk_count = struct.unpack_from("<I", data, pos + 0x14)[0]
    meta2_count = struct.unpack_from("<I", data, pos + 0x18)[0]
    has_uncomp = struct.unpack_from("<I", data, pos + 0x1C)[0]
    uncomp_size = struct.unpack_from("<I", data, pos + 0x20)[0]

    pos += 36  # 9 * 4 bytes header

    # metaStride = depth * totalLayers * faces
    meta_stride = depth * total_layers * faces

    # Read meta1 entries (16 bytes each, meta1_count * metaStride entries)
    meta1_total = meta1_count * meta_stride * 16
    meta1_raw = data[pos:pos + meta1_total]
    pos += meta1_total
    # Read meta2 entries (16 bytes each, meta2_count * metaStride entries)
    meta2_total = meta2_count * meta_stride * 16
    meta2_raw = data[pos:pos + meta2_total]
    pos += meta2_total

    # Read chunk table
    chunks = []
    for j in range(chunk_count):
        c_off = struct.unpack_from("<I", data, pos)[0]
        c_size = struct.unpack_from("<I", data, pos + 4)[0]
        chunks.append((c_off, c_size))
        pos += 8

    uncomp_chunk = (0, 0)
    if has_uncomp:
        uncomp_chunk = (
            struct.unpack_from("<I", data, pos)[0],
            struct.unpack_from("<I", data, pos + 4)[0],
        )
        pos += 8

    # Decompress
    total_size = chunk_count * window_size + (uncomp_size if has_uncomp else 0)
    result = bytearray(total_size)

    for j in range(chunk_count):
        c_off, c_sz = chunks[j]
        out_off = j * window_size
        if c_sz >= window_size:
            # Raw (uncompressed) chunk: stored without size prefix
            result[out_off:out_off + window_size] = data[c_off:c_off + window_size]
        else:
            comp_data_size = struct.unpack_from("<I", data, c_off)[0]
            comp_data = data[c_off + 4:c_off + 4 + comp_data_size]
            try:
                decompressed = zlib.decompress(comp_data)
            except zlib.error:
                decompressed = zlib.decompress(comp_data, -15)
            to_copy = min(len(decompressed), window_size)
            result[out_off:out_off + to_copy] = decompressed[:to_copy]

    if has_uncomp:
        uc_off, uc_sz = uncomp_chunk
        last_data = data[uc_off:uc_off + uc_sz]
        final_off = chunk_count * window_size
        to_copy = min(len(last_data), total_size - final_off)
        result[final_off:final_off + to_copy] = last_data[:to_copy]

    streaming_info = {
        "unk08": unk08,
        "window_size": window_size,
        "meta1_count": meta1_count,
        "meta2_count": meta2_count,
        "meta1_raw": meta1_raw,
        "meta2_raw": meta2_raw,
    }
    return bytes(result), streaming_info


# ============================================================================
# DDS Export
# ============================================================================

# DDS header constants
DDSD_CAPS = 0x1
DDSD_HEIGHT = 0x2
DDSD_WIDTH = 0x4
DDSD_PITCH = 0x8
DDSD_PIXELFORMAT = 0x1000
DDSD_MIPMAPCOUNT = 0x20000
DDSD_LINEARSIZE = 0x80000
DDPF_FOURCC = 0x4
DDSCAPS_TEXTURE = 0x1000
DDSCAPS_MIPMAP = 0x400000
DDSCAPS_COMPLEX = 0x8
DDS_DIMENSION_TEXTURE2D = 3


def _needs_dx10_header(dxgi_fmt):
    """Check if this DXGI format requires a DX10 extended header."""
    # Legacy DDS can handle DXT1-5, BC4/BC5 via FourCC, and some uncompressed.
    # For BC6H, BC7, and many others we need DX10.
    legacy_fourcc = {
        71: b"DXT1", 72: b"DXT1",  # BC1
        74: b"DXT3", 75: b"DXT3",  # BC2
        77: b"DXT5", 78: b"DXT5",  # BC3
        80: b"ATI1",               # BC4
        83: b"ATI2",               # BC5
    }
    if dxgi_fmt in legacy_fourcc:
        return False, legacy_fourcc[dxgi_fmt]
    return True, None


def build_dds(tex, pixel_data=None, dds_array_size=1, dds_is_cube=False):
    """Build a DDS file from a G1TTexture. Returns bytes."""
    if tex.format not in G1T_TO_DXGI:
        raise ValueError("Unsupported G1T format: 0x%02X" % tex.format)

    dxgi_fmt = G1T_TO_DXGI[tex.format][0]
    w, h = tex.width, tex.height
    mips = tex.mip_count if tex.mip_count > 0 else 1
    if pixel_data is None:
        pixel_data = tex.image_data

    use_dx10, legacy_fcc = _needs_dx10_header(dxgi_fmt)
    if dds_array_size > 1 or dds_is_cube:
        use_dx10 = True
        legacy_fcc = None

    # Calculate pitch/linear size for the top mip
    ps = POINT_SIZES[tex.format] if tex.format < len(POINT_SIZES) else 0
    if is_block_compressed(tex.format):
        bw = max(1, (w + 3) // 4)
        bh = max(1, (h + 3) // 4)
        block_bytes = 8 if ps == 4 else 16
        pitch_or_linear = bw * bh * block_bytes
    else:
        pitch_or_linear = w * (ps // 8) if ps >= 8 else w

    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    if is_block_compressed(tex.format):
        flags |= DDSD_LINEARSIZE
    else:
        flags |= DDSD_PITCH
    if mips > 1:
        flags |= DDSD_MIPMAPCOUNT

    caps = DDSCAPS_TEXTURE
    if mips > 1:
        caps |= DDSCAPS_MIPMAP | DDSCAPS_COMPLEX

    # Build pixel format
    if use_dx10:
        pf_flags = DDPF_FOURCC
        pf_fourcc = DX10_FOURCC
        pf_rgb_bits = 0
        pf_rmask = pf_gmask = pf_bmask = pf_amask = 0
    elif legacy_fcc:
        pf_flags = DDPF_FOURCC
        pf_fourcc = struct.unpack("<I", legacy_fcc)[0]
        pf_rgb_bits = 0
        pf_rmask = pf_gmask = pf_bmask = pf_amask = 0
    else:
        # Uncompressed - use RGBA masks
        pf_flags = 0x41  # DDPF_RGB | DDPF_ALPHAPIXELS
        pf_fourcc = 0
        bpp = ps if ps >= 8 else 32
        pf_rgb_bits = bpp
        if dxgi_fmt in (28, 29, 30):  # R8G8B8A8
            pf_rmask, pf_gmask, pf_bmask, pf_amask = 0xFF, 0xFF00, 0xFF0000, 0xFF000000
        elif dxgi_fmt in (87, 91):  # B8G8R8A8
            pf_rmask, pf_gmask, pf_bmask, pf_amask = 0xFF0000, 0xFF00, 0xFF, 0xFF000000
        else:
            # Fallback: use DX10 header for safety
            use_dx10 = True
            pf_flags = DDPF_FOURCC
            pf_fourcc = DX10_FOURCC
            pf_rgb_bits = 0
            pf_rmask = pf_gmask = pf_bmask = pf_amask = 0

    # DDS header (128 bytes)
    hdr = struct.pack("<I", DDS_MAGIC)
    hdr += struct.pack("<I", 124)  # header size
    hdr += struct.pack("<I", flags)
    hdr += struct.pack("<I", h)
    hdr += struct.pack("<I", w)
    hdr += struct.pack("<I", pitch_or_linear)
    hdr += struct.pack("<I", 0)  # depth
    hdr += struct.pack("<I", mips)
    hdr += b"\x00" * 44  # reserved[11]
    # Pixel format (32 bytes)
    hdr += struct.pack("<I", 32)  # pf size
    hdr += struct.pack("<I", pf_flags)
    hdr += struct.pack("<I", pf_fourcc)
    hdr += struct.pack("<I", pf_rgb_bits)
    hdr += struct.pack("<I", pf_rmask)
    hdr += struct.pack("<I", pf_gmask)
    hdr += struct.pack("<I", pf_bmask)
    hdr += struct.pack("<I", pf_amask)
    # Caps
    hdr += struct.pack("<I", caps)
    hdr += struct.pack("<I", 0)  # caps2
    hdr += struct.pack("<I", 0)  # caps3
    hdr += struct.pack("<I", 0)  # caps4
    hdr += struct.pack("<I", 0)  # reserved2

    if use_dx10:
        misc_flags = DDS_RESOURCE_MISC_TEXTURECUBE if dds_is_cube else 0
        hdr += struct.pack("<I", dxgi_fmt)
        hdr += struct.pack("<I", DDS_DIMENSION_TEXTURE2D)
        hdr += struct.pack("<I", misc_flags)
        hdr += struct.pack("<I", max(1, dds_array_size))
        hdr += struct.pack("<I", 0)  # misc flags2

    return hdr + pixel_data


def export_textures(g1t_path, output_dir=None):
    """Export all textures from a G1T/G1TS file to DDS files."""
    g = load_g1t(g1t_path)
    base_name = os.path.splitext(os.path.basename(g1t_path))[0]

    if output_dir is None:
        output_dir = os.path.dirname(g1t_path) or "."

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    ver = parse_version(g.header.version)
    fmt_type = "G1TS (streaming, v%d)" % ver if g.is_streaming else "G1T (v%d)" % ver
    print("Loaded %s: %d texture(s), platform=0x%X" % (fmt_type, len(g.textures), g.header.platform))

    exported = []
    for i, tex in enumerate(g.textures):
        if tex.format not in G1T_TO_DXGI:
            print("  Texture %d: unsupported format 0x%02X, skipping" % (i, tex.format))
            continue

        dxgi = G1T_TO_DXGI[tex.format][0]
        ext = format_extension(dxgi)
        pixel_data = tex.image_data
        dds_array_size = 1
        dds_is_cube = False

        # G1T image_data is mip-major (mip->slice). DDS arrays use slice-major (slice->mip).
        slice_count = _texture_slice_count(tex)
        if tex.load_type == 2 and tex.depth > 1:
            print("  Texture %d: volume texture export keeps raw order (limited DDS support)" % i)
        elif slice_count > 1:
            mip_sizes = _mip_level_sizes(tex.format, tex.width, tex.height, tex.mip_count, tex.depth)
            try:
                pixel_data, tail = _mip_major_to_slice_major(tex.image_data, mip_sizes, slice_count)
                if tail:
                    print("  Texture %d: extra trailing bytes after expected slices (%d bytes), appending" % (
                        i, len(tail)))
                    pixel_data += tail
                dds_is_cube = _texture_is_cube(tex)
                dds_array_size = _texture_array_size(tex) if dds_is_cube else slice_count
            except ValueError as e:
                print("  Texture %d: cannot reorder array/cube data (%s), exporting raw order" % (i, e))

        out_name = "%s.TEX%d%s.dds" % (base_name, i, ext)

        out_path = os.path.join(output_dir, out_name)
        dds_data = build_dds(
            tex,
            pixel_data=pixel_data,
            dds_array_size=dds_array_size,
            dds_is_cube=dds_is_cube,
        )
        with open(out_path, "wb") as f:
            f.write(dds_data)

        print("  [%d] %dx%d %s mips=%d -> %s" % (
            i, tex.width, tex.height, dxgi_format_name(dxgi), tex.mip_count, out_name))
        exported.append(out_path)

    print("Exported %d texture(s)" % len(exported))
    return exported


# ============================================================================
# DDS Import
# ============================================================================

def parse_dds(path):
    """Parse a DDS file and return a metadata dict."""
    with open(path, "rb") as f:
        data = f.read()

    if len(data) < 128:
        raise ValueError("DDS file too small: %s" % path)

    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != DDS_MAGIC:
        raise ValueError("Not a DDS file: %s" % path)

    height = struct.unpack_from("<I", data, 12)[0]
    width = struct.unpack_from("<I", data, 16)[0]
    mips = struct.unpack_from("<I", data, 28)[0]

    # Pixel format at offset 76
    pf_flags = struct.unpack_from("<I", data, 80)[0]
    pf_fourcc = struct.unpack_from("<I", data, 84)[0]
    caps2 = struct.unpack_from("<I", data, 112)[0]

    header_size = 128
    dxgi_fmt = 0
    array_size = 1
    is_cube = (caps2 & DDSCAPS2_CUBEMAP) != 0

    if (pf_flags & DDPF_FOURCC) and pf_fourcc == DX10_FOURCC:
        # DX10 extended header
        if len(data) < 148:
            raise ValueError("DDS DX10 header missing: %s" % path)
        dxgi_fmt = struct.unpack_from("<I", data, 128)[0]
        _resource_dimension = struct.unpack_from("<I", data, 132)[0]
        misc_flags = struct.unpack_from("<I", data, 136)[0]
        array_size = struct.unpack_from("<I", data, 140)[0]
        is_cube = (misc_flags & DDS_RESOURCE_MISC_TEXTURECUBE) != 0
        header_size = 148
    elif pf_flags & DDPF_FOURCC:
        fcc_bytes = struct.pack("<I", pf_fourcc)
        fcc_map = {
            b"DXT1": 71, b"DXT2": 74, b"DXT3": 74, b"DXT4": 77, b"DXT5": 77,
            b"ATI1": 80, b"BC4U": 80, b"ATI2": 83, b"BC5U": 83,
        }
        dxgi_fmt = fcc_map.get(fcc_bytes, 0)
    else:
        # Try to determine from RGB masks
        rgb_bits = struct.unpack_from("<I", data, 88)[0]
        rmask = struct.unpack_from("<I", data, 92)[0]
        if rgb_bits == 32 and rmask == 0xFF:
            dxgi_fmt = 28  # R8G8B8A8_UNORM
        elif rgb_bits == 32 and rmask == 0xFF0000:
            dxgi_fmt = 87  # B8G8R8A8_UNORM
        else:
            dxgi_fmt = 28  # fallback

    if mips == 0:
        mips = 1

    raw_data = data[header_size:]
    return {
        "dxgi_format": dxgi_fmt,
        "width": width,
        "height": height,
        "mips": mips,
        "array_size": max(1, array_size),
        "is_cube": is_cube,
        "raw_data": raw_data,
    }


# ============================================================================
# G1T/G1TS Save
# ============================================================================

def _build_extra_header(tex):
    """Build or update extra header raw bytes from texture properties."""
    if tex.extra_header_version == 0 or not tex.extra_header_raw:
        return tex.extra_header_raw

    raw = bytearray(tex.extra_header_raw)
    ex_size = struct.unpack_from("<I", raw, 0)[0]

    if ex_size >= 0x10:
        struct.pack_into("<I", raw, 0x0C, tex.width)
    if ex_size >= 0x14:
        struct.pack_into("<I", raw, 0x10, tex.height)

    # Preserve non-streaming swizzle (commonly 0x00/0x01 in legacy G1T).
    if len(raw) > 10:
        swz = tex.swizzle_type & 0xFF
        if swz == 0x03:
            swz = 0x00
        raw[10] = swz

    return bytes(raw)


def _build_extra_header_streaming(tex):
    """Build extra header for streaming (G1TS) output, keeping swizzle=0x03."""
    if tex.extra_header_version == 0 or not tex.extra_header_raw:
        return tex.extra_header_raw

    raw = bytearray(tex.extra_header_raw)
    ex_size = struct.unpack_from("<I", raw, 0)[0]

    if ex_size >= 0x10:
        struct.pack_into("<I", raw, 0x0C, tex.width)
    if ex_size >= 0x14:
        struct.pack_into("<I", raw, 0x10, tex.height)

    if len(raw) > 10:
        raw[10] = 0x03  # ZLIB_COMPRESSED

    return bytes(raw)


def _compress_zlib_data(raw_data, window_size=65536, base_offset=0,
                        unk08=0x80, meta1_count=0, meta2_count=0,
                        meta1_raw=b"", meta2_raw=b""):
    """Compress raw texture data into ZLIB streaming format.

    base_offset: the file offset where this streaming block will be written.
    Chunk offsets in the table are absolute file offsets.
    meta1_raw/meta2_raw: preserved raw meta bytes from the original file.
    """
    total = len(raw_data)
    if window_size <= 0:
        raise ValueError("Invalid streaming window_size: %d" % window_size)

    # Determine uncompressed tail size from meta2 entries.
    # Each meta2 entry is 16 bytes; field at offset 4 is MipSize.
    # The uncompressed tail holds exactly the meta2-described mip data.
    uncomp_size = 0
    if meta2_raw:
        num_meta2_entries = len(meta2_raw) // 16
        for j in range(num_meta2_entries):
            uncomp_size += struct.unpack_from("<I", meta2_raw, j * 16 + 4)[0]

    if uncomp_size > total:
        raise ValueError(
            "Invalid streaming metadata: meta2 tail size %d exceeds data size %d" % (uncomp_size, total))

    compressed_part = total - uncomp_size
    if compressed_part % window_size != 0:
        raise ValueError(
            "Invalid streaming metadata: compressed part %d is not a multiple of window_size %d" % (
                compressed_part, window_size))
    chunk_count = compressed_part // window_size
    has_uncomp = 1 if uncomp_size > 0 else 0

    # Header: 9 * 4 = 36 bytes
    # Meta1: meta1_raw bytes
    # Meta2: meta2_raw bytes
    # Chunk table: chunk_count * 8 bytes
    # Uncomp entry: 8 bytes if has_uncomp
    table_header_size = 36 + len(meta1_raw) + len(meta2_raw) + chunk_count * 8
    if has_uncomp:
        table_header_size += 8

    # Compress each chunk (store raw if compression doesn't help)
    # Each entry is (compressed_bytes_or_None, is_raw)
    chunk_entries = []
    for j in range(chunk_count):
        chunk_data = raw_data[j * window_size:(j + 1) * window_size]
        comp = zlib.compress(chunk_data, 6)
        if len(comp) + 4 >= window_size:
            # Compressed + prefix is not smaller: store raw
            chunk_entries.append((chunk_data, True))
        else:
            chunk_entries.append((comp, False))

    # Calculate absolute file offsets for each chunk
    # Data starts at base_offset + table_header_size
    data_section_start = base_offset + table_header_size
    chunk_offsets = []
    current_offset = data_section_start
    for entry_data, is_raw in chunk_entries:
        chunk_offsets.append(current_offset)
        if is_raw:
            current_offset += window_size  # raw data, no prefix
        else:
            current_offset += 4 + len(entry_data)  # 4-byte size prefix + compressed data

    uncomp_offset = current_offset if has_uncomp else 0

    # Build streaming table
    table = bytearray()
    table += struct.pack("<I", ZLIB_MAGIC)
    table += struct.pack("<I", table_header_size)
    table += struct.pack("<I", unk08)
    table += struct.pack("<I", window_size)
    table += struct.pack("<I", meta1_count)
    table += struct.pack("<I", chunk_count)
    table += struct.pack("<I", meta2_count)
    table += struct.pack("<I", has_uncomp)
    table += struct.pack("<I", uncomp_size)

    # Meta1 and Meta2 raw entries
    table += meta1_raw
    table += meta2_raw

    # Chunk table (c_size = window_size for raw, compressed_len + 4 for compressed)
    for j in range(chunk_count):
        entry_data, is_raw = chunk_entries[j]
        table += struct.pack("<I", chunk_offsets[j])
        if is_raw:
            table += struct.pack("<I", window_size)
        else:
            table += struct.pack("<I", len(entry_data) + 4)

    if has_uncomp:
        table += struct.pack("<I", uncomp_offset)
        table += struct.pack("<I", uncomp_size)

    # Build data section
    data_section = bytearray()
    for entry_data, is_raw in chunk_entries:
        if is_raw:
            data_section += entry_data
        else:
            data_section += struct.pack("<I", len(entry_data))
            data_section += entry_data

    if has_uncomp:
        data_section += raw_data[chunk_count * window_size:]

    return bytes(table) + bytes(data_section)


def _collect_normal_flags(g):
    """Collect per-texture normal flags with texture values preferred."""
    flags = []
    n = len(g.textures)
    for i in range(n):
        if i < len(g.textures) and hasattr(g.textures[i], "normal_flags"):
            flags.append(g.textures[i].normal_flags & 0xFFFFFFFF)
        elif i < len(g.header.normal_flags):
            flags.append(g.header.normal_flags[i] & 0xFFFFFFFF)
        else:
            flags.append(0)
    return flags


def _estimate_texture_record_size(tex, streaming):
    """Estimate texture record byte size for layout decisions."""
    size = 8
    if tex.extra_header_version > 0:
        size += len(tex.extra_header_raw)

    if streaming:
        comp = _compress_zlib_data(
            tex.image_data,
            window_size=tex.streaming_window_size,
            base_offset=0,
            unk08=tex.streaming_unk08,
            meta1_count=tex.streaming_meta1_count,
            meta2_count=tex.streaming_meta2_count,
            meta1_raw=tex.streaming_meta1_raw,
            meta2_raw=tex.streaming_meta2_raw,
        )
        size += len(comp)
    else:
        size += len(tex.image_data)

    return size


def save_g1t(g, path, force_streaming=None):
    """Save a G1TFile to disk.

    force_streaming: None = auto-detect from original, True = G1TS, False = G1T
    """
    streaming = g.is_streaming if force_streaming is None else force_streaming
    normal_flags = _collect_normal_flags(g)
    global_meta = g.header.global_metadata if g.header.global_metadata else b""
    tex_count = len(g.textures)
    trailing_raw = g.header.trailing_raw if g.header.trailing_raw else b""
    header_size = 0x1C

    out = bytearray()

    # Header (0x1C bytes) + NormalFlags + OffsetTable + Metadata
    out += struct.pack("<I", G1T_MAGIC)
    out += b"6600" if streaming else g.header.version
    file_size_pos = len(out)
    out += struct.pack("<I", 0)  # placeholder for file_size
    table_offset_pos = len(out)
    out += struct.pack("<I", 0)  # placeholder for table_offset
    out += struct.pack("<I", tex_count)
    out += struct.pack("<I", g.header.platform)
    out += struct.pack("<I", len(global_meta))
    for flag in normal_flags:
        out += struct.pack("<I", flag)
    table_start = header_size + tex_count * 4
    offset_table_pos = len(out)
    out += b"\x00" * (tex_count * 4)
    out += global_meta
    struct.pack_into("<I", out, table_offset_pos, table_start)

    # Texture entries
    offsets = []
    for i, tex in enumerate(g.textures):
        offsets.append(len(out) - table_start)

        # MipSys byte
        mip_count = tex.mip_count if tex.mip_count > 0 else 1
        mip_sys = (mip_count << 4) | (tex.load_type & 0x0F)
        out += struct.pack("B", mip_sys)
        out += struct.pack("B", tex.format)

        # DxDy
        wlog = int(math.log(tex.width, 2)) if tex.width > 0 else 0
        hlog = int(math.log(tex.height, 2)) if tex.height > 0 else 0
        calc_dxdy = ((hlog << 4) | (wlog & 0x0F)) & 0xFF
        # Keep original packed DxDy when present; some files store non-canonical base values
        # and rely on extra-header width/height instead.
        if tex.packed_dxdy is not None:
            dxdy_byte = tex.packed_dxdy & 0xFF
        else:
            dxdy_byte = calc_dxdy
        out += struct.pack("B", dxdy_byte)

        # Depth
        dlog = int(math.log(tex.depth, 2)) if tex.depth > 0 else 0
        if tex.packed_depth_ex is not None:
            d_ex_byte = (tex.packed_depth_ex & 0xF0) | (dlog & 0x0F)
        else:
            d_ex_byte = dlog & 0x0F
        out += struct.pack("B", d_ex_byte)

        # Metadata
        out += tex.metadata[:3] if len(tex.metadata) >= 3 else tex.metadata + b"\x00" * (3 - len(tex.metadata))
        out += struct.pack("B", tex.extra_header_version)

        # Extra header
        if tex.extra_header_version > 0:
            if streaming:
                ex_raw = _build_extra_header_streaming(tex)
            else:
                ex_raw = _build_extra_header(tex)
            out += ex_raw

        # Texture data
        if streaming:
            if getattr(tex, "streaming_decode_failed", False):
                raise ValueError(
                    "Cannot recompress streaming texture after decode failure")
            tex_data_for_disk = tex.image_data
            if tex.d3d12_tiled:
                tex_data_for_disk = _apply_d3d12_tiling_transform(
                    tex, tex.image_data, g.header.platform, to_linear=False)
            compressed = _compress_zlib_data(
                tex_data_for_disk,
                window_size=tex.streaming_window_size,
                base_offset=len(out),
                unk08=tex.streaming_unk08,
                meta1_count=tex.streaming_meta1_count,
                meta2_count=tex.streaming_meta2_count,
                meta1_raw=tex.streaming_meta1_raw,
                meta2_raw=tex.streaming_meta2_raw,
            )
            out += compressed
        else:
            tex_data_for_disk = tex.image_data
            if tex.d3d12_tiled:
                tex_data_for_disk = _apply_d3d12_tiling_transform(
                    tex, tex.image_data, g.header.platform, to_linear=False)
            out += tex_data_for_disk

    # Write offsets
    for i, off in enumerate(offsets):
        struct.pack_into("<I", out, offset_table_pos + i * 4, off)

    if trailing_raw:
        out += trailing_raw

    # Write file size
    file_size_to_write = len(out)
    if trailing_raw and g.header.original_physical_size > 0:
        if g.header.file_size + len(trailing_raw) == g.header.original_physical_size:
            file_size_to_write = len(out) - len(trailing_raw)
    struct.pack_into("<I", out, file_size_pos, file_size_to_write)

    with open(path, "wb") as f:
        f.write(out)

    print("Saved %s (%d bytes)" % (path, len(out)))


def import_textures(g1t_path, dds_input, output_path=None):
    """Import DDS file(s) into a G1T/G1TS file.

    dds_input: path to a single .dds file, a directory, or a list of .dds paths
    output_path: if None, write to <g1t_dir>/output/<g1t_name>
    """
    g = load_g1t(g1t_path)

    if output_path is None:
        output_dir = os.path.join(os.path.dirname(g1t_path) or ".", "output")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        output_path = os.path.join(output_dir, os.path.basename(g1t_path))

    replaced = 0

    if isinstance(dds_input, (list, tuple)):
        dds_files = list(dds_input)
        if not dds_files:
            print("No .dds files provided for %s" % g1t_path)
            return 0

        used_indices = set()
        for dds_path in dds_files:
            fn = os.path.basename(dds_path)
            idx = _parse_tex_index(fn, len(g.textures))
            if idx is None:
                if len(g.textures) == 1:
                    idx = 0
                else:
                    print("  Cannot determine index for %s, skipping" % fn)
                    continue
            if idx in used_indices:
                print("  Duplicate texture index %d in %s, skipping" % (idx, fn))
                continue
            if _replace_texture(g, idx, dds_path):
                used_indices.add(idx)
                replaced += 1
    elif os.path.isdir(dds_input):
        # Directory mode: find matching DDS files
        dds_files = _collect_dds_files(dds_input, recursive=True)
        if not dds_files:
            print("No .dds files found in %s" % dds_input)
            return 0

        used_indices = set()
        for dds_path in dds_files:
            fn = os.path.basename(dds_path)
            # Try to extract texture index from filename like "Tex 0.dxt1.dds"
            idx = _parse_tex_index(fn, len(g.textures))
            if idx is None:
                if len(g.textures) == 1:
                    idx = 0
                else:
                    print("  Cannot determine index for %s, skipping" % fn)
                    continue
            if idx in used_indices:
                print("  Duplicate texture index %d in %s, skipping" % (idx, fn))
                continue
            if _replace_texture(g, idx, dds_path):
                used_indices.add(idx)
                replaced += 1
    else:
        # Single file mode
        if len(g.textures) == 0:
            print("G1T file has no textures")
            return 0
        if _replace_texture(g, 0, dds_input):
            replaced += 1

    if replaced <= 0:
        print("No textures were replaced for %s" % os.path.basename(g1t_path))
        return 0

    save_g1t(g, output_path)
    return replaced


def _parse_tex_index(filename, num_textures):
    """Try to extract texture index from a DDS filename."""
    idx = _extract_tex_index(filename)
    if idx is None:
        return None
    return idx if idx < num_textures else None


def _replace_texture(g, idx, dds_path):
    """Replace texture at index with data from a DDS file."""
    if idx >= len(g.textures):
        print("  Index %d out of range, skipping %s" % (idx, dds_path))
        return False

    tex = g.textures[idx]
    dds = parse_dds(dds_path)
    dxgi_fmt = dds["dxgi_format"]
    dds_w = dds["width"]
    dds_h = dds["height"]
    dds_mips = dds["mips"]
    raw_data = dds["raw_data"]
    dds_slices = max(1, dds["array_size"]) * (6 if dds["is_cube"] else 1)

    # Map DXGI format to G1T format
    prev_fmt = tex.format
    if dxgi_fmt in DXGI_TO_G1T:
        new_g1t_fmt = DXGI_TO_G1T[dxgi_fmt]
    else:
        print("  Unsupported DXGI format %d in %s" % (dxgi_fmt, dds_path))
        return False

    # Check if format changed
    prev_dxgi = G1T_TO_DXGI.get(prev_fmt, (0, 0))[0]
    format_changed = prev_dxgi != dxgi_fmt
    target_fmt = new_g1t_fmt if format_changed else prev_fmt
    if prev_dxgi != dxgi_fmt:
        print("  [%d] Format changed: %s -> %s" % (
            idx, dxgi_format_name(prev_dxgi), dxgi_format_name(dxgi_fmt)))

    tex_slice_count = _texture_slice_count(tex)
    converted_data = raw_data

    if tex.load_type == 2 and tex.depth > 1:
        if dds_slices != 1:
            print("  [%d] Volume textures require non-array DDS input, skipping %s" % (idx, dds_path))
            return False
    elif tex_slice_count > 1:
        # Backward compatibility with old exports that wrote combined mip-major blob as 1 slice.
        if dds_slices == 1 and len(raw_data) == len(tex.image_data):
            print("  [%d] Detected legacy single-slice DDS blob for array/cube texture, using raw order" % idx)
            converted_data = raw_data
        else:
            if dds_slices != tex_slice_count:
                print("  [%d] Slice count mismatch: texture expects %d, DDS has %d, skipping %s" % (
                    idx, tex_slice_count, dds_slices, dds_path))
                return False

            mip_sizes = _mip_level_sizes(target_fmt, dds_w, dds_h, dds_mips, tex.depth)

            # Limit mips to original count if new has more
            if dds_mips > tex.mip_count and tex.mip_count > 0:
                try:
                    raw_data, mip_sizes = _truncate_slice_major_mips(
                        raw_data, mip_sizes, dds_slices, tex.mip_count)
                    dds_mips = tex.mip_count
                except ValueError as e:
                    print("  [%d] Cannot truncate DDS mips (%s), skipping %s" % (idx, e, dds_path))
                    return False

            try:
                converted_data, tail = _slice_major_to_mip_major(raw_data, mip_sizes, dds_slices)
                if tail:
                    print("  [%d] Ignoring %d trailing DDS bytes after expected slice data" % (idx, len(tail)))
            except ValueError as e:
                print("  [%d] Cannot convert DDS array/cube layout (%s), skipping %s" % (idx, e, dds_path))
                return False
    else:
        if dds_slices != 1:
            print("  [%d] Cannot import array/cube DDS into non-array texture, skipping %s" % (idx, dds_path))
            return False

        # Limit mips to original count if new has more
        if dds_mips > tex.mip_count and tex.mip_count > 0:
            truncated_size = sum(_mip_level_sizes(target_fmt, dds_w, dds_h, tex.mip_count, tex.depth))
            if truncated_size <= len(raw_data):
                converted_data = raw_data[:truncated_size]
                dds_mips = tex.mip_count

    # For G1TS textures, preserve streaming metadata safety:
    # without full meta regeneration support, only size-invariant replacements are safe.
    old_mips = tex.mip_count if tex.mip_count > 0 else 1
    new_mips = dds_mips if dds_mips > 0 else 1
    if g.is_streaming and tex.swizzle_type == 0x03:
        if (target_fmt != prev_fmt or dds_w != tex.width or dds_h != tex.height or
                new_mips != old_mips or len(converted_data) != len(tex.image_data)):
            print("  [%d] G1TS streaming replacement requires same format/size/mips/data length; "
                  "metadata regeneration is not implemented, skipping %s" % (idx, dds_path))
            return False

    if format_changed:
        tex.format = target_fmt

    tex.width = dds_w
    tex.height = dds_h
    tex.mip_count = dds_mips
    tex.image_data = converted_data
    tex.streaming_decode_failed = False
    tex.streaming_decode_error = ""

    print("  [%d] Replaced: %dx%d %s mips=%d from %s" % (
        idx, dds_w, dds_h, dxgi_format_name(dxgi_fmt), dds_mips,
        os.path.basename(dds_path)))
    return True


# ============================================================================
# CLI
# ============================================================================

def _batch_output_path(src_path, input_root, output_root):
    """Build output path for batch import, preserving relative layout."""
    if output_root is None:
        return None
    rel = os.path.relpath(src_path, input_root)
    out_path = os.path.join(output_root, rel)
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir)
    return out_path


def run_export(input_path, output_dir=None):
    """Run export command for one file or a directory tree."""
    if not os.path.isdir(input_path):
        ok, reason = _is_gt1g_magic(input_path)
        if not ok:
            print("Skipped %s: %s" % (input_path, reason))
            return
        export_textures(input_path, output_dir)
        return

    all_candidates = _collect_g1t_files(input_path)
    if not all_candidates:
        print("No .g1t/.g1ts files found in %s" % input_path)
        return
    g1t_files, invalid_magic = _split_magic_valid_g1t(all_candidates)
    if not g1t_files:
        _print_magic_skip_summary(invalid_magic, input_path)
        print("No GT1G files found in %s" % input_path)
        return

    ok = 0
    failed = 0
    print("Batch export: %d file(s)" % len(g1t_files))
    for idx, g1t_path in enumerate(g1t_files):
        if idx:
            print("")
        try:
            per_output = output_dir
            if output_dir is not None:
                rel_dir = os.path.relpath(os.path.dirname(g1t_path), input_path)
                per_output = output_dir if rel_dir == "." else os.path.join(output_dir, rel_dir)
            export_textures(g1t_path, per_output)
            ok += 1
        except Exception as e:
            failed += 1
            print("Failed to export %s: %s" % (g1t_path, e))

    print("")
    _print_magic_skip_summary(invalid_magic, input_path)
    print("Batch export finished: %d succeeded, %d failed, %d skipped_non_g1t_magic" % (
        ok, failed, len(invalid_magic)))


def run_import(input_path, output_path=None):
    """Run import command for a directory by per-file DDS matching."""
    if not os.path.isdir(input_path):
        print("Import now expects <input_dir> containing both .g1t/.g1ts and .dds files.")
        return

    all_candidates = _collect_g1t_files(input_path)
    if not all_candidates:
        print("No .g1t/.g1ts files found in %s" % input_path)
        return
    g1t_files, invalid_magic = _split_magic_valid_g1t(all_candidates)
    if not g1t_files:
        _print_magic_skip_summary(invalid_magic, input_path)
        print("No GT1G files found in %s" % input_path)
        return

    if output_path is None:
        output_path = os.path.join(input_path, "output")
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    matched = 0
    skipped = 0
    failed = 0
    print("Batch import: %d g1t/g1ts" % len(g1t_files))
    for g1t_path in g1t_files:
        dds_candidates = _find_matching_dds_for_g1t(g1t_path)
        if not dds_candidates:
            skipped += 1
            continue

        out_path = _batch_output_path(g1t_path, input_path, output_path)
        try:
            replaced = import_textures(g1t_path, dds_candidates, out_path)
            if replaced > 0:
                matched += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            print("Failed to import %s: %s" % (g1t_path, e))

    _print_magic_skip_summary(invalid_magic, input_path)
    print("Batch import finished: %d matched, %d skipped, %d failed, %d skipped_non_g1t_magic" % (
        matched, skipped, failed, len(invalid_magic)))


def run_info(input_path):
    """Run info command for one file or a directory tree."""
    if not os.path.isdir(input_path):
        ok, reason = _is_gt1g_magic(input_path)
        if not ok:
            print("Skipped %s: %s" % (input_path, reason))
            return
        show_info(input_path)
        return

    all_candidates = _collect_g1t_files(input_path)
    if not all_candidates:
        print("No .g1t/.g1ts files found in %s" % input_path)
        return
    g1t_files, invalid_magic = _split_magic_valid_g1t(all_candidates)
    if not g1t_files:
        _print_magic_skip_summary(invalid_magic, input_path)
        print("No GT1G files found in %s" % input_path)
        return

    ok = 0
    failed = 0
    print("Batch info: %d file(s)" % len(g1t_files))
    for idx, g1t_path in enumerate(g1t_files):
        if idx:
            print("")
        try:
            show_info(g1t_path)
            ok += 1
        except Exception as e:
            failed += 1
            print("Failed to read %s: %s" % (g1t_path, e))

    print("")
    _print_magic_skip_summary(invalid_magic, input_path)
    print("Batch info finished: %d succeeded, %d failed, %d skipped_non_g1t_magic" % (
        ok, failed, len(invalid_magic)))


def main():
    parser = argparse.ArgumentParser(
        description="G1T/G1TS Texture Tool - Export and import DDS textures")
    sub = parser.add_subparsers(dest="command")

    # Export
    p_export = sub.add_parser("export", help="Export textures to DDS")
    p_export.add_argument("input", help="Input G1T/G1TS file or directory")
    p_export.add_argument("output_dir", nargs="?", default=None,
                          help="Output directory (batch: keeps input relative layout)")

    # Import
    p_import = sub.add_parser("import", help="Import DDS textures into G1T/G1TS")
    p_import.add_argument("input", help="Input directory containing G1T/G1TS and DDS files")
    p_import.add_argument("output", nargs="?", default=None,
                          help="Output directory; default: <input>/output")

    # Info
    p_info = sub.add_parser("info", help="Show G1T/G1TS file information")
    p_info.add_argument("input", help="Input G1T/G1TS file or directory")

    args = parser.parse_args()

    if args.command == "export":
        run_export(args.input, args.output_dir)
    elif args.command == "import":
        run_import(args.input, args.output)
    elif args.command == "info":
        run_info(args.input)
    else:
        parser.print_help()


def show_info(path):
    """Display information about a G1T/G1TS file."""
    g = load_g1t(path)
    h = g.header
    ver = parse_version(h.version)
    fmt_type = "G1TS (streaming)" if g.is_streaming else "G1T"

    print("File: %s" % path)
    print("Type: %s" % fmt_type)
    print("Version: %s (v%d)" % (h.version.decode("ascii", errors="replace"), ver))
    print("FileSize: 0x%X (%d)" % (h.file_size, h.file_size))
    print("Platform: 0x%X" % h.platform)
    print("Textures: %d" % len(g.textures))

    for i, tex in enumerate(g.textures):
        dxgi = G1T_TO_DXGI.get(tex.format, (0, 0))[0]
        print("  [%d] %dx%d fmt=0x%02X(%s) mips=%d load=%d swizzle=0x%02X data=%d bytes" % (
            i, tex.width, tex.height, tex.format, dxgi_format_name(dxgi),
            tex.mip_count, tex.load_type, tex.swizzle_type, len(tex.image_data)))


if __name__ == "__main__":
    main()
