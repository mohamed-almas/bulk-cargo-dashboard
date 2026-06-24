import plotly.express as px
import streamlit as st
from common import apply_theme, call_rpc, render_global_filters, get_filter_params, CARGO_COLORS

st.set_page_config(page_title="Region | Bulk Cargo Dashboard", layout="wide")
apply_theme()
st.title("🗺️ Region Overview")
st.caption("Region = continent of the load or discharge port")

render_global_filters()
params = get_filter_params()

side = st.radio("Side", ["Load", "Discharge"], horizontal=True)
side_key = "load" if side == "Load" else "discharge"

regions_df = call_rpc("f_region_options", {"p_side": side_key})
regions = sorted(regions_df["region"].dropna().tolist()) if not regions_df.empty else []
region = st.selectbox("Region", regions)

if region:
    rpc_params = {"p_region": region, "p_side": side_key, **params}

    summary = call_rpc("f_region_summary", rpc_params)
    if not summary.empty:
        row = summary.iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.metric("Voyages", f"{row['voyages']:,.0f}")
        c2.metric("Total Volume", f"{row['total_volume']:,.0f}")
        c3.metric("Distinct Vessels", f"{row['vessels']:,.0f}")

    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        trend = call_rpc("f_region_trend", rpc_params)
        if not trend.empty:
            st.plotly_chart(px.line(trend, x="month", y="volume", title="Volume Trend"), width="stretch")

    with col2:
        vtype = call_rpc("f_region_vessel_mix", rpc_params)
        if not vtype.empty:
            st.plotly_chart(
                px.pie(vtype, names="vessel_type", values="voyages", title="Cargo Type Mix",
                       color="vessel_type", color_discrete_map=CARGO_COLORS),
                width="stretch",
            )

    col3, col4 = st.columns(2)

    with col3:
        countries = call_rpc("f_region_top_countries", {**rpc_params, "p_limit": 10})
        st.subheader("Top Countries")
        st.dataframe(countries, width="stretch", hide_index=True)

    with col4:
        ports = call_rpc("f_region_top_ports", {**rpc_params, "p_limit": 10})
        st.subheader("Top Ports")
        st.dataframe(ports, width="stretch", hide_index=True)
