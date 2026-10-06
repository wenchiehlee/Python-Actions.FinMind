import os
import sys
import argparse
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
from dotenv import load_dotenv
from token_env import TokenRotator

load_dotenv()

# Add parent directory to sys.path to enable self_update imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import self_update
except ImportError:
    pass

# Reconfigure stdout to support UTF-8 on Windows
sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# FinMind API URL
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

def parse_args():
    parser = argparse.ArgumentParser(description="Fetch Taiwan stock margin and price data from FinMind API and export/merge to CSV.")
    parser.add_argument("--input-csv", type=str, default=None,
                        help="Path to the existing raw_margin_daily.csv for incremental updates.")
    parser.add_argument("--stock-list", type=str, default=None,
                        help="Path to CSV containing list of stocks (columns: 代號, 名稱).")
    parser.add_argument("--stocks", type=str, default=None,
                        help="Comma-separated stock codes to fetch (overrides stock-list). E.g., '0000,2330'")
    parser.add_argument("--start-date", type=str, default=None,
                        help="Start date (YYYY-MM-DD). If omitted and input-csv exists, performs incremental update.")
    parser.add_argument("--end-date", type=str, default=None,
                        help="End date (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--output-csv", type=str, default=None,
                        help="Output CSV path. Defaults to overwriting the input-csv.")
    parser.add_argument("--token", type=str, default=None,
                        help="FinMind API Token. Can also be set via FINMIND_TOKEN env var.")
    parser.add_argument("--debug-limit", type=int, default=None,
                        help="Limit number of stocks fetched (for debugging).")
    return parser.parse_args()

def fetch_data(dataset, data_id=None, start_date=None, end_date=None, token=None):
    params = {
        "dataset": dataset,
        "start_date": start_date,
        "end_date": end_date
    }
    if data_id:
        params["data_id"] = data_id
    request_token = token.next() if isinstance(token, TokenRotator) else token
    if request_token:
        params["token"] = request_token
        
    try:
        r = requests.get(FINMIND_URL, params=params)
        res = r.json()
        if r.ok and res.get("status") == 200:
            return pd.DataFrame(res.get("data", []))
        msg = str(res.get("msg", "")).strip().lower()
        quota_exhausted = res.get("status") == 402 or "reach the upper limit" in msg
        logger.warning("FinMind API rejected dataset %s for %s: status=%s message=%s", dataset, data_id, res.get("status"), res.get("msg", ""))
        if isinstance(token, TokenRotator) and ("token is illegal" in msg or quota_exhausted):
            token.retire(request_token)
            if token.count:
                return fetch_data(dataset, data_id, start_date, end_date, token)
            logger.error("FinMind rejected all configured tokens")
            return pd.DataFrame()
        logger.warning(f"FinMind API return status {res.get('status')} for dataset {dataset}: {res.get('msg')}")
        return pd.DataFrame()
    except Exception as e:
        # Never log requests' URL, because it may contain the token query parameter.
        logger.error(f"Error fetching dataset {dataset} for {data_id}: {type(e).__name__}: request failed")
        return pd.DataFrame()

def to_stage1_date(date_str):
    """Convert YYYY-MM-DD to 'YY/MM/DD"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"'{dt.strftime('%y/%m/%d')}"
    except Exception:
        return date_str

def parse_stage1_date(stage1_date_str):
    """Convert 'YY/MM/DD to YYYY-MM-DD"""
    try:
        clean = stage1_date_str.lstrip("'")
        dt = datetime.strptime(clean, "%y/%m/%d")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None

