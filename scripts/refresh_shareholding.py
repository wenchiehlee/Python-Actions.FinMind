#!/usr/bin/env python3
"""Refresh Type 6 annual ownership from FinMind, using Type 9 year-end prices."""
import argparse,csv,json,sys,time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/skill-finmind-fetch/scripts'))
from fetch_to_csv import fetch_data
from token_env import TokenRotator
from fetch_type6 import COLUMNS,build

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input-csv',default=str(ROOT/'data/stage1_raw/raw_equity_distribution.csv'));p.add_argument('--cache-dir',required=True);p.add_argument('--end-date',default=datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat());a=p.parse_args()
 with open(a.input_csv,encoding='utf-8-sig',newline='') as h:r=csv.DictReader(h);header=r.fieldnames;combined=list(r)
 cache=Path(a.cache_dir);cache.mkdir(parents=True,exist_ok=True);rot=TokenRotator()
 price_rows=list(csv.DictReader(open(ROOT/'data/stage1_raw/raw_stock_his_quar.csv',encoding='utf-8-sig',newline='')))
 prices_by_stock={}
 for row in price_rows:
  close=next((row[f'{q}_收盤_元'] for q in reversed(['第一季','第二季','第三季','第四季']) if row[f'{q}_收盤_元']), '')
  if close:prices_by_stock.setdefault(row['stock_code'],[]).append({'date':f"{row['年度']}-12-31",'close':close})
 targets={r['stock_code']:r['company_name'] for r in combined}
 old={}
 for stock in targets:
  path=ROOT/'financial/type6'/f'raw_equity_distribution_{stock}.csv'
  with path.open(encoding='utf-8-sig',newline='') as h:reader=csv.DictReader(h);assert reader.fieldnames==COLUMNS,(stock,reader.fieldnames);old[stock]=list(reader)
 updates={};report=[]
 for index,(stock,name) in enumerate(sorted(targets.items()),1):
  f=cache/f'TaiwanStockShareholding_{stock}_2018-01-01.json'
  if f.exists() and datetime.fromtimestamp(f.stat().st_mtime,ZoneInfo('Asia/Taipei')).date().isoformat()>=a.end_date:records=json.loads(f.read_text())
  else:
   data=fetch_data('TaiwanStockShareholding',data_id=stock,start_date='2018-01-01',end_date=a.end_date,token=rot)
   if data.empty:raise RuntimeError(f'No FinMind shareholding data for existing Type 6 stock {stock}; no combined output written')
   records=data.to_dict('records');f.write_text(json.dumps(records,ensure_ascii=False));time.sleep(.25)
  fresh=build(stock,name,records,prices_by_stock.get(stock,[]))
  if fresh.empty:raise RuntimeError(f'No Type 6 output for {stock}')
  fresh=fresh[fresh['年度'].astype(str)>='2025'].copy()
  fresh=fresh.where(pd.notna(fresh),'')
  stamp=datetime.fromtimestamp(f.stat().st_mtime,ZoneInfo('Asia/Taipei')).isoformat(timespec='seconds')
  fresh['download_timestamp']=stamp
  prior=pd.DataFrame(old[stock]);merged=pd.concat([prior[~prior['年度'].isin(fresh['年度'])],fresh],ignore_index=True).sort_values('年度')
  if list(merged.columns)!=COLUMNS or merged['年度'].duplicated().any():raise ValueError(f'Type 6 schema/key failure for {stock}')
  updates[stock]=merged.to_dict('records');report.append({'stock':stock,'rows':len(merged),'latest_share_date':max(x['date'] for x in records)})
  if index%10==0:print(f'Type 6: processed {index}/{len(targets)} stocks',flush=True)
 checkpoint=cache/'type6_refresh_progress.json';checkpoint.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 for stock,rows in updates.items():
  path=ROOT/'financial/type6'/f'raw_equity_distribution_{stock}.csv'
  with path.open('w',encoding='utf-8-sig',newline='') as h:w=csv.DictWriter(h,fieldnames=COLUMNS,lineterminator='\n');w.writeheader();w.writerows(rows)
 result=[r for stock in sorted(updates) for r in updates[stock]]
 if len(result)!=len(combined):raise ValueError(f'Coverage changed: {len(combined)} -> {len(result)}')
 with open(a.input_csv,'w',encoding='utf-8-sig',newline='') as h:w=csv.DictWriter(h,fieldnames=COLUMNS,lineterminator='\r\n');w.writeheader();w.writerows(result)
 print(f'Type 6 complete: {len(updates)} stocks, {len(result)} rows',flush=True)
if __name__=='__main__':main()
