import datetime as dt

import pandas as pd
import streamlit as st

from common import apply_theme, render_header, kpi_card, human_format, query_table, matview_query, render_snapshot_year_filter, get_matview_cargo_buckets
from charts import yoy_bar_chart, yearly_forecast_chart, monthly_forecast_chart, donut_chart

st.set_page_config(page_title="Country | Bulk Cargo Dashboard", layout="wide")
apply_theme()
render_header("🏳️ Country Trade Overview", "Cargo Intelligence — Country Drilldown")

snapshot_year = render_snapshot_year_filter()
cargo_buckets = get_matview_cargo_buckets()
current_calendar_year = dt.date.today().year

countries = sorted(query_table("xmv_country_list", select="country_short_name")["country_short_name"].dropna().unique())
country = st.selectbox("Country", countries)


def snapshot(table_name, **kwargs):
    filters = dict(kwargs.pop("filters", None) or {})
    filters["country_short_name"] = country
    return matview_query(table_name, snapshot_year, snapshot_year, cargo_buckets, filters=filters, **kwargs)


def full_history(table_name, **kwargs):
    filters = dict(kwargs.pop("filters", None) or {})
    filters["country_short_name"] = country
    return matview_query(table_name, None, None, cargo_buckets, filters=filters, **kwargs)


yearly_snap = snapshot("xmv_country_yearly")
load_snap = yearly_snap[yearly_snap["direction"] == "load"]
disch_snap = yearly_snap[yearly_snap["direction"] == "discharge"]

total_load = load_snap["total_volume"].sum()
total_disch = disch_snap["total_volume"].sum()
total_volume = total_load + total_disch

c1, c2, c3, c4 = st.columns(4)
with c1: kpi_card("Total Volume", human_format(total_volume), f"Snapshot year {snapshot_year}", 0)
with c2: kpi_card("Load Volume", human_format(total_load), f"Snapshot year {snapshot_year}", 1)
with c3: kpi_card("Discharge Volume", human_format(total_disch), f"Snapshot year {snapshot_year}", 2)
with c4: kpi_card("Total Voyages", human_format(yearly_snap["voyages"].sum()), f"Snapshot year {snapshot_year}", 3)

st.write("")
balance = "Net Exporter" if total_load > total_disch else "Net Importer"
st.markdown(
    f"<div class='insight-card'><b>Trade Balance — {country} ({snapshot_year})</b><br>{country} is a "
    f"<b>{balance}</b> of bulk commodities (Load {human_format(total_load)} vs Discharge {human_format(total_disch)}).</div>",
    unsafe_allow_html=True,
)

st.divider()
col1, col2 = st.columns(2)

with col1:
    monthly_full = full_history("xmv_country_monthly")
    monthly_full["period"] = pd.to_datetime(dict(year=monthly_full["year"], month=monthly_full["month"], day=1))
    current_month_start = dt.date.today().replace(day=1)
    monthly_full = monthly_full[monthly_full["period"] < pd.Timestamp(current_month_start)]
    monthly_by_period = monthly_full.groupby("period", as_index=False)["total_volume"].sum().sort_values("period")
    monthly_last12 = monthly_by_period.tail(12)
    st.plotly_chart(yoy_bar_chart(monthly_last12, "period", "total_volume", "Monthly Volume Trend & MoM % (last 12 full months)", pct_label="MoM %"), width="stretch")

with col2:
    yearly_full = full_history("xmv_country_yearly")
    yearly_full = yearly_full[yearly_full["year"] < current_calendar_year]
    yearly_full_by_year = yearly_full.groupby("year", as_index=False)["total_volume"].sum().sort_values("year")
    st.plotly_chart(yearly_forecast_chart(yearly_full_by_year, "year", "total_volume", 7, "Volume Forecast — 7 Years (current year is forecast-only)"), width="stretch")

st.divider()
col3, col4 = st.columns(2)

with col3:
    ports = snapshot("xmv_country_top_ports")
    load_ports = ports[ports["direction"] == "load"].groupby("port_name", as_index=False)["total_volume"].sum()
    st.plotly_chart(donut_chart(load_ports, "port_name", "total_volume", f"Top Load Ports — {country} ({snapshot_year})"), width="stretch")

with col4:
    disch_ports = ports[ports["direction"] == "discharge"].groupby("port_name", as_index=False)["total_volume"].sum()
    st.plotly_chart(donut_chart(disch_ports, "port_name", "total_volume", f"Top Discharge Ports — {country} ({snapshot_year})"), width="stretch")

col5, col6 = st.columns(2)
with col5:
    partners = snapshot("xmv_country_top_partners")
    load_partners = partners[partners["direction"] == "load"].groupby("partner_country_short_name", as_index=False)["total_volume"].sum()
    st.plotly_chart(donut_chart(load_partners, "partner_country_short_name", "total_volume", f"Top Discharge Partners (from {country}) — {snapshot_year}"), width="stretch")

with col6:
    disch_partners = partners[partners["direction"] == "discharge"].groupby("partner_country_short_name", as_index=False)["total_volume"].sum()
    st.plotly_chart(donut_chart(disch_partners, "partner_country_short_name", "total_volume", f"Top Load Partners (into {country}) — {snapshot_year}"), width="stretch")

st.divider()
st.subheader(f"Commodity Breakdown — {snapshot_year}")
commodities = snapshot("xmv_country_top_commodities")

col7, col8 = st.columns(2)
with col7:
    load_commodities = commodities[commodities["direction"] == "load"].groupby("commodity_group_short", as_index=False)["total_volume"].sum()
    st.plotly_chart(donut_chart(load_commodities, "commodity_group_short", "total_volume", f"Top Load Commodities — {country} ({snapshot_year})"), width="stretch")
with col8:
    disch_commodities = commodities[commodities["direction"] == "discharge"].groupby("commodity_group_short", as_index=False)["total_volume"].sum()
    st.plotly_chart(donut_chart(disch_commodities, "commodity_group_short", "total_volume", f"Top Discharge Commodities — {country} ({snapshot_year})"), width="stretch")
