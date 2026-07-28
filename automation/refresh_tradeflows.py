"""Weekly Oceanbolt -> Supabase incremental refresh for the tradeflows table.

Fetches the last N days (default 60) of trade flow data for all four vessel
types, upserts the 23 shared columns keyed on flow_id, stamps vessel_type
and refresh_date, then refreshes every materialized view built on
tradeflows. Credentials are read only from the environment - see
scripts/requirements.txt and the refresh_tradeflows.yml workflow.
"""
import logging
import math
import os
import sys
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from oceanbolt.sdk.client import APIClient
from oceanbolt.sdk.helpers import pb_list_to_pandas

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
OCEANBOLT_TOKEN = os.environ["OCEANBOLT_TOKEN"]

TABLE = "tradeflows"
PAGE_SIZE = 50000
UPSERT_BATCH_SIZE = 500

# (Oceanbolt platform code, vessel_type label stored in Supabase).
# Platform codes match the SDK's `x-ob-platform` header value used by the
# original per-segment CSV pull scripts in Scripts/ (note: Tanker is
# "tank", not "tanker").
VESSEL_TYPES = [
    ("dry", "Dry"),
    ("lng", "LNG"),
    ("lpg", "LPG"),
    ("tank", "Tanker"),
]

# The 23 columns shared by the tradeflows schema (of the ~56 the API
# returns) and how to coerce each one. Every cleaned record carries the
# exact same set of keys so a batch can be sent to PostgREST as one upsert.
COLUMN_TYPES = {
    "voyage_id": "str", "flow_id": "str", "commodity_value": "str",
    "imo": "int", "volume": "int", "load_port_id": "int", "discharge_port_id": "int",
    "load_port_days_total": "numeric", "load_port_days_berthed": "numeric",
    "load_port_days_waiting": "numeric", "discharge_port_days_total": "numeric",
    "discharge_port_days_berthed": "numeric", "discharge_port_days_waiting": "numeric",
    "days_steaming": "numeric", "days_total_duration": "numeric",
    "distance_calculated": "numeric", "distance_actual": "numeric",
    "load_port_arrived_at": "timestamp", "load_port_berthed_at": "timestamp",
    "load_port_departed_at": "timestamp", "discharge_port_arrived_at": "timestamp",
    "discharge_port_berthed_at": "timestamp", "discharge_port_departed_at": "timestamp",
}


def safe_int(val: Any) -> Optional[int]:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, str) and val.strip() == "":
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return None
        return int(val) if val.is_integer() else None
    if isinstance(val, str):
        try:
            return int(float(val))
        except ValueError:
            return None
    return None


def clean_value(val: Any, target_type: str) -> Any:
    if val is None:
        return None
    if isinstance(val, str) and val.strip() == "":
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None

    if target_type == "str":
        return val if isinstance(val, str) else str(val)
    if target_type == "int":
        return safe_int(val)
    if target_type == "numeric":
        if isinstance(val, (int, float)):
            return val
        try:
            return float(val)
        except (ValueError, TypeError):
            return None
    if target_type == "timestamp":
        if isinstance(val, (pd.Timestamp, date)):
            return val.isoformat()
        if isinstance(val, str):
            try:
                pd.Timestamp(val)
                return val
            except (ValueError, TypeError):
                return None
        return None
    return val


def clean_record(record: dict, vessel_type: str, refresh_date: str) -> Optional[dict]:
    cleaned = {col: clean_value(record.get(col), ftype) for col, ftype in COLUMN_TYPES.items()}
    if not cleaned.get("flow_id") or not cleaned.get("voyage_id"):
        return None
    cleaned["vessel_type"] = vessel_type
    cleaned["refresh_date"] = refresh_date
    return cleaned


def chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


