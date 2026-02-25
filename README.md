# Nioh 3 `g1m` <-> `g1t` Mapping Guide (for Modders)

Use these files to map model resources (`g1m`) to texture resources (`g1t`).

## Output Files
- `all_model_g1t_mapping_agg.csv`
  - Aggregated by `g1m_hash`.
  - Best starting point to quickly find all related `ktid` and `g1t` hashes for a model.
- `all_model_g1t_mapping_detail.csv`
  - Slot-level mapping (usually one row per `ktid_index`).
  - Best for precise per-slot texture replacement.
- `0xXXXXXXXX.kidsobjdb.model_g1t_mapping.csv`
  - Detail mapping from a single `kidsobjdb`.
- `*.json`
  - Structured equivalents for scripting/automation.

## Key Columns
- `g1m_hash`
  - Model resource hash (typically `0xXXXXXXXX.g1m`).
- `ktid_hash`
  - Texture bind table hash (typically `0xXXXXXXXX.ktid`).
- `ktid_index`
  - Texture slot index inside the KTID file.
- `static_texture_object_hash`
  - `TypeInfo::Object::Render::Texture::Static` object hash in `kidsobjdb`.
- `g1t_hash`
  - Final texture pack hash (typically `0xXXXXXXXX.g1t`).
- `status`
  - Mapping status for the row. `ok` means valid mapping.

## Recommended Workflow
1. Identify your target model hash (`g1m_hash`).
2. Search that hash in `all_model_g1t_mapping_agg.csv` to get candidate `ktid_hashes` and `g1t_hashes`.
3. For precise replacement, filter `all_model_g1t_mapping_detail.csv` by that `g1m_hash` and inspect `ktid_index`.
4. Locate/extract files by `g1t_hash` and replace the corresponding textures.

## Example
In `0x8D99EFB8.kidsobjdb.model_g1t_mapping.csv`, you can see:
- `g1m_hash = 0xCCB26970`
- `ktid_hash = 0x1725530B`
- Multiple `ktid_index` rows mapped to different `g1t_hash` values (`status = ok`).

## Common `status` Values
- `ok`
  - Mapping resolved successfully.
- `ktid_file_not_found`
  - `kidsobjdb` references a `ktid_hash`, but the corresponding `0xXXXXXXXX.ktid` file is not present in your scan scope.
- `ktid_parse_error:*`
  - KTID file exists but failed to parse (for example, empty or corrupted file).
- `textures_object_not_found` / `static_texture_object_not_found`
  - Reference chain is incomplete in `kidsobjdb`.

## Notes
- The same `g1m_hash` can appear in different `kidsobjdb` files.
- The same `g1t_hash` can be shared by multiple models and slots.
- Prefer rows with `status = ok` for actual replacement work.
- If your dataset does not include all KTID files, `ktid_file_not_found` is expected.
