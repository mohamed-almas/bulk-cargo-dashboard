"""Helpers shared by refresh_congestion_timeseries.py and refresh_port_particulars.py.

Credentials come only from the environment (OCEANBOLT_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY).
"""
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

REQUEST_DELAY = 0.5   # pause after every Oceanbolt call; these endpoints rate-limit (429)
RETRIES = 4
RATE_TRIES = 8        # attempts when the API answers 429 / a connection drop


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def retry(fn, tries=RETRIES):
    attempt = 0
    while True:
        attempt += 1
        try:
            out = fn()
            time.sleep(REQUEST_DELAY)
            return out
        except Exception as e:
            msg = str(e).lower()
            limited = any(k in msg for k in ("429", "rate limit", "503", "500", "unavailable", "stream removed",
                                             "deadline", "connection", "resolving"))
            if "bad request" in msg or attempt >= (RATE_TRIES if limited else tries):  # a 400 never succeeds on retry
                raise
            wait = min(90, 10 * attempt) if limited else min(60, 5 * 2 ** attempt)
            log("  retry %d in %ds: %s" % (attempt, wait, str(e)[:120]))
            time.sleep(wait)


def snake(df):
    df = df.copy()
    df.columns = [re.sub(r"(?<!^)(?=[A-Z])", "_", str(c)).lower() for c in df.columns]
    return df


def clean(v):
    """JSON-safe value: NaN / NaT / inf -> None, numpy scalars -> python."""
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if isinstance(v, float) and math.isinf(v):
        return None
    return v.item() if hasattr(v, "item") else v


class Supabase:
    """Minimal PostgREST client (service role): paged select and batched upsert."""

    def __init__(self):
        self.base = os.environ["SUPABASE_URL"].rstrip("/")
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"].strip().strip("\"'")
        self.headers = {"apikey": key, "Content-Type": "application/json"}
        if not key.startswith("sb_"):  # new-style sb_secret_ keys go in apikey only; legacy JWT keys also as Bearer
            self.headers["Authorization"] = "Bearer " + key

    def select_all(self, table, columns, page=1000):
        out, start = [], 0
        while True:
            r = requests.get("%s/rest/v1/%s" % (self.base, table), params={"select": ",".join(columns)},
                             headers=dict(self.headers, Range="%d-%d" % (start, start + page - 1)), timeout=120)
            r.raise_for_status()
            rows = r.json()
            out += rows
            if len(rows) < page:
                return out
            start += page

    def upsert(self, table, rows, conflict, batch=1000):
        """Upsert rows (all dicts share the same keys). Returns the number of rows that could NOT be saved."""
        failed = 0
        for i in range(0, len(rows), batch):
            failed += self._post(table, rows[i:i + batch], conflict)
        return failed

    def _post(self, table, rows, conflict, tries=3):
        for attempt in range(tries):
            try:
                r = requests.post("%s/rest/v1/%s" % (self.base, table), params={"on_conflict": conflict},
                                  headers=dict(self.headers, Prefer="resolution=merge-duplicates,return=minimal"),
                                  json=rows, timeout=120)
            except requests.RequestException as e:
                log("  upsert error (%s), retrying" % str(e)[:100])
                time.sleep(5)
                continue
            if r.status_code in (200, 201, 204):
                return 0
            if r.status_code == 400 and len(rows) > 1:  # isolate the bad row(s) instead of losing the batch
                h = len(rows) // 2
                return self._post(table, rows[:h], conflict, tries) + self._post(table, rows[h:], conflict, tries)
            if r.status_code in (401, 403):  # a wrong key never works on retry
                raise SystemExit("Supabase rejected the key (%s): %s\nUse the service_role key of project %s "
                                 "(Project Settings > API), not the anon key." % (r.status_code, r.text[:150], self.base))
            log("  upsert failed (%s): %s" % (r.status_code, r.text[:200]))
            time.sleep(5)
        return len(rows)


def run_parallel(label, items, work, on_result, workers, flush=None, flush_seconds=600, max_fails=3):
    """work(item) runs in worker threads; on_result / flush run in the main thread. Returns the failure count."""
    t0 = last_flush = time.time()
    done = ok = fail = 0
    ex = ThreadPoolExecutor(max_workers=workers)
    try:
        futs = {ex.submit(work, it): it for it in items}
        for f in as_completed(futs):
            it = futs[f]
            done += 1
            try:
                res = f.result()
            except Exception as e:
                fail += 1
                if fail <= 10:
                    log("[%s %d/%d] FAILED %s: %s" % (label, done, len(items), it, str(e)[:150]))
                if ok == 0 and fail >= max_fails:
                    log("[%s] first %d requests all failed, endpoint looks down - aborting" % (label, max_fails))
                    break
                continue
            ok += 1
            on_result(it, res)
            if done % 100 == 0 or done == len(items):
                log("[%s] %d/%d done, %d failed (%.0fs)" % (label, done, len(items), fail, time.time() - t0))
            if flush and time.time() - last_flush > flush_seconds:
                flush()
                last_flush = time.time()
    finally:  # keep whatever we got, even on cancel
        ex.shutdown(wait=False, cancel_futures=True)
        if flush:
            flush()
    return fail + (len(items) - done)  # requests never reached (aborted run) count as failed