class SupabaseREST:
    def __init__(self, url: str, key: str):
        self.base = url
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        }

    def upsert_batch(self, table: str, records: List[dict], retries: int = 3) -> int:
        if not records:
            return 0
        for attempt in range(retries):
            r = requests.post(
                f"{self.base}/rest/v1/{table}",
                params={"on_conflict": "flow_id"},
                headers=self.headers,
                json=records,
                timeout=120,
            )
            if r.status_code in (200, 201, 204):
                return len(records)
            if r.status_code == 400 and len(records) > 1:
                # Isolate the bad record(s) instead of failing the whole batch.
                mid = len(records) // 2
                return self.upsert_batch(table, records[:mid], retries) + \
                    self.upsert_batch(table, records[mid:], retries)
            if attempt < retries - 1:
                log.warning("Upsert batch failed (%s), retrying: %s", r.status_code, r.text[:200])
                time.sleep(2)
                continue
            log.error("Upsert batch failed permanently (%s): %s", r.status_code, r.text[:300])
            return 0
        return 0

    def rpc(self, fn: str, params: Optional[dict] = None):
        r = requests.post(
            f"{self.base}/rest/v1/rpc/{fn}",
            headers=self.headers,
            json=params or {},
            timeout=300,
        )
        if not r.ok:
            raise RuntimeError(f"RPC {fn} failed {r.status_code}: {r.text[:500]}")
        return r


def fetch_vessel_type(platform: str, days_back: int) -> List[dict]:
    """Fetch all trade flows for one vessel type over the trailing window.

    The high-level TradeFlows.get() wrapper doesn't paginate, and Dry bulk
    volume is high enough to hit a single page's max_results over a 60-day
    window, so this walks next_token directly against the underlying
    gRPC client (the same one TradeFlows.get() uses internally).
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    log.info("Fetching %s from %s to %s", platform, start_date, end_date)

    client = APIClient(OCEANBOLT_TOKEN, platform)
    trade_flows_client = client._trade_flows_client()

    all_records: List[dict] = []
    next_token = None
    page = 1
    while True:
        request = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "max_results": PAGE_SIZE,
        }
        if next_token:
            request["next_token"] = next_token
        response = trade_flows_client.get_trade_flows(request=request, metadata=client.metadata)
        df = pb_list_to_pandas(response.data)
        if len(df):
            all_records.extend(df.to_dict(orient="records"))
        log.info("  %s page %d: %d rows (running total %d)", platform, page, len(df), len(all_records))

        next_token = getattr(response, "next_token", "") or ""
        if not next_token:
            break
        page += 1

    return all_records


def main():
    days_back = int(os.environ.get("REFRESH_DAYS_BACK", "60"))
    sb = SupabaseREST(SUPABASE_URL, SUPABASE_KEY)
    refresh_date = pd.Timestamp.now(tz="UTC").isoformat()

    totals: Dict[str, int] = {"fetched": 0, "upserted": 0, "skipped": 0}
    had_error = False

    for platform, vessel_type in VESSEL_TYPES:
        try:
            raw_records = fetch_vessel_type(platform, days_back)
        except Exception:
            log.exception("Fetch failed for %s", vessel_type)
            had_error = True
            continue

        cleaned = []
        skipped = 0
        for rec in raw_records:
            c = clean_record(rec, vessel_type, refresh_date)
            if c is None:
                skipped += 1
                continue
            cleaned.append(c)

        upserted = 0
        for batch in chunked(cleaned, UPSERT_BATCH_SIZE):
            upserted += sb.upsert_batch(TABLE, batch)

        log.info("%s: fetched %d, upserted %d, skipped %d", vessel_type, len(raw_records), upserted, skipped)
        totals["fetched"] += len(raw_records)
        totals["upserted"] += upserted
        totals["skipped"] += skipped

        if upserted < len(cleaned):
            had_error = True

    log.info("Totals: %s", totals)

    log.info("Refreshing tradeflows materialized views ...")
    try:
        sb.rpc("refresh_tradeflows_matviews")
        log.info("Materialized views refreshed")
    except Exception:
        log.exception("Matview refresh failed")
        had_error = True

    if had_error:
        log.error("Finished with errors")
        sys.exit(1)
    log.info("Done")


if __name__ == "__main__":
    main()
