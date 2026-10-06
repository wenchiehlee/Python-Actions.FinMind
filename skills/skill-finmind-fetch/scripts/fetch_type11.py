#!/usr/bin/env python3
"""Build GoodInfo Type 11 weekly trading data from FinMind."""
from __future__ import annotations
import argparse
from datetime import datetime,timedelta
from pathlib import Path
import numpy as np,pandas as pd
from dotenv import load_dotenv
from fetch_to_csv import fetch_data,process_stock_data
from price_cache import cached_price
from token_env import TokenRotator
load_dotenv()
COLUMNS=['stock_code','company_name','交易_週別','交易_日數','開盤_價格_元','最高_價格_元','最低_價格_元','收盤_價格_元','漲跌_價格_元','漲跌_pct','振幅_pct','成交_張數','成交_金額_億','法人買賣超_千張','外資_淨買超_千張','投信_淨買超_千張','自營_淨買超_千張','法人_合計_千張','外資_持股_pct','融資_增減_張','融資_餘額_張','融券_增減_張','融券_餘額_張','券資比_pct','融券_千張_增減','融券_千張_餘額','券資_比_pct','file_type','source_file','download_success','download_timestamp','process_timestamp','stage1_process_timestamp']
def build(stock_id,name,price,inst,margin):
 if price.empty:
  return pd.DataFrame(columns=COLUMNS)
 p=price.copy(); i=inst.copy();
 p['date']=pd.to_datetime(p.date,errors='coerce'); p=p.dropna(subset=['date']).sort_values('date');
 if i.empty or 'date' not in i.columns:
  i=pd.DataFrame({'date': pd.Series(dtype='datetime64[ns]')})
 else:
  i['date']=pd.to_datetime(i.date,errors='coerce');
 m=process_stock_data(stock_id,price,margin,name) if not price.empty and not margin.empty else pd.DataFrame();
 if not m.empty:m['date']=pd.to_datetime(m['期別'].str.lstrip("'"),format='%y/%m/%d')
 p['_week']=p.date-pd.to_timedelta(p.date.dt.weekday,unit='D'); rows=[]; prev=np.nan; stamp=datetime.now().isoformat(timespec='seconds')
 for ws,g in p.groupby('_week',sort=True):
  last=g.iloc[-1]; label=f'{ws.isocalendar().year%100:02d}W{ws.isocalendar().week:02d}'; close=float(last.close); change=close-prev if pd.notna(prev) else np.nan; iw=i[i.date.isin(g.date)]
  def total_net(pairs):
   value=0.0
   for buy_col,sell_col in pairs:
    buy=pd.to_numeric(iw[buy_col],errors='coerce').fillna(0).sum() if buy_col in iw else 0.0
    sell=pd.to_numeric(iw[sell_col],errors='coerce').fillna(0).sum() if sell_col in iw else 0.0
    value += buy-sell
   return value/1e6
  foreign=total_net([('Foreign_Investor_buy','Foreign_Investor_sell'),('Foreign_Dealer_Self_buy','Foreign_Dealer_Self_sell')]); trust=total_net([('Investment_Trust_buy','Investment_Trust_sell')]); dealer=total_net([('Dealer_buy','Dealer_sell'),('Dealer_self_buy','Dealer_self_sell'),('Dealer_Hedging_buy','Dealer_Hedging_sell')])
  mr=m[m.date.isin(g.date)].sort_values('date') if 'date' in m.columns else pd.DataFrame(); ml=mr.iloc[-1] if not mr.empty else pd.Series()
  row={'stock_code':str(stock_id).zfill(4),'company_name':name,'交易_週別':label,'交易_日數':len(g),'開盤_價格_元':g.iloc[0].open,'最高_價格_元':g['max'].max(),'最低_價格_元':g['min'].min(),'收盤_價格_元':close,'漲跌_價格_元':change,'漲跌_pct':round(change/prev*100,2) if pd.notna(change) and prev else np.nan,'振幅_pct':round((g['max'].max()-g['min'].min())/g.iloc[0].open*100,2),'成交_張數':round(g.Trading_Volume.sum()/1e6,2),'成交_金額_億':round(g.Trading_money.sum()/1e10,2),'法人買賣超_千張':foreign+trust+dealer,'外資_淨買超_千張':foreign,'投信_淨買超_千張':trust,'自營_淨買超_千張':dealer,'法人_合計_千張':foreign+trust+dealer,'外資_持股_pct':np.nan,'融資_增減_張':ml.get('融資_增減_張',np.nan),'融資_餘額_張':ml.get('融資_餘額_張',np.nan),'融券_增減_張':ml.get('融券_增減_張',np.nan),'融券_餘額_張':ml.get('融券_餘額_張',np.nan),'券資比_pct':ml.get('券資比_pct',np.nan),'融券_千張_增減':ml.get('融券_增減_張',np.nan)/1000 if pd.notna(ml.get('融券_增減_張',np.nan)) else np.nan,'融券_千張_餘額':ml.get('融券_餘額_張',np.nan)/1000 if pd.notna(ml.get('融券_餘額_張',np.nan)) else np.nan,'券資_比_pct':ml.get('券資比_pct',np.nan),'file_type':'WeeklyTradingData','source_file':f'FinMind_API_WeeklyTradingData_{str(stock_id).zfill(4)}','download_success':True,'download_timestamp':stamp,'process_timestamp':stamp,'stage1_process_timestamp':stamp}; rows.append(row); prev=close
 return pd.DataFrame(rows,columns=COLUMNS)
def main():
 p=argparse.ArgumentParser();p.add_argument('--stock-id',default='2330');p.add_argument('--company-name',default='台積電');p.add_argument('--start-date',default='2021-01-01');p.add_argument('--end-date',default=(datetime.now()+timedelta(hours=8)).strftime('%Y-%m-%d'));p.add_argument('--output',default='financial/type11/raw_weekly_trading_data_2330.csv');p.add_argument('--token',default=None);p.add_argument('--price-cache-dir',default=None);a=p.parse_args();rot=TokenRotator(a.token); price=cached_price(a.stock_id,a.start_date,a.end_date,rot,a.price_cache_dir,fetch_data); inst=fetch_data('TaiwanStockInstitutionalInvestorsBuySellWide',data_id=a.stock_id,start_date=a.start_date,end_date=a.end_date,token=rot); margin=fetch_data('TaiwanStockMarginPurchaseShortSale',data_id=a.stock_id,start_date=a.start_date,end_date=a.end_date,token=rot); out=build(a.stock_id,a.company_name,price,inst,margin);
 if out.empty:raise SystemExit('No weekly trading data available')
 Path(a.output).parent.mkdir(parents=True,exist_ok=True);out.to_csv(a.output,index=False,encoding='utf-8-sig');print(f'Wrote {len(out)} weekly trading rows to {a.output}')
if __name__=='__main__':main()
