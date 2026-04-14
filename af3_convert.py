#!/usr/bin/env python3
"""
af3_convert.py — AlphaFold 3 Web Server → Local Installation JSON Converter

Usage:
    python af3_convert.py <file1.json> [file2.json ...]

    or drag-and-drop JSON files onto the script.

Each input file is validated and converted. Output is saved alongside the
input file as <name>_local.json.
"""

import json
import sys
import os
from pathlib import Path


# ---------------------------------------------------------------------------
# Field names required in each entry by the AF3 local installation format
# ---------------------------------------------------------------------------
REQUIRED_TOP_LEVEL = ["name", "sequences"]
REQUIRED_SEQUENCE_TYPES = {"protein", "rna", "dna", "ligand", "ion"}


def error(msg: str) -> None:
    print(f"  [ERROR] {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"  [WARN]  {msg}")


def info(msg: str) -> None:
    print(f"  [OK]    {msg}")


# ---------------------------------------------------------------------------
# Seed normalisation
# ---------------------------------------------------------------------------


def normalise_seeds(entry: dict) -> dict:
    """
    The web server exports `seed` as a plain integer, e.g.:
        "seed": 42

    The local installation expects a list of seed dicts, e.g.:
        "seeds": [{"seed": 42}]

    This function handles all observed variants and writes the canonical form.
    """
    seeds_out = []

    # Case 1: already in the correct local format  {"seeds": [...]}
    if "seeds" in entry:
        raw = entry.pop("seeds")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and "seed" in item:
                    seeds_out.append({"seed": int(item["seed"])})
                elif isinstance(item, int):
                    seeds_out.append({"seed": item})
                else:
                    seeds_out.append({"seed": int(item)})
        elif isinstance(raw, int):
            seeds_out.append({"seed": raw})
        else:
            warn(f"Unexpected 'seeds' format: {raw!r} — defaulting to seed 1")
            seeds_out.append({"seed": 1})

    # Case 2: web server format  {"seed": 42}
    elif "seed" in entry:
        raw = entry.pop("seed")
        if isinstance(raw, int):
            seeds_out.append({"seed": raw})
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and "seed" in item:
                    seeds_out.append({"seed": int(item["seed"])})
                else:
                    seeds_out.append({"seed": int(item)})
        else:
            warn(f"Unexpected 'seed' format: {raw!r} — defaulting to seed 1")
            seeds_out.append({"seed": 1})

    # Case 3: no seed field at all
    else:
        warn("No 'seed' field found — defaulting to seed 1")
        seeds_out.append({"seed": 1})

    entry["seeds"] = seeds_out
    return entry


# ---------------------------------------------------------------------------
# Sequence / ligand normalisation
# ---------------------------------------------------------------------------


def normalise_sequences(sequences: list, entry_name: str) -> list:
    """
    The web server may use a different key layout for sequences than the local
    format. Ensure each sequence entry uses the canonical structure:

        {"protein": {"id": "A", "sequence": "MAST..."}}
        {"ligand":  {"id": ["C", "D"], "ccdCodes": ["ATP"]}}

    Known web-server differences handled here:
    - `smiles` key instead of `ccdCodes` for small molecules
    - flat `id` string instead of list for multi-chain ligands
    - `type` discriminator field instead of a typed wrapper key
    """
    normalised = []
    for seq in sequences:
        if not isinstance(seq, dict):
            warn(f"[{entry_name}] Skipping non-dict sequence entry: {seq!r}")
            continue

        # --- Handle "type" discriminator pattern (some web exports) ----------
        if "type" in seq:
            seq_type = seq.pop("type").lower()
            seq = {seq_type: seq}

        # --- Determine the type key -----------------------------------------
        type_key = None
        for key in seq:
            if key.lower() in REQUIRED_SEQUENCE_TYPES:
                type_key = key
                break

        if type_key is None:
            warn(
                f"[{entry_name}] Cannot determine sequence type for entry: "
                f"{list(seq.keys())} — skipping"
            )
            continue

        inner = seq[type_key]

        if not isinstance(inner, dict):
            warn(
                f"[{entry_name}] Expected dict under '{type_key}', got {type(inner).__name__} — skipping"
            )
            continue

        # --- Ligand-specific fixes ------------------------------------------
        if type_key == "ligand":
            # id must be a list
            if "id" in inner and isinstance(inner["id"], str):
                inner["id"] = [inner["id"]]

            # smiles → ccdCodes (web server sometimes uses smiles)
            if "smiles" in inner and "ccdCodes" not in inner:
                inner["ccdCodes"] = inner.pop("smiles")

            # ccdCodes must be a list
            if "ccdCodes" in inner and isinstance(inner["ccdCodes"], str):
                inner["ccdCodes"] = [inner["ccdCodes"]]

        normalised.append({type_key: inner})

    return normalised


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_entry(entry: dict, entry_name: str) -> list[str]:
    """Return a list of validation error strings (empty = valid)."""
    errors = []

    for field in REQUIRED_TOP_LEVEL:
        if field not in entry:
            errors.append(f"Missing required field: '{field}'")

    if "sequences" in entry:
        seqs = entry["sequences"]
        if not isinstance(seqs, list) or len(seqs) == 0:
            errors.append("'sequences' must be a non-empty list")
        else:
            has_protein_or_nucleic = False
            for seq in seqs:
                if isinstance(seq, dict):
                    for t in ("protein", "rna", "dna"):
                        if t in seq:
                            has_protein_or_nucleic = True
            if not has_protein_or_nucleic:
                errors.append(
                    "'sequences' contains no protein, RNA, or DNA chain — "
                    "at least one is required"
                )

    if "seeds" not in entry:
        errors.append("'seeds' field is missing after normalisation")
    elif not isinstance(entry["seeds"], list) or len(entry["seeds"]) == 0:
        errors.append("'seeds' must be a non-empty list")

    return errors


# ---------------------------------------------------------------------------
# Per-entry conversion
# ---------------------------------------------------------------------------


def convert_entry(raw: dict, idx: int) -> dict | None:
    """Convert a single web-server entry dict to local format."""
    entry = dict(raw)  # shallow copy so we don't mutate the original
    entry_name = entry.get("name", f"entry_{idx}")

    print(f"\n  Processing entry: '{entry_name}'")

    # 1. Normalise seeds
    entry = normalise_seeds(entry)

    # 2. Normalise sequences
    if "sequences" in entry:
        entry["sequences"] = normalise_sequences(entry["sequences"], entry_name)

    # 3. Validate
    errs = validate_entry(entry, entry_name)
    if errs:
        for e in errs:
            error(e)
        error(f"Entry '{entry_name}' failed validation — skipped")
        return None

    info(f"Entry '{entry_name}' converted successfully")
    return entry


# ---------------------------------------------------------------------------
# File-level processing
# ---------------------------------------------------------------------------


def process_file(path: Path) -> bool:
    """Load, convert, and save one JSON file. Returns True on success."""
    print(f"\n{'=' * 60}")
    print(f"Input:  {path}")

    # --- Load ---------------------------------------------------------------
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        error(f"Cannot read file: {exc}")
        return False

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        error(f"Invalid JSON: {exc}")
        return False

    # Normalise to a list of entries (web server may export a single dict or a list)
    if isinstance(data, dict):
        entries_in = [data]
    elif isinstance(data, list):
        entries_in = data
    else:
        error(f"Unexpected top-level JSON type: {type(data).__name__}")
        return False

    print(f"  Found {len(entries_in)} entry/entries")

    # --- Convert ------------------------------------------------------------
    entries_out = []
    for idx, raw in enumerate(entries_in):
        if not isinstance(raw, dict):
            warn(f"Skipping non-dict entry at index {idx}: {type(raw).__name__}")
            continue
        converted = convert_entry(raw, idx)
        if converted is not None:
            entries_out.append(converted)

    if not entries_out:
        error("No entries were successfully converted — output file not written")
        return False

    # --- Write --------------------------------------------------------------
    out_path = path.with_stem(path.stem + "_local")
    try:
        out_path.write_text(
            json.dumps(entries_out, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        error(f"Cannot write output file: {exc}")
        return False

    print(f"\nOutput: {out_path}")
    print(
        f"  {len(entries_out)}/{len(entries_in)} entr{'y' if len(entries_in) == 1 else 'ies'} written"
    )
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        print("Error: no input files provided.", file=sys.stderr)
        sys.exit(1)

    results = {}
    for arg in args:
        p = Path(arg)
        if not p.exists():
            print(f"\n[ERROR] File not found: {arg}", file=sys.stderr)
            results[arg] = False
        elif not p.is_file():
            print(f"\n[ERROR] Not a file: {arg}", file=sys.stderr)
            results[arg] = False
        elif p.suffix.lower() != ".json":
            print(f"\n[WARN]  File does not have a .json extension: {arg}")
            results[arg] = process_file(p)
        else:
            results[arg] = process_file(p)

    # --- Summary ------------------------------------------------------------
    print(f"\n{'=' * 60}")
    ok = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"Done: {ok}/{total} file(s) converted successfully")

    if ok < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