def process_index_data(price_df, margin_df, company_name="台灣加權指數"):
    """
    Process Taiwan Weighted Index (0000) data.
    - price_df columns from TAIEX: date, stock_id, Trading_Volume, Trading_money, open, max, min, close, spread, Trading_turnover
    - margin_df columns from TaiwanStockTotalMarginPurchaseShortSale
    """
    if price_df.empty or margin_df.empty:
        return pd.DataFrame()
        
    # Pivot margin_df because it contains multiple names: MarginPurchase, ShortSale, MarginPurchaseMoney
    mp_df = margin_df[margin_df["name"] == "MarginPurchase"].copy()
    ss_df = margin_df[margin_df["name"] == "ShortSale"].copy()
    mpm_df = margin_df[margin_df["name"] == "MarginPurchaseMoney"].copy()
    
    # Rename columns for merging
    mp_df = mp_df.rename(columns={"TodayBalance": "mp_bal_lots", "YesBalance": "mp_yes_bal_lots", "buy": "mp_buy_lots", "sell": "mp_sell_lots", "Return": "mp_ret_lots"})
    ss_df = ss_df.rename(columns={"TodayBalance": "ss_bal_lots", "YesBalance": "ss_yes_bal_lots", "buy": "ss_buy_lots", "sell": "ss_sell_lots", "Return": "ss_ret_lots"})
    mpm_df = mpm_df.rename(columns={"TodayBalance": "mp_bal_money", "YesBalance": "mp_yes_bal_money", "buy": "mp_buy_money", "sell": "mp_sell_money", "Return": "mp_ret_money"})
    
    # Merge price and margin parts
    m_df = price_df.merge(mp_df[["date", "mp_bal_lots", "mp_yes_bal_lots", "mp_buy_lots", "mp_sell_lots", "mp_ret_lots"]], on="date", how="left")
    m_df = m_df.merge(ss_df[["date", "ss_bal_lots", "ss_yes_bal_lots", "ss_buy_lots", "ss_sell_lots", "ss_ret_lots"]], on="date", how="left")
    m_df = m_df.merge(mpm_df[["date", "mp_bal_money", "mp_yes_bal_money", "mp_buy_money", "mp_sell_money", "mp_ret_money"]], on="date", how="left")
    
    # Calculate fields for 0000
    rows = []
    now_cst = datetime.now() + timedelta(hours=8)
    timestamp_str = now_cst.strftime("%Y-%m-%d %H:%M:%S CST")
    
    for _, row in m_df.iterrows():
        date_str = row["date"]
        close_val = row["close"]
        spread_val = row["spread"]
        
        # 前一日收盤
        prev_close = close_val - spread_val
        change_pct = (spread_val / prev_close * 100) if prev_close != 0 else np.nan
        
        # 成交金額 (億元)
        vol_money_100m = row["Trading_money"] / 1e8 if pd.notna(row["Trading_money"]) else np.nan
        
        # 融資 (Money, 單位: 億元)
        mp_buy_val = row["mp_buy_money"] / 1e8 if pd.notna(row["mp_buy_money"]) else np.nan
        mp_sell_val = row["mp_sell_money"] / 1e8 if pd.notna(row["mp_sell_money"]) else np.nan
        mp_ret_val = row["mp_ret_money"] / 1e8 if pd.notna(row["mp_ret_money"]) else np.nan
        mp_diff_val = mp_buy_val - mp_sell_val - mp_ret_val if pd.notna(mp_buy_val) else np.nan
        
        mp_yes_money = row["mp_yes_bal_money"] / 1e8 if pd.notna(row["mp_yes_bal_money"]) else np.nan
        mp_pct_val = (mp_diff_val / mp_yes_money * 100) if mp_yes_money and mp_yes_money > 0 else np.nan
        mp_bal_money_val = row["mp_bal_money"] / 1e8 if pd.notna(row["mp_bal_money"]) else np.nan
        
        # 融券 (Lots, 單位: 張)
        ss_buy_val = row["ss_buy_lots"] if pd.notna(row["ss_buy_lots"]) else np.nan
        ss_sell_val = row["ss_sell_lots"] if pd.notna(row["ss_sell_lots"]) else np.nan
        ss_ret_val = row["ss_ret_lots"] if pd.notna(row["ss_ret_lots"]) else np.nan
        ss_diff_val = ss_sell_val - ss_buy_val - ss_ret_val if pd.notna(ss_sell_val) else np.nan
        
        ss_yes_lots = row["ss_yes_bal_lots"] if pd.notna(row["ss_yes_bal_lots"]) else np.nan
        ss_pct_val = (ss_diff_val / ss_yes_lots * 100) if ss_yes_lots and ss_yes_lots > 0 else np.nan
        ss_bal_money_val = row["ss_bal_lots"] if pd.notna(row["ss_bal_lots"]) else np.nan  # 這是融券餘額張數，對應 0000 的錯位欄位
        
        # 券資比 = 融券餘額張數 / 融資餘額張數 * 100
        mp_bal_lots = row["mp_bal_lots"]
        ss_bal_lots = row["ss_bal_lots"]
        ratio_pct = (ss_bal_lots / mp_bal_lots * 100) if mp_bal_lots and mp_bal_lots > 0 else np.nan
        
        res_row = {
            "stock_code": "0000",
            "company_name": company_name,
            "期別": to_stage1_date(date_str),
            "收盤_價格_元": close_val,
            "漲跌_價格_元": spread_val,
            "漲跌_pct": round(change_pct, 2) if pd.notna(change_pct) else np.nan,
            "成交_張數": round(vol_money_100m, 2) if pd.notna(vol_money_100m) else np.nan,
            "融資_買進_張": round(mp_buy_val, 2) if pd.notna(mp_buy_val) else np.nan,
            "融資_賣出_張": round(mp_sell_val, 2) if pd.notna(mp_sell_val) else np.nan,
            "融資_現償_張": round(mp_ret_val, 2) if pd.notna(mp_ret_val) else np.nan,
            "融資_增減_張": round(mp_diff_val, 2) if pd.notna(mp_diff_val) else np.nan,
            "融資_餘額_張": round(mp_pct_val, 2) if pd.notna(mp_pct_val) else np.nan,
            "融資_餘額_億": round(mp_bal_money_val, 2) if pd.notna(mp_bal_money_val) else np.nan,
            "融券_買進_張": ss_buy_val,
            "融券_賣出_張": ss_sell_val,
            "融券_現償_張": ss_ret_val,
            "融券_增減_張": ss_diff_val,
            "融券_餘額_張": round(ss_pct_val, 2) if pd.notna(ss_pct_val) else np.nan,
            "融券_餘額_億": ss_bal_money_val,
            "券資比_pct": round(ratio_pct, 2) if pd.notna(ratio_pct) else np.nan,
            "現股當沖_pct": np.nan,
            "融資_使用率_pct": np.nan,
            "融券_使用率_pct": np.nan,
            "資券互抵_張": np.nan,
            "資券當沖_pct": np.nan,
            "file_type": "ShowMarginChart",
            "source_file": "FinMind_API_TaiwanStockTotalMarginPurchaseShortSale_0000",
            "download_success": True,
            "download_timestamp": timestamp_str,
            "process_timestamp": timestamp_str,
            "stage1_process_timestamp": timestamp_str
        }
        rows.append(res_row)
        
    return pd.DataFrame(rows)

