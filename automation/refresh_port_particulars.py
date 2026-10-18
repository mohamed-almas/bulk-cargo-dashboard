"""Weekly Oceanbolt -> Supabase refresh of the port_particulars table.

One row per platform x port x window ('all' time and each calendar year). Step 1 fetches the all-time window for every
port, which shows which ports have calls at all; step 2 fetches each calendar year only for ports with calls. What is
refetched is decided from the rows already in Supabase (fetched_at):
  - a year that closed more than 14 days before it was fetched is final and never fetched again
  - the all-time window and the current year are refetched after --stale-days (default 6, so a weekly run refreshes them)
  - ports that never had a call are only rechecked after --zero-stale-days (default 28)
Missing windows (a new port, a new year, a first run) are always fetched. Rows are upserted on
(platform, port_id, "window"). --dry-run fetches but writes nothing.
Credentials: OCEANBOLT_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.
"""
import argparse
import os
import sys
from datetime import date, timedelta

import pandas as pd
from oceanbolt.sdk.client import APIClient
from oceanbolt.sdk.data.entities import Ports
from oceanbolt.sdk.data.port_calls import PortParticulars

from oceanbolt_common import Supabase, clean, log, retry, run_parallel, snake

TABLE = "port_particulars"
CONFLICT = "platform,port_id,window"
PLATFORMS = ["dry", "tank", "lng", "lpg"]
HISTORY_START = date(2018, 1, 1)
OVERLAP_DAYS = 14
STATS = ["loa", "beam", "max_draught", "reported_draught", "dwt", "air_draught"]
STAT_FIELDS = [("min_", "min"), ("max_", "max"), ("percentile_10", "p10"), ("percentile_50", "p50"),
               ("percentile_90", "p90"), ("percentile_95", "p95"), ("percentile_99", "p99"), ("mean", "mean")]
FLUSH_ROWS = 5000


def flatten(r):
    row = {"number_of_port_calls": r.number_of_port_calls}
    for s in STATS:
        present = s in r  # an unset statistic (e.g. no air draught data) stays empty, not zero
        st = getattr(r, s)
        for src, dst in STAT_FIELDS:
            row["%s_%s" % (s, dst)] = clean(getattr(st, src)) if present else None
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platforms", nargs="*", default=PLATFORMS)
    ap.add_argument("--workers", type=int, default=2, help="parallel API requests (more than 2 mostly gets 429s)")
    ap.add_argument("--stale-days", type=int, default=6, help="refetch open windows older than this many days")
    ap.add_argument("--zero-stale-days", type=int, default=28, help="recheck never-called ports after this many days")
    ap.add_argument("--full", action="store_true", help="ignore what is in Supabase and fetch everything")
    ap.add_argument("--limit", type=int, help="test: stop after this many requests per step")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    token = os.environ["OCEANBOLT_TOKEN"].strip()
    today = date.today()
    sb = None if a.dry_run and not os.environ.get("SUPABASE_SERVICE_ROLE_KEY") else Supabase()

    clients, ports = {}, {}
    for p in a.platforms:
        c = APIClient(token, p)
        df = snake(retry(lambda: Ports(c).get(), tries=3))
        clients[p], ports[p] = c, df
        log("[%s] connected, %d ports" % (p, len(df)))
    names = {}  # (platform, port_id) -> (port_name, unlocode)
    for p, df in ports.items():
        for r in df.itertuples():
            names[(p, int(r.port_id))] = (clean(getattr(r, "port_name", None)), clean(getattr(r, "unlocode", None)))

    fetched = {}  # (platform, port_id, window) -> (fetched_at, number_of_port_calls)
    if sb and not a.full:
        rows = sb.select_all(TABLE, ["platform", "port_id", "window", "fetched_at", "number_of_port_calls"])
        fetched = {(r["platform"], r["port_id"], str(r["window"])): (r["fetched_at"], r["number_of_port_calls"])
                   for r in rows}
        log("%d windows already in Supabase" % len(fetched))

    def stale(k, window_end):
        got = fetched.get(k)
        if got is None:
            return True
        at = date.fromisoformat(got[0])
        if at > window_end + timedelta(days=OVERLAP_DAYS):  # fetched well after the window closed: final
            return False
        quiet = k[2] == "all" and not got[1]  # never any call at this port
        return (today - at).days >= (a.zero_stale_days if quiet else a.stale_days)

    buf, total, failed_rows = [], [0], [0]

    def work(u):
        p, port_id, window, ws, we = u
        # get_raw skips the SDK's date conversion, so the dates must be text, not date objects
        r = retry(lambda: PortParticulars(clients[p]).get_raw(port_id=port_id, start_date=ws.isoformat(),
                                                              end_date=we.isoformat()))
        name, unlocode = names.get((p, port_id), (None, None))
        row = dict(platform=p, port_id=port_id, port_name=name, unlocode=unlocode, window=window,
                   window_start=ws.isoformat(), window_end=we.isoformat(), fetched_at=today.isoformat())
        row.update(flatten(r))
        return row

    def flush():
        if not buf:
            return
        if sb and not a.dry_run:
            failed_rows[0] += sb.upsert(TABLE, buf, CONFLICT)
        total[0] += len(buf)
        log("upserted %d rows (running total %d, failed %d)" % (len(buf), total[0], failed_rows[0]))
        buf.clear()

    def on_result(u, row):
        fetched[(row["platform"], row["port_id"], row["window"])] = (row["fetched_at"], row["number_of_port_calls"])
        buf.append(row)
        if len(buf) >= FLUSH_ROWS:
            flush()

    failures = 0
    all_units = [(p, int(pid), "all", HISTORY_START, today) for p, df in ports.items()
                 for pid in df["port_id"] if stale((p, int(pid), "all"), today)]
    all_units = all_units[:a.limit] if a.limit else all_units
    log("step 1, all-time window: %d requests" % len(all_units))
    failures += run_parallel("all-time", all_units, work, on_result, a.workers, flush)

    year_units = []
    for p, df in ports.items():
        for pid in df["port_id"]:
            got = fetched.get((p, int(pid), "all"))
            if got is None or not got[1]:  # never saw a call at this port: no yearly rows needed
                continue
            for y in range(HISTORY_START.year, today.year + 1):
                we = min(date(y, 12, 31), today)
                if stale((p, int(pid), str(y)), we):
                    year_units.append((p, int(pid), str(y), date(y, 1, 1), we))
    year_units = year_units[:a.limit] if a.limit else year_units
    log("step 2, calendar years for ports with calls: %d requests" % len(year_units))
    failures += run_parallel("years", year_units, work, on_result, a.workers, flush)

    log("rows: %d, failed requests: %d, failed rows: %d%s" % (total[0], failures, failed_rows[0],
                                                             " (dry run: nothing written)" if a.dry_run else ""))
    sys.exit(1 if failures or failed_rows[0] else 0)


if __name__ == "__main__":
    main()
