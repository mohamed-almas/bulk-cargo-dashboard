"""Pre-generate dynamic executive insights (data + news) for a curated list
of dashboard entities by calling the generate-insights Supabase Edge
Function once per entity. Results are cached server-side in the
news_insights table by the function itself (upsert on
scope_type/scope_key/year) - this script just drives which entities get
(re)generated and on what cadence.

Kept to a curated list (not all ~190 countries / ~3000 ports) because each
call does a live Tavily search + Claude synthesis, so cost/time scale with
entity count. Long-tail countries/ports simply have no cached row; the
dashboard falls back to its existing pure-data-driven insights for those.

Credentials are read only from the environment - see
refresh_insights.yml.
"""
import logging
import os
import sys
import time
from datetime import date

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
FUNCTION_URL = f"{SUPABASE_URL}/functions/v1/generate-insights"

YEAR = int(os.environ.get("INSIGHTS_YEAR", date.today().year - 1))

# Curated entity list. Country/coastal-region/port picks are the current
# top-N by total_volume for YEAR (re-check periodically as trade shifts).
ENTITIES = [
    {"scope_type": "global", "scope_key": "all", "scope_label": "Global"},
    {"scope_type": "global", "scope_key": "Dry", "scope_label": "Global Dry Bulk"},
    {"scope_type": "global", "scope_key": "Liquid", "scope_label": "Global Liquid Bulk"},

    {"scope_type": "region", "scope_key": "Asia", "scope_label": "Asia"},
    {"scope_type": "region", "scope_key": "Europe", "scope_label": "Europe"},
    {"scope_type": "region", "scope_key": "North America", "scope_label": "North America"},
    {"scope_type": "region", "scope_key": "South America", "scope_label": "South America"},
    {"scope_type": "region", "scope_key": "Oceania", "scope_label": "Oceania"},
    {"scope_type": "region", "scope_key": "Africa", "scope_label": "Africa"},

    {"scope_type": "coastal_region", "scope_key": "Rest of Asia", "scope_label": "Rest of Asia"},
    {"scope_type": "coastal_region", "scope_key": "China", "scope_label": "China (coastal region)"},
    {"scope_type": "coastal_region", "scope_key": "Latin America & Caribbean", "scope_label": "Latin America & Caribbean"},
    {"scope_type": "coastal_region", "scope_key": "Middle East", "scope_label": "Middle East"},
    {"scope_type": "coastal_region", "scope_key": "North America", "scope_label": "North America (coastal region)"},
    {"scope_type": "coastal_region", "scope_key": "North Europe", "scope_label": "North Europe"},
    {"scope_type": "coastal_region", "scope_key": "Oceania", "scope_label": "Oceania (coastal region)"},
    {"scope_type": "coastal_region", "scope_key": "Indian Sub-Continent", "scope_label": "Indian Sub-Continent"},
    {"scope_type": "coastal_region", "scope_key": "Sub-Saharan Africa", "scope_label": "Sub-Saharan Africa"},
    {"scope_type": "coastal_region", "scope_key": "Mediterranean Europe", "scope_label": "Mediterranean Europe"},
    {"scope_type": "coastal_region", "scope_key": "North Africa", "scope_label": "North Africa"},
    {"scope_type": "coastal_region", "scope_key": "Black Sea", "scope_label": "Black Sea"},

    {"scope_type": "country", "scope_key": "China", "scope_label": "China"},
    {"scope_type": "country", "scope_key": "Australia", "scope_label": "Australia"},
    {"scope_type": "country", "scope_key": "USA", "scope_label": "USA"},
    {"scope_type": "country", "scope_key": "Brazil", "scope_label": "Brazil"},
    {"scope_type": "country", "scope_key": "Indonesia", "scope_label": "Indonesia"},
    {"scope_type": "country", "scope_key": "India", "scope_label": "India"},
    {"scope_type": "country", "scope_key": "Japan", "scope_label": "Japan"},
    {"scope_type": "country", "scope_key": "S. Korea", "scope_label": "S. Korea"},
    {"scope_type": "country", "scope_key": "Russia", "scope_label": "Russia"},
    {"scope_type": "country", "scope_key": "UAE", "scope_label": "UAE"},
    {"scope_type": "country", "scope_key": "KSA", "scope_label": "KSA"},
    {"scope_type": "country", "scope_key": "Canada", "scope_label": "Canada"},
    {"scope_type": "country", "scope_key": "Malaysia", "scope_label": "Malaysia"},
    {"scope_type": "country", "scope_key": "Netherlands", "scope_label": "Netherlands"},
    {"scope_type": "country", "scope_key": "Turkiye", "scope_label": "Turkiye"},

    {"scope_type": "port", "scope_key": "128", "scope_label": "Port Hedland"},
    {"scope_type": "port", "scope_key": "2143", "scope_label": "Singapore"},
    {"scope_type": "port", "scope_key": "2114", "scope_label": "Ras Tanura"},
    {"scope_type": "port", "scope_key": "349", "scope_label": "Caofeidian"},
    {"scope_type": "port", "scope_key": "1905", "scope_label": "Rotterdam"},
    {"scope_type": "port", "scope_key": "461", "scope_label": "Tianjin"},
    {"scope_type": "port", "scope_key": "1729", "scope_label": "Gwangyang"},
    {"scope_type": "port", "scope_key": "4", "scope_label": "Fujairah"},
    {"scope_type": "port", "scope_key": "2338", "scope_label": "Corpus Christi"},
    {"scope_type": "port", "scope_key": "492", "scope_label": "Zhoushan"},
    {"scope_type": "port", "scope_key": "7466", "scope_label": "Al Basrah"},
    {"scope_type": "port", "scope_key": "2366", "scope_label": "Houston, TX"},
    {"scope_type": "port", "scope_key": "405", "scope_label": "Lanshan"},
    {"scope_type": "port", "scope_key": "395", "scope_label": "Jingtang"},
    {"scope_type": "port", "scope_key": "90", "scope_label": "Dampier"},
    {"scope_type": "port", "scope_key": "133", "scope_label": "Port Walcott"},
    {"scope_type": "port", "scope_key": "228", "scope_label": "Ponta da Madeira / Sao Luis"},
    {"scope_type": "port", "scope_key": "1743", "scope_label": "Ulsan"},
]


def generate_one(entity: dict) -> bool:
    payload = {**entity, "year": YEAR}
    resp = requests.post(
        FUNCTION_URL,
        headers={
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "apikey": SUPABASE_KEY,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    if resp.status_code != 200:
        log.error("FAILED %s/%s: HTTP %s %s", entity["scope_type"], entity["scope_key"], resp.status_code, resp.text[:300])
        return False
    body = resp.json()
    if not body.get("ok"):
        log.error("FAILED %s/%s: %s", entity["scope_type"], entity["scope_key"], body)
        return False
    n = len(body.get("insights") or [])
    log.info("OK %s/%s -> %d insights", entity["scope_type"], entity["scope_key"], n)
    return True


def main():
    log.info("Generating insights for %d entities, year=%d", len(ENTITIES), YEAR)
    ok = fail = 0
    for entity in ENTITIES:
        try:
            if generate_one(entity):
                ok += 1
            else:
                fail += 1
        except Exception:
            log.exception("Exception generating %s/%s", entity["scope_type"], entity["scope_key"])
            fail += 1
        time.sleep(1)  # light pacing against Tavily/Anthropic rate limits

    log.info("Done: %d ok, %d failed", ok, fail)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
