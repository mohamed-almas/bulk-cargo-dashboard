"""Weekly refresh: Oceanbolt zone data -> Supabase zones_* tables (dry, tank, lng, lpg).

Incremental: for every series (platform x zone x segment x laden status) it looks up the last stored date, re-downloads
from OVERLAP_DAYS before that (late revisions get overwritten) and upserts. Series with no data yet download their full
history from 2018. A gap of any length therefore heals itself on the next run.

Env:  OCEANBOLT_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
Run:  python automation/zones/refresh_zones.py [--platforms dry tank] [--steps dims count changes pairs]
                                               [--full] [--overlap 14] [--workers 4] [--dry-run]

Steps: dims (zones, segments, adjacency, chokepoints, polygons, calendar) | count | changes | pairs
Tables: zones_count, zones_changes, zones_changes_pairs + zones_dim_*, zones_adjacency, zones_bridge_pair_chokepoint,
        zones_polygon_*; zones_refresh_log gets one row per run. View zones_changes_daily is the zero-filled crossings.
Exit code 1 if any series failed (the rest is still saved; the next run retries the failed ones).
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import pandas as pd
from oceanbolt.sdk.client import APIClient
from oceanbolt.sdk.data.entities import Segments, Zones
from oceanbolt.sdk.data.tonnage import TonnageZoneTimeseries, ZoneChangesTimeseries
from supabase import create_client

import build_zone_adjacency as adjmod

HISTORY_START = date(2018, 1, 1)
OVERLAP_DAYS = 14
PLATFORMS = ["dry", "tank", "lng", "lpg"]  # sent as the x-ob-platform header
LADEN = ["laden", "ballast"]
FLOWS = ["arrivals", "departures"]
DIRECTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "nested"]
SUB_LEVEL = {"tank", "lng", "lpg"}  # one top-level segment -> one series per sub-segment (VLCC, ...)
ALL = "(all)"  # sub_segment value for dry, which is downloaded at top-level segment
BATCH = 4000  # rows per upsert request
FLUSH_ROWS = 20000
REQUEST_DELAY = 0.2
RETRIES = 4
SUBKEY = {}  # (platform, sub_segment display name) -> API key


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


RATE_TRIES = 8  # rate limits (429) and connection drops need more patience than other errors


def with_retry(fn, tries=RETRIES):
    attempt = 0
    while True:
        attempt += 1
        try:
            out = fn()
            time.sleep(REQUEST_DELAY)
            return out
        except Exception as e:
            msg = str(e).lower()
            limited = any(k in msg for k in ("429", "rate limit", "503", "unavailable", "stream removed", "deadline",
                                             "connection", "resolving"))
            limit = max(tries, RATE_TRIES) if limited else tries
            if attempt >= limit or "bad request" in msg:  # a 400 never succeeds on retry
                raise
            wait = min(90, 10 * attempt) if limited else min(60, 5 * 2 ** attempt)
            log("  retry %d/%d in %ds: %s" % (attempt, limit - 1, wait, str(e)[:120]))
            time.sleep(wait)


def key(platform, i):
    return "%s-%s" % (platform, i)


def series(p, s):
    """[(segment, sub_segment, segment_key, order)] to download for platform p."""
    if p in SUB_LEVEL:
        u = s[["segment", "sub_segment", "sub_segment_key", "sub_segment_int"]].drop_duplicates(["segment", "sub_segment"])
        for r in u.itertuples():  # the API filters on the lowercase KEY ('tiny_tanker'), not the display name
            SUBKEY[(p, r.sub_segment)] = r.sub_segment_key
        return [(r.segment, r.sub_segment, key(p, r.sub_segment), r.sub_segment_int) for r in u.itertuples()]
    u = s[["segment", "segment_int"]].drop_duplicates("segment")
    return [(r.segment, ALL, key(p, r.segment), r.segment_int) for r in u.itertuples()]


def segkw(c):  # the API takes segment OR sub_segment, never both
    if c["sub_segment"] == ALL:
        return {"segment": [c["segment"]]}
    return {"sub_segment": [SUBKEY.get((c["platform"], c["sub_segment"]), c["sub_segment"])]}


def connect(token, platforms):
    out = {}
    for p in platforms:
        try:
            c = APIClient(token, p)
            z = with_retry(lambda: Zones(c).get(), tries=3)
            s = with_retry(lambda: Segments(c).get(), tries=3)
            if len(z) == 0 or len(s) == 0:
                raise RuntimeError("no zones/segments returned")
            out[p] = (c, z, s)
            log("[%s] %d zones, %d series" % (p, len(z), len(series(p, s))))
        except Exception as e:
            log("[%s] SKIPPED - %s" % (p, str(e)[:150]))
    return out


# ---------------------------------------------------------------- supabase helpers
def records(df):
    """DataFrame -> JSON-safe list of dicts (NaN -> null, '' -> null)."""
    rows = json.loads(df.to_json(orient="records"))
    return [{k: (None if v == "" else v) for k, v in r.items()} for r in rows]


def upsert(sb, table, rows, on_conflict):
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        with_retry(lambda c=chunk: sb.table(table).upsert(c, on_conflict=on_conflict).execute(), tries=4)


def last_dates(sb, table, keys):
    data = with_retry(lambda: sb.rpc("zones_last_dates", {"p_table": table}).execute()).data or []
    return {tuple(r[k] for k in keys): r["last_date"] for r in data}


# ---------------------------------------------------------------- dims / adjacency / polygons
def write_dims(sb, conn, dry):
    n = {}

    def put(table, df, conflict):
        rows = records(df)
        n[table] = len(rows)
        if not dry:
            upsert(sb, table, rows, conflict)

    zones, segs = [], []
    for p, (c, z, s) in conn.items():
        zz = z[["zone_id", "zone_name"]].copy()
        zz.insert(0, "platform", p)
        zz.insert(1, "zone_key", [key(p, i) for i in zz["zone_id"]])
        zz["chokepoint"] = zz["zone_name"].map(adjmod.ZONE_CHOKEPOINTS).fillna("")
        zones.append(zz)
        ss = pd.DataFrame(series(p, s), columns=["segment", "sub_segment", "segment_key", "segment_order"])
        ss.insert(0, "platform", p)
        segs.append(ss.merge(s[["segment", "highlevel_type"]].drop_duplicates("segment"), on="segment", how="left"))
    put("zones_dim_platform", pd.DataFrame({"platform": list(conn)}), "platform")
    put("zones_dim_zone", pd.concat(zones), "platform,zone_id")
    put("zones_dim_segment", pd.concat(segs), "platform,segment_key")
    put("zones_dim_laden", pd.DataFrame({"laden_status": LADEN}), "laden_status")
    put("zones_dim_flow", pd.DataFrame({"flow": FLOWS}), "flow")
    put("zones_dim_direction", pd.DataFrame({"direction": DIRECTIONS, "direction_order": range(1, len(DIRECTIONS) + 1)}),
        "direction")
    d = pd.DataFrame({"date": pd.date_range("2018-01-01", date(date.today().year + 1, 12, 31))})
    d["year"], d["month_no"] = d["date"].dt.year, d["date"].dt.month
    d["month"], d["year_month"] = d["date"].dt.strftime("%b"), d["date"].dt.strftime("%Y-%m")
    d["date"] = d["date"].dt.strftime("%Y-%m-%d")
    put("zones_dim_date", d, "date")
    put("zones_dim_chokepoint", adjmod.chokepoint_dim(), "portwatch_id")
    v = pd.read_excel(adjmod.XLSX, sheet_name="Vertices").rename(columns={
        "Zone": "zone", "Zone ID": "zone_id", "Vertex #": "vertex_no", "Latitude": "latitude", "Longitude": "longitude"})
    put("zones_polygon_vertices", v[["zone_id", "zone", "vertex_no", "latitude", "longitude"]], "zone_id,vertex_no")
    sm = pd.read_excel(adjmod.XLSX, sheet_name="Zone summary").rename(columns={
        "Zone": "zone", "Zone ID": "zone_id", "Vertices": "vertices", "Min Lat": "min_lat", "Max Lat": "max_lat",
        "Min Lon": "min_lon", "Max Lon": "max_lon"})
    put("zones_polygon_summary", sm[["zone_id", "zone", "vertices", "min_lat", "max_lat", "min_lon", "max_lon"]], "zone_id")
    return n


def adjacency(sb, conn, dry, n):
    """Neighbouring zone pairs from the polygons, matched to each platform's zones by NAME."""
    a = adjmod.build()[["from_zone", "to_zone", "relation", "bearing_deg", "direction", "direction4",
                        "chokepoint", "chokepoint_basis"]]
    parts = []
    for p, (c, z, s) in conn.items():
        ids = dict(zip(z["zone_name"], z["zone_id"]))
        m = a[a["from_zone"].isin(ids) & a["to_zone"].isin(ids)].copy()
        missing = sorted(set(z["zone_name"]) - set(a["from_zone"]))
        if missing:
            log("[%s] no polygon for zones (left out of pairs): %s" % (p, missing))
        m.insert(0, "platform", p)
        m["from_zone_id"], m["to_zone_id"] = m["from_zone"].map(ids), m["to_zone"].map(ids)
        m["from_zone_key"] = [key(p, i) for i in m["from_zone_id"]]
        m["to_zone_key"] = [key(p, i) for i in m["to_zone_id"]]
        m["pair_key"] = m["from_zone_key"] + "|" + m["to_zone_key"]
        parts.append(m)
    adj = pd.concat(parts, ignore_index=True)
    bk = adj[["platform", "pair_key", "from_zone", "to_zone"]].merge(adjmod.bridge(), on=["from_zone", "to_zone"])
    bk = bk[["platform", "pair_key", "portwatch_id", "chokepoint", "basis"]]
    for table, df, conflict in (("zones_adjacency", adj, "platform,pair_key"),
                                ("zones_bridge_pair_chokepoint", bk, "platform,pair_key,portwatch_id")):
        rows = records(df)
        n[table] = len(rows)
        if not dry:
            upsert(sb, table, rows, conflict)
    return adj


