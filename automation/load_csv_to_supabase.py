"""One-off: load the Oceanbolt CSVs into Supabase (same upsert as the weekly refresh, so it is safe to rerun).

    set SUPABASE_URL=https://lsyombbeyjokpndczvdj.supabase.co
    set SUPABASE_SERVICE_ROLE_KEY=<service_role key: Supabase > Project Settings > API>
    python load_csv_to_supabase.py congestion_timeseries "..\\..\\Bulk Cargo\\Congestion Timeseries\\congestion_timeseries.csv"
    python load_csv_to_supabase.py port_particulars "..\\..\\Bulk Cargo\\Port Particulars\\port_particulars.csv"

Add --dry-run to read and convert the file without writing.
"""
import argparse
import sys
import time

import pandas as pd

from oceanbolt_common import Supabase, clean, log

TABLES = {  # table -> (conflict columns, integer columns, date columns)
    "congestion_timeseries": ("platform,dimension,dimension_value,date", ["vessel_count"], ["date"]),
    "port_particulars": ("platform,port_id,window", ["port_id", "number_of_port_calls"],
                         ["window_start", "window_end", "fetched_at"]),
}
CHUNK = 20000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("table", choices=TABLES)
    ap.add_argument("csv")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    conflict, ints, dates = TABLES[a.table]
    sb = None if a.dry_run else Supabase()
    total = failed = 0
    t0 = time.time()
    for chunk in pd.read_csv(a.csv, chunksize=CHUNK, dtype={"window": str}):
        for c in ints:
            chunk[c] = chunk[c].astype("Int64")
        for c in dates:
            chunk[c] = pd.to_datetime(chunk[c]).dt.strftime("%Y-%m-%d")
        rows = [{k: clean(v) for k, v in r.items()} for r in chunk.to_dict("records")]
        if sb:
            failed += sb.upsert(a.table, rows, conflict)
        total += len(rows)
        log("%d rows read%s, %d failed (%.0fs)" % (total, "" if a.dry_run else " and upserted", failed, time.time() - t0))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
