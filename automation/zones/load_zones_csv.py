"""One-off bulk load of the local zone CSVs + polygon workbook into Supabase (zones_* tables) using Postgres COPY.

Needs a direct Postgres connection (REST is too slow for ~15 million rows):
    set ZONES_DB_URL=postgresql://postgres.<project-ref>:<db-password>@aws-0-<region>.pooler.supabase.com:5432/postgres
    (Supabase dashboard > Connect > Session pooler; project Bulk_Tradeflows)
    python automation/zones/load_zones_csv.py "C:\\Users\\mohamed.almas\\OneDrive\\Claude\\Bulk Cargo\\Zones\\data"

Safe to re-run or resume: every chunk is loaded into a temp table and inserted with ON CONFLICT DO NOTHING
(--overwrite updates existing rows instead). Dims load first, then the fact tables.
    --only zones_count zones_changes     load just these tables
    --dry-run                            check files and columns, load nothing
After this, the weekly workflow (refresh_zones.yml) keeps the tables current.
"""
import argparse
import os
import sys
import time

import pandas as pd

CHUNK = 250_000
# table: (source file, {table column: source column}, primary key, integer columns)
FACT = ["platform", "zone_id", "segment", "sub_segment", "laden_status", "date", "vessel_count", "vessel_dwt"]
SPECS = {
    "zones_dim_platform": ("dim_platform.csv", {"platform": "platform"}, ["platform"], []),
    "zones_dim_zone": ("dim_zone.csv", {c: c for c in ["platform", "zone_id", "zone_key", "zone_name", "chokepoint"]},
                       ["platform", "zone_id"], ["zone_id"]),
    "zones_dim_segment": ("dim_segment.csv", {c: c for c in ["platform", "segment_key", "segment", "sub_segment",
                                                             "segment_order", "highlevel_type"]},
                          ["platform", "segment_key"], ["segment_order"]),
    "zones_dim_laden": ("dim_laden.csv", {"laden_status": "laden_status"}, ["laden_status"], []),
    "zones_dim_flow": ("dim_flow.csv", {"flow": "flow"}, ["flow"], []),
    "zones_dim_direction": ("dim_direction.csv", {"direction": "direction", "direction_order": "direction_order"},
                            ["direction"], ["direction_order"]),
    "zones_dim_date": ("dim_date.csv", {c: c for c in ["date", "year", "month_no", "month", "year_month"]},
                       ["date"], ["year", "month_no"]),
    "zones_dim_chokepoint": ("dim_chokepoint.csv", {c: c for c in ["portwatch_id", "chokepoint", "lat", "lon", "mapped",
                                                                    "best_basis", "zone_pairs", "note"]},
                             ["portwatch_id"], []),
    "zones_adjacency": ("zone_adjacency.csv", {c: c for c in ["platform", "pair_key", "from_zone_id", "to_zone_id",
                                                              "from_zone", "to_zone", "relation", "bearing_deg",
                                                              "direction", "direction4", "chokepoint",
                                                              "chokepoint_basis", "from_zone_key", "to_zone_key"]},
                        ["platform", "pair_key"], ["from_zone_id", "to_zone_id"]),
    "zones_bridge_pair_chokepoint": ("bridge_pair_chokepoint.csv",
                                     {c: c for c in ["platform", "pair_key", "portwatch_id", "chokepoint", "basis"]},
                                     ["platform", "pair_key", "portwatch_id"], []),
    "zones_count": ("zone_count.csv", {c: c for c in FACT + ["avg_speed"]},
                    ["platform", "zone_id", "segment", "sub_segment", "laden_status", "date"], ["zone_id", "vessel_count"]),
    "zones_changes": ("zone_changes.csv", {c: c for c in ["platform", "flow"] + FACT[1:]},
                      ["platform", "flow", "zone_id", "segment", "sub_segment", "laden_status", "date"],
                      ["zone_id", "vessel_count"]),
    "zones_changes_pairs": ("zone_changes_pairs.csv",
                            {c: c for c in ["platform", "from_zone_id", "to_zone_id"] + FACT[2:]},
                            ["platform", "from_zone_id", "to_zone_id", "segment", "sub_segment", "laden_status", "date"],
                            ["from_zone_id", "to_zone_id", "vessel_count"]),
}
XLSX = "Oceanbolt_Tonnage_Map_Zones.xlsx"


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def chunks(table, folder):
    """Yield DataFrames with exactly the table's columns (in order)."""
    file, cols, pk, ints = SPECS[table]
    path = os.path.join(folder, file)
    use = list(cols.values())
    dtypes = {c: "Int64" for c in ints}
    for ch in pd.read_csv(path, usecols=use, dtype=dtypes, chunksize=CHUNK, low_memory=False):
        yield ch.rename(columns={v: k for k, v in cols.items()})[list(cols)]


