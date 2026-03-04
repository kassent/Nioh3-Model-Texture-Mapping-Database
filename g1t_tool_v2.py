#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
G1T/G1TS Texture Tool
=====================
Export G1T/G1TS textures to DDS files and import DDS files back.

Usage:
    python g1t_tool.py export <input_path> [output_dir]
    python g1t_tool.py import <input_dir> [output_dir]
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import sys
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


GT1G_MAGIC = b"GT1G"
STREAMING_MAGIC = 0x30303030  # ASCII "0000"
DDS_MAGIC = b"DDS "


# G1T load type (low nibble of MipSys)
LOAD_PLANAR = 0
LOAD_CUBE = 1
LOAD_VOLUME = 2
LOAD_PLANE_ARRAY = 3
LOAD_CUBE_ARRAY = 4


# DDS / D3D constants
DDSD_CAPS = 0x1
DDSD_HEIGHT = 0x2
DDSD_WIDTH = 0x4
DDSD_PITCH = 0x8
DDSD_PIXELFORMAT = 0x1000
DDSD_MIPMAPCOUNT = 0x20000
DDSD_LINEARSIZE = 0x80000
DDSD_DEPTH = 0x800000

DDSCAPS_COMPLEX = 0x8
DDSCAPS_TEXTURE = 0x1000
DDSCAPS_MIPMAP = 0x400000

DDSCAPS2_CUBEMAP = 0x200
DDSCAPS2_CUBEMAP_ALLFACES = 0xFC00
DDSCAPS2_VOLUME = 0x200000

DDPF_FOURCC = 0x4
DDPF_RGB = 0x40
DDPF_ALPHA = 0x2
DDPF_ALPHAPIXELS = 0x1

D3D10_RESOURCE_DIMENSION_TEXTURE2D = 3
D3D10_RESOURCE_DIMENSION_TEXTURE3D = 4
DDS_RESOURCE_MISC_TEXTURECUBE = 0x4
PLATFORM_PS4 = 0x0B
PLATFORM_WIN_DX12 = 0x0E


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def le_u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def pack_u32(v: int) -> bytes:
    return struct.pack("<I", v)


@dataclass(frozen=True)
class DxgiFormatInfo:
    name: str
    block_compressed: bool
    block_bytes: int = 0
    bytes_per_pixel: int = 0


# Only formats required by current documented mapping.
DXGI_INFO: Dict[int, DxgiFormatInfo] = {
    71: DxgiFormatInfo("BC1_UNORM", True, block_bytes=8),
    74: DxgiFormatInfo("BC2_UNORM", True, block_bytes=16),
    77: DxgiFormatInfo("BC3_UNORM", True, block_bytes=16),
    80: DxgiFormatInfo("BC4_UNORM", True, block_bytes=8),
    83: DxgiFormatInfo("BC5_UNORM", True, block_bytes=16),
    95: DxgiFormatInfo("BC6H_UF16", True, block_bytes=16),
    98: DxgiFormatInfo("BC7_UNORM", True, block_bytes=16),
    28: DxgiFormatInfo("R8G8B8A8_UNORM", False, bytes_per_pixel=4),
    87: DxgiFormatInfo("B8G8R8A8_UNORM", False, bytes_per_pixel=4),
    41: DxgiFormatInfo("R32_FLOAT", False, bytes_per_pixel=4),
    10: DxgiFormatInfo("R16G16B16A16_FLOAT", False, bytes_per_pixel=8),
    2: DxgiFormatInfo("R32G32B32A32_FLOAT", False, bytes_per_pixel=16),
    65: DxgiFormatInfo("A8_UNORM", False, bytes_per_pixel=1),
    61: DxgiFormatInfo("R8_UNORM", False, bytes_per_pixel=1),
    54: DxgiFormatInfo("R16_FLOAT", False, bytes_per_pixel=2),
}

# G1T format -> DXGI format
G1T_TO_DXGI: Dict[int, int] = {
    0x06: 71,
    0x10: 71,
    0x59: 71,
    0x60: 71,
    0x07: 74,
    0x11: 74,
    0x5A: 74,
    0x61: 74,
    0x08: 77,
    0x12: 77,
    0x5B: 77,
    0x62: 77,
    0x5C: 80,
    0x63: 80,
    0x5D: 83,
    0x64: 83,
    0x5E: 95,
    0x65: 95,
    0x5F: 98,
    0x66: 98,
    0x00: 28,
    0x09: 28,
    0x01: 87,
    0x0A: 87,
    0x02: 41,
    0x0B: 41,
    0x03: 10,
    0x0C: 10,
    0x04: 2,
    0x0D: 2,
    0x0F: 65,
    0x18: 65,
    0x2A: 61,
    0x72: 61,
    0x6A: 54,
}

# Canonical G1T format when DXGI->G1T conversion is needed.
DXGI_TO_G1T_CANONICAL: Dict[int, int] = {
    71: 0x59,
    74: 0x5A,
    77: 0x5B,
    80: 0x5C,
    83: 0x5D,
    95: 0x5E,
    98: 0x5F,
    28: 0x00,
    87: 0x01,
    41: 0x02,
    10: 0x03,
    2: 0x04,
    65: 0x0F,
    61: 0x2A,
    54: 0x6A,
}

LEGACY_FOURCC_TO_DXGI = {
    b"DXT1": 71,
    b"DXT3": 74,
    b"DXT5": 77,
    b"ATI1": 80,
    b"BC4U": 80,
    b"ATI2": 83,
    b"BC5U": 83,
}

DXGI_TO_LEGACY_FOURCC = {
    71: b"DXT1",
    74: b"DXT3",
    77: b"DXT5",
    80: b"ATI1",
    83: b"ATI2",
}

DXGI_SUFFIX = {
    87: "rgba",
    71: "dxt1",
    74: "dxt3",
    77: "dxt5",
    80: "bc4",
    83: "bc5",
    95: "bc6h",
    98: "bc7",
}

LOAD_TYPE_NAMES = {
    LOAD_PLANAR: "PLANAR",
    LOAD_CUBE: "CUBE",
    LOAD_VOLUME: "VOLUME",
    LOAD_PLANE_ARRAY: "PLANE_ARRAY",
    LOAD_CUBE_ARRAY: "CUBE_ARRAY",
}


