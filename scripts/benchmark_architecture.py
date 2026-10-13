"""Measure isolated recovery/query work with one year of daily and 30 days of minute data."""
from pathlib import Path
from datetime import datetime, timedelta
import argparse
import json
import statistics
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.bootstrap.application import DesktopApplication
from app.storage.db import connect_db, init_schema


def measure(samples=10):
    scratch=ROOT/'.local'
    scratch.mkdir(exist_ok=True)
    balance=json.loads((ROOT/'config/balance.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(dir=scratch) as folder:
        conn=connect_db(Path(folder)/'app.db')
        try:
            init_schema(conn)
            today=(datetime.now()-timedelta(hours=balance.get('day_start_hour',4))).date()
            days=[((today-timedelta(days=i)).isoformat(),14400,14400,14400,1440,10.0,1.0) for i in range(365)]
            conn.executemany('INSERT INTO daily_stats(date,typed_chars,valid_chars,total_tw,active_minutes,avg_tw,accuracy) VALUES(?,?,?,?,?,?,?)',days)
            minutes=[((today-timedelta(days=i)).isoformat(),f'{minute//60:02}:{minute%60:02}',10,0,10)
                     for i in range(30) for minute in range(1440)]
            conn.executemany('INSERT INTO minute_stats VALUES(?,?,?,?,?)',minutes)
            conn.execute('UPDATE lifetime SET total_typed=?,total_tw=?,total_active_minutes=?',
                         (365*14400,365*14400,365*1440))
            conn.commit()
        finally:
            conn.close()
        start=time.perf_counter()
        app=DesktopApplication(folder,balance,{})
        try:
            result=dict(sample_daily_rows=365,sample_minute_rows=len(minutes),samples=samples,
                        startup_ms=(time.perf_counter()-start)*1000)
            values=[]
            for _ in range(samples):
                app.counter.handle_char('letter')
                start=time.perf_counter()
                app.flush().result(10)
                values.append((time.perf_counter()-start)*1000)
            result['checkpoint_median_ms']=statistics.median(values)
            result['checkpoint_max_ms']=max(values)
            start=time.perf_counter()
            for _ in range(1000):
                app.counter.snapshot()
                app.models.get_setting('nickname')
                app.models.get_exp()
            result['snapshot_and_summary_mean_ms']=(time.perf_counter()-start)*1000/1000
            start=time.perf_counter()
            app.models.get_hourly_stats((today-timedelta(days=29)).isoformat(),today.isoformat())
            result['hourly_query_ms']=(time.perf_counter()-start)*1000
        finally:
            app.close()
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples',type=int,default=10)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.samples<1:
        parser.error('--samples must be positive')
    result=measure(args.samples)
    output=json.dumps(result,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(output+'\n',encoding='utf-8')
    print(output)

if __name__=='__main__':main()
