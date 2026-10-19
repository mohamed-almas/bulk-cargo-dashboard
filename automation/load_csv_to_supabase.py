"""One-off: load the Oceanbolt CSVs into Supabase (same upsert as the weekly refresh, so it is safe to rerun).

    set SUPABASE_SERVICE_ROLE_KEY=<service_role key: Supabase > Project Settings > API>
    python load_csv_to_supabase.py congestion_timeseries "..\\..\\Bulk Cargo\\Congestion Timeseries\\congestion_timeseries.csv"
    python load_csv_to_supabase.py port_particulars "..\\..\\Bulk Cargo\\Port Particulars\\port_particulars.csv"
    python load_csv_to_supabase.py congested_vessels "..\\..\\Bulk Cargo\\Congested Vessels\\congested_vessels_*.csv"

congested_vessels takes a wildcard (all yearly files). Its current_port_id is recovered from the port name + country
code using ports.csv (--ports), because Oceanbolt returns only the name; a last load port id of 0 means unknown -> null.
Add --dry-run to read and convert the files without writing.
"""
import argparse
import glob
import os
import sys
import time

import pandas as pd

from oceanbolt_common import Supabase, clean, log

TABLES = {  # table -> (conflict columns, integer columns, date columns)
    "congestion_timeseries": ("platform,dimension,dimension_value,date", ["vessel_count"], ["date"]),
    "port_particulars": ("platform,port_id,window", ["port_id", "number_of_port_calls"],
                         ["window_start", "window_end", "fetched_at"]),
    "congested_vessels": ("platform,snapshot_date,imo", ["imo", "dwt", "last_load_port_id", "current_port_id"],
                          ["snapshot_date"]),
}
CHUNK = 20000
DEFAULT_PORTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Bulk Cargo", "Port Particulars",
                             "ports.csv")


def port_lookup(path):
    p = pd.read_csv(path, keep_default_na=False, na_values=[""], dtype={"country_code": str})
    p = p.drop_duplicates(["platform", "port_name", "country_code"])
    return p[["platform", "port_name", "country_code", "port_id"]].rename(
        columns={"port_name": "current_port_name", "country_code": "current_country_code", "port_id": "current_port_id"})


def chunks(a):
    """Yield DataFrames of at most CHUNK rows from every file matching a.csv."""
    files = sorted(glob.glob(a.csv))
    if not files:
        sys.exit("no file matches " + a.csv)
    lookup = port_lookup(a.ports) if a.table == "congested_vessels" else None
    for f in files:
        log("file " + os.path.basename(f))
        # keep_default_na=False: the country code NA (Namibia) must stay text, only empty cells are null
        for c in pd.read_csv(f, chunksize=CHUNK, dtype={"window": str}, keep_default_na=False, na_values=[""]):
            if lookup is not None:
                c = c.drop(columns=["current_port_id", "last_port_departed_at"], errors="ignore").merge(
                    lookup, on=["platform", "current_port_name", "current_country_code"], how="left")
                c["last_load_port_id"] = c["last_load_port_id"].replace(0, pd.NA)
            yield c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("table", choices=TABLES)
    ap.add_argument("csv", help="CSV path (congested_vessels: wildcard for the yearly files)")
    ap.add_argument("--ports", default=DEFAULT_PORTS, help="ports.csv, used to recover current_port_id")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    conflict, ints, dates = TABLES[a.table]
    sb = None if a.dry_run else Supabase()
    total = failed = 0
    t0 = time.time()
    for chunk in chunks(a):
        for c in ints:
            chunk[c] = chunk[c].astype("Int64")
        for c in dates:
            chunk[c] = pd.to_datetime(chunk[c]).dt.strftime("%Y-%m-%d")
        if a.table == "congestion_timeseries":  # a blank country code is a real series: keep it as '' (key column)
            chunk["dimension_value"] = chunk["dimension_value"].fillna("")
        rows = [{k: clean(v) for k, v in r.items()} for r in chunk.to_dict("records")]
        if sb:
            failed += sb.upsert(a.table, rows, conflict)
        total += len(rows)
        log("%d rows read%s, %d failed (%.0fs)" % (total, "" if a.dry_run else " and upserted", failed, time.time() - t0))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
