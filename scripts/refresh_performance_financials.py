#!/usr/bin/env python3
"""Refresh Types 4 and 7 from shared FinMind statements, balance sheets and prices."""
import argparse,csv,json,sys,time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/skill-finmind-fetch/scripts'))
from fetch_to_csv import fetch_data
from token_env import TokenRotator
import fetch_type4 as t4,fetch_type7 as t7
SPECS={4:('raw_performance','年度',t4),7:('raw_performance1','季度',t7)}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache-dir',required=True);p.add_argument('--end-date',default=datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat());a=p.parse_args()
 cache=Path(a.cache_dir);cache.mkdir(parents=True,exist_ok=True);rot=TokenRotator()
 header_by_type={};old_by_type={};stock_names={}
 for t,(stem,key,adapter) in SPECS.items():
  stage=ROOT/'data/stage1_raw'/f'{stem}.csv'
  with stage.open(encoding='utf-8-sig',newline='') as h:r=csv.DictReader(h);header_by_type[t]=r.fieldnames;old_by_type[t]=list(r)
  for row in old_by_type[t]:stock_names[row['stock_code']]=row['company_name']
  for stock in stock_names:
   f=ROOT/'financial'/f'type{t}'/f'{stem}_{stock}.csv'
   if f.exists():
    with f.open(encoding='utf-8-sig',newline='') as h:
     if csv.DictReader(h).fieldnames!=adapter.COLUMNS:raise ValueError(f'Type {t} schema mismatch: {f}')
 reports={}
 for index,(stock,name) in enumerate(sorted(stock_names.items()),1):
  def dataset(ds):
   path=cache/f'{ds}_{stock}_2024-01-01.json'
   if path.exists() and datetime.fromtimestamp(path.stat().st_mtime,ZoneInfo('Asia/Taipei')).date().isoformat()>=a.end_date:
    data=pd.DataFrame(json.loads(path.read_text()))
   else:
    data=fetch_data(ds,data_id=stock,start_date='2024-01-01',end_date=a.end_date,token=rot)
    if data.empty:raise RuntimeError(f'No {ds} data for {stock}; no combined output written')
    path.write_text(data.to_json(orient='records'));time.sleep(.25)
   if data.empty:raise RuntimeError(f'Cached {ds} data is empty for {stock}')
   return data,path
  fin,finfile=dataset('TaiwanStockFinancialStatements');bal,balf=dataset('TaiwanStockBalanceSheet');px,pxf=dataset('TaiwanStockPrice')
  latest_source=max(finfile.stat().st_mtime,balf.stat().st_mtime,pxf.stat().st_mtime)
  stamp=datetime.fromtimestamp(latest_source,ZoneInfo('Asia/Taipei')).isoformat(timespec='seconds')
  per_stock={}
  for t,(stem,key,adapter) in SPECS.items():
   built=adapter.build(stock,name,fin.to_dict('records'),bal.to_dict('records'),px.to_dict('records'))
   if built.empty:raise RuntimeError(f'Type {t} produced no data for {stock}')
   built=built[built[key].astype(str)>='2025'].copy().where(pd.notna(built[built[key].astype(str)>='2025'].copy()),'')
   built['download_timestamp']=stamp
   priorpath=ROOT/'financial'/f'type{t}'/f'{stem}_{stock}.csv'
   with priorpath.open(encoding='utf-8-sig',newline='') as h:r=csv.DictReader(h);prior=list(r);header=r.fieldnames
   if header!=adapter.COLUMNS:raise ValueError(f'Type {t} header mismatch for {stock}')
   freshkeys=set(built[key].astype(str));merged=[r for r in prior if str(r[key]) not in freshkeys]+built.to_dict('records')
   merged.sort(key=lambda row:row[key])
   if len({str(row[key]) for row in merged})!=len(merged):raise ValueError(f'Duplicate Type {t} rows for {stock}')
   per_stock[t]=merged
  for t,(stem,key,adapter) in SPECS.items():
   f=ROOT/'financial'/f'type{t}'/f'{stem}_{stock}.csv'
   with f.open('w',encoding='utf-8-sig',newline='') as h:w=csv.DictWriter(h,fieldnames=adapter.COLUMNS,lineterminator='\n');w.writeheader();w.writerows(per_stock[t])
  reports[stock]=True
  if index%10==0:print(f'Types 4/7: processed {index}/{len(stock_names)} stocks',flush=True)
 # Stage outputs are written only after every stock and both adapters succeeded.
 for t,(stem,key,adapter) in SPECS.items():
  rows=[]
  for stock in sorted(stock_names):
   with (ROOT/'financial'/f'type{t}'/f'{stem}_{stock}.csv').open(encoding='utf-8-sig',newline='') as h:rows.extend(csv.DictReader(h))
  path=ROOT/'data/stage1_raw'/f'{stem}.csv'
  with path.open('w',encoding='utf-8-sig',newline='') as h:w=csv.DictWriter(h,fieldnames=adapter.COLUMNS,lineterminator='\r\n');w.writeheader();w.writerows(rows)
  print(f'Type {t} complete: {len(stock_names)} stocks, {len(rows)} rows',flush=True)
if __name__=='__main__':main()