# ---------------------------------------------------------------- facts
def sync_table(sb, table, keys, combos, fetch, cols, conflict, workers, full, overlap, dry):
    """Download every combo (parallel), upsert in the main thread. Returns (rows_upserted, failed)."""
    last = {} if full else last_dates(sb, table, keys)
    today = date.today()
    failed, buf, total, done = [], [], 0, 0
    t0 = time.time()

    def work(c):
        k = tuple(c[x] for x in keys)
        lst = last.get(k)
        start = HISTORY_START if not lst else max(HISTORY_START, date.fromisoformat(lst) - timedelta(days=overlap))
        df = fetch(c, start, today)
        if df is None or len(df) == 0:
            return []
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        for x in cols:
            if x not in df.columns and x in c:
                df[x] = c[x]
        return records(df[cols])

    def flush():
        nonlocal buf, total
        if buf and not dry:
            upsert(sb, table, buf, conflict)
        total += len(buf)
        buf = []

    ex = ThreadPoolExecutor(max_workers=workers)
    try:
        futs = {ex.submit(work, c): c for c in combos}
        for f in as_completed(futs):
            done += 1
            c = futs[f]
            try:
                buf.extend(f.result())
            except Exception as e:
                failed.append({"table": table, "series": [c[x] for x in keys], "error": str(e)[:150]})
                log("[%s] FAILED %s: %s" % (table, [c[x] for x in keys], str(e)[:150]))
            if len(buf) >= FLUSH_ROWS:
                flush()
            if done % 200 == 0:
                log("[%s] %d/%d series (%.0fs), %d rows so far" % (table, done, len(combos), time.time() - t0, total + len(buf)))
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
        flush()
    log("[%s] done: %d series, %d rows upserted, %d failed (%.0fs)" % (table, len(combos), total, len(failed), time.time() - t0))
    return total, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platforms", nargs="*", default=PLATFORMS)
    ap.add_argument("--steps", nargs="*", default=["dims", "count", "changes", "pairs"],
                    choices=["dims", "count", "changes", "pairs"])
    ap.add_argument("--full", action="store_true", help="ignore stored dates and download the full history")
    ap.add_argument("--overlap", type=int, default=OVERLAP_DAYS, help="days re-downloaded before the last stored date")
    ap.add_argument("--workers", type=int, default=2)  # 4 workers mostly produced 429 storms, not speed
    ap.add_argument("--zones", nargs="*", help="zone names only (default all)")
    ap.add_argument("--segments", nargs="*", help="segment or sub-segment names only (default all)")
    ap.add_argument("--dry-run", action="store_true", help="download and count, but write nothing to Supabase")
    a = ap.parse_args()

    token, url, skey = os.environ.get("OCEANBOLT_TOKEN"), os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not (token and url and skey):
        sys.exit("Set OCEANBOLT_TOKEN, SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
    sb = create_client(url, skey)
    run_id = None
    if not a.dry_run:
        run_id = sb.table("zones_refresh_log").insert({"status": "running", "platforms": " ".join(a.platforms)}).execute().data[0]["id"]

    conn = connect(token, a.platforms)
    if not conn:
        sys.exit("No platform could be reached")

    counts, failed = {}, []
    if "dims" in a.steps:
        counts.update(write_dims(sb, conn, a.dry_run))
    adj = adjacency(sb, conn, a.dry_run, counts) if ("dims" in a.steps or "pairs" in a.steps) else None

    def zsel(z):
        return z[z["zone_name"].isin(a.zones)] if a.zones else z

    def ssel(p, s):
        return [t for t in series(p, s) if not a.segments or t[0] in a.segments or t[1] in a.segments]

    run = lambda *x, **k: sync_table(sb, *x, workers=a.workers, full=a.full, overlap=a.overlap, dry=a.dry_run, **k)
    if "count" in a.steps:
        api = {p: TonnageZoneTimeseries(c) for p, (c, z, s) in conn.items()}
        combos = [dict(platform=p, zone_id=int(r.zone_id), segment=t[0], sub_segment=t[1], laden_status=l)
                  for p, (c, z, s) in conn.items() for r in zsel(z).itertuples() for t in ssel(p, s) for l in LADEN]
        n, f = run("zones_count", ["platform", "zone_id", "segment", "sub_segment", "laden_status"], combos,
                   lambda c, st, en: with_retry(lambda: api[c["platform"]].get(
                       zone_id=[c["zone_id"]], laden_status=[c["laden_status"]], start_date=st, end_date=en,
                       sort="asc", **segkw(c))),
                   cols=["platform", "zone_id", "segment", "sub_segment", "laden_status", "date",
                         "vessel_count", "vessel_dwt", "avg_speed"],
                   conflict="platform,zone_id,segment,sub_segment,laden_status,date")
        counts["zones_count"], failed = n, failed + f
    if "changes" in a.steps:
        api = {p: ZoneChangesTimeseries(c) for p, (c, z, s) in conn.items()}
        combos = [dict(platform=p, flow=fl, zone_id=int(r.zone_id), segment=t[0], sub_segment=t[1], laden_status=l)
                  for p, (c, z, s) in conn.items() for fl in FLOWS for r in zsel(z).itertuples()
                  for t in ssel(p, s) for l in LADEN]

        def fetch_changes(c, st, en):  # departures: only from_zone set; arrivals: only to_zone set
            side = "from_zone_id" if c["flow"] == "departures" else "to_zone_id"
            return with_retry(lambda: api[c["platform"]].get(
                laden_status=[c["laden_status"]], frequency="daily", start_date=st, end_date=en, sort="asc",
                **segkw(c), **{side: [c["zone_id"]]}))

        n, f = run("zones_changes", ["platform", "flow", "zone_id", "segment", "sub_segment", "laden_status"], combos,
                   fetch_changes,
                   cols=["platform", "flow", "zone_id", "segment", "sub_segment", "laden_status", "date",
                         "vessel_count", "vessel_dwt"],
                   conflict="platform,flow,zone_id,segment,sub_segment,laden_status,date")
        counts["zones_changes"], failed = n, failed + f
    if "pairs" in a.steps:
        api = {p: ZoneChangesTimeseries(c) for p, (c, z, s) in conn.items()}
        ids = {p: set(zsel(z)["zone_id"]) for p, (c, z, s) in conn.items()}
        combos = [dict(platform=r.platform, from_zone_id=int(r.from_zone_id), to_zone_id=int(r.to_zone_id),
                       segment=t[0], sub_segment=t[1], laden_status=l)
                  for r in adj.itertuples() if r.from_zone_id in ids[r.platform] or r.to_zone_id in ids[r.platform]
                  for t in ssel(r.platform, conn[r.platform][2]) for l in LADEN]
        n, f = run("zones_changes_pairs", ["platform", "from_zone_id", "to_zone_id", "segment", "sub_segment", "laden_status"],
                   combos,
                   lambda c, st, en: with_retry(lambda: api[c["platform"]].get(
                       from_zone_id=[c["from_zone_id"]], to_zone_id=[c["to_zone_id"]], laden_status=[c["laden_status"]],
                       frequency="daily", start_date=st, end_date=en, sort="asc", **segkw(c))),
                   cols=["platform", "from_zone_id", "to_zone_id", "segment", "sub_segment", "laden_status", "date",
                         "vessel_count", "vessel_dwt"],
                   conflict="platform,from_zone_id,to_zone_id,segment,sub_segment,laden_status,date")
        counts["zones_changes_pairs"], failed = n, failed + f

    status = "ok" if not failed else "partial"
    log("finished: %s | rows %s | %d failed series" % (status, counts, len(failed)))
    if run_id:
        sb.table("zones_refresh_log").update({
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": status,
            "rows_upserted": counts, "failed": failed[:200]}).eq("id", run_id).execute()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
