#!/usr/bin/env python3
"""Fetch FinMind fundamentals and export a GoodInfo Type 4 (StockBzPerformance) CSV.

GoodInfo's proprietary 財報_評分 (financial report score) has no FinMind
equivalent and is left blank. Everything else is derived from FinMind's
TaiwanStockFinancialStatements, TaiwanStockBalanceSheet, and TaiwanStockPrice.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
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
    "stock_code", "company_name", "年度", "股本_億", "財報_評分",
    "年度股價_元_收盤", "年度股價_元_平均", "年度股價_元_漲跌", "年度股價_元_漲跌_pct",
    "獲利金額_億_營業_收入", "獲利金額_億_營業_毛利", "獲利金額_億_營業_利益",
    "獲利金額_億_業外_損益", "獲利金額_億_稅後_淨利",
    "獲利率_pct_營業_毛利", "獲利率_pct_營業_利益", "獲利率_pct_業外_損益", "獲利率_pct_稅後_淨利",
    "roe_pct", "roa_pct", "eps_元_稅後_eps", "eps_元_年增_元", "bps_元",
    "目前股價_103.85\u00a0元", "目前股價_103.85\u00a0元_目前股價_103.85\u00a0元.1", "目前股價_103.85\u00a0元_目前股價_103.85\u00a0元.2",
    "成交價_元_平均", "成交價_元_平均.1", "成交價_元_最低", "成交價_元_最低.1", "成交價_元_最高", "成交價_元_最高.1",
    "平均漲跌_漲跌_元", "平均漲跌_漲跌_元.1", "平均漲跌_漲跌_元.2", "平均漲跌_漲跌_pct", "平均漲跌_漲跌_pct.1", "平均漲跌_漲跌_pct.2",
    "成交量_張_最低量", "成交量_張_最低量.1", "成交量_張_最低量.2", "成交量_張_最高量", "成交量_張_最高量.1", "成交量_張_最高量.2",
    "營業收入_平均_億元", "營業收入_平均_億元.1", "營業收入_平均_億元.2", "營業收入_均成長_pct", "營業收入_均成長_pct.1", "營業收入_均成長_pct.2",
    "稅後淨利_平均_億元", "稅後淨利_平均_億元.1", "稅後淨利_平均_億元.2", "稅後淨利_均成長_pct", "稅後淨利_均成長_pct.1", "稅後淨利_均成長_pct.2",
    "平均獲利率_毛利率", "平均獲利率_毛利率.1", "平均獲利率_毛利率.2", "平均獲利率_淨利率", "平均獲利率_淨利率.1", "平均獲利率_淨利率.2",
    "目前股價_60.6\u00a0元", "目前股價_60.6\u00a0元_目前股價_60.6\u00a0元.1", "目前股價_60.6\u00a0元_目前股價_60.6\u00a0元.2",
    "file_type", "source_file", "download_success", "download_timestamp", "process_timestamp", "stage1_process_timestamp",
]


def index_by_year(records):
    """One dict per year: flow items (Revenue etc.) summed across quarters,
    stock items (equity, assets, capital) kept as the latest quarter's value."""
    by_quarter = defaultdict(dict)
    for item in records:
        kind = item.get("type", "")
        if kind.endswith("_per"):
            continue
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            continue
        by_quarter[item["date"]][kind] = value
    return by_quarter


FLOW_FIELDS = ("Revenue", "GrossProfit", "OperatingIncome", "PreTaxIncome", "IncomeAfterTaxes", "EPS")
STOCK_FIELDS = ("OrdinaryShare", "Equity", "EquityAttributableToOwnersOfParent", "TotalAssets")


def annualize(fin_by_quarter, bal_by_quarter):
    dates = sorted(set(fin_by_quarter) & set(bal_by_quarter))
    years = defaultdict(lambda: {f: 0.0 for f in FLOW_FIELDS})
    latest_stock = {}
    for d in dates:
        year = d[:4]
        fin, bal = fin_by_quarter[d], bal_by_quarter[d]
        for f in FLOW_FIELDS:
            if f in fin:
                years[year][f] += fin[f]
        stock_row = {f: bal.get(f) for f in STOCK_FIELDS if f in bal}
        stock_row["OrdinaryShare_income"] = fin.get("OrdinaryShare")
        latest_stock[year] = {**latest_stock.get(year, {}), **stock_row}
    return years, latest_stock


def price_by_year(prices):
    px = pd.DataFrame(prices)
    if px.empty:
        return {}
    px["date"] = pd.to_datetime(px["date"], errors="coerce")
    px = px.dropna(subset=["date"]).sort_values("date")
    px["year"] = px.date.dt.year.astype(str)
    result = {}
    for year, g in px.groupby("year"):
        result[year] = {"close": float(g.iloc[-1].close), "open": float(g.iloc[0].open), "avg": float(g.close.mean())}
    return result


