import pandas as pd
import plotly.express as px
import streamlit as st

from common import apply_theme, human_format, matview_query, render_year_filter, get_matview_cargo_buckets
from charts import yoy_bar_chart, simple_forecast_chart, donut_chart, hbar_chart, treemap_chart, sankey_chart

st.set_page_config(page_title="Global Overview | Bulk Cargo Dashboard", layout="wide")
apply_theme()
st.title("🌍 Global Bulk Trade Flows")
st.caption("Cargo Intelligence — Global Overview")

year_from, year_to = render_year_filter()
cargo_buckets = get_matview_cargo_buckets()


def mv(table_name, **kwargs):
    return matview_query(table_name, year_from, year_to, cargo_buckets, **kwargs)


yearly = mv("xmv_global_yearly")
yearly_by_year = yearly.groupby("year", as_index=False)["total_volume"].sum()
yearly_by_year["voyages"] = yearly.groupby("year")["voyages"].sum().values

monthly = mv("xmv_global_monthly")
monthly["period"] = pd.to_datetime(dict(year=monthly["year"], month=monthly["month"], day=1))
monthly_by_period = monthly.groupby("period", as_index=False)["total_volume"].sum().sort_values("period")

countries = mv("xmv_global_countries")
ports = mv("xmv_global_ports")
commodities = mv("xmv_global_commodities")
flows = mv("xmv_global_region_flows")

# ---------------------------------------------------------------------------
# KPI row
# ---------------------------------------------------------------------------
total_volume = yearly_by_year["total_volume"].sum()
total_voyages = yearly_by_year["voyages"].sum()
dry_volume = yearly[yearly["cargo_bucket"] == "Dry Bulk"]["total_volume"].sum()
liquid_volume = yearly[yearly["cargo_bucket"] == "Liquid Bulk"]["total_volume"].sum()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Volume", human_format(total_volume))
c2.metric("Dry Bulk Volume", human_format(dry_volume))
c3.metric("Liquid Bulk Volume", human_format(liquid_volume))
c4.metric("Total Voyages", human_format(total_voyages))

load_countries = countries[countries["direction"] == "load"].groupby("country_short_name", as_index=False)["total_volume"].sum()
disch_countries = countries[countries["direction"] == "discharge"].groupby("country_short_name", as_index=False)["total_volume"].sum()
load_ports = ports[ports["direction"] == "load"].groupby("port_name", as_index=False)["total_volume"].sum()
disch_ports = ports[ports["direction"] == "discharge"].groupby("port_name", as_index=False)["total_volume"].sum()
top_commodity_row = commodities.groupby("commodity_group", as_index=False)["total_volume"].sum().sort_values("total_volume", ascending=False)

c5, c6, c7, c8 = st.columns(4)
c5.metric("Top Commodity", top_commodity_row.iloc[0]["commodity_group"] if not top_commodity_row.empty else "—")
c6.metric("Top Load Country", load_countries.sort_values("total_volume", ascending=False).iloc[0]["country_short_name"] if not load_countries.empty else "—")
c7.metric("Top Discharge Country", disch_countries.sort_values("total_volume", ascending=False).iloc[0]["country_short_name"] if not disch_countries.empty else "—")
c8.metric("Top Load Port", load_ports.sort_values("total_volume", ascending=False).iloc[0]["port_name"] if not load_ports.empty else "—")

# ---------------------------------------------------------------------------
# Executive insights
# ---------------------------------------------------------------------------
yoy_pct = None
if len(yearly_by_year) >= 2:
    last_two = yearly_by_year.sort_values("year").tail(2)["total_volume"].tolist()
    if last_two[0]:
        yoy_pct = (last_two[1] - last_two[0]) / last_two[0] * 100

insight_cols = st.columns(3)
with insight_cols[0]:
    if yoy_pct is not None:
        direction = "up" if yoy_pct >= 0 else "down"
        st.markdown(
            f"<div class='insight-card'><b>Trade Volume Trend</b><br>Global volume is {direction} "
            f"{abs(yoy_pct):.1f}% year-over-year.</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div class='insight-card'><b>Trade Volume Trend</b><br>Not enough years selected for a YoY comparison.</div>",
            unsafe_allow_html=True,
        )
