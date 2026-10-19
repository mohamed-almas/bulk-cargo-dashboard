"""Weekly Oceanbolt -> Supabase refresh of the congested_vessels table.

One snapshot per day: daily for the last RECENT_DAYS (90) days and weekly (every 7th calendar day) before that, the
same grid as the CSV history. Per platform the window starts OVERLAP_DAYS (14) before the newest snapshot already in
Supabase (or at REFRESH_START_DATE / REFRESH_END_DATE when set, to backfill) and ends today. Rows are upserted on
(platform, snapshot_date, imo).
The API needs a location filter, so each day is fetched region by region in groups; a server reset on a group
halves it, and a single region the server cannot answer is skipped and logged (the next weekly run retries it,
because the window overlaps).
current_port_id is recovered from current_port_name + current_country_code with the platform's port list
(Oceanbolt returns only the name); a last load port id of 0 means unknown and becomes null.
--dry-run fetches but writes nothing. Credentials: OCEANBOLT_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.
"""
import argparse
import os
import sys
from datetime import date, timedelta

import pandas as pd
import requests
from oceanbolt.sdk.client import APIClient
from oceanbolt.sdk.data.congestion import CongestionVessels
from oceanbolt.sdk.data.entities import Ports, Regions

from oceanbolt_common import Supabase, clean, is_heavy, log, retry, run_parallel, snake

TABLE = "congested_vessels"
CONFLICT = "platform,snapshot_date,imo"
PLATFORMS = ["dry", "tank", "lng", "lpg"]
OVERLAP_DAYS = 14
RECENT_DAYS = 90
STEP_DAYS = 7
FLUSH_ROWS = 5000
COLUMNS = ["vessel_name", "segment", "sub_segment", "dwt", "current_port_name", "current_country",
           "current_country_code", "arrived_at", "waiting_time_days", "last_load_country", "last_load_country_code",
           "last_load_port_id", "last_load_port_name", "last_load_berth_name", "commodity_group", "commodity",
           "volume", "laden_status"]


def to_rows(platform, day, df, ports):
    rows, seen = [], set()
    for r in df.to_dict("records"):
        imo = clean(r.get("imo"))
        if imo is None or int(imo) in seen:  # one row per vessel and day (the primary key)
            continue
        seen.add(int(imo))
        row = {"platform": platform, "snapshot_date": day.isoformat(), "imo": int(imo)}
        for c in COLUMNS:
            row[c] = clean(r.get(c))
        for c in ("dwt", "last_load_port_id"):
            row[c] = int(row[c]) if row[c] is not None else None
        if row["last_load_port_id"] == 0:  # Oceanbolt's 'unknown'
            row["last_load_port_id"] = None
        row["current_port_id"] = ports.get((row["current_port_name"], row["current_country_code"]))
        if row["arrived_at"] is not None:
            row["arrived_at"] = pd.Timestamp(row["arrived_at"]).isoformat()
        rows.append(row)
    return rows


def last_snapshot(sb, platform):
    r = requests.get("%s/rest/v1/%s" % (sb.base, TABLE), headers=sb.headers, timeout=60,
                     params={"select": "snapshot_date", "platform": "eq." + platform,
                             "order": "snapshot_date.desc", "limit": "1"})
    r.raise_for_status()
    j = r.json()
    return date.fromisoformat(j[0]["snapshot_date"]) if j else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platforms", nargs="*", default=PLATFORMS)
    ap.add_argument("--workers", type=int, default=1, help="parallel days (this endpoint rate-limits: keep 1)")
    ap.add_argument("--region-chunk", type=int, default=6, help="regions per request (halves itself on a reset)")
    ap.add_argument("--limit-days", type=int, help="test: only the newest N days per platform")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    token = os.environ["OCEANBOLT_TOKEN"].strip()
    today = date.today()
    s_env, e_env = os.environ.get("REFRESH_START_DATE", "").strip(), os.environ.get("REFRESH_END_DATE", "").strip()
    if bool(s_env) != bool(e_env):
        sys.exit("REFRESH_START_DATE and REFRESH_END_DATE must both be set, or neither")
    sb = None if a.dry_run and not os.environ.get("SUPABASE_SERVICE_ROLE_KEY") else Supabase()
    failures = skipped_total = 0

    for p in a.platforms:
        c = APIClient(token, p)
        api = CongestionVessels(c)
        regions = list(retry(lambda: Regions(c).get(), tries=3)["region_id"])
        pdf = snake(retry(lambda: Ports(c).get(), tries=3)).drop_duplicates(["port_name", "country_code"])
        ports = {(r.port_name, r.country_code): int(r.port_id) for r in pdf.itertuples()}
        if s_env:
            start, end = date.fromisoformat(s_env), date.fromisoformat(e_env)
        else:
            last = last_snapshot(sb, p) if sb else None
            start, end = (last - timedelta(days=OVERLAP_DAYS) if last else today - timedelta(days=120)), today
        days = [d for d in (start + timedelta(n) for n in range((end - start).days + 1))
                if (today - d).days <= RECENT_DAYS or d.toordinal() % STEP_DAYS == 0]
        days = days[-a.limit_days:] if a.limit_days else days
        log("[%s] %d regions, %d ports, %d snapshot days (%s to %s)" % (p, len(regions), len(ports), len(days), start, end))
        chunk, buf, total, failed_rows, skipped = [max(1, a.region_chunk)], [], [0], [0], []

        def fetch(day, regs, ctx):
            try:
                out = retry(lambda: api.get(display_date=day.isoformat(), region_id=regs), heavy_tries=1)
                ctx[0] = max(ctx[0], len(regs))
                return out
            except Exception as e:
                if not is_heavy(str(e).lower()):
                    raise  # network / rate-limit trouble that outlasted the retries: the day fails
                if len(regs) > 1:  # server reset: too many regions at once, ask for half
                    h = len(regs) // 2
                    log("  server reset on %d regions, retrying in smaller groups" % len(regs))
                    return pd.concat([fetch(day, regs[:h], ctx), fetch(day, regs[h:], ctx)], ignore_index=True)
                log("  skipping %s on %s: the server cannot answer it (retried next week)" % (regs[0], day))
                skipped.append((day, regs[0]))
                return pd.DataFrame()

        def work(day):
            ctx = [0]
            parts = [fetch(day, regions[i:i + chunk[0]], ctx) for i in range(0, len(regions), chunk[0])]
            parts = [x for x in parts if x is not None and len(x)]
            if ctx[0] and ctx[0] < chunk[0]:  # shrink to the largest group that really worked
                chunk[0] = ctx[0]
            return to_rows(p, day, snake(pd.concat(parts, ignore_index=True)), ports) if parts else []

        def flush():
            if not buf:
                return
            if sb and not a.dry_run:
                failed_rows[0] += sb.upsert(TABLE, buf, CONFLICT)
            total[0] += len(buf)
            log("[%s] upserted %d rows (running total %d, failed %d)" % (p, len(buf), total[0], failed_rows[0]))
            buf.clear()

        def on_result(day, rows):
            buf.extend(rows)
            if len(buf) >= FLUSH_ROWS:
                flush()

        failed = run_parallel(p, days, work, on_result, a.workers, flush)
        failures += failed + failed_rows[0]
        skipped_total += len(skipped)
        log("[%s] rows: %d, failed days: %d, failed rows: %d, skipped region-days: %d%s" % (
            p, total[0], failed, failed_rows[0], len(skipped), " (dry run)" if a.dry_run else ""))

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