def build(stock_id, name, fin_records, bal_records, prices):
    fin_by_quarter = index_by_year(fin_records)
    bal_by_quarter = index_by_year(bal_records)
    years, stock_by_year = annualize(fin_by_quarter, bal_by_quarter)
    prices_by_year = price_by_year(prices)

    rows = []
    timestamp = datetime.now().isoformat(timespec="seconds")
    previous_close = np.nan
    previous_eps = np.nan
    for year in sorted(years):
        flows = years[year]
        stock = stock_by_year.get(year, {})
        revenue, gross, op_income, pretax, net_income, eps = (
            flows.get("Revenue"), flows.get("GrossProfit"), flows.get("OperatingIncome"),
            flows.get("PreTaxIncome"), flows.get("IncomeAfterTaxes"), flows.get("EPS"))
        non_operating = pretax - op_income if pretax is not None and op_income is not None else np.nan
        equity = stock.get("EquityAttributableToOwnersOfParent") or stock.get("Equity")
        assets = stock.get("TotalAssets")
        capital = stock.get("OrdinaryShare")
        shares = capital / 10 if capital else None  # NT$10 par value
        price = prices_by_year.get(year, {})
        close = price.get("close", np.nan)
        change = close - previous_close if pd.notna(close) and pd.notna(previous_close) else np.nan
        row = {
            "stock_code": str(stock_id).zfill(4), "company_name": name, "年度": year,
            "股本_億": round(capital / 1e8, 2) if capital else np.nan,
            "財報_評分": np.nan,
            "年度股價_元_收盤": close, "年度股價_元_平均": price.get("avg", np.nan),
            "年度股價_元_漲跌": change,
            "年度股價_元_漲跌_pct": round(change / previous_close * 100, 2) if pd.notna(change) and previous_close else np.nan,
            "獲利金額_億_營業_收入": round(revenue / 1e8, 2) if revenue is not None else np.nan,
            "獲利金額_億_營業_毛利": round(gross / 1e8, 2) if gross is not None else np.nan,
            "獲利金額_億_營業_利益": round(op_income / 1e8, 2) if op_income is not None else np.nan,
            "獲利金額_億_業外_損益": round(non_operating / 1e8, 2) if pd.notna(non_operating) else np.nan,
            "獲利金額_億_稅後_淨利": round(net_income / 1e8, 2) if net_income is not None else np.nan,
            "獲利率_pct_營業_毛利": round(gross / revenue * 100, 2) if gross is not None and revenue else np.nan,
            "獲利率_pct_營業_利益": round(op_income / revenue * 100, 2) if op_income is not None and revenue else np.nan,
            "獲利率_pct_業外_損益": round(non_operating / revenue * 100, 2) if pd.notna(non_operating) and revenue else np.nan,
            "獲利率_pct_稅後_淨利": round(net_income / revenue * 100, 2) if net_income is not None and revenue else np.nan,
            "roe_pct": round(net_income / equity * 100, 2) if net_income is not None and equity else np.nan,
            "roa_pct": round(net_income / assets * 100, 2) if net_income is not None and assets else np.nan,
            "eps_元_稅後_eps": round(eps, 2) if eps is not None else np.nan,
            "eps_元_年增_元": round(eps - previous_eps, 2) if eps is not None and pd.notna(previous_eps) else np.nan,
            "bps_元": round(equity / shares, 2) if equity and shares else np.nan,
            "file_type": "StockBzPerformance",
            "source_file": f"FinMind_API_TaiwanStockFinancialStatements_{str(stock_id).zfill(4)}",
            "download_success": True, "download_timestamp": timestamp,
            "process_timestamp": timestamp, "stage1_process_timestamp": timestamp,
        }
        rows.append(row)
        if pd.notna(close):
            previous_close = close
        if eps is not None:
            previous_eps = eps
    return pd.DataFrame(rows, columns=COLUMNS)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--stock-id', default='2330')
    p.add_argument('--company-name', default='台積電')
    p.add_argument('--start-date', default='2018-01-01')
    p.add_argument('--end-date', default=(datetime.now() + timedelta(hours=8)).strftime('%Y-%m-%d'))
    p.add_argument('--output', default='financial/type4/raw_performance_2330.csv')
    p.add_argument('--token', default=None)
    p.add_argument('--price-cache-dir', default=None)
    a = p.parse_args()
    rot = TokenRotator(a.token)
    fin = cached_dataset('TaiwanStockFinancialStatements', a.stock_id, a.start_date, a.end_date, rot, a.price_cache_dir, fetch_data)
    bal = fetch_data('TaiwanStockBalanceSheet', data_id=a.stock_id, start_date=a.start_date, end_date=a.end_date, token=rot)
    px = cached_price(a.stock_id, a.start_date, a.end_date, rot, a.price_cache_dir, fetch_data)
    out = build(a.stock_id, a.company_name, fin.to_dict('records'), bal.to_dict('records'), px.to_dict('records'))
    if out.empty:
        raise SystemExit('No performance data available')
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(a.output, index=False, encoding='utf-8-sig')
    print(f'Wrote {len(out)} annual performance rows to {a.output}')


if __name__ == '__main__':
    main()
