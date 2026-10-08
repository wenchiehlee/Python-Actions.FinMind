#!/usr/bin/env python3
"""Incrementally refresh Type 9, preserving quarter opens and older history."""
import argparse
import csv
import json
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/skill-finmind-fetch/scripts'))
from fetch_to_csv import fetch_data
from token_env import TokenRotator

QUARTERS = ['第一季', '第二季', '第三季', '第四季']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-csv', default=str(ROOT / 'data/stage1_raw/raw_stock_his_quar.csv'))
    parser.add_argument('--cache-dir', required=True)
    parser.add_argument('--end-date', default=datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat())
    args = parser.parse_args()
    path = Path(args.input_csv)
    with path.open(encoding='utf-8-sig', newline='') as h:
        reader = csv.DictReader(h)
        header, rows = reader.fieldnames, list(reader)
    by_stock = {}
    for row in rows:
        by_stock.setdefault(row['stock_code'], []).append(row)
    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    rot = TokenRotator()
    report = []
    for index, (stock, history) in enumerate(sorted(by_stock.items()), 1):
        current = max(history, key=lambda r: r['年度'])
        start = datetime.fromisoformat(current['download_timestamp']).date().isoformat()
        cached = cache / f'TaiwanStockPrice_{stock}_2024-01-01.json'
        if cached.exists() and datetime.fromtimestamp(cached.stat().st_mtime, ZoneInfo("Asia/Taipei")).date().isoformat() >= args.end_date:
            records = json.loads(cached.read_text())
        else:
            cached = cache / f'TaiwanStockPrice_{stock}_{start}_{args.end_date}.json'
            if cached.exists():
                records = json.loads(cached.read_text())
            else:
                data = fetch_data('TaiwanStockPrice', data_id=stock, start_date=start,
                                  end_date=args.end_date, token=rot)
                if data.empty:
                    raise RuntimeError(f'No source prices for {stock}; combined stage1 remains unchanged')
                records = data.to_dict('records')
                cached.write_text(json.dumps(records, ensure_ascii=False))
                time.sleep(0.25)
        records = sorted((r for r in records if start <= r['date'] <= args.end_date), key=lambda r: r['date'])
        if not records:
            raise RuntimeError(f'No current prices for {stock}; combined stage1 remains unchanged')
        download_stamp = datetime.fromtimestamp(cached.stat().st_mtime, ZoneInfo('Asia/Taipei')).isoformat(timespec='seconds')
        updates = {}
        for item in records:
            day = datetime.strptime(item['date'], '%Y-%m-%d')
            updates.setdefault((str(day.year), (day.month - 1) // 3), []).append(item)
        for (year, q), prices in sorted(updates.items()):
            row = next((r for r in history if r['年度'] == year), None)
            if row is None:
                row = dict.fromkeys(header, '')
                row.update(stock_code=stock, company_name=current['company_name'], 年度=year)
                history.append(row)
            label = QUARTERS[q]
            # An existing open is the quarter's true first trading-day open.
            if not row[f'{label}_開盤_元']:
                quarter_start = f'{year}-{q * 3 + 1:02d}-01'
                if start > quarter_start:
                    raise RuntimeError(f'Missing quarter-start price for {stock}/{year}/{label}')
                row[f'{label}_開盤_元'] = str(prices[0]['open'])
            close = Decimal(str(prices[-1]['close']))
            row[f'{label}_收盤_元'] = str(close)
            baseline = None
            for earlier in sorted(history, key=lambda r: r['年度']):
                for j, name in enumerate(QUARTERS):
                    if (earlier['年度'], j) >= (year, q):
                        break
                    value = earlier[f'{name}_收盤_元']
                    if value:
                        baseline = Decimal(value)
            if baseline is not None:
                row[f'{label}_漲跌_元'] = str(close - baseline)
                row[f'{label}_漲跌_pct'] = str(round((close - baseline) / baseline * 100, 2)) if baseline else ''
            stamp = datetime.now(ZoneInfo('Asia/Taipei')).isoformat(timespec='seconds')
            row.update(file_type='StockHisAnaQuar', source_file=f'FinMind_API_TaiwanStockPrice_{stock}',
                       download_success='True', download_timestamp=download_stamp,
                       process_timestamp=stamp, stage1_process_timestamp=stamp)
        report.append({'stock': stock, 'latest_price_date': records[-1]['date']})
        checkpoint = cache / 'type9_refresh_progress.json'
        checkpoint.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        if index % 10 == 0:
            print(f'Type 9: processed {index}/{len(by_stock)} stocks; latest {records[-1]["date"]}', flush=True)
    result = [row for stock in sorted(by_stock) for row in sorted(by_stock[stock], key=lambda r: r['年度'])]
    with path.open('w', encoding='utf-8-sig', newline='') as h:
        w = csv.DictWriter(h, fieldnames=header)
        w.writeheader()
        w.writerows(result)
    for stock, history in by_stock.items():
        out = ROOT / 'financial/type9' / f'raw_stock_his_quar_{stock}.csv'
        with out.open('w', encoding='utf-8-sig', newline='') as h:
            w = csv.DictWriter(h, fieldnames=header, lineterminator='\n')
            w.writeheader()
            w.writerows(sorted(history, key=lambda r: r['年度']))
    print(f'Type 9 complete: {len(by_stock)} stocks, {len(result)} rows', flush=True)


if __name__ == '__main__':
    main()