def process_stock_data(stock_code, price_df, margin_df, company_name):
    """
    Process individual stock data.
    - price_df columns: date, stock_id, Trading_Volume, Trading_money, open, max, min, close, spread, Trading_turnover
    - margin_df columns: date, stock_id, MarginPurchaseBuy, MarginPurchaseCashRepayment, MarginPurchaseLimit, MarginPurchaseTodayBalance, MarginPurchaseYesterdayBalance, ShortSaleCashRepayment, ShortSaleLimit, ShortSaleSell, ShortSaleTodayBalance, ShortSaleYesterdayBalance, ShortSaleBuy, OffsetLoanAndShort
    """
    if price_df.empty:
        return pd.DataFrame()

    # Some stocks (e.g. not yet eligible for margin trading) have price data
    # but no margin data at all; GoodInfo still reports them with blank
    # margin columns rather than omitting them, so match that here.
    m_df = price_df.merge(margin_df, on="date", how="left") if not margin_df.empty else price_df.copy()
    
    rows = []
    now_cst = datetime.now() + timedelta(hours=8)
    timestamp_str = now_cst.strftime("%Y-%m-%d %H:%M:%S CST")
    
    for _, row in m_df.iterrows():
        date_str = row["date"]
        close_val = row["close"]
        spread_val = row["spread"]
        
        # 前一日收盤
        prev_close = close_val - spread_val
        change_pct = (spread_val / prev_close * 100) if prev_close != 0 else np.nan
        
        # 成交量 (張)
        vol_lots = row["Trading_Volume"] / 1000 if pd.notna(row["Trading_Volume"]) else np.nan
        
        # 融資
        mp_buy = row.get("MarginPurchaseBuy", np.nan)
        mp_sell = row.get("MarginPurchaseSell", np.nan)
        mp_ret = row.get("MarginPurchaseCashRepayment", np.nan)
        mp_diff = mp_buy - mp_sell - mp_ret if pd.notna(mp_buy) else np.nan
        mp_bal = row.get("MarginPurchaseTodayBalance", np.nan)
        
        # 融資使用率 % = 融資餘額 / 融資限額 * 100
        mp_limit = row.get("MarginPurchaseLimit", np.nan)
        mp_usage = (mp_bal / mp_limit * 100) if mp_limit and mp_limit > 0 else np.nan
        
        # 融券
        ss_buy = row.get("ShortSaleBuy", np.nan)
        ss_sell = row.get("ShortSaleSell", np.nan)
        ss_ret = row.get("ShortSaleCashRepayment", np.nan)
        ss_diff = ss_sell - ss_buy - ss_ret if pd.notna(ss_sell) else np.nan
        ss_bal = row.get("ShortSaleTodayBalance", np.nan)
        
        # 融券使用率 %
        ss_limit = row.get("ShortSaleLimit", np.nan)
        ss_usage = (ss_bal / ss_limit * 100) if ss_limit and ss_limit > 0 else np.nan
        
        # 券資比
        ratio_pct = (ss_bal / mp_bal * 100) if mp_bal and mp_bal > 0 else np.nan
        
        # 資券互抵 (OffsetLoanAndShort)
        offset_lots = row.get("OffsetLoanAndShort", np.nan)
        offset_pct = (offset_lots / vol_lots * 100) if vol_lots and vol_lots > 0 and pd.notna(offset_lots) else np.nan
        
        res_row = {
            "stock_code": stock_code,
            "company_name": company_name,
            "期別": to_stage1_date(date_str),
            "收盤_價格_元": close_val,
            "漲跌_價格_元": spread_val,
            "漲跌_pct": round(change_pct, 2) if pd.notna(change_pct) else np.nan,
            # GoodInfo Type 13 stores trading volume as whole lots.
            "成交_張數": int(round(vol_lots)) if pd.notna(vol_lots) else np.nan,
            "融資_買進_張": mp_buy,
            "融資_賣出_張": mp_sell,
            "融資_現償_張": mp_ret,
            "融資_增減_張": mp_diff,
            "融資_餘額_張": mp_bal,
            "融資_餘額_億": np.nan,
            "融券_買進_張": ss_buy,
            "融券_賣出_張": ss_sell,
            "融券_現償_張": ss_ret,
            "融券_增減_張": ss_diff,
            "融券_餘額_張": ss_bal,
            "融券_餘額_億": np.nan,
            "券資比_pct": round(ratio_pct, 2) if pd.notna(ratio_pct) else np.nan,
            "現股當沖_pct": np.nan,
            "融資_使用率_pct": round(mp_usage, 2) if pd.notna(mp_usage) else np.nan,
            "融券_使用率_pct": round(ss_usage, 2) if pd.notna(ss_usage) else np.nan,
            "資券互抵_張": offset_lots,
            "資券當沖_pct": round(offset_pct, 2) if pd.notna(offset_pct) else np.nan,
            "file_type": "ShowMarginChart",
            "source_file": f"FinMind_API_TaiwanStockMarginPurchaseShortSale_{stock_code}",
            "download_success": True,
            "download_timestamp": timestamp_str,
            "process_timestamp": timestamp_str,
            "stage1_process_timestamp": timestamp_str
        }
        rows.append(res_row)
        
    return pd.DataFrame(rows)

