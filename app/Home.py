import datetime as dt

import pandas as pd
import plotly.express as px
import streamlit as st

from common import apply_theme, render_header, kpi_card, human_format, matview_query, query_table, render_snapshot_year_filter, get_matview_cargo_buckets
from charts import yoy_bar_chart, yearly_forecast_chart, monthly_forecast_chart, donut_chart, hbar_chart, treemap_chart, sankey_chart

st.set_page_config(page_title="Global Overview | Bulk Cargo Dashboard", layout="wide")
apply_theme()
render_header("🌍 Global Bulk Trade Flows", "Cargo Intelligence — Global Overview")

snapshot_year = render_snapshot_year_filter()
cargo_buckets = get_matview_cargo_buckets()
current_calendar_year = dt.date.today().year


def snapshot(table_name, **kwargs):
    return matview_query(table_name, snapshot_year, snapshot_year, cargo_buckets, **kwargs)


def full_history(table_name, **kwargs):
    return matview_query(table_name, None, None, cargo_buckets, **kwargs)


# ---------------------------------------------------------------------------
# Snapshot-year data (KPIs, insights, donuts, top lists)
# ---------------------------------------------------------------------------
yearly_snap = snapshot("xmv_global_yearly")
countries_snap = snapshot("xmv_global_countries")
ports_snap = snapshot("xmv_global_ports")
commodities_snap = snapshot("xmv_global_commodities")
flows_snap = snapshot("xmv_global_region_flows")

total_volume = yearly_snap["total_volume"].sum()
total_voyages = yearly_snap["voyages"].sum()
dry_volume = yearly_snap[yearly_snap["cargo_bucket"] == "Dry Bulk"]["total_volume"].sum()
liquid_volume = yearly_snap[yearly_snap["cargo_bucket"] == "Liquid Bulk"]["total_volume"].sum()

c1, c2, c3, c4 = st.columns(4)
with c1: kpi_card("Total Volume", human_format(total_volume), f"Snapshot year {snapshot_year}", 0)
with c2: kpi_card("Dry Bulk Volume", human_format(dry_volume), f"Snapshot year {snapshot_year}", 1)
with c3: kpi_card("Liquid Bulk Volume", human_format(liquid_volume), f"Snapshot year {snapshot_year}", 2)
with c4: kpi_card("Total Voyages", human_format(total_voyages), f"Snapshot year {snapshot_year}", 3)

st.write("")

load_countries = countries_snap[countries_snap["direction"] == "load"].groupby("country_short_name", as_index=False)["total_volume"].sum()
disch_countries = countries_snap[countries_snap["direction"] == "discharge"].groupby("country_short_name", as_index=False)["total_volume"].sum()
load_ports = ports_snap[ports_snap["direction"] == "load"].groupby("port_name", as_index=False)["total_volume"].sum()
disch_ports = ports_snap[ports_snap["direction"] == "discharge"].groupby("port_name", as_index=False)["total_volume"].sum()
top_commodity_row = commodities_snap.groupby("commodity_group_short", as_index=False)["total_volume"].sum().sort_values("total_volume", ascending=False)

c5, c6, c7, c8 = st.columns(4)
with c5: kpi_card("Top Commodity", top_commodity_row.iloc[0]["commodity_group_short"] if not top_commodity_row.empty else "—", "", 4)
with c6: kpi_card("Top Load Country", load_countries.sort_values("total_volume", ascending=False).iloc[0]["country_short_name"] if not load_countries.empty else "—", "", 5)
with c7: kpi_card("Top Discharge Country", disch_countries.sort_values("total_volume", ascending=False).iloc[0]["country_short_name"] if not disch_countries.empty else "—", "", 6)
with c8: kpi_card("Top Load Port", load_ports.sort_values("total_volume", ascending=False).iloc[0]["port_name"] if not load_ports.empty else "—", "", 7)

st.write("")

# ---------------------------------------------------------------------------
# Executive insights
# ---------------------------------------------------------------------------
yearly_full = full_history("xmv_global_yearly")
yearly_full = yearly_full[yearly_full["year"] < current_calendar_year]
yearly_full_by_year = yearly_full.groupby("year", as_index=False)["total_volume"].sum().sort_values("year")

yoy_pct = None
if len(yearly_full_by_year) >= 2:
    last_two = yearly_full_by_year.tail(2)["total_volume"].tolist()
    if last_two[0]:
        yoy_pct = (last_two[1] - last_two[0]) / last_two[0] * 100

insight_cols = st.columns(3)
with insight_cols[0]:
    if yoy_pct is not None:
        direction = "up" if yoy_pct >= 0 else "down"
        st.markdown(
            f"<div class='insight-card'><b>Trade Volume Trend</b><br>Global volume (full years) is {direction} "
            f"{abs(yoy_pct):.1f}% year-over-year.</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div class='insight-card'><b>Trade Volume Trend</b><br>Not enough full years of history yet for a YoY comparison.</div>",
            unsafe_allow_html=True,
        )
