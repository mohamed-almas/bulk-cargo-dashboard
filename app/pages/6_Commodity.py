import plotly.express as px
import streamlit as st

from common import apply_theme, call_rpc, query_table, render_global_filters, get_filter_params
from charts import donut_chart, hbar_chart

st.set_page_config(page_title="Commodity | Bulk Cargo Dashboard", layout="wide")
apply_theme()
st.title("📦 Commodity Analysis")

render_global_filters()
params = get_filter_params()

commodity_groups = sorted(query_table("ml_bulk_commodities", select="commodity_group")["commodity_group"].dropna().unique())
commodity = st.selectbox("Commodity Group", commodity_groups)

side = st.radio("Side", ["Load", "Discharge"], horizontal=True)
side_key = "load" if side == "Load" else "discharge"

if commodity:
    commodity_params = {
        "p_commodity_group": commodity,
        "p_date_from": params["p_date_from"],
        "p_date_to": params["p_date_to"],
        "p_cargo_buckets": params["p_cargo_buckets"],
    }

    summary = call_rpc("f_commodity_summary", commodity_params)
    if not summary.empty:
        row = summary.iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.metric("Voyages", f"{row['voyages']:,.0f}")
        c2.metric("Total Volume", f"{row['total_volume']:,.0f}")
        c3.metric("Distinct Vessels", f"{row['vessels']:,.0f}")

    st.divider()
    trend = call_rpc("f_commodity_trend", commodity_params)
    if not trend.empty:
        st.plotly_chart(px.line(trend, x="month", y="volume", title=f"{commodity} — Volume Trend"), width="stretch")

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        countries = call_rpc("f_commodity_top_countries", {**commodity_params, "p_side": side_key, "p_limit": 10})
        if not countries.empty:
            st.plotly_chart(donut_chart(countries, "country", "volume", f"Top {side} Countries — {commodity}"), width="stretch")
    with col2:
        ports = call_rpc("f_commodity_top_ports", {**commodity_params, "p_side": side_key, "p_limit": 15})
        if not ports.empty:
            st.plotly_chart(hbar_chart(ports, "port", "volume", f"Top {side} Ports — {commodity}"), width="stretch")
