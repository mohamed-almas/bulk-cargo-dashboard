"""Weekly Oceanbolt -> Supabase refresh of the congestion_timeseries table.

One series per platform (dry/tank/lng/lpg) x country and per platform x region (the API needs a location filter, so
there is no global series). Each series is re-fetched for the trailing REFRESH_DAYS_BACK days (default 35: Oceanbolt
revises recent days) and upserted on (platform, dimension, dimension_value, date).
To backfill a window instead, set REFRESH_START_DATE and REFRESH_END_DATE (YYYY-MM-DD, both).
--dry-run fetches but writes nothing. Credentials: OCEANBOLT_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.
"""
import argparse
import os
import sys
from datetime import date, timedelta

import pandas as pd
from oceanbolt.sdk.client import APIClient
from oceanbolt.sdk.data.congestion import CongestionTimeseries
from oceanbolt.sdk.data.entities import Countries, Regions

from oceanbolt_common import Supabase, clean, log, retry, run_parallel, snake

TABLE = "congestion_timeseries"
CONFLICT = "platform,dimension,dimension_value,date"
PLATFORMS = ["dry", "tank", "lng", "lpg"]
COLUMNS = ["vessel_count", "vessel_dwt", "avg_waiting_days", "median_waiting_days"]
FLUSH_ROWS = 20000


def date_range():
    s, e = os.environ.get("REFRESH_START_DATE", "").strip(), os.environ.get("REFRESH_END_DATE", "").strip()
    if s or e:
        if not (s and e):
            sys.exit("REFRESH_START_DATE and REFRESH_END_DATE must both be set, or neither")
        return date.fromisoformat(s), date.fromisoformat(e)
    return date.today() - timedelta(days=int(os.environ.get("REFRESH_DAYS_BACK") or 35)), date.today()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platforms", nargs="*", default=PLATFORMS)
    ap.add_argument("--workers", type=int, default=2, help="parallel API requests (more than 2 mostly gets 429s)")
    ap.add_argument("--only-country", help="test: only this country code")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    token = os.environ["OCEANBOLT_TOKEN"].strip()
    start, end = date_range()
    sb = None if a.dry_run else Supabase()

    apis, units = {}, []  # unit = (platform, dimension, value, request filters)
    for p in a.platforms:
        c = APIClient(token, p)
        units += [(p, "country", r.country_code, {"country_code": [r.country_code]})
                  for r in retry(lambda: Countries(c).get(), tries=3).itertuples()]
        units += [(p, "region", r.region_id, {"region_id": [r.region_id]})
                  for r in retry(lambda: Regions(c).get(), tries=3).itertuples()]
        apis[p] = CongestionTimeseries(c)
        log("[%s] connected" % p)
    if a.only_country:
        units = [u for u in units if u[1] == "country" and u[2] == a.only_country]
    log("%d series, %s to %s" % (len(units), start, end))

    buf, total, failed_rows = [], [0], [0]

    def work(u):
        p, dim, val, kw = u
        df = retry(lambda: apis[p].get(start_date=start, end_date=end, **kw))
        if df is None or not len(df):
            return []
        df = snake(df).rename(columns={"average_waiting_days": "avg_waiting_days"})
        rows = []
        for r in df.to_dict("records"):
            row = {"platform": p, "dimension": dim, "dimension_value": val,
                   "date": pd.Timestamp(r["date"]).strftime("%Y-%m-%d")}
            row.update({c: clean(r.get(c)) for c in COLUMNS})
            rows.append(row)
        return rows

    def flush():
        if not buf:
            return
        if sb:
            failed_rows[0] += sb.upsert(TABLE, buf, CONFLICT)
        total[0] += len(buf)
        log("upserted %d rows (running total %d, failed %d)" % (len(buf), total[0], failed_rows[0]))
        buf.clear()

    def on_result(u, rows):
        buf.extend(rows)
        if len(buf) >= FLUSH_ROWS:
            flush()

    failed = run_parallel("series", units, work, on_result, a.workers, flush)
    log("rows: %d, failed series: %d, failed rows: %d%s" % (total[0], failed, failed_rows[0],
                                                           " (dry run: nothing written)" if a.dry_run else ""))
    sys.exit(1 if failed or failed_rows[0] else 0)


if __name__ == "__main__":
    main()
