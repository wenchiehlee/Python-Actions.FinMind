#!/usr/bin/env python3
"""Fetch FinMind fundamentals and export a GoodInfo Type 7 (StockBzPerformance1) CSV.

Quarterly counterpart of Type 4. GoodInfo's proprietary 財報_評分 has no
FinMind equivalent and is left blank.
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
    "stock_code", "company_name", "季度", "股本_億", "財報_評分",
    "季度股價_元_收盤", "季度股價_元_平均", "季度股價_元_漲跌", "季度股價_元_漲跌_pct",
    "獲利金額_億_營業_收入", "獲利金額_億_營業_毛利", "獲利金額_億_營業_利益",
    "獲利金額_億_業外_損益", "獲利金額_億_稅後_淨利",
    "獲利率_pct_營業_毛利", "獲利率_pct_營業_利益", "獲利率_pct_業外_損益", "獲利率_pct_稅後_淨利",
    "單季_ROE_pct", "年化_ROE_pct", "單季_ROA_pct", "年化_ROA_pct",
    "eps_元_稅後_eps", "eps_元_年增_元", "bps_元",
    "成交價_成交張數", "昨收_成交金額", "漲跌價_成交筆數", "漲跌幅_成交均張", "振幅_成交均價",
    "開盤_淨值\u00a0_折溢價_pct", "最高_淨值\u00a0_折溢價_pct", "最低_淨值\u00a0_折溢價_pct",
    "file_type", "source_file", "download_success", "download_timestamp", "process_timestamp", "stage1_process_timestamp",
]


def index_by_date(records):
    by_date = {}
    for item in records:
        kind = item.get("type", "")
        if kind.endswith("_per"):
            continue
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            continue
        by_date.setdefault(item["date"], {})[kind] = value
    return by_date


def to_quarter_label(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.year}/{(d.month - 1) // 3 + 1}"


def price_by_quarter(prices):
    px = pd.DataFrame(prices)
    if px.empty:
        return {}
    px["date"] = pd.to_datetime(px["date"], errors="coerce")
    px = px.dropna(subset=["date"]).sort_values("date")
    px["label"] = px.date.dt.year.astype(str) + "/" + px.date.dt.quarter.astype(str)
    result = {}
    for label, g in px.groupby("label"):
        result[label] = {"close": float(g.iloc[-1].close), "open": float(g.iloc[0].open), "avg": float(g.close.mean())}
    return result


def build(stock_id, name, fin_records, bal_records, prices):
    fin_by_date = index_by_date(fin_records)
    bal_by_date = index_by_date(bal_records)
    dates = sorted(set(fin_by_date) & set(bal_by_date))
    prices_by_quarter = price_by_quarter(prices)

    rows = []
    timestamp = datetime.now().isoformat(timespec="seconds")
    previous_close = np.nan
    eps_by_label = {}
    for d in dates:
        fin, bal = fin_by_date[d], bal_by_date[d]
        label = to_quarter_label(d)
        revenue, gross, op_income, pretax, net_income, eps = (
            fin.get("Revenue"), fin.get("GrossProfit"), fin.get("OperatingIncome"),
            fin.get("PreTaxIncome"), fin.get("IncomeAfterTaxes"), fin.get("EPS"))
        non_operating = pretax - op_income if pretax is not None and op_income is not None else np.nan
        equity = bal.get("EquityAttributableToOwnersOfParent") or bal.get("Equity")
        assets = bal.get("TotalAssets")
        capital = bal.get("OrdinaryShare")
        shares = capital / 10 if capital else None  # NT$10 par value
        price = prices_by_quarter.get(label, {})
        close = price.get("close", np.nan)
        change = close - previous_close if pd.notna(close) and pd.notna(previous_close) else np.nan
        year, q = label.split("/")
        prior_year_label = f"{int(year) - 1}/{q}"
        prior_eps = eps_by_label.get(prior_year_label)
        row = {
            "stock_code": str(stock_id).zfill(4), "company_name": name, "季度": label,
            "股本_億": round(capital / 1e8, 2) if capital else np.nan,
            "財報_評分": np.nan,
            "季度股價_元_收盤": close, "季度股價_元_平均": price.get("avg", np.nan),
            "季度股價_元_漲跌": change,
            "季度股價_元_漲跌_pct": round(change / previous_close * 100, 2) if pd.notna(change) and previous_close else np.nan,
            "獲利金額_億_營業_收入": round(revenue / 1e8, 2) if revenue is not None else np.nan,
            "獲利金額_億_營業_毛利": round(gross / 1e8, 2) if gross is not None else np.nan,
            "獲利金額_億_營業_利益": round(op_income / 1e8, 2) if op_income is not None else np.nan,
            "獲利金額_億_業外_損益": round(non_operating / 1e8, 2) if pd.notna(non_operating) else np.nan,
            "獲利金額_億_稅後_淨利": round(net_income / 1e8, 2) if net_income is not None else np.nan,
            "獲利率_pct_營業_毛利": round(gross / revenue * 100, 2) if gross is not None and revenue else np.nan,
            "獲利率_pct_營業_利益": round(op_income / revenue * 100, 2) if op_income is not None and revenue else np.nan,
            "獲利率_pct_業外_損益": round(non_operating / revenue * 100, 2) if pd.notna(non_operating) and revenue else np.nan,
            "獲利率_pct_稅後_淨利": round(net_income / revenue * 100, 2) if net_income is not None and revenue else np.nan,
            "單季_ROE_pct": round(net_income / equity * 100, 2) if net_income is not None and equity else np.nan,
            "年化_ROE_pct": round(net_income * 4 / equity * 100, 2) if net_income is not None and equity else np.nan,
            "單季_ROA_pct": round(net_income / assets * 100, 2) if net_income is not None and assets else np.nan,
            "年化_ROA_pct": round(net_income * 4 / assets * 100, 2) if net_income is not None and assets else np.nan,
            "eps_元_稅後_eps": round(eps, 2) if eps is not None else np.nan,
            "eps_元_年增_元": round(eps - prior_eps, 2) if eps is not None and prior_eps is not None else np.nan,
            "bps_元": round(equity / shares, 2) if equity and shares else np.nan,
            "成交價_成交張數": np.nan, "昨收_成交金額": np.nan, "漲跌價_成交筆數": np.nan,
            "漲跌幅_成交均張": np.nan, "振幅_成交均價": np.nan,
            "開盤_淨值\u00a0_折溢價_pct": np.nan, "最高_淨值\u00a0_折溢價_pct": np.nan,
            "最低_淨值\u00a0_折溢價_pct": np.nan,
            "file_type": "StockBzPerformance1",
            "source_file": f"FinMind_API_TaiwanStockFinancialStatements_{str(stock_id).zfill(4)}",
            "download_success": True, "download_timestamp": timestamp,
            "process_timestamp": timestamp, "stage1_process_timestamp": timestamp,
        }
        rows.append(row)
        if pd.notna(close):
            previous_close = close
        if eps is not None:
            eps_by_label[label] = eps
    return pd.DataFrame(rows, columns=COLUMNS)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--stock-id', default='2330')
    p.add_argument('--company-name', default='台積電')
    p.add_argument('--start-date', default='2018-01-01')
    p.add_argument('--end-date', default=(datetime.now() + timedelta(hours=8)).strftime('%Y-%m-%d'))
    p.add_argument('--output', default='financial/type7/raw_performance1_2330.csv')
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
    print(f'Wrote {len(out)} quarterly performance rows to {a.output}')


if __name__ == '__main__':
    main()
