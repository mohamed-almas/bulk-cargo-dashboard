import pandas as pd
import streamlit as st

from common import apply_theme, human_format, query_table, matview_query, render_year_filter, get_matview_cargo_buckets
from charts import yoy_bar_chart, simple_forecast_chart, donut_chart

st.set_page_config(page_title="Country | Bulk Cargo Dashboard", layout="wide")
apply_theme()
st.title("🏳️ Country Trade Overview")

year_from, year_to = render_year_filter()
cargo_buckets = get_matview_cargo_buckets()

countries = sorted(query_table("xmv_country_list", select="country_short_name")["country_short_name"].dropna().unique())
country = st.selectbox("Country", countries)


def mv(table_name, **kwargs):
    filters = dict(kwargs.pop("filters", None) or {})
    filters["country_short_name"] = country
    return matview_query(table_name, year_from, year_to, cargo_buckets, filters=filters, **kwargs)


yearly = mv("xmv_country_yearly")
load_yearly = yearly[yearly["direction"] == "load"]
disch_yearly = yearly[yearly["direction"] == "discharge"]

total_load = load_yearly["total_volume"].sum()
total_disch = disch_yearly["total_volume"].sum()
total_volume = total_load + total_disch

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Volume", human_format(total_volume))
c2.metric("Load Volume", human_format(total_load))
c3.metric("Discharge Volume", human_format(total_disch))
c4.metric("Total Voyages", human_format(yearly["voyages"].sum()))

balance = "Net Exporter" if total_load > total_disch else "Net Importer"
st.markdown(
    f"<div class='insight-card'><b>Trade Balance — {country}</b><br>{country} is a "
    f"<b>{balance}</b> of bulk commodities (Load {human_format(total_load)} vs Discharge {human_format(total_disch)}).</div>",
    unsafe_allow_html=True,
)

st.divider()
col1, col2 = st.columns(2)

with col1:
    monthly = mv("xmv_country_monthly")
    monthly["period"] = pd.to_datetime(dict(year=monthly["year"], month=monthly["month"], day=1))
    monthly_by_period = monthly.groupby("period", as_index=False)["total_volume"].sum().sort_values("period")
    st.plotly_chart(yoy_bar_chart(monthly_by_period.tail(13), "period", "total_volume", "Monthly Volume Trend & MoM %"), width="stretch")

with col2:
    yearly_by_year = yearly.groupby("year", as_index=False)["total_volume"].sum()
    st.plotly_chart(simple_forecast_chart(yearly_by_year, "year", "total_volume", 3, "Volume Projection (simple linear trend)"), width="stretch")

st.divider()
col3, col4 = st.columns(2)

with col3:
    ports = mv("xmv_country_top_ports")
    load_ports = ports[ports["direction"] == "load"].groupby("port_name", as_index=False)["total_volume"].sum()
    st.plotly_chart(donut_chart(load_ports, "port_name", "total_volume", f"Top Load Ports — {country}"), width="stretch")

with col4:
    disch_ports = ports[ports["direction"] == "discharge"].groupby("port_name", as_index=False)["total_volume"].sum()
    st.plotly_chart(donut_chart(disch_ports, "port_name", "total_volume", f"Top Discharge Ports — {country}"), width="stretch")

col5, col6 = st.columns(2)
with col5:
    partners = mv("xmv_country_top_partners")
    load_partners = partners[partners["direction"] == "load"].groupby("partner_country_short_name", as_index=False)["total_volume"].sum()
    st.plotly_chart(donut_chart(load_partners, "partner_country_short_name", "total_volume", f"Top Discharge Partners (from {country})"), width="stretch")

with col6:
    disch_partners = partners[partners["direction"] == "discharge"].groupby("partner_country_short_name", as_index=False)["total_volume"].sum()
    st.plotly_chart(donut_chart(disch_partners, "partner_country_short_name", "total_volume", f"Top Load Partners (into {country})"), width="stretch")

st.divider()
st.subheader("Commodity Breakdown")
commodities = mv("xmv_country_top_commodities")

col7, col8 = st.columns(2)
with col7:
    load_commodities = commodities[commodities["direction"] == "load"].groupby("commodity_group", as_index=False)["total_volume"].sum()
    st.plotly_chart(donut_chart(load_commodities, "commodity_group", "total_volume", f"Top Load Commodities — {country}"), width="stretch")
with col8:
    disch_commodities = commodities[commodities["direction"] == "discharge"].groupby("commodity_group", as_index=False)["total_volume"].sum()
    st.plotly_chart(donut_chart(disch_commodities, "commodity_group", "total_volume", f"Top Discharge Commodities — {country}"), width="stretch")
