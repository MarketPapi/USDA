"""USDA Dashboard — contents page with links to Balance Sheet, Chart Builder, Map, and Data Status."""
import streamlit as st

st.set_page_config(layout="wide", page_title="USDA Dashboard")
st.title("USDA Dashboard")
st.markdown("Explore PSD data with the pages below. You can also use the **sidebar** to switch pages.")

st.divider()

# Contents with descriptions and links
PAGES = [
    ("pages/Balance_Sheet.py", "Balance Sheet", "Country and product balance sheets: production, exports, imports, ending stocks, and total use by market year."),
    ("pages/Chart_Builder.py", "Chart Builder", "Build custom charts from the balance sheet mart: time series, bar charts, and comparisons by commodity, country, or attribute."),
    ("pages/Map.py", "Map", "World map view of PSD data by country (GENC codes). Filter by commodity, attribute, unit, and animate by market year."),
    ("pages/Status.py", "Data Status", "Track when parquets were last updated, pipeline run status, and checks for missing files or stale data."),
]

for page_path, label, description in PAGES:
    st.page_link(page_path, label=f"**{label}**")
    st.caption(description)
    st.write("")
