# Nioh 3 Modding Guide: Find `g1m` -> `g1t` Using JSON Dumps

This guide explains how to use the JSON dump files in this folder to map model files (`g1m`) to texture files (`g1t`) for Nioh 3 modding.

## 1. JSON Files You Need

- `all_g1m2glt_agg.json`
  - Main lookup table.
  - Best file to quickly resolve `g1m_hash -> g1t_hashes`.
- `all_g1m2glt_detail.json`
  - Per-kidsobjdb summary and model-level details.
  - Useful for validation and troubleshooting.
- `0xXXXXXXXX.kidsobjdb.g1m2glt.json`
  - Per source database mapping.
  - Useful when you want to inspect one specific kidsobjdb in depth.

## 2. Hash Format and Naming

- Hashes are in hex string format: `0x1234ABCD`.
- Game files are commonly named by hash:
  - Model: `0xXXXXXXXX.g1m`
  - Texture pack: `0xXXXXXXXX.g1t`
  - Bind table: `0xXXXXXXXX.ktid`

So if your model file is `0xCCB26970.g1m`, the model hash is `0xCCB26970`.

## 3. Fast Path: `g1m` -> `g1t`

Open `all_g1m2glt_agg.json`, then:

1. Find the object where `g1m_hash` matches your model hash.
2. Read:
   - `ktid_hashes` (string; multiple values use `|`)
   - `g1t_hashes` (object map: key = `ktid_index`, value = `g1t_hash`)
   - `kidsobjdb_files` (string; multiple values use `|`)

Example structure:

```json
{
  "g1m_hash": "0xCCB26970",
  "ktid_hashes": "0x1725530B",
  "g1t_hashes": {
    "0": "0x7D2AF030",
    "1": "0xFC6736F4",
    "2": "0x78D18BA4",
    "3": "0xA64D0871"
  },
  "kidsobjdb_count": 1,
  "kidsobjdb_files": "0x8D99EFB8.kidsobjdb"
}
```

This means the model uses 4 texture slots, each slot pointing to a `g1t` hash.

## 4. What `g1t_hashes` Means

- `g1t_hashes` is a key-value map:
  - Key: KTID slot index (`ktid_index`)
  - Value: `g1t_hash`
- If one key contains `A|B|C`, that slot has multiple candidates from merged sources.

For most replacement workflows, you usually replace one or more of those `g1t` hashes directly.

## 5. Recommended Mod Workflow

1. Pick a target model (`0xXXXXXXXX.g1m`).
2. Resolve `g1t_hashes` from `all_g1m2glt_agg.json`.
3. Extract each target `0xXXXXXXXX.g1t` from your game package.
4. Edit textures and rebuild the `g1t` payload.
5. Repack/replace the modified `g1t` files with your standard Nioh 3 mod pipeline.

## 6. Validation (Optional but Recommended)

If you want to confirm a mapping:

1. Open `all_g1m2glt_detail.json`.
2. Locate the relevant `kidsobjdb_file` entry under `per_file`.
3. Find the model in `models` and compare `g1m_hash`, `ktid_hash`, and `g1t_hashes`.
4. If needed, open the specific `0xXXXXXXXX.kidsobjdb.g1m2glt.json`.

## 7. Common Edge Cases

- A model may appear in multiple kidsobjdb sources.
- One `g1t` can be shared by many models.
- Some models may have no resolved textures in one source but valid mappings in another.
- If `g1t_hashes` is empty (`{}`), that entry did not resolve textures in this dump.

## 8. Minimal Python Lookup Example

```python
import json

target_g1m = "0xCCB26970"
data = json.load(open("all_g1m2glt_agg.json", "r", encoding="utf-8"))

for row in data["mappings"]:
    if row["g1m_hash"].upper() == target_g1m.upper():
        print("KTID:", row["ktid_hashes"])
        print("G1T by slot:", row["g1t_hashes"])
        print("Source kidsobjdb:", row["kidsobjdb_files"])
        break
else:
    print("Model hash not found in dump.")
```

