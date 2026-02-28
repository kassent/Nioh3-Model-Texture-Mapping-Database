# g1t_tool.py Usage Guide

## Overview

`g1t_tool.py` exports textures from `G1T/G1TS` files to `DDS`, and imports `DDS` back into `G1T/G1TS`.

Format context:

- `G1T` is the texture container format used by **Nioh 3**.
- `G1TS` is the streaming-capable texture variant used for on-demand texture loading.

Supported workflows:

- `export`: extract all textures as `.dds`
- `import`: batch-import matching `.dds` files into `.g1t/.g1ts`
- `info`: print file and texture metadata

The tool supports:

- Traditional `G1T` (non-streaming)
- Streaming `G1TS` (ZLIB chunked data)

## Requirements

- Python 3
- No third-party Python packages required

Run from project root:

```bash
python g1t_tool.py <command> ...
```

## Commands

### 1) Export

```bash
python g1t_tool.py export <input.g1t_or_dir> [output_dir]
```

Behavior:

- If input is a single file, exports DDS files next to it (or into `output_dir` if provided).
- If input is a directory, scans recursively for `.g1t/.g1ts`, keeps relative layout in batch output.
- Non-`GT1G` files are skipped (magic check).

Output naming:

- `baseName.TEX<index><format_ext>.dds`
- Example: `0x2D86652D.TEX0.bc7.dds`

### 2) Import

```bash
python g1t_tool.py import <input_dir> [output_dir]
```

Important:

- CLI import expects a directory, not a single DDS file argument.
- The directory should contain `.g1t/.g1ts` and matching `.dds` files.

Behavior:

- Recursively finds `.g1t/.g1ts`.
- For each file, auto-discovers matching DDS candidates:
  - Same directory (non-recursive), filename matches base name
  - Same-name subfolder (recursive), e.g. `<dir>/<baseName>/...`
- Writes outputs to:
  - `<input_dir>/output` by default
  - or your custom `output_dir`
- Preserves relative folder structure in batch mode.

### 3) Info

```bash
python g1t_tool.py info <input.g1t_or_dir>
```

Behavior:

- Prints file-level header info and per-texture summary.
- Batch mode scans recursively and skips non-`GT1G` files.

## DDS Matching Rules for Import

### Base-name matching

A DDS file is considered related to `X.g1t/.g1ts` if:

- DDS name starts with `X.` or `X_`, or
- DDS stem (after stripping all extensions) equals `X`

Examples:

- `0x2D86652D.TEX0.bc7.dds`
- `0x2D86652D.bc7.dds`

### Texture index parsing

The index is parsed from DDS filename using these patterns:

- `TEX<number>` or `TEXTURE<number>` (recommended)
- `Tex <number>` / `Arr <number>` (legacy)
- pure numeric stem fallback (e.g. `2.dds`)

If target G1T has only one texture and no index is found, index `0` is used.

## Import Constraints

### Generic constraints

- DDS format must map to a supported G1T format.
- Import replaces existing textures only (does not change texture count).
- Array/cube data is layout-converted between DDS and G1T ordering.

### G1TS-specific constraints

For streaming textures (`SwizzleType == 0x03`), replacement is allowed only when all are unchanged:

- format
- width/height
- mip count
- total pixel-data length

If any differs, that DDS is skipped (streaming metadata regeneration is not implemented).

## Streaming Behavior (G1TS)

- Saving G1TS always recompresses streaming chunks.
- Binary differences can exist even when semantic content is unchanged.
- If a streaming texture fails decode, it cannot be written back.

## Project-Specific Parsing Assumption

This version is aligned to the reverse-validated project dataset:

- Logical header size: `0x1C`
- `TableOffset` must satisfy:
  - `TableOffset == 0x1C + NumTextures * 4`
- Layout order:
  - `Header(0x1C) -> NormalFlags -> OffsetTable -> GlobalMetadata -> TextureEntries`

Files outside this layout model are rejected by parser validation.

## Typical Examples

Export one file:

```bash
python g1t_tool.py export "res/g1t/0x2D86652D.g1t"
```

Export a full folder:

```bash
python g1t_tool.py export "res/g1t" "test_tmp/exported_dds"
```

Import from prepared folder:

```bash
python g1t_tool.py import "res/g1t" "test_tmp/import_output"
```

Inspect metadata:

```bash
python g1t_tool.py info "res/g1ts"
```

## Troubleshooting

- `Invalid G1T magic`: file is not `GT1G`.
- `Unexpected table_offset for this parser`: file layout does not match the current project model.
- `Cannot recompress streaming texture after decode failure`: problematic G1TS streaming block variant.
- `G1TS streaming replacement requires same format/size/mips/data length`: import DDS does not match streaming constraints.
