import streamlit as st
from common import apply_theme, render_header, call_rpc, call_rpc_scalar, render_global_filters, get_filter_params

st.set_page_config(page_title="Voyage | Bulk Cargo Dashboard", layout="wide")
apply_theme()
render_header("📋 Voyage Detail", "Cargo Intelligence — Voyage Search")

render_global_filters()
params = get_filter_params()

col1, col2, col3 = st.columns(3)
with col1:
    voyage_id_search = st.text_input("Voyage ID contains")
with col2:
    load_port_search = st.text_input("Load port contains")
with col3:
    discharge_port_search = st.text_input("Discharge port contains")

search_params = {
    **params,
    "p_voyage_id_like": voyage_id_search,
    "p_load_port_like": load_port_search,
    "p_discharge_port_like": discharge_port_search,
}

total = call_rpc_scalar("f_voyage_count", search_params) or 0
st.caption(f"{total:,} voyages match current filters")

page_size = 100
max_page = max(1, (total - 1) // page_size + 1) if total else 1
page = st.number_input("Page", min_value=1, max_value=int(max_page), value=1, step=1)
offset = (page - 1) * page_size

rows = call_rpc("f_voyage_search", {**search_params, "p_limit": page_size, "p_offset": offset})
st.dataframe(rows, width="stretch", hide_index=True)

st.divider()
st.subheader("Single Voyage Lookup")
voyage_id = st.text_input("Exact Voyage ID")
if voyage_id:
    detail = call_rpc("f_voyage_detail", {"p_voyage_id": voyage_id})
    if detail.empty:
        st.warning("No voyage found with that ID.")
    else:
        st.dataframe(detail.T, width="stretch")