with insight_cols[1]:
    top_commodity = top_commodity_row.iloc[0]["commodity_group_short"] if not top_commodity_row.empty else "—"
    st.markdown(
        f"<div class='insight-card'><b>Commodity Mix — {snapshot_year}</b><br><b>{top_commodity}</b> is the largest commodity group by volume.</div>",
        unsafe_allow_html=True,
    )
with insight_cols[2]:
    top_flow = flows_snap.groupby(["load_continent", "disch_continent"], as_index=False)["total_volume"].sum().sort_values("total_volume", ascending=False)
    flow_text = f"{top_flow.iloc[0]['load_continent']} → {top_flow.iloc[0]['disch_continent']}" if not top_flow.empty else "—"
    st.markdown(
        f"<div class='insight-card'><b>Busiest Trade Lane — {snapshot_year}</b><br>{flow_text} is the largest region-to-region flow.</div>",
        unsafe_allow_html=True,
    )

st.divider()

# ---------------------------------------------------------------------------
# Trend charts — always full history, ignore the snapshot-year filter
# ---------------------------------------------------------------------------
col1, col2 = st.columns(2)
with col1:
    st.plotly_chart(yoy_bar_chart(yearly_full_by_year, "year", "total_volume", "Annual Volume Trend & YoY % (full years)"), width="stretch")
with col2:
    st.plotly_chart(yearly_forecast_chart(yearly_full_by_year, "year", "total_volume", 7, "Volume Forecast — 7 Years (current year is forecast-only)"), width="stretch")

monthly_full = full_history("xmv_global_monthly")
monthly_full["period"] = pd.to_datetime(dict(year=monthly_full["year"], month=monthly_full["month"], day=1))
current_month_start = dt.date.today().replace(day=1)
monthly_full = monthly_full[monthly_full["period"] < pd.Timestamp(current_month_start)]
monthly_by_period = monthly_full.groupby("period", as_index=False)["total_volume"].sum().sort_values("period")
monthly_last12 = monthly_by_period.tail(12)

col3, col4 = st.columns(2)
with col3:
    st.plotly_chart(yoy_bar_chart(monthly_last12, "period", "total_volume", "Monthly Volume Trend & MoM % (last 12 full months)", pct_label="MoM %"), width="stretch")
with col4:
    st.plotly_chart(monthly_forecast_chart(monthly_by_period, "period", "total_volume", 12, "Volume Forecast — 12 Months (current month is forecast-only)"), width="stretch")

st.divider()

# ---------------------------------------------------------------------------
# Countries & ports (snapshot year)
# ---------------------------------------------------------------------------
col5, col6 = st.columns(2)
with col5:
    st.plotly_chart(donut_chart(load_countries, "country_short_name", "total_volume", f"Top Load Countries — {snapshot_year}"), width="stretch")
with col6:
    st.plotly_chart(donut_chart(disch_countries, "country_short_name", "total_volume", f"Top Discharge Countries — {snapshot_year}"), width="stretch")

col7, col8 = st.columns(2)
with col7:
    st.plotly_chart(hbar_chart(load_ports, "port_name", "total_volume", f"Top 20 Load Ports — {snapshot_year}"), width="stretch")
with col8:
    st.plotly_chart(hbar_chart(disch_ports, "port_name", "total_volume", f"Top 20 Discharge Ports — {snapshot_year}", color="#ef8a17"), width="stretch")

st.divider()

# ---------------------------------------------------------------------------
# Commodity & region hierarchy (snapshot year)
# ---------------------------------------------------------------------------
col9, col10 = st.columns(2)
with col9:
    commodity_tree = commodities_snap.groupby(["cargo_bucket", "commodity_group_short"], as_index=False)["total_volume"].sum()
    st.plotly_chart(treemap_chart(commodity_tree, ["cargo_bucket", "commodity_group_short"], "total_volume", f"Commodity Hierarchy — {snapshot_year}"), width="stretch")
with col10:
    top_commodities10 = commodities_snap.groupby("commodity_group_short", as_index=False)["total_volume"].sum()
    st.plotly_chart(donut_chart(top_commodities10, "commodity_group_short", "total_volume", f"Top Commodity Groups — {snapshot_year}"), width="stretch")

col11, col12 = st.columns(2)
with col11:
    region_tree = countries_snap[countries_snap["direction"] == "load"].groupby(["continent", "country_short_name"], as_index=False)["total_volume"].sum()
    region_tree = region_tree[region_tree["continent"].notna()]
    st.plotly_chart(treemap_chart(region_tree, ["continent", "country_short_name"], "total_volume", f"Geographic Hierarchy — {snapshot_year} (Load)"), width="stretch")
with col12:
    flow_agg = flows_snap.groupby(["load_continent", "disch_continent"], as_index=False)["total_volume"].sum()
    st.plotly_chart(sankey_chart(flow_agg, "load_continent", "disch_continent", "total_volume", f"Load Region → Discharge Region Trade Flows — {snapshot_year}"), width="stretch")

st.divider()
st.subheader(f"Volume by Country (Load) — {snapshot_year}")
fig = px.choropleth(
    load_countries, locations="country_short_name", locationmode="country names", color="total_volume",
    color_continuous_scale="Blues", title=f"Load Volume by Country — {snapshot_year}",
)
st.plotly_chart(fig, width="stretch")