def polygon_frames(folder):
    xl = os.path.join(folder, "..", XLSX)
    if not os.path.exists(xl):
        xl = os.path.join(folder, XLSX)
    v = pd.read_excel(xl, sheet_name="Vertices").rename(columns={
        "Zone": "zone", "Zone ID": "zone_id", "Vertex #": "vertex_no", "Latitude": "latitude", "Longitude": "longitude"})
    s = pd.read_excel(xl, sheet_name="Zone summary").rename(columns={
        "Zone": "zone", "Zone ID": "zone_id", "Vertices": "vertices", "Min Lat": "min_lat", "Max Lat": "max_lat",
        "Min Lon": "min_lon", "Max Lon": "max_lon"})
    return {"zones_polygon_vertices": (v[["zone_id", "zone", "vertex_no", "latitude", "longitude"]], ["zone_id", "vertex_no"]),
            "zones_polygon_summary": (s[["zone_id", "zone", "vertices", "min_lat", "max_lat", "min_lon", "max_lon"]], ["zone_id"])}


def load_frame(cur, table, df, pk, overwrite):
    cols = list(df.columns)
    cl = ", ".join(cols)
    cur.execute("create temp table if not exists _stg (like public.%s including defaults) on commit delete rows" % table)
    with cur.copy("copy _stg (%s) from stdin with (format csv)" % cl) as cp:
        cp.write(df.to_csv(index=False, header=False))
    upd = ", ".join("%s = excluded.%s" % (c, c) for c in cols if c not in pk)
    action = "do update set " + upd if overwrite and upd else "do nothing"
    cur.execute("insert into public.%s (%s) select %s from _stg on conflict (%s) %s" % (table, cl, cl, ", ".join(pk), action))
    return cur.rowcount


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="folder with the CSVs (dim_*.csv, zone_count.csv, ...)")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    tables = [t for t in list(SPECS) + ["zones_polygon_vertices", "zones_polygon_summary"] if not a.only or t in a.only]
    poly = polygon_frames(a.folder)
    if a.dry_run:
        for t in tables:
            if t in poly:
                df, pk = poly[t]
                log("%-32s %6d rows  cols=%s" % (t, len(df), list(df.columns)))
            else:
                first = next(chunks(t, a.folder))
                log("%-32s first chunk %d rows  cols=%s" % (t, len(first), list(first.columns)))
        return

    import psycopg
    url = os.environ.get("ZONES_DB_URL")
    if not url:
        sys.exit("Set ZONES_DB_URL (Supabase > Connect > Session pooler connection string for project Bulk_Tradeflows)")
    with psycopg.connect(url, autocommit=False) as conn:
        cur = conn.cursor()
        cur.execute("set statement_timeout = 0")
        for t in tables:
            t0, n = time.time(), 0
            cur.execute("drop table if exists _stg")  # staging table is shaped like the current target
            pk = poly[t][1] if t in poly else SPECS[t][2]
            for df in ([poly[t][0]] if t in poly else chunks(t, a.folder)):
                n += load_frame(cur, t, df, pk, a.overwrite)
                conn.commit()
                log("%-32s +%d rows loaded so far (%.0fs)" % (t, n, time.time() - t0))
            cur.execute("select count(*) from public.%s" % t)
            log("%-32s DONE: table now has %d rows" % (t, cur.fetchone()[0]))
        for t in ("zones_count", "zones_changes", "zones_changes_pairs"):
            if not a.only or t in a.only:
                cur.execute("analyze public.%s" % t)
        conn.commit()


if __name__ == "__main__":
    main()