with insight_cols[1]:
    top_commodity = top_commodity_row.iloc[0]["commodity_group"] if not top_commodity_row.empty else "—"
    st.markdown(
        f"<div class='insight-card'><b>Commodity Mix</b><br><b>{top_commodity}</b> is the largest commodity group by volume.</div>",
        unsafe_allow_html=True,
    )
with insight_cols[2]:
    top_flow = flows.groupby(["load_continent", "disch_continent"], as_index=False)["total_volume"].sum().sort_values("total_volume", ascending=False)
    flow_text = f"{top_flow.iloc[0]['load_continent']} → {top_flow.iloc[0]['disch_continent']}" if not top_flow.empty else "—"
    st.markdown(
        f"<div class='insight-card'><b>Busiest Trade Lane</b><br>{flow_text} is the largest region-to-region flow.</div>",
        unsafe_allow_html=True,
    )

st.divider()

# ---------------------------------------------------------------------------
# Trend charts
# ---------------------------------------------------------------------------
col1, col2 = st.columns(2)
with col1:
    st.plotly_chart(yoy_bar_chart(yearly_by_year, "year", "total_volume", "Annual Volume Trend & YoY %"), width="stretch")
with col2:
    st.plotly_chart(simple_forecast_chart(yearly_by_year, "year", "total_volume", 3, "Volume Projection (simple linear trend, not a statistical forecast)"), width="stretch")

col3, col4 = st.columns(2)
with col3:
    st.plotly_chart(yoy_bar_chart(monthly_by_period.tail(13), "period", "total_volume", "Monthly Volume Trend & MoM %"), width="stretch")
with col4:
    seasonal = monthly.groupby("month", as_index=False)["total_volume"].mean()
    fig = px.bar(seasonal, x="month", y="total_volume", title="Average Seasonal Pattern (avg volume by calendar month)")
    st.plotly_chart(fig, width="stretch")

st.divider()

# ---------------------------------------------------------------------------
# Countries & ports
# ---------------------------------------------------------------------------
col5, col6 = st.columns(2)
with col5:
    st.plotly_chart(donut_chart(load_countries, "country_short_name", "total_volume", "Top Load Countries"), width="stretch")
with col6:
    st.plotly_chart(donut_chart(disch_countries, "country_short_name", "total_volume", "Top Discharge Countries"), width="stretch")

col7, col8 = st.columns(2)
with col7:
    st.plotly_chart(hbar_chart(load_ports, "port_name", "total_volume", "Top 20 Load Ports"), width="stretch")
with col8:
    st.plotly_chart(hbar_chart(disch_ports, "port_name", "total_volume", "Top 20 Discharge Ports", color="#ef8a17"), width="stretch")

st.divider()

# ---------------------------------------------------------------------------
# Commodity & region hierarchy
# ---------------------------------------------------------------------------
col9, col10 = st.columns(2)
with col9:
    commodity_tree = commodities.groupby(["cargo_bucket", "commodity_group"], as_index=False)["total_volume"].sum()
    st.plotly_chart(treemap_chart(commodity_tree, ["cargo_bucket", "commodity_group"], "total_volume", "Commodity Hierarchy (Cargo Type → Group)"), width="stretch")
with col10:
    top_commodities10 = commodities.groupby("commodity_group", as_index=False)["total_volume"].sum()
    st.plotly_chart(donut_chart(top_commodities10, "commodity_group", "total_volume", "Top 10 Commodity Groups"), width="stretch")

col11, col12 = st.columns(2)
with col11:
    region_tree = countries[countries["direction"] == "load"].groupby(["continent", "country_short_name"], as_index=False)["total_volume"].sum()
    region_tree = region_tree[region_tree["continent"].notna()]
    st.plotly_chart(treemap_chart(region_tree, ["continent", "country_short_name"], "total_volume", "Geographic Hierarchy (Region → Country, Load)"), width="stretch")
with col12:
    flow_agg = flows.groupby(["load_continent", "disch_continent"], as_index=False)["total_volume"].sum()
    st.plotly_chart(sankey_chart(flow_agg, "load_continent", "disch_continent", "total_volume", "Load Region → Discharge Region Trade Flows"), width="stretch")

st.divider()
st.subheader("Volume by Country (Load)")
fig = px.choropleth(
    load_countries, locations="country_short_name", locationmode="country names", color="total_volume",
    color_continuous_scale="Blues", title="Load Volume by Country",
)
st.plotly_chart(fig, width="stretch")
