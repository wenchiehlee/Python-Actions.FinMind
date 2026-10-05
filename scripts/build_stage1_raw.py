#!/usr/bin/env python3
"""Combine per-stock financial/type*/*.csv files into Analyzer-style
data/stage1_raw/<stem>.csv files (one row per stock, all stocks combined).

Column layout matches Python-Actions.GoodInfo.Analyzer's stage1_raw CSVs
exactly, so this repo's output can be dropped in as a source for it.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import status_common


def combine_type(financial_root: Path, type_id: str, stem: str) -> tuple[Path, int]:
    directory = financial_root / f"type{type_id}"
    out_path = ROOT / "data" / "stage1_raw" / f"{stem}.csv"

    # Type 13 is already one combined file across all stocks; just reuse it.
    if type_id == "13":
        combined = directory / f"{stem}.csv"
        if not combined.exists():
            return out_path, 0
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(combined.read_bytes())
        with combined.open(encoding="utf-8-sig", newline="") as handle:
            return out_path, sum(1 for _ in csv.reader(handle)) - 1

    if not directory.is_dir():
        return out_path, 0

    files = sorted(
        p for p in directory.glob(f"{stem}_*.csv")
        if status_common.STOCK_CODE.search(p.stem)
    )
    if not files:
        return out_path, 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = None
    row_count = 0
    with out_path.open("w", encoding="utf-8-sig", newline="") as out_handle:
        writer = None
        for path in files:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                file_header = next(reader, None)
                if file_header is None:
                    continue
                if header is None:
                    header = file_header
                    if type_id == "16":
                        schema_path = ROOT / "skills" / "skill-finmind-fetch" / "schemas" / "raw_fin_ratio_quarter_header.csv"
                        with schema_path.open(encoding="utf-8-sig", newline="") as schema_handle:
                            expected_header = next(csv.reader(schema_handle), None)
                        if file_header != expected_header:
                            raise SystemExit(
                                f"Type 16 schema mismatch in {path}: expected canonical Analyzer-compatible header"
                            )
                    writer = csv.writer(out_handle)
                    writer.writerow(header)
                elif file_header != header:
                    raise SystemExit(f"Column mismatch in {path}: expected {header}, got {file_header}")
                process_timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                for row in reader:
                    if type_id == "16":
                        for field in ("process_timestamp", "stage1_process_timestamp"):
                            if field in header:
                                row[header.index(field)] = process_timestamp
                    writer.writerow(row)
                    row_count += 1
    return out_path, row_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="financial")
    args = parser.parse_args()
    financial_root = Path(args.data_root)

    for type_id, stem in status_common.ACTIVE_TYPES.items():
        out_path, rows = combine_type(financial_root, type_id, stem)
        print(f"type{type_id}: wrote {rows} rows to {out_path}")


if __name__ == "__main__":
    main()
