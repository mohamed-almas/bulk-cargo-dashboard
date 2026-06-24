import datetime as dt

import pandas as pd
import streamlit as st
from supabase import create_client

# ---------------------------------------------------------------------------
# Theme — matches the palette used in the Container Ports reference dashboard
# ---------------------------------------------------------------------------
THEME = {
    "bg": "#eef1f5",
    "card": "#ffffff",
    "header": "#0b2545",
    "header2": "#13315c",
    "text": "#1b2733",
    "text_secondary": "#5b6b7c",
    "positive": "#1e8a4c",
    "negative": "#d1473a",
}
CHART_COLORS = ["#1b6ca8", "#ef8a17", "#2a9d8f", "#e76f51", "#8d6fb8", "#4b8b3b", "#c9444d", "#5b6b7c"]
CARGO_COLORS = {"Dry Bulk": "#1b6ca8", "Liquid Bulk": "#ef8a17"}


def apply_theme():
    st.markdown(
        f"""
        <style>
        .stApp {{ background-color: {THEME['bg']}; }}
        [data-testid="stSidebar"] {{ background-color: {THEME['header']}; }}
        [data-testid="stSidebar"] * {{ color: #e9f0f9 !important; }}
        h1, h2, h3 {{ color: {THEME['text']}; }}

        .dash-header {{
            background: linear-gradient(120deg, {THEME['header']}, {THEME['header2']});
            color: #ffffff;
            padding: 22px 28px;
            border-radius: 10px;
            margin-bottom: 16px;
        }}
        .dash-header h1 {{ color: #ffffff; font-size: 21px; font-weight: 700; margin: 0; }}
        .dash-header .subtitle {{ font-size: 12.5px; color: #bcd2ec; margin-top: 4px; }}

        .kpi-card {{
            background: {THEME['card']};
            border-radius: 10px;
            padding: 16px 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,.08);
            border-left: 4px solid {CHART_COLORS[0]};
            height: 100%;
        }}
        .kpi-label {{ font-size: 11.5px; color: {THEME['text_secondary']}; text-transform: uppercase; letter-spacing: .5px; margin-bottom: 6px; }}
        .kpi-value {{ font-size: 25px; font-weight: 700; color: {THEME['text']}; }}
        .kpi-sub {{ font-size: 11px; color: {THEME['text_secondary']}; margin-top: 2px; }}

        .insight-card {{
            background: #f6f8fb;
            border-radius: 8px;
            padding: 14px 16px;
            border-top: 3px solid {CHART_COLORS[0]};
            margin-bottom: 8px;
            color: {THEME['text']};
            height: 100%;
        }}
        .insight-card b {{ color: {THEME['header']}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(title: str, subtitle: str):
    st.markdown(
        f"""<div class="dash-header"><h1>{title}</h1><div class="subtitle">{subtitle}</div></div>""",
        unsafe_allow_html=True,
    )


def kpi_card(label: str, value: str, sub: str = "", color_index: int = 0):
    color = CHART_COLORS[color_index % len(CHART_COLORS)]
    st.markdown(
        f"""
        <div class="kpi-card" style="border-left-color:{color};">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value">{value}</div>
            <div class="kpi-sub">{sub}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def human_format(n) -> str:
    if n is None or pd.isna(n):
        return "—"
    n = float(n)
    sign = "-" if n < 0 else ""
    n = abs(n)
    for unit, div in [("Bn", 1e9), ("M", 1e6), ("K", 1e3)]:
        if n >= div:
            return f"{sign}{n / div:,.1f} {unit}"
    return f"{sign}{n:,.0f}"


# ---------------------------------------------------------------------------
# Supabase client + query helpers
# ---------------------------------------------------------------------------
@st.cache_resource
def get_client():
    cfg = st.secrets["supabase"]
    return create_client(cfg["url"], cfg["anon_key"])


_PAGE_SIZE = 1000


@st.cache_data(ttl=300)
def call_rpc(fn_name: str, params: dict) -> pd.DataFrame:
    """Calls an RPC function, paginating past PostgREST's default 1000-row response cap."""
    client = get_client()
    rows = []
    offset = 0
    while True:
        page = client.rpc(fn_name, params).range(offset, offset + _PAGE_SIZE - 1).execute().data
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return pd.DataFrame(rows)


@st.cache_data(ttl=300)
def call_rpc_scalar(fn_name: str, params: dict):
    """For RPC functions that return a single scalar value (e.g. a row count) rather than a table."""
    client = get_client()
    return client.rpc(fn_name, params).execute().data


@st.cache_data(ttl=300)
def query_table(
    table_name: str,
    select: str = "*",
    filters: dict | None = None,
    in_filters: dict | None = None,
    gte_filters: dict | None = None,
    lte_filters: dict | None = None,
    order: str | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Fetches all matching rows, paginating past PostgREST's default 1000-row cap.

    Equality/range filters are pushed server-side (eq/gte/lte/in_) to keep result sets small —
    several of the xmv_* matviews have tens of thousands of rows and fetching them whole
    before filtering client-side is too slow for interactive use.
    """
    client = get_client()
    rows = []
    offset = 0
    while True:
        page_limit = min(_PAGE_SIZE, limit - len(rows)) if limit else _PAGE_SIZE
        q = client.table(table_name).select(select)
        for col, val in (filters or {}).items():
            q = q.eq(col, val)
        for col, val in (in_filters or {}).items():
            q = q.in_(col, val)
        for col, val in (gte_filters or {}).items():
            q = q.gte(col, val)
        for col, val in (lte_filters or {}).items():
            q = q.lte(col, val)
        if order:
            q = q.order(order)
        q = q.range(offset, offset + page_limit - 1)
        page = q.execute().data
        rows.extend(page)
        if len(page) < page_limit or (limit and len(rows) >= limit):
            break
        offset += page_limit
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def get_filter_options():
    client = get_client()
    commodity_groups = sorted(r["commodity_group"] for r in client.rpc("f_commodity_groups", {}).execute().data)
    bounds = client.rpc("f_date_bounds", {}).execute().data[0]
    return commodity_groups, bounds["min_date"], bounds["max_date"]


def render_global_filters(default_window_days: int = 60):
    commodity_groups, min_date_str, max_date_str = get_filter_options()
    max_date = dt.datetime.fromisoformat(max_date_str.replace("Z", "+00:00")).date()
    min_date = dt.datetime.fromisoformat(min_date_str.replace("Z", "+00:00")).date()
    default_start = max(min_date, max_date - dt.timedelta(days=default_window_days))

    st.sidebar.header("Filters")

    date_range = st.sidebar.date_input(
        "Load date range",
        value=(default_start, max_date),
        min_value=min_date,
        max_value=max_date,
    )
    st.sidebar.caption(
        "Defaults to the last 60 days for speed. The tradeflows table isn't physically "
        "ordered by date, so wider ranges on Region/Port/Vessel/Voyage pages scan more "
        "of the table and can be slow or time out."
    )

    selected_cargo = st.sidebar.multiselect(
        "Cargo type", options=["Dry Bulk", "Liquid Bulk"], default=["Dry Bulk", "Liquid Bulk"]
    )
    selected_commodity_groups = st.sidebar.multiselect(
        "Commodity group", options=commodity_groups, default=[]
    )

    st.session_state["date_range"] = date_range
    st.session_state["cargo_buckets"] = selected_cargo
    st.session_state["commodity_groups"] = selected_commodity_groups


def render_snapshot_year_filter() -> int:
    """Single-year snapshot filter for the matview pages (Home/Country).

    Drives KPIs, pies, and other point-in-time widgets only — trend/line charts always
    show the full history of complete years/months regardless of this selection.
    """
    years_df = query_table("xmv_global_yearly", select="year", order="year")
    years = sorted(years_df["year"].unique().tolist())
    current_calendar_year = dt.date.today().year
    last_full_year = current_calendar_year - 1 if years and years[-1] >= current_calendar_year else (years[-1] if years else current_calendar_year)
    default_year = last_full_year if last_full_year in years else years[-1]

    st.sidebar.header("Filters")
    snapshot_year = st.sidebar.selectbox(
        "Year", options=list(reversed(years)), index=years[::-1].index(default_year),
    )
    st.sidebar.caption("Year filters KPIs and pie/donut charts only. Trend charts always show full history.")

    st.sidebar.divider()
    selected_cargo = st.sidebar.multiselect(
        "Cargo type", options=["Dry Bulk", "Liquid Bulk"], default=["Dry Bulk", "Liquid Bulk"], key="matview_cargo"
    )
    st.session_state["matview_cargo_buckets"] = selected_cargo

    return snapshot_year


def get_filter_params() -> dict:
    date_range = st.session_state.get("date_range")
    if date_range and len(date_range) == 2:
        start, end = date_range
    else:
        start, end = dt.date(2000, 1, 1), dt.date.today()

    return {
        "p_date_from": f"{start}T00:00:00Z",
        "p_date_to": f"{end}T23:59:59Z",
        "p_cargo_buckets": st.session_state.get("cargo_buckets") or None,
        "p_commodity_groups": st.session_state.get("commodity_groups") or None,
    }


def get_matview_cargo_buckets() -> list[str]:
    return st.session_state.get("matview_cargo_buckets") or ["Dry Bulk", "Liquid Bulk"]


def matview_query(table_name: str, year_from: int | None, year_to: int | None, cargo_buckets: list[str] | None = None, **kwargs) -> pd.DataFrame:
    """query_table wrapper that pushes a year-range + cargo_bucket filter server-side.

    Pass year_from=year_to=None to fetch full history (used for trend charts, which ignore
    the snapshot-year filter). Several xmv_* matviews (e.g. xmv_global_ports) have tens of
    thousands of rows; fetching the whole table before filtering client-side means hundreds
    of paginated requests.
    """
    in_filters = dict(kwargs.pop("in_filters", None) or {})
    if cargo_buckets:
        in_filters["cargo_bucket"] = cargo_buckets
    gte_filters = dict(kwargs.pop("gte_filters", None) or {})
    lte_filters = dict(kwargs.pop("lte_filters", None) or {})
    if year_from is not None:
        gte_filters["year"] = year_from
    if year_to is not None:
        lte_filters["year"] = year_to
    return query_table(table_name, in_filters=in_filters, gte_filters=gte_filters, lte_filters=lte_filters, **kwargs)
