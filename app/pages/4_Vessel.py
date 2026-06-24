import plotly.express as px
import streamlit as st
from common import apply_theme, render_header, call_rpc, render_global_filters, get_filter_params, CARGO_COLORS

st.set_page_config(page_title="Vessel | Bulk Cargo Dashboard", layout="wide")
apply_theme()
render_header("🚢 Vessel Overview", "Cargo Intelligence — Vessel Drilldown")

render_global_filters()
params = get_filter_params()

st.subheader("Fleet Aggregate by Cargo Type")
agg = call_rpc("f_vessel_aggregate", params)
st.dataframe(agg, width="stretch", hide_index=True)

if not agg.empty:
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(
            px.bar(agg, x="vessel_type", y="total_volume", title="Total Volume by Cargo Type",
                   color="vessel_type", color_discrete_map=CARGO_COLORS),
            width="stretch",
        )
    with col2:
        st.plotly_chart(
            px.bar(agg, x="vessel_type", y="avg_distance", title="Avg Distance by Cargo Type",
                   color="vessel_type", color_discrete_map=CARGO_COLORS),
            width="stretch",
        )

st.divider()
st.subheader("Vessel Drilldown")

vessels = call_rpc("f_vessel_options", {**params, "p_limit": 5000})
if not vessels.empty:
    vessels["label"] = vessels["vessel_name"] + " (IMO " + vessels["imo"].astype(str) + ")"
    selected_label = st.selectbox("Vessel", vessels["label"])

    if selected_label:
        selected_imo = int(vessels.loc[vessels["label"] == selected_label, "imo"].iloc[0])
        vessel_params = {"p_imo": selected_imo, **params}

        kpis = call_rpc("f_vessel_kpis", vessel_params)
        if not kpis.empty:
            row = kpis.iloc[0]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Voyages", f"{row['voyages']:,.0f}")
            c2.metric("Total Volume", f"{row['total_volume']:,.0f}")
            c3.metric("Avg Duration (days)", f"{row['avg_duration']:,.1f}")
            c4.metric("Avg Distance (nm)", f"{row['avg_distance']:,.0f}")

        history = call_rpc("f_vessel_history", {**vessel_params, "p_limit": 500})
        st.subheader("Voyage History")
        st.dataframe(history, width="stretch", hide_index=True)
else:
    st.info("No vessels match the current filters.")