def load_existing_csv(csv_path):
    if not csv_path or not os.path.exists(csv_path):
        logger.info(f"Existing CSV not found: {csv_path}")
        return pd.DataFrame()
        
    try:
        df = pd.read_csv(csv_path, dtype={'stock_code': str})
        logger.info(f"Loaded {len(df)} existing rows from {csv_path}")
        return df
    except Exception as e:
        logger.error(f"Error loading {csv_path}: {e}")
        return pd.DataFrame()

def determine_incremental_targets(existing_df, stock_list_df, default_start_date):
    """
    Determine which stocks to fetch and from what start date.
    Returns: dict of {stock_code: (start_date, company_name)}
    """
    targets = {}
    today_str = (datetime.now() + timedelta(hours=8)).strftime("%Y-%m-%d")
    
    # Identify unique stocks in the list
    stocks_to_fetch = {}
    for _, row in stock_list_df.iterrows():
        code = str(row["代號"]).strip()
        name = str(row["名稱"]).strip()
        stocks_to_fetch[code] = name
        
    # Add index
    if "0000" not in stocks_to_fetch:
        stocks_to_fetch["0000"] = "台灣加權指數"
        
    # If no existing data, fetch all from default_start_date
    if existing_df.empty:
        for code, name in stocks_to_fetch.items():
            targets[code] = (default_start_date, name)
        return targets
        
    # Parse existing max dates
    existing_df["temp_date"] = existing_df["期別"].apply(parse_stage1_date)
    max_dates = existing_df.groupby("stock_code")["temp_date"].max().to_dict()
    existing_df.drop(columns=["temp_date"], inplace=True)
    
    for code, name in stocks_to_fetch.items():
        if code in max_dates and pd.notna(max_dates[code]):
            # Get max date
            max_dt = datetime.strptime(max_dates[code], "%Y-%m-%d")
            # We want to fetch from max_dt + 1 day
            start_dt = max_dt + timedelta(days=1)
            start_str = start_dt.strftime("%Y-%m-%d")
            
            if start_str > today_str:
                logger.info(f"Stock {code} ({name}) is already up to date (max date: {max_dates[code]}). Skipping.")
                continue
                
            targets[code] = (start_str, name)
            logger.info(f"Stock {code} ({name}) incremental fetch starting from {start_str} (previous max: {max_dates[code]})")
        else:
            targets[code] = (default_start_date, name)
            logger.info(f"Stock {code} ({name}) not found in existing data, fetch starting from {default_start_date}")
            
    return targets

