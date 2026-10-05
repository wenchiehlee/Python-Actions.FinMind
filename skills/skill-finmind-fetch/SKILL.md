---
name: skill-finmind-fetch
description: 從 FinMind API 獲取台灣股市個股與大盤指數的融資融券以及收盤價資料，並格式化/合併寫入與 GoodInfo 結構相同的 stage1 raw CSV 中。
---

# FinMind Fetch Skill (FinMind 資料抓取與合併技能)

此技能利用 FinMind API，獲取台灣股市個股與大盤的每日收盤價與融資融券數據。它會將獲取的資料整理為與 `raw_margin_daily.csv` (Type 13: ShowMarginChart) 相同的 31 個欄位格式；另可由 Type 13 每日 CSV 聚合 `raw_margin_weekly.csv` (Type 14: ShowMarginChartWeek)，並自動與現有資料進行增量合併（Incremental Update）及去重。欄位排序與定義完全遵循 [raw_column_definition_Analyzer.md](file:///C:/Users/WJLEE/SynologyDrive/NAS/github.com/Python-Actions.GoodInfo.Analyzer/definitions/raw_column_definition_Analyzer.md) 規格。

## 適用場景

- 需要透過穩定的 API 管道（FinMind）獲取每日融資融券數據，以避開 GoodInfo 網頁強大的反爬蟲機制。
- 需要更新 `Python-Actions.GoodInfo.Analyzer` 專案中的 `data\stage1_raw\raw_margin_daily.csv`，使後續的籌碼分析管道（如 `margin_daily_report.py`）能使用最新資料。

## 依賴需求

- `pandas`
- `requests`
- `numpy`
- 可設定 `FINMIND_TOKEN`、`FINMIND_API_TOKEN`、`FINMIND_TOKEN1`..`FINMIND_TOKEN7`、`FINDMIND_GMAIL_TOKEN`、`FINDMIND_GMAIL_TOKEN1`..`FINDMIND_GMAIL_TOKEN7`；所有非空 token 會依當前剩餘配額多寡排序並按 request round-robin rotation 自動輪替使用。

## 核心腳本與指令

技能的執行腳本位於技能目錄下的 `scripts/fetch_to_csv.py`。

### 1. 增量更新（推薦）

讀取現有 CSV，分析每檔股票（與大盤）在 CSV 中的最新日期，並只向 API 請求最新日期之後的資料，追加並合併寫回：

```bash
python scripts/fetch_to_csv.py --input-csv "/path/to/raw_margin_daily.csv" --stock-list "/path/to/StockID_TWSE_TPEX.csv"
```

### 2. 獲取特定範圍與股票（全量或指定更新）

```bash
python scripts/fetch_to_csv.py --stocks "0000,2330,0050" --start-date "2026-07-01" --end-date "2026-07-10" --output-csv "/path/to/output.csv"
```

## 參數說明

- `--input-csv`：現有 `raw_margin_daily.csv` 檔案的路徑。若提供此參數，程式會自動以此進行增量更新。
- `--stock-list`：包含股票代號與名稱的 CSV 路徑（格式：`代號,名稱`）。若不指定 `--stocks`，則以此列表中的股票為更新目標。
- `--stocks`：以逗號分隔的股票代碼字串（例如 `0000,2330`）。會覆蓋 `--stock-list`。大盤代碼為 `0000`。
- `--start-date`：手動指定的起始日期 (YYYY-MM-DD)。
- `--end-date`：手動指定的結束日期 (YYYY-MM-DD)，預設為今天。
- `--output-csv`：輸出的 CSV 儲存路徑，若未指定則預設覆寫 `--input-csv` 的檔案。
- `--token`：手動指定的 FinMind API Token。
- `--debug-limit`：除大盤外，限制只下載前 N 檔個股，供測試使用。


## Type 1：股利政策 CSV

```bash
python skills/skill-finmind-fetch/scripts/fetch_type1.py \
  --stock-id 2330 --company-name 台積電 \
  --start-date 2018-01-01 --end-date 2026-12-31 \
  --output financial/type1/raw_dividends_2330.csv
```

Type 1 使用 FinMind `TaiwanStockDividend`；GoodInfo 特有的填息天數與多種歷史殖利率欄位，若來源沒有提供則保留空值。

## Type 5：每月營收 CSV

```bash
python skills/skill-finmind-fetch/scripts/fetch_type5.py \
  --stock-id 2330 --company-name 台積電 \
  --start-date 2021-01-01 --end-date 2026-12-31 \
  --output financial/type5/raw_revenue_2330.csv
```

Type 5 使用 FinMind `TaiwanStockMonthRevenue` 搭配 `TaiwanStockPrice`，輸出月營收、月增/年增、年度累計與月內價格欄位。

## Type 8、12、17、18：K 線 / PER 資金流向 CSV

四個類型共用 `fetch_k_chart_flow.py`，差異只在頻率與目標 PER 倍數：

```bash
python skills/skill-finmind-fetch/scripts/fetch_k_chart_flow.py --type 17 \
  --stock-id 2330 --company-name 台積電 \
  --start-date 2021-01-01 --end-date 2026-12-31 \
  --output financial/type17/raw_weekly_k_chart_flow_2330.csv
```

`--type` 可使用 `8`（週）、`12`（月）、`17`（週）、`18`（日）。資料使用 FinMind `TaiwanStockPrice`、`TaiwanStockPER` 與可用的季度 EPS；來源缺少的欄位保留空值。

## Type 11：每週交易資料（含法人）

```bash
python skills/skill-finmind-fetch/scripts/fetch_type11.py \
  --stock-id 2330 --company-name 台積電 \
  --start-date 2021-01-01 --end-date 2026-12-31 \
  --output financial/type11/raw_weekly_trading_data_2330.csv
```

Type 11 使用 FinMind 每日價格、三大法人寬表與融資融券資料聚合；來源沒有的持股比例欄位保留空值。

## Type 19：除權息日程

```bash
python skills/skill-finmind-fetch/scripts/fetch_type19.py \
  --stock-id 2330 --company-name 台積電 \
  --start-date 2018-01-01 --end-date 2026-12-31 \
  --output financial/type19/raw_dividend_schedule_2330.csv
```

Type 19 使用 FinMind `TaiwanStockDividend`；填息/填權完成日與參考價若來源沒有提供則保留空值。

## Type 14：每週融資融券 CSV

Type 14 優先重用 Type 13 每日 CSV 聚合，不需重新下載同一批每日資料：

```bash
python skills/skill-finmind-fetch/scripts/fetch_type14.py \
  --stock-id 2330 --company-name 台積電 \
  --daily-csv /path/to/raw_margin_daily.csv \
  --output financial/type14/raw_margin_weekly_2330.csv
```

若沒有 Type 13 CSV，省略 `--daily-csv`，腳本會使用 FinMind 每日價格與融資融券 API 建立資料：

```bash
python skills/skill-finmind-fetch/scripts/fetch_type14.py \
  --stock-id 2330 --company-name 台積電 \
  --start-date 2021-01-01 --end-date 2026-12-31 \
  --output financial/type14/raw_margin_weekly_2330.csv
```

用 `compare_type14.py` 可與 Analyzer 的 `raw_margin_weekly.csv` 做欄位及數值比對。

## Type 15：每月融資融券 CSV

Type 15 優先重用 Type 13 每日 CSV 聚合，並將張數轉為千張：

```bash
python skills/skill-finmind-fetch/scripts/fetch_type15.py \
  --stock-id 2330 --company-name 台積電 \
  --daily-csv /path/to/raw_margin_daily.csv \
  --output financial/type15/raw_margin_monthly_2330.csv
```

若沒有 Type 13 CSV，省略 `--daily-csv`，腳本會使用 FinMind 每日 API：

```bash
python skills/skill-finmind-fetch/scripts/fetch_type15.py \
  --stock-id 2330 --company-name 台積電 \
  --start-date 2021-01-01 --end-date 2026-12-31 \
  --output financial/type15/raw_margin_monthly_2330.csv
```

用 `compare_type15.py` 可與 Analyzer 的 `raw_margin_monthly.csv` 做欄位及數值比對。

## Type 16：季度財務比率 CSV

同一個 skill 也提供季度財務比率 adapter，使用 FinMind 的綜合損益、資產負債表與現金流量表，輸出與 GoodInfo Analyzer 的 `raw_fin_ratio_quarter.csv` 相同的 164 欄 schema：

```bash
python skills/skill-finmind-fetch/scripts/fetch_type16.py \
  --stock-id 2330 --company-name 台積電 \
  --start-date 2020-01-01 --end-date 2026-12-31 \
  --output financial/type16/raw_fin_ratio_quarter_2330.csv
```

用 `compare_type16.py` 可對照 Analyzer 的 GoodInfo CSV。Type 13 與 Type 16 共用同一個 skill，但使用不同 script、dataset 與輸出 schema，不保留第二份實作。

## Type 4、7：年度／季度營運績效 CSV

```bash
python skills/skill-finmind-fetch/scripts/fetch_type4.py \
  --stock-id 2330 --company-name 台積電 \
  --start-date 2018-01-01 --end-date 2026-12-31 \
  --output financial/type4/raw_performance_2330.csv

python skills/skill-finmind-fetch/scripts/fetch_type7.py \
  --stock-id 2330 --company-name 台積電 \
  --start-date 2018-01-01 --end-date 2026-12-31 \
  --output financial/type7/raw_performance1_2330.csv
```

兩者都使用 FinMind `TaiwanStockFinancialStatements`（營收/毛利/營業利益/稅前淨利/稅後淨利/EPS，單季值直接加總成年度或原樣輸出季度）、`TaiwanStockBalanceSheet`（股本/淨值/資產，取當期末餘額）與 `TaiwanStockPrice`。GoodInfo 專有的「財報_評分」沒有 FinMind 對應欄位，留空。

## Type 9：季度股價 CSV

```bash
python skills/skill-finmind-fetch/scripts/fetch_type9.py \
  --stock-id 2330 --company-name 台積電 \
  --start-date 2018-01-01 --end-date 2026-12-31 \
  --output financial/type9/raw_stock_his_quar_2330.csv
```

純粹從 FinMind `TaiwanStockPrice` 依季度聚合開盤/收盤/漲跌，不需要財務報表資料。

## Type 6：股權分散表 CSV

```bash
python skills/skill-finmind-fetch/scripts/fetch_type6.py \
  --stock-id 2330 --company-name 台積電 \
  --start-date 2018-01-01 --end-date 2026-12-31 \
  --output financial/type6/raw_equity_distribution_2330.csv
```

使用 FinMind `TaiwanStockShareholding`（每週資料，取每年最後一筆作為年度快照）。FinMind 只提供僑外資合計持股比例，GoodInfo 的政府機構/金融機構/證券投信/本國法人/本國自然人等細項沒有對應資料來源，留空，不臆測。

## Token 配額池與階層化調度策略 (Quota Pool & Tiered Priority Strategy)

### 1. Token 配額架構與輪替
- 每個 FinMind 帳號提供 **600 requests / hr** 的 API 額度（按整點/滾動小時重置，非每日重置）。
- 支援透過環境變數池（`FINMIND_TOKEN1`..`FINMIND_TOKEN7`、`FINDMIND_GMAIL_TOKEN1`..`FINDMIND_GMAIL_TOKEN7`）進行輪替調度：
  - **7 組 Token 額度池**：`7 × 600 = 4,200 requests / hr`。
  - 當遇到 HTTP 402 或超出額度限制時，自動暫退該 Token 並無縫切換至下一個有效 Token。

### 2. 階層化股票更新需求與配額模型 (Tiered Prioritization)
台股全市場（Universe）共有 1,733+ 檔上市櫃股票。若每次排程對全市場所有個股無差別拉取，單檔完整更新需打約 3~4 次 API（股價、財報、股利、基本資料），全市場一次即需 5,000 ~ 7,000 次 API，將瞬時擊穿單小時配額池導致大量 402 錯誤。
因此依商業價值與市場趨勢實施階層化調度：

| 層級 (Tier) | 範疇定義 | 實體檔數 | 更新頻率 | 每次 API 消耗 | 調度與額度策略 |
| :--- | :--- | :---: | :--- | :---: | :--- |
| **Tier 1 (Focus)** | 核心重倉與必看持股（`StockID_TWSE_TPEX_focus.csv`） | 37 檔 | **每日必新 (Daily)** | ~148 次 | 每日首批執行，佔小時配額 <4%，永不延遲。 |
| **Tier 2 (AI + Obs)** | **AI 強勢主題股** (AI伺服器/邊緣AI/NVIDIA鏈/CoWoS/CPO/HBM/資料中心等) 與核心觀察池（`StockID_TWSE_TPEX.csv`） | 436 檔 | **每日必新 (Daily)** | ~1,744 次 | 接在 Tier 1 後執行。Tier 1+2 總共僅 ~1,892 次，在單一小時（4,200 次）內即可 100% 完整完成。 |
| **Tier 3 (Other Themes)** | 次要產業主題（蘋果鏈、電動車、低軌衛星、工業電腦、半導體材料等） | 373 檔 | **2~3 天 / 週頻** | ~1,492 次 | 安排於後續排程（如 04:00/07:00）或特定交易日批次輪替更新。 |
| **Tier 4 (Universe Tail)** | 全市場冷門長尾個股 | 919 檔 | **雙週 / 季報事件驅動** | ~3,676 次 | 平時跳過，分 14 天平攤（每天僅 ~260 次）或僅於每季財報與除權息公布期間觸發。 |
| **合計總消耗** | **全市場階層化排程** | **1,733 檔** | — | **~2,652 次 / 日** | **遠低於每日總額度池，安全率高達 80% 以上。** |

## Parity 驗證

- Type 13：`python skills/skill-finmind-fetch/scripts/compare_type13.py <finmind.csv> <analyzer/raw_margin_daily.csv> --stock-id 2330`
- Type 14：`python skills/skill-finmind-fetch/scripts/compare_type14.py --candidate <finmind.csv> --reference <analyzer/raw_margin_weekly.csv> --stock-id 2330`
- Type 15：`python skills/skill-finmind-fetch/scripts/compare_type15.py --candidate <finmind.csv> --reference <analyzer/raw_margin_monthly.csv> --stock-id 2330`
- Type 16：`python skills/skill-finmind-fetch/scripts/compare_type16.py <finmind.csv> <analyzer/raw_fin_ratio_quarter.csv> --stock-id 2330`

驗證器以數值比較 CSV，會分開報告來源缺少的欄位；不會把缺少的 FinMind 欄位填成假資料。

## 全 type 通用驗證：compare_stage1_raw.py

每個 `data/stage1_raw/<stem>.csv` 的欄位結構（stock_code、company_name、期別欄位、資料欄、6 個固定 metadata 欄）跟 `Python-Actions.GoodInfo.Analyzer` 的同名檔案完全一致，所以可以用同一支腳本比對任何一個 type，不用每個 type 各寫一支：

```bash
# 單一 type
python skills/skill-finmind-fetch/scripts/compare_stage1_raw.py --type 1

# 全部 active type 一次跑完
python skills/skill-finmind-fetch/scripts/compare_stage1_raw.py

# 指定 reference 路徑（預設抓 ../Python-Actions.GoodInfo.Analyzer/data/stage1_raw）
python skills/skill-finmind-fetch/scripts/compare_stage1_raw.py --type 1 --reference-root /path/to/Analyzer/data/stage1_raw
```

輸出內容：
- 只存在 reference、我們這邊完全沒有的股票（缺股）
- 只存在其中一邊的 (股票, 期別) 資料列（缺期別）
- 逐欄位比對：數值誤差超過 `--tolerance`（預設 1%）的筆數、我方缺值筆數、reference 缺值筆數，並各列出幾個範例

metadata 欄位（file_type/source_file/download_success/download_timestamp/process_timestamp/stage1_process_timestamp）一定會因來源、執行時間不同而不同，不列入比對。
