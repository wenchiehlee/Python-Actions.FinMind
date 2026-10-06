#!/usr/bin/env python3
"""Fetch all currently implemented FinMind types for the observation list.

The workflow supplies the token secrets as environment variables. Each stock
subprocess is handed the full pool of currently-healthy tokens, rotated so
its round-robin-assigned token comes first; the child's own TokenRotator can
then retire and fall back to another token if its primary 402s mid-call,
instead of failing outright. Type 13 is fetched once as a combined CSV;
Types 14 and 15 are derived locally from that file.
"""
from __future__ import annotations
import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "skill-finmind-fetch" / "scripts"))
from token_env import get_finmind_tokens, order_tokens
sys.path.insert(0, str(ROOT / "scripts"))
import status_common
from download_log import now_cst, result_row, write_results

# The exact "no data" SystemExit message each script raises when the FinMind
# API genuinely has nothing for that stock (as opposed to a failed request).
NO_DATA_MESSAGES = {
    "1": "No dividend data available",
    "4": "No performance data available",
    "5": "No revenue data available",
    "6": "No shareholding data available",
    "7": "No performance data available",
    "8": "No price data available",
    "9": "No price data available",
    "12": "No price data available",
    "17": "No price data available",
    "18": "No price data available",
    "11": "No weekly trading data available",
    "19": "No dividend schedule data available",
    "14": "No daily data available for Type 14",
    "15": "No daily data available for Type 15",
}


def classify_status(type_id: str, success: bool, output_text: str) -> str:
    if success:
        return "success"
    text = (output_text or "").lower()
    if "402" in text or "reach the upper limit" in text:
        return "rate_limited"
    no_data_message = NO_DATA_MESSAGES.get(type_id)
    if no_data_message and no_data_message.lower() in text:
        return "no_data"
    return "retryable_failed"

TOKEN_NAMES = (
    "FINMIND_TOKEN1", "FINMIND_TOKEN2", "FINMIND_TOKEN3",
    "FINMIND_TOKEN4", "FINMIND_TOKEN5", "FINMIND_TOKEN6", "FINMIND_TOKEN7",
)
TOKEN_ORDER = []
MIN_QUOTA_HEADROOM = 20  # skip a token's round-robin slot once it's this close to its hourly 402 cutoff
PYTHON = sys.executable
SCRIPTS = ROOT / "skills" / "skill-finmind-fetch" / "scripts"