def calc_mip_size(dxgi_fmt: int, width: int, height: int) -> int:
    info = DXGI_INFO.get(dxgi_fmt)
    if not info:
        raise ValueError("Unsupported DXGI format: {}".format(dxgi_fmt))
    if info.block_compressed:
        bw = max(1, (width + 3) // 4)
        bh = max(1, (height + 3) // 4)
        return bw * bh * info.block_bytes
    return width * height * info.bytes_per_pixel


def calc_total_size_2d(dxgi_fmt: int, width: int, height: int, mip_count: int, slices: int) -> int:
    total = 0
    for mip in range(mip_count):
        w = max(1, width >> mip)
        h = max(1, height >> mip)
        total += calc_mip_size(dxgi_fmt, w, h) * slices
    return total


def calc_total_size_3d(dxgi_fmt: int, width: int, height: int, depth: int, mip_count: int) -> int:
    total = 0
    for mip in range(mip_count):
        w = max(1, width >> mip)
        h = max(1, height >> mip)
        d = max(1, depth >> mip)
        total += calc_mip_size(dxgi_fmt, w, h) * d
    return total


def mip_sizes_2d(dxgi_fmt: int, width: int, height: int, mip_count: int) -> List[int]:
    out = []
    for mip in range(mip_count):
        out.append(calc_mip_size(dxgi_fmt, max(1, width >> mip), max(1, height >> mip)))
    return out


def platform_mip_alignment(platform: int) -> int:
    # Kept consistent with prior reverse-engineered behavior.
    if platform == PLATFORM_PS4:
        return 1024
    if platform == PLATFORM_WIN_DX12:
        return 4096
    return 0


def mip_sizes_2d_platform(
    dxgi_fmt: int, width: int, height: int, mip_count: int, platform: int
) -> List[int]:
    out = []
    align = platform_mip_alignment(platform)
    for mip in range(mip_count):
        sz = calc_mip_size(dxgi_fmt, max(1, width >> mip), max(1, height >> mip))
        if align:
            sz = (sz + align - 1) & ~(align - 1)
        out.append(sz)
    return out


def bytes_per_bc_block(dxgi_fmt: int) -> int:
    info = DXGI_INFO.get(dxgi_fmt)
    if not info or not info.block_compressed:
        return 0
    return info.block_bytes


def deswizzle_d3d12_64kb_bc(src: bytes, width: int, height: int, dxgi_fmt: int) -> bytes:
    bpb = bytes_per_bc_block(dxgi_fmt)
    if bpb == 0:
        return src

    block_w = (width + 3) // 4
    block_h = (height + 3) // 4
    dst = bytearray(len(src))

    tile_row_bytes = 1024
    tile_width = tile_row_bytes // bpb
    tile_height = 64
    if tile_width <= 0:
        return src

    tiles_x = (block_w + tile_width - 1) // tile_width
    tiles_y = (block_h + tile_height - 1) // tile_height

    src_pos = 0
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            x_off = tx * tile_width
            if x_off >= block_w:
                continue
            copy_blocks = min(tile_width, block_w - x_off)
            copy_bytes = copy_blocks * bpb

            y0 = ty * tile_height
            rows = min(tile_height, block_h - y0)
            if rows <= 0:
                continue

            for row in range(rows):
                y = y0 + row
                dst_row_off = y * block_w * bpb
                dst_off = dst_row_off + x_off * bpb
                src_row_off = src_pos
                src_pos += copy_bytes

                if src_row_off + copy_bytes <= len(src) and dst_off + copy_bytes <= len(dst):
                    dst[dst_off:dst_off + copy_bytes] = src[src_row_off:src_row_off + copy_bytes]

    if src_pos < len(src):
        tail = min(len(src) - src_pos, len(dst) - src_pos)
        if tail > 0:
            dst[src_pos:src_pos + tail] = src[src_pos:src_pos + tail]

    return bytes(dst)


def swizzle_d3d12_64kb_bc(src: bytes, width: int, height: int, dxgi_fmt: int) -> bytes:
    bpb = bytes_per_bc_block(dxgi_fmt)
    if bpb == 0:
        return src

    block_w = (width + 3) // 4
    block_h = (height + 3) // 4
    dst = bytearray(len(src))

    tile_row_bytes = 1024
    tile_width = tile_row_bytes // bpb
    tile_height = 64
    if tile_width <= 0:
        return src

    tiles_x = (block_w + tile_width - 1) // tile_width
    tiles_y = (block_h + tile_height - 1) // tile_height

    dst_pos = 0
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            x_off = tx * tile_width
            if x_off >= block_w:
                continue
            copy_blocks = min(tile_width, block_w - x_off)
            copy_bytes = copy_blocks * bpb

            y0 = ty * tile_height
            rows = min(tile_height, block_h - y0)
            if rows <= 0:
                continue

            for row in range(rows):
                y = y0 + row
                src_row_off = y * block_w * bpb
                src_off = src_row_off + x_off * bpb
                dst_row_off = dst_pos
                dst_pos += copy_bytes

                if src_off + copy_bytes <= len(src) and dst_row_off + copy_bytes <= len(dst):
                    dst[dst_row_off:dst_row_off + copy_bytes] = src[src_off:src_off + copy_bytes]

    if dst_pos < len(dst):
        tail = min(len(src) - dst_pos, len(dst) - dst_pos)
        if tail > 0:
            dst[dst_pos:dst_pos + tail] = src[dst_pos:dst_pos + tail]

    return bytes(dst)


def is_power_of_two(x: int) -> bool:
    return x > 0 and (x & (x - 1)) == 0


def ilog2_pow2(x: int) -> int:
    if not is_power_of_two(x):
        raise ValueError("Value is not power of two: {}".format(x))
    return x.bit_length() - 1


def strip_multi_ext(filename: str) -> str:
    stem = filename
    while True:
        s, ext = os.path.splitext(stem)
        if not ext:
            return stem
        stem = s


def ensure_dir(path: str) -> None:
    if not os.path.isdir(path):
        os.makedirs(path)


def format_size_human(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(max(0, size_bytes))
    idx = 0
    while value >= 1024.0 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    return "{:.1f}{}".format(value, units[idx])


def parse_texture_index_from_dds_name(name: str) -> Optional[int]:
    # Accept both stems and full filenames, including multi-suffix forms:
    #   0x2D86652D.TEX0.bc7.dds
    #   0x2D86652D.TEX0
    #   Tex 0
    candidates = [
        name,
        os.path.splitext(name)[0],
        strip_multi_ext(name),
    ]
    patterns = [
        r"\.(?:TEX|TEXTURE)\s*(\d+)(?:\.|$)",
        r"^(?:Tex|Arr)\s*(\d+)(?:\.|$)",
        r"^(\d+)(?:\.|$)",
    ]
    for cand in candidates:
        for pat in patterns:
            m = re.search(pat, cand, flags=re.IGNORECASE)
            if m:
                return int(m.group(1))
    return None


def g1t_compute_total_layers(load_type: int, ex_array: int) -> int:
    if load_type == LOAD_PLANAR:
        layers = 1
    elif load_type == LOAD_PLANE_ARRAY:
        layers = max(1, ex_array)
    elif load_type == LOAD_VOLUME:
        layers = max(1, 1 << ex_array)
    elif load_type == LOAD_CUBE:
        layers = 1
    elif load_type == LOAD_CUBE_ARRAY:
        layers = max(1, ex_array)
    else:
        layers = 1

    if load_type in (LOAD_CUBE, LOAD_CUBE_ARRAY):
        layers *= 6
    return layers


def g1t_compute_meta_stride(depth: int, load_type: int, ex_array: int, ex_faces: int) -> int:
    faces = ex_faces or 1
    total_layers = g1t_compute_total_layers(load_type, ex_array)
    return max(1, depth) * max(1, total_layers) * max(1, faces)


def g1t_slice_count_for_2d(load_type: int, depth: int, ex_array: int, ex_faces: int) -> int:
    if load_type == LOAD_VOLUME:
        # volume texture is represented as 3D, not 2D array slices
        return 1
    faces = ex_faces or 1
    layers = g1t_compute_total_layers(load_type, ex_array)
    return max(1, depth) * max(1, layers) * max(1, faces)


def expected_texture_data_size(tex: "TextureEntry") -> Optional[int]:
    dxgi = G1T_TO_DXGI.get(tex.format_id)
    if dxgi not in DXGI_INFO:
        return None
    if tex.load_type == LOAD_VOLUME:
        return calc_total_size_3d(dxgi, tex.width, tex.height, tex.depth, tex.mip_count)
    return calc_total_size_2d(dxgi, tex.width, tex.height, tex.mip_count, tex.slice_count_for_dds())


def texture_uses_d3d12_tiling(tex: "TextureEntry", platform: int) -> bool:
    # Strict rule: use extra-header swizzle bit0 as tiled-layout indicator.
    # 0x01 = DX12_64KB tiled, 0x03 = ZLIB stream + tiled.
    _ = platform
    return (tex.ex_packed_flags & 0x01) != 0


def apply_d3d12_tiling_transform(
    tex: "TextureEntry", pixel_data: bytes, platform: int, to_linear: bool
) -> bytes:
    # 3D texture swizzle layout is currently out of scope.
    if tex.depth > 1:
        return pixel_data

    try:
        dxgi_fmt = tex.dxgi_format()
    except Exception:
        return pixel_data

    if bytes_per_bc_block(dxgi_fmt) == 0:
        return pixel_data

    mip_count = max(1, tex.mip_count)
    slice_count = tex.slice_count_for_dds()
    mip_sizes = mip_sizes_2d_platform(dxgi_fmt, tex.width, tex.height, mip_count, platform)

    expected = sum(mip_sizes) * slice_count
    if expected > len(pixel_data):
        return pixel_data

    out = bytearray()
    pos = 0
    for mip, sz in enumerate(mip_sizes):
        mw = max(1, tex.width >> mip)
        mh = max(1, tex.height >> mip)
        for _ in range(slice_count):
            chunk = pixel_data[pos:pos + sz]
            pos += sz
            if sz > 65536:
                chunk = (
                    deswizzle_d3d12_64kb_bc(chunk, mw, mh, dxgi_fmt)
                    if to_linear
                    else swizzle_d3d12_64kb_bc(chunk, mw, mh, dxgi_fmt)
                )
            out.extend(chunk)

    if pos < len(pixel_data):
        out.extend(pixel_data[pos:])
    return bytes(out)


def reorder_mip_major_to_slice_major(data: bytes, mip_sizes: Sequence[int], slices: int) -> bytes:
    # G1T stores array/cube as mip-major: mip0[slice0..N], mip1[slice0..N], ...
    # DDS editors usually expect slice-major: slice0[mip0..M], slice1[mip0..M], ...
    offs = 0
    by_mip: List[List[bytes]] = []
    for ms in mip_sizes:
        arr = []
        for _ in range(slices):
            arr.append(data[offs:offs + ms])
            offs += ms
        by_mip.append(arr)
    out = bytearray()
    for s in range(slices):
        for m in range(len(mip_sizes)):
            out.extend(by_mip[m][s])
    return bytes(out)


def reorder_slice_major_to_mip_major(data: bytes, mip_sizes: Sequence[int], slices: int) -> bytes:
    chunks: List[List[bytes]] = [[b"" for _ in range(slices)] for _ in range(len(mip_sizes))]
    offs = 0
    for s in range(slices):
        for m, ms in enumerate(mip_sizes):
            chunks[m][s] = data[offs:offs + ms]
            offs += ms
    out = bytearray()
    for m in range(len(mip_sizes)):
        for s in range(slices):
            out.extend(chunks[m][s])
    return bytes(out)


@dataclass
class StreamingInfo:
    table_magic: int = STREAMING_MAGIC
    table_size: int = 0
    unk08: int = 0
    window_size: int = 0x10000
    meta1_count: int = 0
    chunk_count: int = 0
    meta2_count: int = 0
    has_uncomp_chunk: int = 0
    uncomp_chunk_size: int = 0

    meta_stride: int = 1
    meta1_raw: bytes = b""
    meta2_raw: bytes = b""
    stream_table_pos: int = 0

    # Read-only details parsed from file
    chunk_entries: List[Tuple[int, int]] = field(default_factory=list)
    uncomp_entry: Optional[Tuple[int, int]] = None
    preserve_zero_uncomp_entry: bool = False
    decode_failed: bool = False


@dataclass
class TextureEntry:
    index: int

    metadata3_raw: bytes
    extra_header_version: int
    extra_header_raw: bytes

    # Decoded fields
    mip_count: int
    load_type: int
    format_id: int
    packed_dxdy: int
    packed_depth: int

    width: int
    height: int
    depth: int

    ex_zscale: int = 0
    ex_array_info: int = 0
    # High 16 bits from extra-header dword at +0x08..+0x0B.
    ex_packed_flags: int = 0

    is_streaming: bool = False
    streaming: Optional[StreamingInfo] = None

    image_data: bytes = b""

    def ex_faces(self) -> int:
        return self.ex_array_info & 0xF

    def ex_array(self) -> int:
        return self.ex_array_info >> 4

    def ex_swizzle_flag(self) -> int:
        return self.ex_packed_flags & 0xFF

    def ex_is_streaming_flag(self) -> bool:
        # original bit17 maps to bit1 of high 16-bit word
        return ((self.ex_packed_flags >> 1) & 1) == 1

    def dxgi_format(self) -> int:
        if self.format_id not in G1T_TO_DXGI:
            raise ValueError("Unsupported G1T format: 0x{:02X}".format(self.format_id))
        return G1T_TO_DXGI[self.format_id]

    def slice_count_for_dds(self) -> int:
        return g1t_slice_count_for_2d(self.load_type, self.depth, self.ex_array(), self.ex_faces())

    def is_3d_texture(self) -> bool:
        return self.load_type == LOAD_VOLUME

    def rebuild_base_header(self) -> bytes:
        mipsys = ((self.mip_count & 0xF) << 4) | (self.load_type & 0xF)
        packed_dxdy = self.packed_dxdy
        packed_depth = self.packed_depth

        # Keep raw packed fields by default. If width/height/depth changed and they are power-of-two,
        # sync packed nibbles so Deserialize-equivalent fields remain coherent.
        try:
            wlog = ilog2_pow2(self.width) & 0xF
            hlog = ilog2_pow2(self.height) & 0xF
            dlog = ilog2_pow2(self.depth) & 0xF
            packed_dxdy = (hlog << 4) | wlog
            packed_depth = (packed_depth & 0xF0) | dlog
        except ValueError:
            pass

        return struct.pack(
            "<BBBB3sB",
            mipsys,
            self.format_id,
            packed_dxdy,
            packed_depth,
            self.metadata3_raw,
            self.extra_header_version,
        )

    def rebuild_extra_header(self, force_streaming_swizzle: bool = False) -> bytes:
        if self.extra_header_version == 0:
            return b""
        if len(self.extra_header_raw) < 4:
            raise ValueError("Extra header raw too small")

        data = bytearray(self.extra_header_raw)
        ex_size = u32(data, 0)
        if ex_size >= 0x0C:
            ex_hi16 = self.ex_packed_flags & 0xFFFF
            swizzle = 0x03 if force_streaming_swizzle else self.ex_swizzle_flag()
            ex_hi16 = (ex_hi16 & 0xFF00) | (swizzle & 0xFF)
            struct.pack_into("<I", data, 4, self.ex_zscale)
            struct.pack_into("<H", data, 8, self.ex_array_info)
            struct.pack_into("<H", data, 0x0A, ex_hi16)

        if ex_size >= 0x10:
            struct.pack_into("<I", data, 0x0C, self.width)
        if ex_size >= 0x14:
            struct.pack_into("<I", data, 0x10, self.height)

        return bytes(data)


@dataclass
class G1TFile:
    path: str
    version_ascii: str
    table_offset: int
    num_textures: int
    platform: int

    file_size_declared: int
    metadata_size_declared: int

    normal_flags: List[int]
    pre_table_raw: bytes
    global_metadata_raw: bytes
    post_table_raw: bytes
    trailing_raw: bytes
    preserve_declared_split: bool

    textures: List[TextureEntry]

    @staticmethod
    def parse(path: str) -> "G1TFile":
        raw = open(path, "rb").read()
        if len(raw) < 0x1C:
            raise ValueError("File too small: {}".format(path))
        if raw[:4] != GT1G_MAGIC:
            raise ValueError("Not GT1G file: {}".format(path))

        version_ascii = raw[4:8].decode("ascii", errors="replace")
        file_size_declared = u32(raw, 0x08)
        if file_size_declared > len(raw):
            raise ValueError("Declared file size beyond physical file length")

        payload = raw[:file_size_declared]
        trailing_raw = raw[file_size_declared:]

        table_offset = u32(payload, 0x0C)
        num_textures = u32(payload, 0x10)
        platform = u32(payload, 0x14)
        metadata_size_declared = u32(payload, 0x18)

        flags_start = 0x1C
        flags_end = flags_start + num_textures * 4
        if flags_end > len(payload):
            raise ValueError("NormalFlags out of range")
        normal_flags = list(struct.unpack_from("<{}I".format(num_textures), payload, flags_start))

        if table_offset < flags_end or table_offset + num_textures * 4 > len(payload):
            raise ValueError("Invalid table offset")

        pre_table_raw = payload[flags_end:table_offset]

        offsets = list(struct.unpack_from("<{}I".format(num_textures), payload, table_offset))
        table_end = table_offset + num_textures * 4

        meta_end = table_end + metadata_size_declared
        if meta_end > len(payload):
            raise ValueError("Global metadata out of range")

        global_metadata_raw = payload[table_end:meta_end]

        starts_abs: List[int] = []
        for off in offsets:
            starts_abs.append(table_offset + off)

        # Determine first texture start to preserve unknown gap after metadata.
        valid_starts = [s for s in starts_abs if 0 <= s < len(payload)]
        first_start = min(valid_starts) if valid_starts else meta_end
        if first_start < meta_end:
            first_start = meta_end
        post_table_raw = payload[meta_end:first_start]

        # Build end positions using next greater start; fallback to file end.
        sorted_starts = sorted([s for s in starts_abs if 0 <= s <= len(payload)])

        def compute_end(start: int) -> int:
            for s in sorted_starts:
                if s > start:
                    return s
            return len(payload)

        textures: List[TextureEntry] = []

        for idx, start in enumerate(starts_abs):
            if not (0 <= start < len(payload)):
                raise ValueError("Texture offset out of range: index {}".format(idx))
            end = compute_end(start)
            if end <= start:
                end = len(payload)
            tex = parse_texture_entry(payload, idx, start, end, version_ascii, platform)
            textures.append(tex)

        preserve_declared_split = False
        # Some non-streaming textures store a suffix beyond file_size_declared.
        # Attach the missing tail to the last texture payload so DDS export can
        # work with complete data, and preserve split semantics on serialize.
        if textures and trailing_raw:
            last_tex = textures[-1]
            if not last_tex.is_streaming:
                expected = expected_texture_data_size(last_tex)
                if expected is not None:
                    have = len(last_tex.image_data)
                    if expected > have and expected - have <= len(trailing_raw):
                        need = expected - have
                        last_tex.image_data += trailing_raw[:need]
                        trailing_raw = trailing_raw[need:]
                        preserve_declared_split = True

        return G1TFile(
            path=path,
            version_ascii=version_ascii,
            table_offset=table_offset,
            num_textures=num_textures,
            platform=platform,
            file_size_declared=file_size_declared,
            metadata_size_declared=metadata_size_declared,
            normal_flags=normal_flags,
            pre_table_raw=pre_table_raw,
            global_metadata_raw=global_metadata_raw,
            post_table_raw=post_table_raw,
            trailing_raw=trailing_raw,
            preserve_declared_split=preserve_declared_split,
            textures=textures,
        )

    def serialize(self) -> bytes:
        if len(self.textures) != self.num_textures:
            raise ValueError("Texture count mismatch")

        out = bytearray()
        out.extend(GT1G_MAGIC)
        out.extend(self.version_ascii.encode("ascii", errors="replace")[:4].ljust(4, b"0"))
        out.extend(b"\x00\x00\x00\x00")  # file size placeholder
        out.extend(pack_u32(self.table_offset))
        out.extend(pack_u32(self.num_textures))
        out.extend(pack_u32(self.platform))
        out.extend(pack_u32(len(self.global_metadata_raw)))

        out.extend(struct.pack("<{}I".format(self.num_textures), *self.normal_flags))
        out.extend(self.pre_table_raw)

        if len(out) != self.table_offset:
            if len(out) > self.table_offset:
                raise ValueError("Header+flags exceed table_offset")
            out.extend(b"\x00" * (self.table_offset - len(out)))

        offset_table_pos = len(out)
        out.extend(b"\x00" * (self.num_textures * 4))

        out.extend(self.global_metadata_raw)
        out.extend(self.post_table_raw)

        offsets: List[int] = []
        for tex in self.textures:
            tex_start = len(out)
            offsets.append(tex_start - self.table_offset)
            out.extend(serialize_texture_entry(tex, tex_start, self.version_ascii, self.platform))

        # Patch offsets
        for i, off in enumerate(offsets):
            struct.pack_into("<I", out, offset_table_pos + i * 4, off)

        trailing_out = self.trailing_raw
        declared_size = len(out)

        if self.preserve_declared_split and self.file_size_declared > 0 and self.file_size_declared <= len(out):
            # Preserve original "declared payload + physical tail" layout.
            split = self.file_size_declared
            tail_from_payload = bytes(out[split:])
            del out[split:]
            declared_size = split
            trailing_out = tail_from_payload + trailing_out

        struct.pack_into("<I", out, 0x08, declared_size)
        out.extend(trailing_out)
        return bytes(out)


def parse_texture_entry(
    payload: bytes,
    index: int,
    start: int,
    end: int,
    version_ascii: str,
    platform: int,
) -> TextureEntry:
    if start + 8 > end:
        raise ValueError("Texture {} header out of range".format(index))

    base = payload[start:start + 8]
    mip_sys, fmt, packed_dxdy, packed_depth, md0, md1, md2, ex_ver = struct.unpack("<BBBBBBBb", base)
    ex_ver &= 0xFF

    mip_count = (mip_sys >> 4) & 0xF
    load_type = mip_sys & 0xF

    width = 1 << (packed_dxdy & 0xF)
    height = 1 << ((packed_dxdy >> 4) & 0xF)
    depth = 1 << (packed_depth & 0xF)

    ex_size = 0
    ex_zscale = 0
    ex_array_info = 0
    ex_packed_flags = 0
    extra_raw = b""

    pos = start + 8
    if ex_ver > 0:
        if pos + 4 > end:
            raise ValueError("Texture {} extra header size out of range".format(index))
        ex_size = u32(payload, pos)
        if pos + ex_size > end:
            raise ValueError("Texture {} extra header out of range".format(index))
        extra_raw = payload[pos:pos + ex_size]
        if ex_size >= 0x0C:
            ex_zscale = u32(payload, pos + 0x04)
            ex_array_info = le_u16(payload, pos + 0x08)      # low 16 bits
            ex_packed_flags = le_u16(payload, pos + 0x0A)    # high 16 bits
        if ex_size >= 0x10:
            width = u32(payload, pos + 0x0C)
        if ex_size >= 0x14:
            height = u32(payload, pos + 0x10)
        pos += ex_size

    tex = TextureEntry(
        index=index,
        metadata3_raw=bytes((md0, md1, md2)),
        extra_header_version=ex_ver,
        extra_header_raw=extra_raw,
        mip_count=max(1, mip_count),
        load_type=load_type,
        format_id=fmt,
        packed_dxdy=packed_dxdy,
        packed_depth=packed_depth,
        width=max(1, width),
        height=max(1, height),
        depth=max(1, depth),
        ex_zscale=ex_zscale,
        ex_array_info=ex_array_info,
        ex_packed_flags=ex_packed_flags,
    )

    # Strict streaming detection from extra-header packed flags.
    is_streaming = version_ascii == "6600" and tex.ex_is_streaming_flag()
    tex.is_streaming = is_streaming

    if is_streaming:
        parse_streaming_payload(payload, pos, end, tex)
    else:
        tex.image_data = payload[pos:end]

    if texture_uses_d3d12_tiling(tex, platform):
        tex.image_data = apply_d3d12_tiling_transform(tex, tex.image_data, platform, to_linear=True)

    return tex


def parse_streaming_payload(payload: bytes, pos: int, end: int, tex: TextureEntry) -> None:
    if pos + 36 > end:
        raise ValueError("Texture {} streaming header truncated".format(tex.index))

    s = StreamingInfo()
    s.stream_table_pos = pos

    (
        s.table_magic,
        s.table_size,
        s.unk08,
        s.window_size,
        s.meta1_count,
        s.chunk_count,
        s.meta2_count,
        s.has_uncomp_chunk,
        s.uncomp_chunk_size,
    ) = struct.unpack_from("<9I", payload, pos)

    if s.table_magic != STREAMING_MAGIC:
        raise ValueError("Texture {} invalid streaming magic".format(tex.index))
    if s.window_size == 0:
        raise ValueError("Texture {} invalid streaming window size".format(tex.index))

    meta_stride = g1t_compute_meta_stride(tex.depth, tex.load_type, tex.ex_array(), tex.ex_faces())
    s.meta_stride = meta_stride

    off = pos + 36
    meta1_bytes = s.meta1_count * meta_stride * 16
    meta2_bytes = s.meta2_count * meta_stride * 16

    if off + meta1_bytes + meta2_bytes > end:
        raise ValueError("Texture {} streaming meta out of range".format(tex.index))

    s.meta1_raw = payload[off:off + meta1_bytes]
    off += meta1_bytes
    s.meta2_raw = payload[off:off + meta2_bytes]
    off += meta2_bytes

    chunk_table_bytes = s.chunk_count * 8
    if off + chunk_table_bytes > end:
        raise ValueError("Texture {} chunk table out of range".format(tex.index))

    chunk_entries: List[Tuple[int, int]] = []
    for i in range(s.chunk_count):
        c_off, c_size = struct.unpack_from("<II", payload, off + i * 8)
        chunk_entries.append((c_off, c_size))
    s.chunk_entries = chunk_entries
    off += chunk_table_bytes

    if s.has_uncomp_chunk:
        if off + 8 > end:
            raise ValueError("Texture {} uncomp entry out of range".format(tex.index))
        s.uncomp_entry = struct.unpack_from("<II", payload, off)
        off += 8
    else:
        # Preserve non-standard layout:
        # has_uncomp_chunk == 0 but table_size still includes an extra 8-byte entry.
        expected_table_size = 36 + meta1_bytes + meta2_bytes + chunk_table_bytes
        if s.table_size == expected_table_size + 8 and off + 8 <= end:
            s.uncomp_entry = struct.unpack_from("<II", payload, off)
            s.preserve_zero_uncomp_entry = True
            off += 8

    # Decode stream chunks to legacy-like linear mip payload.
    decoded = decode_streaming_chunks(payload, s)
    s.decode_failed = False
    tex.streaming = s
    tex.image_data = bytes(decoded)


def decode_streaming_chunks(payload: bytes, s: StreamingInfo) -> bytearray:
    out = bytearray(s.chunk_count * s.window_size + (s.uncomp_chunk_size if s.has_uncomp_chunk else 0))

    # Mirrors in-game condition: CompressedSize < WindowSize means compressed path.
    for idx, (off, comp_size) in enumerate(s.chunk_entries):
        dst_off = idx * s.window_size
        if comp_size >= s.window_size:
            chunk = payload[off:off + s.window_size]
            if len(chunk) != s.window_size:
                raise ValueError("Raw chunk truncated")
            out[dst_off:dst_off + s.window_size] = chunk
            continue

        if off + 4 > len(payload):
            raise ValueError("Compressed chunk truncated")

        pref_len = u32(payload, off)
        comp_data = payload[off + 4:off + 4 + pref_len]
        if len(comp_data) != pref_len:
            raise ValueError("Compressed chunk payload truncated")

        try:
            raw_chunk = zlib.decompress(comp_data)
        except zlib.error:
            raw_chunk = zlib.decompress(comp_data, -15)

        if len(raw_chunk) != s.window_size:
            raise ValueError("Decompressed chunk size mismatch")

        out[dst_off:dst_off + s.window_size] = raw_chunk

    if s.has_uncomp_chunk:
        if not s.uncomp_entry:
            raise ValueError("Missing uncomp chunk entry")
        u_off, u_size = s.uncomp_entry
        tail = payload[u_off:u_off + u_size]
        if len(tail) != u_size:
            raise ValueError("Uncompressed tail truncated")
        if u_size != s.uncomp_chunk_size:
            raise ValueError("Uncompressed tail size mismatch")
        out[s.chunk_count * s.window_size:s.chunk_count * s.window_size + u_size] = tail

    return out


def serialize_texture_entry(tex: TextureEntry, tex_start: int, version_ascii: str, platform: int) -> bytes:
    is_streaming = tex.is_streaming and version_ascii == "6600"

    base = tex.rebuild_base_header()
    tex_data_for_disk = tex.image_data
    if texture_uses_d3d12_tiling(tex, platform):
        tex_data_for_disk = apply_d3d12_tiling_transform(tex, tex_data_for_disk, platform, to_linear=False)

    if is_streaming:
        extra = tex.rebuild_extra_header(force_streaming_swizzle=True)
        if not tex.streaming:
            raise ValueError("Texture {} missing streaming info".format(tex.index))
        if tex.streaming.decode_failed:
            raise ValueError("Texture {} streaming decode failed; cannot rebuild".format(tex.index))

        stream_blob = rebuild_streaming_blob(
            tex, tex_start + len(base) + len(extra), image_data=tex_data_for_disk
        )
        return base + extra + stream_blob

    # Non-streaming path keeps declared swizzle value from texture descriptor.
    extra = tex.rebuild_extra_header(force_streaming_swizzle=False)

    return base + extra + tex_data_for_disk


def rebuild_streaming_blob(tex: TextureEntry, stream_abs_start: int, image_data: Optional[bytes] = None) -> bytes:
    s = tex.streaming
    if s is None:
        raise ValueError("Missing streaming info")

    if s.window_size <= 0:
        raise ValueError("Invalid window size")

    if image_data is None:
        image_data = tex.image_data

    total = len(image_data)

    # Prefer original streaming split when incoming data length still matches it.
    # Otherwise, fall back to recomputing by total % window_size.
    orig_chunk_count = max(0, s.chunk_count)
    orig_has_uncomp = s.has_uncomp_chunk
    orig_uncomp_size = s.uncomp_chunk_size if orig_has_uncomp else 0
    orig_total = orig_chunk_count * s.window_size + orig_uncomp_size

    if total == orig_total:
        chunk_count = orig_chunk_count
        uncomp_size = orig_uncomp_size
    else:
        # 如果有meta2的话需要保证uncomp_size跟meta2_mipsize_sum一致
        # 处理很麻烦，所有直接抛出异常
        chunk_count = total // s.window_size
        uncomp_size = total % s.window_size
        raise ValueError("Texture {} streaming data size mismatch: expected {} bytes, got {} bytes".format(tex.index, orig_total, total))

    # Keep streaming descriptor coherent with chosen split, while preserving
    # original non-zero has_uncomp_chunk sentinel value.
    has_uncomp_value = 0
    if uncomp_size > 0:
        has_uncomp_value = orig_has_uncomp if orig_has_uncomp != 0 else 1

    s.chunk_count = chunk_count
    s.has_uncomp_chunk = has_uncomp_value
    s.uncomp_chunk_size = uncomp_size
    compressed_part = chunk_count * s.window_size

    raw_chunks: List[bytes] = []
    for i in range(chunk_count):
        a = i * s.window_size
        b = a + s.window_size
        raw_chunks.append(image_data[a:b])

    packed_chunks: List[bytes] = []
    chunk_entries: List[Tuple[int, int]] = []

    keep_zero_uncomp_entry = (
        uncomp_size == 0 and has_uncomp_value == 0 and s.preserve_zero_uncomp_entry
    )
    table_size = (
        36
        + len(s.meta1_raw)
        + len(s.meta2_raw)
        + chunk_count * 8
        + (8 if uncomp_size > 0 or keep_zero_uncomp_entry else 0)
    )
    cur_data_off = stream_abs_start + table_size

    for raw_chunk in raw_chunks:
        comp = zlib.compress(raw_chunk, 6)
        if len(comp) >= s.window_size:
            # Same strategy as documented tool behavior: store raw chunk when compression has no gain.
            blob = raw_chunk
            comp_size = s.window_size
        else:
            blob = pack_u32(len(comp)) + comp
            # Keep old-tool behavior: table stores payload size including 4-byte prefix.
            comp_size = len(comp) + 4
        chunk_entries.append((cur_data_off, comp_size))
        packed_chunks.append(blob)
        cur_data_off += len(blob)

    uncomp_entry = None
    if uncomp_size > 0:
        uncomp_entry = (cur_data_off, uncomp_size)
    elif keep_zero_uncomp_entry:
        # Keep original redundant entry bytes when source table had them.
        uncomp_entry = s.uncomp_entry if s.uncomp_entry is not None else (cur_data_off, 0)

    out = bytearray()
    out.extend(
        struct.pack(
            "<9I",
            STREAMING_MAGIC,
            table_size,
            s.unk08,
            s.window_size,
            s.meta1_count,
            chunk_count,
            s.meta2_count,
            has_uncomp_value,
            uncomp_size,
        )
    )

    out.extend(s.meta1_raw)
    out.extend(s.meta2_raw)

    for c_off, c_size in chunk_entries:
        out.extend(struct.pack("<II", c_off, c_size))

    if uncomp_entry is not None:
        out.extend(struct.pack("<II", uncomp_entry[0], uncomp_entry[1]))

    for blob in packed_chunks:
        out.extend(blob)

    if uncomp_size > 0:
        out.extend(image_data[compressed_part:compressed_part + uncomp_size])

    return bytes(out)


@dataclass
class DdsImage:
    width: int
    height: int
    depth: int
    mip_count: int
    dxgi_format: int

    is_volume: bool
    slice_count: int

    pixel_data: bytes


def parse_dds(path: str) -> DdsImage:
    data = open(path, "rb").read()
    if len(data) < 128 or data[:4] != DDS_MAGIC:
        raise ValueError("Not DDS: {}".format(path))

    if u32(data, 4) != 124:
        raise ValueError("Invalid DDS header size")

    height = u32(data, 12)
    width = u32(data, 16)
    depth = u32(data, 24)
    mip_count = u32(data, 28) or 1

    # NOTE:
    # Offsets below are absolute file offsets (including 4-byte 'DDS ' magic).
    # DDS_HEADER starts at offset 0x04, and DDS_PIXELFORMAT starts at 0x4C.
    pf_size = u32(data, 76)
    pf_flags = u32(data, 80)
    fourcc = data[84:88]
    rgb_bits = u32(data, 88)
    r_mask = u32(data, 92)
    g_mask = u32(data, 96)
    b_mask = u32(data, 100)
    a_mask = u32(data, 104)
    caps2 = u32(data, 112)

    if pf_size != 32:
        raise ValueError("Invalid DDS pixel format size")

    dxgi_format = None
    is_volume = False
    slice_count = 1
    data_off = 128

    if fourcc == b"DX10":
        if len(data) < 148:
            raise ValueError("DDS DX10 header truncated")
        dxgi_format = u32(data, 128)
        res_dim = u32(data, 132)
        misc_flag = u32(data, 136)
        array_size = u32(data, 140)

        data_off = 148

        if res_dim == D3D10_RESOURCE_DIMENSION_TEXTURE3D:
            is_volume = True
            slice_count = 1
            depth = max(1, depth)
        else:
            is_volume = False
            if misc_flag & DDS_RESOURCE_MISC_TEXTURECUBE:
                slice_count = max(1, array_size) * 6
            else:
                slice_count = max(1, array_size)
            depth = 1
    else:
        if fourcc in LEGACY_FOURCC_TO_DXGI:
            dxgi_format = LEGACY_FOURCC_TO_DXGI[fourcc]
        elif fourcc in (b"DXT2", b"DXT3"):
            dxgi_format = 74
        elif fourcc in (b"DXT4", b"DXT5"):
            dxgi_format = 77
        elif (pf_flags & DDPF_RGB) and rgb_bits == 32:
            # Optional fallback for common 32-bit uncompressed DDS variants.
            if (r_mask, g_mask, b_mask, a_mask) == (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000):
                dxgi_format = 87  # B8G8R8A8
            elif (r_mask, g_mask, b_mask, a_mask) == (0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000):
                dxgi_format = 28  # R8G8B8A8
        elif (pf_flags & DDPF_ALPHA) and rgb_bits == 8:
            dxgi_format = 65

        if caps2 & DDSCAPS2_VOLUME:
            is_volume = True
            slice_count = 1
            depth = max(1, depth)
        elif caps2 & DDSCAPS2_CUBEMAP:
            is_volume = False
            slice_count = 6
            depth = 1
        else:
            is_volume = False
            slice_count = 1
            depth = 1

    if dxgi_format is None:
        raise ValueError("Unsupported DDS format in {}".format(path))

    if dxgi_format not in DXGI_INFO:
        raise ValueError("Unsupported DXGI format {} in {}".format(dxgi_format, path))

    if data_off >= len(data):
        raise ValueError("DDS pixel payload missing")

    # Keep full payload bytes after headers. Size normalization is handled by
    # import path per texture type, so truncated/extended DDS blobs stay usable.
    pixels = data[data_off:]

    return DdsImage(
        width=width,
        height=height,
        depth=max(1, depth),
        mip_count=max(1, mip_count),
        dxgi_format=dxgi_format,
        is_volume=is_volume,
        slice_count=max(1, slice_count),
        pixel_data=pixels,
    )


def build_dds(tex: TextureEntry) -> bytes:
    dxgi_fmt = tex.dxgi_format()
    info = DXGI_INFO[dxgi_fmt]

    mip_count = tex.mip_count
    width = tex.width
    height = tex.height

    src_is_volume = tex.is_3d_texture()
    is_volume = src_is_volume
    depth = tex.depth if src_is_volume else 1
    slices = tex.slice_count_for_dds() if not src_is_volume else 1

    data = tex.image_data
    if src_is_volume:
        expected = calc_total_size_3d(dxgi_fmt, width, height, depth, mip_count)
    else:
        expected = calc_total_size_2d(dxgi_fmt, width, height, mip_count, slices)

    if len(data) > expected:
        data = data[:expected]
    elif src_is_volume and len(data) < expected:
        # Standard 3D DDS requires payload consistent with width/height/depth/mips.
        data = data + (b"\x00" * (expected - len(data)))

    # Convert array/cube mip ordering for DDS tools.
    if (not src_is_volume) and slices > 1:
        data = reorder_mip_major_to_slice_major(data, mip_sizes_2d(dxgi_fmt, width, height, mip_count), slices)

    use_legacy = (slices == 1 and not src_is_volume and dxgi_fmt in DXGI_TO_LEGACY_FOURCC)

    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    caps = DDSCAPS_TEXTURE
    caps2 = 0

    if mip_count > 1:
        flags |= DDSD_MIPMAPCOUNT
        caps |= DDSCAPS_COMPLEX | DDSCAPS_MIPMAP

    if is_volume:
        flags |= DDSD_DEPTH
        caps |= DDSCAPS_COMPLEX
        caps2 |= DDSCAPS2_VOLUME

    if info.block_compressed:
        flags |= DDSD_LINEARSIZE
        pitch_or_linear = calc_mip_size(dxgi_fmt, width, height)
    else:
        flags |= DDSD_PITCH
        pitch_or_linear = width * info.bytes_per_pixel

    ddspf = bytearray(32)
    struct.pack_into("<I", ddspf, 0, 32)

    dx10_header = b""

    if use_legacy:
        struct.pack_into("<I", ddspf, 4, DDPF_FOURCC)
        ddspf[8:12] = DXGI_TO_LEGACY_FOURCC[dxgi_fmt]
    else:
        struct.pack_into("<I", ddspf, 4, DDPF_FOURCC)
        ddspf[8:12] = b"DX10"

        res_dim = D3D10_RESOURCE_DIMENSION_TEXTURE3D if is_volume else D3D10_RESOURCE_DIMENSION_TEXTURE2D
        misc_flag = 0
        array_size = 1

        if not is_volume:
            if tex.load_type in (LOAD_CUBE, LOAD_CUBE_ARRAY):
                misc_flag |= DDS_RESOURCE_MISC_TEXTURECUBE
                array_size = max(1, slices // 6)
            else:
                array_size = max(1, slices)

        dx10_header = struct.pack("<IIIII", dxgi_fmt, res_dim, misc_flag, array_size, 0)

    header = bytearray(124)
    struct.pack_into("<I", header, 0, 124)
    struct.pack_into("<I", header, 4, flags)
    struct.pack_into("<I", header, 8, height)
    struct.pack_into("<I", header, 12, width)
    struct.pack_into("<I", header, 16, pitch_or_linear)
    struct.pack_into("<I", header, 20, depth if is_volume else 0)
    struct.pack_into("<I", header, 24, mip_count)
    # DDS_HEADER-relative offsets:
    # ddspf: 72..103, caps: 104, caps2: 108
    header[72:104] = ddspf
    struct.pack_into("<I", header, 104, caps)

    if not use_legacy and tex.load_type in (LOAD_CUBE, LOAD_CUBE_ARRAY):
        # Keep legacy cubemap caps for compatibility with some tools.
        caps2 = DDSCAPS2_CUBEMAP | DDSCAPS2_CUBEMAP_ALLFACES
    struct.pack_into("<I", header, 108, caps2)

    return DDS_MAGIC + bytes(header) + dx10_header + data


def dxgi_extension(dxgi_fmt: int) -> str:
    suffix = DXGI_SUFFIX.get(dxgi_fmt)
    if suffix:
        return ".{}.dds".format(suffix)
    return ".dds"


def export_g1t_file(
    g1t_path: str,
    out_dir: str,
    verbose: bool = False,
) -> int:
    g = G1TFile.parse(g1t_path)

    base = os.path.splitext(os.path.basename(g1t_path))[0]
    ensure_dir(out_dir)
    count = 0
    for tex in g.textures:
        dxgi_fmt = tex.dxgi_format()
        out_name = "{}.TEX{}{}".format(base, tex.index, dxgi_extension(dxgi_fmt))
        out_path = os.path.join(out_dir, out_name)
        dds = build_dds(tex)
        with open(out_path, "wb") as fp:
            fp.write(dds)
        if verbose:
            fmt_name = DXGI_INFO.get(dxgi_fmt).name if dxgi_fmt in DXGI_INFO else "DXGI_{}".format(dxgi_fmt)
            load_name = LOAD_TYPE_NAMES.get(tex.load_type, "UNKNOWN")
            layer_count = g1t_compute_total_layers(tex.load_type, tex.ex_array()) * max(1, tex.ex_faces() or 1)
            print(
                "    TEX{idx} {w}x{h} fmt={fmt} mips={mips} layers={layers} depth={depth} "
                "loadtype={load}({load_id}) size={size} -> {name}".format(
                    idx=tex.index,
                    w=tex.width,
                    h=tex.height,
                    fmt=fmt_name,
                    mips=tex.mip_count,
                    layers=layer_count,
                    depth=tex.depth,
                    load=load_name,
                    load_id=tex.load_type,
                    size=format_size_human(len(tex.image_data)),
                    name=out_name,
                )
            )
        count += 1

    return count


def collect_g1t_files(root: str) -> List[str]:
    out = []
    for cur, _, files in os.walk(root):
        for fn in files:
            low = fn.lower()
            if low.endswith(".g1t") or low.endswith(".g1ts"):
                out.append(os.path.join(cur, fn))
    out.sort()
    return out


def collect_candidate_dds(g1t_path: str) -> List[str]:
    gdir = os.path.dirname(g1t_path)
    base = os.path.splitext(os.path.basename(g1t_path))[0]
    base_low = base.lower()

    candidates: List[str] = []

    # Rule 1: same directory (non-recursive)
    for fn in sorted(os.listdir(gdir)):
        if not fn.lower().endswith(".dds"):
            continue
        noext = os.path.splitext(fn)[0]
        noext_low = noext.lower()
        if noext_low.startswith(base_low + ".") or noext_low.startswith(base_low + "_"):
            candidates.append(os.path.join(gdir, fn))
            continue
        if strip_multi_ext(fn).lower() == base_low:
            candidates.append(os.path.join(gdir, fn))

    # Rule 2: same-named subdirectory (case-insensitive), recursive
    subdir = None
    for entry in os.listdir(gdir):
        p = os.path.join(gdir, entry)
        if os.path.isdir(p) and entry.lower() == base_low:
            subdir = p
            break

    if subdir:
        for cur, _, files in os.walk(subdir):
            for fn in sorted(files):
                if not fn.lower().endswith(".dds"):
                    continue
                noext = os.path.splitext(fn)[0]
                idx = parse_texture_index_from_dds_name(noext)
                if idx is not None or strip_multi_ext(fn).lower() == base_low:
                    candidates.append(os.path.join(cur, fn))

    # Deduplicate while preserving order
    uniq = []
    seen = set()
    for p in candidates:
        k = os.path.normcase(os.path.normpath(p))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p)
    return uniq


def apply_dds_to_texture(tex: TextureEntry, dds: DdsImage, strict_streaming: bool) -> None:
    old_dxgi = tex.dxgi_format()

    # Decide destination G1T format id.
    if dds.dxgi_format == old_dxgi:
        new_format_id = tex.format_id
    else:
        if dds.dxgi_format not in DXGI_TO_G1T_CANONICAL:
            raise ValueError("DDS DXGI format {} cannot map to G1T format".format(dds.dxgi_format))
        new_format_id = DXGI_TO_G1T_CANONICAL[dds.dxgi_format]

    target_is_3d = tex.is_3d_texture()

    if target_is_3d:
        if not dds.is_volume:
            raise ValueError("DDS is not volume texture")
        if dds.slice_count != 1:
            raise ValueError("Volume texture requires single-slice DDS")
        new_width = dds.width
        new_height = dds.height
        new_depth = dds.depth
        new_mips = dds.mip_count
        new_pixels = dds.pixel_data
    else:
        if dds.is_volume:
            raise ValueError("DDS volume cannot be imported into non-volume G1T texture")

        slices = tex.slice_count_for_dds()
        if dds.slice_count != slices:
            raise ValueError("DDS slice count mismatch: {} != {}".format(dds.slice_count, slices))

        new_width = dds.width
        new_height = dds.height
        new_depth = tex.depth
        new_mips = dds.mip_count

        mip_sizes = mip_sizes_2d(dds.dxgi_format, new_width, new_height, new_mips)
        if slices > 1:
            new_pixels = reorder_slice_major_to_mip_major(dds.pixel_data, mip_sizes, slices)
        else:
            new_pixels = dds.pixel_data

    if strict_streaming:
        # Keep g1ts stream metadata stable: no structural changes.
        if new_format_id != tex.format_id:
            raise ValueError("G1TS import requires same format")
        if new_width != tex.width or new_height != tex.height:
            raise ValueError("G1TS import requires same dimensions")
        if new_mips != tex.mip_count:
            raise ValueError("G1TS import requires same mip count")
        if len(new_pixels) != len(tex.image_data):
            raise ValueError("G1TS import requires same pixel data size")

    tex.format_id = new_format_id
    tex.width = new_width
    tex.height = new_height
    tex.depth = new_depth
    tex.mip_count = new_mips
    tex.image_data = new_pixels


def import_for_file(g1t_path: str, input_root: str, output_root: str) -> Tuple[bool, List[str]]:
    logs: List[str] = []

    # GT1G magic check first (matches documented batch behavior).
    with open(g1t_path, "rb") as fp:
        if fp.read(4) != GT1G_MAGIC:
            logs.append("skip non-GT1G magic")
            return False, logs

    g = G1TFile.parse(g1t_path)

    candidates = collect_candidate_dds(g1t_path)
    if not candidates:
        logs.append("no candidate DDS found")
        return False, logs

    idx_to_dds: Dict[int, str] = {}

    for dds_path in candidates:
        fn = os.path.basename(dds_path)
        noext = os.path.splitext(fn)[0]
        idx = parse_texture_index_from_dds_name(noext)

        if idx is None and len(g.textures) == 1:
            idx = 0

        if idx is None:
            logs.append("skip {} (cannot resolve texture index)".format(fn))
            continue
        if idx < 0 or idx >= len(g.textures):
            logs.append("skip {} (index {} out of range)".format(fn, idx))
            continue
        if idx in idx_to_dds:
            logs.append("skip {} (texture {} already has candidate)".format(fn, idx))
            continue

        idx_to_dds[idx] = dds_path

    if not idx_to_dds:
        logs.append("no valid DDS mapped to textures")
        return False, logs

    changed = False

    for idx in sorted(idx_to_dds.keys()):
        dds_path = idx_to_dds[idx]
        tex = g.textures[idx]
        strict_streaming = tex.is_streaming

        try:
            dds = parse_dds(dds_path)
            apply_dds_to_texture(tex, dds, strict_streaming)
            changed = True
            logs.append("apply TEX{} <- {}".format(idx, os.path.basename(dds_path)))
        except Exception as exc:
            logs.append("skip TEX{} {} ({})".format(idx, os.path.basename(dds_path), exc))

    if not changed:
        return False, logs

    rel = os.path.relpath(g1t_path, input_root)
    out_path = os.path.join(output_root, rel)
    ensure_dir(os.path.dirname(out_path))

    out_bytes = g.serialize()
    with open(out_path, "wb") as fp:
        fp.write(out_bytes)

    logs.append("write {}".format(out_path))
    return True, logs


def cmd_export(args: argparse.Namespace) -> int:
    in_path = os.path.abspath(args.input_path)

    if not os.path.exists(in_path):
        print("Input path not found: {}".format(in_path), file=sys.stderr)
        return 2

    if args.output_dir:
        out_root = os.path.abspath(args.output_dir)
    else:
        if os.path.isdir(in_path):
            out_root = os.path.join(in_path, "output")
        else:
            # base = os.path.splitext(os.path.basename(in_path))[0]
            out_root = os.path.dirname(in_path)

    ensure_dir(out_root)

    files: List[str] = collect_g1t_files(in_path) if os.path.isdir(in_path) else [in_path]
    total_tex = 0
    ok_files = 0

    for fp in files:
        try:
            print("---------------------------------------------------------------")
            print("[Processing] {}".format(fp))
            n = export_g1t_file(fp, out_root, verbose=True)
            total_tex += n
            ok_files += 1
        except Exception as exc:
            print("[error][skip] {} ({})".format(fp, exc), file=sys.stderr)

    print("---------------------------------------------------------------")
    print("[Summary] files_ok={} textures_out={} out_dir={}".format(ok_files, total_tex, out_root))
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    in_dir = os.path.abspath(args.input_dir)
    if not os.path.isdir(in_dir):
        print("Input dir not found: {}".format(in_dir), file=sys.stderr)
        return 2

    if args.output_dir:
        out_dir = os.path.abspath(args.output_dir)
    else:
        out_dir = os.path.join(in_dir, "output")

    ensure_dir(out_dir)

    files = collect_g1t_files(in_dir)

    changed_files = 0
    skipped_magic = 0

    for fp in files:
        changed, logs = import_for_file(fp, in_dir, out_dir)

        # Lightweight stats for non-GT1G skip reason.
        if any("non-GT1G magic" in x for x in logs):
            skipped_magic += 1

        status = "apply" if changed else "skip"
        print("[import][{}] {}".format(status, fp))
        for line in logs:
            print("  - {}".format(line))

        if changed:
            changed_files += 1

    print(
        "[import] changed_files={} scanned_files={} invalid_magic_files={} out_dir={}".format(
            changed_files,
            len(files),
            skipped_magic,
            out_dir,
        )
    )
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="G1T/G1TS <-> DDS tool")
    sub = p.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export", help="Export g1t/g1ts textures to DDS")
    p_export.add_argument("input_path", help="g1t/g1ts file or directory")
    p_export.add_argument("output_dir", nargs="?", help="output directory")
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser("import", help="Import edited DDS back to g1t/g1ts")
    p_import.add_argument("input_dir", help="directory containing g1t/g1ts and DDS")
    p_import.add_argument("output_dir", nargs="?", help="output directory (default: <input_dir>/output)")
    p_import.set_defaults(func=cmd_import)

    return p


def main(argv: Sequence[str]) -> int:
    if sys.version_info[0] < 3:
        print("This script requires Python 3. Please run with a Python 3 'python' executable.", file=sys.stderr)
        return 2

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
