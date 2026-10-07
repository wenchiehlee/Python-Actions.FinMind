#!/usr/bin/env python3
"""Fetch FinMind shareholding data and export a GoodInfo Type 6 (EquityDistribution) CSV.

FinMind's TaiwanStockShareholding only reports foreign-investment ownership
(no government/financial/domestic-institution breakdown), so this adapter can
only fill the aggregate foreign-investment column (僑外投資_合計_pct) plus
price. Every other institutional-holder column GoodInfo tracks has no FinMind
source and is left blank rather than guessed.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from fetch_to_csv import fetch_data
from price_cache import cached_dataset, cached_price
from token_env import TokenRotator
load_dotenv()

COLUMNS = [
    "stock_code", "company_name", "年度", "當年股價_收盤", "當年股價_漲跌_元", "當年股價_漲跌_pct",
    "各類型股東持股比例_pct_政府_公營_機構", "各類型股東持股比例_pct_僑外投資",
    "各類型股東持股比例_pct_僑外投資.1", "各類型股東持股比例_pct_僑外投資.2",
    "各類型股東持股比例_pct_僑外投資.3", "各類型股東持股比例_pct_僑外投資.4",
    "各類型股東持股比例_pct_本國金融機構", "各類型股東持股比例_pct_本國金融機構.1",
    "各類型股東持股比例_pct_本國金融機構.2", "各類型股東持股比例_pct_本國法人",
    "各類型股東持股比例_pct_本國法人.1", "各類型股東持股比例_pct_本國法人.2",
    "各類型股東持股比例_pct_本國_自然人_個人", "各類型股東持股比例_pct_庫藏_股票",
    "成交價_成交張數", "昨收_成交金額", "漲跌價_成交筆數", "漲跌幅_成交均張", "振幅_成交均價",
    "開盤_淨值\u00a0_折溢價_pct", "最高_淨值\u00a0_折溢價_pct", "最低_淨值\u00a0_折溢價_pct",
    "開盤_PBR", "最高_PER", "最低_PEG",
    "file_type", "source_file", "download_success", "download_timestamp", "process_timestamp", "stage1_process_timestamp",
]


def price_by_year(prices):
    px = pd.DataFrame(prices)
    if px.empty:
        return {}
    px["date"] = pd.to_datetime(px["date"], errors="coerce")
    px = px.dropna(subset=["date"]).sort_values("date")
    px["year"] = px.date.dt.year.astype(str)
    return {year: float(g.iloc[-1].close) for year, g in px.groupby("year")}


def build(stock_id, name, shareholding, prices):
    sh = pd.DataFrame(shareholding)
    if sh.empty:
        return pd.DataFrame(columns=COLUMNS)
    sh["date"] = pd.to_datetime(sh["date"], errors="coerce")
    sh = sh.dropna(subset=["date"]).sort_values("date")
    sh["year"] = sh.date.dt.year.astype(str)
    year_end = sh.groupby("year").last()  # last available weekly snapshot per year
    closes = price_by_year(prices)

    rows = []
    timestamp = datetime.now().isoformat(timespec="seconds")
    previous_close = np.nan
    for year, snap in year_end.iterrows():
        close = closes.get(year, np.nan)
        change = close - previous_close if pd.notna(close) and pd.notna(previous_close) else np.nan
        foreign_ratio = snap.get("ForeignInvestmentSharesRatio")
        row = {
            "stock_code": str(stock_id).zfill(4), "company_name": name, "年度": year,
            "當年股價_收盤": close, "當年股價_漲跌_元": change,
            "當年股價_漲跌_pct": round(change / previous_close * 100, 2) if pd.notna(change) and previous_close else np.nan,
            "各類型股東持股比例_pct_政府_公營_機構": np.nan,
            "各類型股東持股比例_pct_僑外投資": np.nan, "各類型股東持股比例_pct_僑外投資.1": np.nan,
            "各類型股東持股比例_pct_僑外投資.2": np.nan, "各類型股東持股比例_pct_僑外投資.3": np.nan,
            "各類型股東持股比例_pct_僑外投資.4": round(foreign_ratio, 2) if pd.notna(foreign_ratio) else np.nan,
            "各類型股東持股比例_pct_本國金融機構": np.nan, "各類型股東持股比例_pct_本國金融機構.1": np.nan,
            "各類型股東持股比例_pct_本國金融機構.2": np.nan, "各類型股東持股比例_pct_本國法人": np.nan,
            "各類型股東持股比例_pct_本國法人.1": np.nan, "各類型股東持股比例_pct_本國法人.2": np.nan,
            "各類型股東持股比例_pct_本國_自然人_個人": np.nan, "各類型股東持股比例_pct_庫藏_股票": np.nan,
            "成交價_成交張數": np.nan, "昨收_成交金額": np.nan, "漲跌價_成交筆數": np.nan,
            "漲跌幅_成交均張": np.nan, "振幅_成交均價": np.nan, "開盤_淨值\u00a0_折溢價_pct": np.nan,
            "最高_淨值\u00a0_折溢價_pct": np.nan, "最低_淨值\u00a0_折溢價_pct": np.nan,
            "開盤_PBR": np.nan, "最高_PER": np.nan, "最低_PEG": np.nan,
            "file_type": "EquityDistribution",
            "source_file": f"FinMind_API_TaiwanStockShareholding_{str(stock_id).zfill(4)}",
            "download_success": True, "download_timestamp": timestamp,
            "process_timestamp": timestamp, "stage1_process_timestamp": timestamp,
        }
        rows.append(row)
        if pd.notna(close):
            previous_close = close
    return pd.DataFrame(rows, columns=COLUMNS)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--stock-id', default='2330')
    p.add_argument('--company-name', default='台積電')
    p.add_argument('--start-date', default='2018-01-01')
    p.add_argument('--end-date', default=(datetime.now() + timedelta(hours=8)).strftime('%Y-%m-%d'))
    p.add_argument('--output', default='financial/type6/raw_equity_distribution_2330.csv')
    p.add_argument('--token', default=None)
    p.add_argument('--price-cache-dir', default=None)
    a = p.parse_args()
    rot = TokenRotator(a.token)
    sh = cached_dataset('TaiwanStockShareholding', a.stock_id, a.start_date, a.end_date, rot, a.price_cache_dir, fetch_data)
    px = cached_price(a.stock_id, a.start_date, a.end_date, rot, a.price_cache_dir, fetch_data)
    out = build(a.stock_id, a.company_name, sh.to_dict('records'), px.to_dict('records'))
    if out.empty:
        raise SystemExit('No shareholding data available')
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(a.output, index=False, encoding='utf-8-sig')
    print(f'Wrote {len(out)} annual equity distribution rows to {a.output}')


if __name__ == '__main__':
    main()