def stocks(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.reader(handle):
            if not row or row[0].strip() in {"代號", "stock_code"}:
                continue
            code = row[0].strip().zfill(4)
            if code and code != "0000":
                yield code, (row[1].strip() if len(row) > 1 else f"Stock_{code}")


def token_env(index: int):
    values = [v for v in (TOKEN_ORDER or [os.environ.get(name, "") for name in TOKEN_NAMES]) if v]
    env = os.environ.copy()
    if not values:
        for name in TOKEN_NAMES:
            env[name] = ""
        return env
    # Rotate so this stock's round-robin-assigned token is offered first, but
    # pass the rest of the healthy pool along too so the child's TokenRotator
    # has somewhere to fall back to if the primary 402s mid-call.
    primary = index % len(values)
    rotated = values[primary:] + values[:primary]
    for slot, name in enumerate(TOKEN_NAMES):
        env[name] = rotated[slot] if slot < len(rotated) else ""
    return env


def run(args, token_index: int, label: str, preserve_pool: bool = False) -> tuple[bool, str]:
    command = [PYTHON, *map(str, args)]
    print(f"[{label}] {Path(command[1]).name if len(command) > 1 else label}", flush=True)
    env = os.environ.copy() if preserve_pool else token_env(token_index)
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    output_text = completed.stdout + completed.stderr
    if output_text:
        print(output_text, end="" if output_text.endswith("\n") else "\n", flush=True)
    if completed.returncode:
        print(f"[{label}] failed with exit code {completed.returncode}", flush=True)
        return False, output_text
    return True, output_text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock-list", required=True)
    parser.add_argument("--start-date", default="2021-01-01")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--types", default=None,
                         help="Comma-separated type IDs to run (e.g. '1,5,8'); default runs every active type")
    args = parser.parse_args()
    end = args.end_date or __import__("datetime").date.today().isoformat()
    target = list(stocks(Path(args.stock_list)))
    if not target:
        raise SystemExit("No stocks found")
    if args.types:
        selected_types = {t.strip() for t in args.types.split(",") if t.strip()}
        unknown = selected_types - set(status_common.ACTIVE_TYPES)
        if unknown:
            raise SystemExit(f"Unknown type id(s): {', '.join(sorted(unknown))}")
    else:
        selected_types = set(status_common.ACTIVE_TYPES)
    print(f"Selected types: {', '.join(sorted(selected_types, key=int))}", flush=True)
    global TOKEN_ORDER
    configured = get_finmind_tokens()

    def refresh_token_order(label: str):
        # Re-checked before each type so a token that ran dry earlier in this
        # run sorts to the back instead of staying pinned to its start-of-run slot.
        ordered, details = order_tokens(configured)
        healthy = [(tok, remaining, state) for tok, (remaining, state) in zip(ordered, details)
                   if remaining < 0 or remaining >= MIN_QUOTA_HEADROOM]
        # A quota-check failure reports remaining=-1; keep those tokens in the
        # pool since we can't tell if they're actually low, only that the
        # user_info lookup itself failed. Only drop tokens confirmed low.
        if not healthy:
            healthy = [(tok, remaining, state) for tok, (remaining, state) in zip(ordered, details)]
        TOKEN_ORDER[:] = [tok for tok, _, _ in healthy]
        for slot, (_, remaining, state) in enumerate(healthy, start=1):
            print(f"[{label}] token-slot={slot} remaining={remaining} quota-check={state}", flush=True)
        skipped = len(ordered) - len(healthy)
        if skipped:
            print(f"[{label}] skipped {skipped} token(s) with <{MIN_QUOTA_HEADROOM} quota remaining", flush=True)

    TOKEN_ORDER = []
    refresh_token_order("startup")
    print(f"Fetching {len(target)} stocks with quota-aware token rotation", flush=True)
    ok = 0

    # Types 1, 5, 8, 11, 12, 17, and 18 all fetch TaiwanStockPrice for the same
    # stock; sharing one cache per run avoids re-requesting it up to 7 times.
    price_cache_dir = ROOT / "financial" / ".price_cache"
    if price_cache_dir.exists():
        shutil.rmtree(price_cache_dir)

    # Rows collected per type as stocks are processed, so the download_results.csv
    # status reflects what actually happened in *this* run instead of just
    # whether a (possibly stale, from a previous day) output file exists. Only
    # the selected types are tracked, so an unselected type's existing log is
    # left untouched rather than overwritten with a cruder fallback.
    type_rows: dict[str, list] = {t: [] for t in selected_types}
    # A green workflow must mean every selected type fetched at least one row.
    # Otherwise stage1 rebuilds can republish stale files as a false success.
    type_success: dict[str, bool] = {t: False for t in selected_types}

    # One combined Type 13 request loop; Type 14/15 reuse this file locally.
    # The path is always defined even when Type 13 itself isn't selected, so
    # a Type 14/15-only run still reuses whatever raw_margin_daily.csv is
    # already on disk.
    type13 = ROOT / "financial" / "type13" / "raw_margin_daily.csv"
    if "13" in selected_types:
        if run([SCRIPTS / "fetch_to_csv.py", "--stock-list", args.stock_list,
                "--start-date", args.start_date, "--end-date", end,
                "--output-csv", type13], 0, "type13", preserve_pool=True)[0]:
            ok += 1
            type_success["13"] = True

    jobs = [
        ("1", "fetch_type1.py", "raw_dividends", "2018-01-01"),
        ("5", "fetch_type5.py", "raw_revenue", "2021-01-01"),
        ("8", "fetch_k_chart_flow.py", "raw_weekly_flow", "2021-01-01"),
        ("12", "fetch_k_chart_flow.py", "raw_monthly_flow", "2021-01-01"),
        ("17", "fetch_k_chart_flow.py", "raw_weekly_k_chart_flow", "2021-01-01"),
        ("18", "fetch_k_chart_flow.py", "raw_daily_k_chart_flow", "2021-01-01"),
        ("11", "fetch_type11.py", "raw_weekly_trading_data", "2021-01-01"),
        ("16", "fetch_type16.py", "raw_fin_ratio_quarter", "2020-01-01"),
        ("19", "fetch_type19.py", "raw_dividend_schedule", "2018-01-01"),
        ("4", "fetch_type4.py", "raw_performance", "2018-01-01"),
        ("7", "fetch_type7.py", "raw_performance1", "2018-01-01"),
        ("9", "fetch_type9.py", "raw_stock_his_quar", "2018-01-01"),
        ("6", "fetch_type6.py", "raw_equity_distribution", "2018-01-01"),
    ]
    price_cache_types = {"1", "5", "8", "12", "17", "18", "11", "4", "7", "9", "6"}
    process_time = now_cst()
    for type_id, script, stem, start in jobs:
        if type_id not in selected_types:
            continue
        refresh_token_order(f"type{type_id}")
        for index, (code, name) in enumerate(target):
            output = ROOT / "financial" / f"type{type_id}" / f"{stem}_{code}.csv"
            command = [SCRIPTS / script, "--stock-id", code, "--company-name", name,
                       "--start-date", start, "--end-date", end, "--output", output]
            if type_id in price_cache_types:
                command += ["--price-cache-dir", price_cache_dir]
            if type_id in {"8", "12", "17", "18"}:
                command[1:1] = ["--type", type_id]
            success, output_text = run(command, index, f"type{type_id}/{code}")
            if success:
                ok += 1
                type_success[type_id] = True
            status = classify_status(type_id, success, output_text)
            type_rows[type_id].append(result_row(f"{stem}_{code}.csv", success, process_time, status=status))

    for type_id, script, stem in (("14", "fetch_type14.py", "raw_margin_weekly"),
                                  ("15", "fetch_type15.py", "raw_margin_monthly")):
        if type_id not in selected_types:
            continue
        refresh_token_order(f"type{type_id}")
        for index, (code, name) in enumerate(target):
            output = ROOT / "financial" / f"type{type_id}" / f"{stem}_{code}.csv"
            command = [SCRIPTS / script, "--stock-id", code, "--company-name", name,
                       "--daily-csv", type13, "--start-date", args.start_date,
                       "--end-date", end, "--output", output]
            success, output_text = run(command, index, f"type{type_id}/{code}")
            if success:
                ok += 1
                type_success[type_id] = True
            status = classify_status(type_id, success, output_text)
            type_rows[type_id].append(result_row(f"{stem}_{code}.csv", success, process_time, status=status))
    print(f"Completed fetch commands: {ok}", flush=True)
    shutil.rmtree(price_cache_dir, ignore_errors=True)

    financial_root = ROOT / "financial"
    for type_id, rows in type_rows.items():
        stem = status_common.ACTIVE_TYPES[type_id]
        if not rows:
            # Type 13 is a single combined request, not looped per stock;
            # fall back to scanning its output for per-stock coverage.
            present = status_common.output_stock_codes(financial_root, type_id)
            rows = [result_row(f"{stem}_{code}.csv", code in present, process_time)
                    for code, _ in target]
            # Unlike every other type, Type 13's combined fetch does cover the
            # market index (0000) with real data.
            rows.append(result_row(f"{stem}_0000.csv", "0000" in present, process_time))
        else:
            # These per-stock adapters never attempt the market index (0000) --
            # dividends, revenue, and similar per-company metrics don't apply
            # to it -- so it's never in `target`. Log it explicitly as no_data
            # instead of letting it silently disappear from the total.
            rows.append(result_row(f"{stem}_0000.csv", False, process_time, status="no_data"))
        write_results(financial_root / f"type{type_id}" / "download_results.csv", rows)
    print("Wrote download_results.csv logs for active types", flush=True)
    failed_types = sorted((type_id for type_id, success in type_success.items() if not success), key=int)
    if failed_types:
        raise SystemExit("No successful fetch completed for selected type(s): " + ", ".join(failed_types))


if __name__ == "__main__":
    main()
