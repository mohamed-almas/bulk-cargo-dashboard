import plotly.express as px
import streamlit as st
from common import apply_theme, call_rpc, render_global_filters, get_filter_params, CARGO_COLORS

st.set_page_config(page_title="Port | Bulk Cargo Dashboard", layout="wide")
apply_theme()
st.title("⚓ Port Overview")

render_global_filters()
params = get_filter_params()

side = st.radio("Side", ["Load", "Discharge"], horizontal=True)
side_key = "load" if side == "Load" else "discharge"

ports_df = call_rpc("f_port_options", {"p_side": side_key})
ports = sorted(ports_df["port"].dropna().tolist()) if not ports_df.empty else []
port = st.selectbox("Port", ports)

if port:
    rpc_params = {"p_port": port, "p_side": side_key, **params}

    summary = call_rpc("f_port_summary", rpc_params)
    if not summary.empty:
        row = summary.iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Voyages", f"{row['voyages']:,.0f}")
        c2.metric("Total Volume", f"{row['total_volume']:,.0f}")
        c3.metric("Avg Days Waiting", f"{row['avg_waiting']:,.2f}")
        c4.metric("Avg Days Berthed", f"{row['avg_berthed']:,.2f}")

    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        trend = call_rpc("f_port_trend", rpc_params)
        if not trend.empty:
            st.plotly_chart(px.line(trend, x="month", y="volume", title="Volume Trend"), width="stretch")

    with col2:
        commodities = call_rpc("f_port_top_commodities", {**rpc_params, "p_limit": 10})
        if not commodities.empty:
            st.plotly_chart(px.bar(commodities, x="commodity_group", y="volume", title="Top Commodities"), width="stretch")

    col3, col4 = st.columns(2)

    with col3:
        counterparts = call_rpc("f_port_counterparts", {**rpc_params, "p_limit": 10})
        st.subheader("Top Counterpart Ports")
        st.dataframe(counterparts, width="stretch", hide_index=True)

    with col4:
        vtype = call_rpc("f_port_vessel_mix", rpc_params)
        if not vtype.empty:
            st.plotly_chart(
                px.pie(vtype, names="vessel_type", values="voyages", title="Cargo Type Mix",
                       color="vessel_type", color_discrete_map=CARGO_COLORS),
                width="stretch",
            )
