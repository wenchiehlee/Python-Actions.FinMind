#!/usr/bin/env python3
"""Incrementally derive Type 17 from a FinMind Type 18 snapshot, without API calls."""
import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo


def read_rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def derive(daily, existing):
    previous = {(r['stock_code'], r['交易_週別']): r for r in existing}
    stocks = {r['stock_code'] for r in existing}
    boundaries = {stock: max(week for code, week in previous if code == stock) for stock in stocks}
    groups = {}
    for row in daily:
        if row['stock_code'] not in stocks:
            continue
        if row['download_success'].lower() != 'true' or not row['source_file'].startswith('FinMind_'):
            raise ValueError('Daily input must contain successful FinMind records')
        iso = date.fromisoformat(row['交易_日期']).isocalendar()
        key = (row['stock_code'], f'{iso.year % 100:02d}W{iso.week:02d}')
        if key not in groups or row['交易_日期'] > groups[key]['交易_日期']:
            groups[key] = row
    if {code for code, week in groups} != stocks:
        raise ValueError('Daily input does not cover all existing weekly stocks')
    stamp = datetime.now(ZoneInfo('Asia/Taipei')).isoformat(timespec='seconds')
    prior_close = {}
    updated = set()
    for (stock, week), daily_row in sorted(groups.items()):
        close = Decimal(daily_row['收盤價_元'])
        baseline = prior_close.get(stock)
        prior_close[stock] = close
        if week < boundaries[stock]:
            continue
        if baseline is None:
            raise ValueError(f'Missing prior weekly close for {stock}/{week}')
        old = previous.get((stock, week))
        if old and Decimal(old['收盤價_元']) == close:
            old_download = datetime.fromisoformat(old['download_timestamp']).replace(tzinfo=None)
            new_download = datetime.fromisoformat(daily_row['download_timestamp']).replace(tzinfo=None)
            if new_download < old_download:
                continue
        row = dict(daily_row)
        row.pop('交易_日期')
        row['交易_週別'] = week
        change = close - baseline
        row['漲跌價_元'] = str(change)
        row['漲跌幅_pct'] = f'{change / baseline * 100:.2f}%' if baseline else ''
        row['file_type'] = 'ShowWeeklyK_ChartFlow'
        row['source_file'] = f'FinMind_Derived_raw_daily_k_chart_flow_{stock}'
        row['process_timestamp'] = stamp
        row['stage1_process_timestamp'] = stamp
        # Preserve the real API download timestamp and daily EPS/PER values.
        previous[(stock, week)] = row
        updated.add(stock)
    if updated != stocks:
        raise ValueError(f'Incomplete refresh: updated {len(updated)}/{len(stocks)} stocks')
    return [previous[key] for key in sorted(previous)]


def write_rows(path, header, rows, line_ending="\r\n"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator=line_ending)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--daily-csv', required=True)
    parser.add_argument('--existing-csv', default='data/stage1_raw/raw_weekly_k_chart_flow.csv')
    parser.add_argument('--output')
    parser.add_argument('--financial-root', default='financial')
    args = parser.parse_args()
    header, existing = read_rows(args.existing_csv)
    daily_header, daily = read_rows(args.daily_csv)
    expected = ['交易_週別' if c == '交易_日期' else c for c in daily_header]
    if header != expected:
        raise ValueError('Daily/weekly headers do not match')
    result = derive(daily, existing)
    write_rows(args.output or args.existing_csv, header, result)
    by_stock = {}
    for row in result:
        by_stock.setdefault(row['stock_code'], []).append(row)
    for stock, rows in by_stock.items():
        write_rows(Path(args.financial_root) / 'type17' / f'raw_weekly_k_chart_flow_{stock}.csv', header, rows, line_ending="\n")
    print(f'Updated Type 17: {len(by_stock)} stocks, {len(existing)} -> {len(result)} rows')


if __name__ == '__main__':
    main()