def main():
    args = parse_args()
    token = TokenRotator(args.token)
    logger.info("Using %d FinMind token(s) with round-robin rotation", token.count)
    
    # 1. Load Stock List
    stock_list_df = pd.DataFrame()
    if args.stocks:
        stocks = [s.strip() for s in args.stocks.split(",") if s.strip()]
        logger.info(f"Fetching manually specified stocks: {stocks}")
        stock_list_df = pd.DataFrame({"代號": stocks, "名稱": ["" for _ in stocks]})
    elif args.stock_list and os.path.exists(args.stock_list):
        try:
            stock_list_df = pd.read_csv(args.stock_list, dtype={"代號": str})
            logger.info(f"Loaded {len(stock_list_df)} stocks from {args.stock_list}")
        except Exception as e:
            logger.error(f"Error loading stock list {args.stock_list}: {e}")
            sys.exit(1)
    else:
        # If no stocks or list is provided, but input-csv is provided, get stocks from input-csv
        if args.input_csv and os.path.exists(args.input_csv):
            try:
                existing_df = pd.read_csv(args.input_csv, dtype={'stock_code': str})
                unique_stocks = existing_df["stock_code"].unique()
                unique_names = existing_df.groupby("stock_code")["company_name"].first().to_dict()
                logger.info(f"Derived {len(unique_stocks)} stocks from existing CSV {args.input_csv}")
                stock_list_df = pd.DataFrame({
                    "代號": unique_stocks,
                    "名稱": [unique_names.get(s, "") for s in unique_stocks]
                })
            except Exception as e:
                logger.error(f"Failed to derive stocks from existing CSV: {e}")
                sys.exit(1)
        else:
            logger.error("No stocks specified, no stock list file, and no existing CSV available to derive targets.")
            sys.exit(1)
        
    # 2. Get Stock Info (Names) from API if missing
    has_missing_names = stock_list_df["名稱"].eq("").any() if "名稱" in stock_list_df.columns else True
    api_names = {}
    if has_missing_names:
        logger.info("Fetching stock info from FinMind to populate company names...")
        info_df = fetch_data("TaiwanStockInfo", token=token)
        if not info_df.empty:
            api_names = info_df.set_index("stock_id")["stock_name"].to_dict()
            
    # Update names
    updated_rows = []
    for _, row in stock_list_df.iterrows():
        code = str(row["代號"]).strip()
        name = str(row.get("名稱", "")).strip()
        if code == "0000":
            name = "台灣加權指數"
        elif not name or name == "nan":
            name = api_names.get(code, f"Stock_{code}")
        updated_rows.append({"代號": code, "名稱": name})
    stock_list_df = pd.DataFrame(updated_rows)
    
    # Apply debug limit
    if args.debug_limit:
        logger.info(f"DEBUG LIMIT: Truncating stock list to {args.debug_limit} stocks.")
        has_index = stock_list_df["代號"].eq("0000").any()
        index_row = stock_list_df[stock_list_df["代號"] == "0000"]
        stock_list_df = stock_list_df[stock_list_df["代號"] != "0000"].head(args.debug_limit)
        if has_index and not index_row.empty:
            stock_list_df = pd.concat([index_row, stock_list_df])
            
    # 3. Load Existing CSV
    existing_df = load_existing_csv(args.input_csv)
    
    # Determine default start date
    default_start_date = args.start_date
    if not default_start_date:
        default_start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
    end_date = args.end_date or (datetime.now() + timedelta(hours=8)).strftime("%Y-%m-%d")
    
    # Determine incremental targets
    targets = {}
    if args.start_date:
        for _, row in stock_list_df.iterrows():
            code = str(row["代號"]).strip()
            name = str(row["名稱"]).strip()
            targets[code] = (args.start_date, name)
        if "0000" not in targets:
            targets["0000"] = (args.start_date, "台灣加權指數")
    else:
        targets = determine_incremental_targets(existing_df, stock_list_df, default_start_date)
        
    # 4. Fetch and Process
    all_new_rows = []
    
    for code, (start_str, name) in targets.items():
        logger.info(f"Fetching data for {code} ({name}) from {start_str} to {end_date}...")
        
        if code == "0000":
            # Index
            price_df = fetch_data("TaiwanStockPrice", data_id="TAIEX", start_date=start_str, end_date=end_date, token=token)
            margin_df = fetch_data("TaiwanStockTotalMarginPurchaseShortSale", start_date=start_str, end_date=end_date, token=token)
            
            if not price_df.empty and not margin_df.empty:
                df_idx = process_index_data(price_df, margin_df, company_name=name)
                if not df_idx.empty:
                    logger.info(f"Processed {len(df_idx)} rows for Index (0000)")
                    all_new_rows.append(df_idx)
            else:
                logger.warning(f"Index data missing or incomplete: price empty? {price_df.empty}, margin empty? {margin_df.empty}")
        else:
            # Individual Stock
            price_df = fetch_data("TaiwanStockPrice", data_id=code, start_date=start_str, end_date=end_date, token=token)
            margin_df = fetch_data("TaiwanStockMarginPurchaseShortSale", data_id=code, start_date=start_str, end_date=end_date, token=token)
            
            if not price_df.empty:
                df_stk = process_stock_data(code, price_df, margin_df, company_name=name)
                if not df_stk.empty:
                    logger.info(f"Processed {len(df_stk)} rows for Stock {code}")
                    all_new_rows.append(df_stk)
            else:
                logger.warning(f"Stock {code} data missing or incomplete: price empty? {price_df.empty}, margin empty? {margin_df.empty}")
                
    # 5. Merge and Save
    if all_new_rows:
        new_df = pd.concat(all_new_rows, ignore_index=True)
        logger.info(f"Fetched {len(new_df)} new rows in total")
        
        # Merge with existing
        if not existing_df.empty:
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            combined_df = combined_df.drop_duplicates(subset=["stock_code", "期別"], keep="last")
        else:
            combined_df = new_df
            
        # Re-sort to match original CSV format:
        def get_dt_temp(s):
            try:
                return datetime.strptime(s.lstrip("'"), "%y/%m/%d")
            except Exception:
                return datetime.min
                
        combined_df["temp_sort_date"] = combined_df["期別"].apply(get_dt_temp)
        combined_df["stock_code"] = combined_df["stock_code"].astype(str)
        combined_df = combined_df.sort_values(by=["stock_code", "temp_sort_date"], ascending=[True, False])
        combined_df.drop(columns=["temp_sort_date"], inplace=True)
        
        # Final columns check
        expected_cols = [
            'stock_code', 'company_name', '期別', '收盤_價格_元', '漲跌_價格_元', '漲跌_pct', '成交_張數',
            '融資_買進_張', '融資_賣出_張', '融資_現償_張', '融資_增減_張', '融資_餘額_張', '融資_餘額_億',
            '融券_買進_張', '融券_賣出_張', '融券_現償_張', '融券_增減_張', '融券_餘額_張', '融券_餘額_億',
            '券資比_pct', '現股當沖_pct', '融資_使用率_pct', '融券_使用率_pct', '資券互抵_張', '資券當沖_pct',
            'file_type', 'source_file', 'download_success', 'download_timestamp', 'process_timestamp',
            'stage1_process_timestamp'
        ]
        
        for col in expected_cols:
            if col not in combined_df.columns:
                combined_df[col] = np.nan
        combined_df = combined_df[expected_cols]
        
        # Save output
        output_path = args.output_csv or args.input_csv
        if not output_path:
            logger.error("No output path specified (neither output-csv nor input-csv is available). Output not saved.")
            sys.exit(1)
            
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
        
        try:
            combined_df.to_csv(output_path, index=False, encoding="utf-8-sig")
            logger.info(f"Successfully saved {len(combined_df)} rows to {output_path}")
        except Exception as e:
            logger.error(f"Error saving output to {output_path}: {e}")
            sys.exit(1)
    else:
        logger.info("No new data fetched or processed. No changes made.")

if __name__ == "__main__":
    main()
