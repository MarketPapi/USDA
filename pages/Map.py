"""World map of PSD data by country (GENC); filter by commodity/attribute/unit, animate by market year."""
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(layout="wide")
st.title("World Map")


@st.cache_data
def load_map_mart() -> pd.DataFrame:
    df = pd.read_parquet("data/marts/mart_map.parquet")

    for c in ["commodityName", "attributeName", "unit_clean", "countryName", "gencCode"]:
        if c in df.columns:
            df[c] = df[c].astype("string").str.strip()

    if "gencCode" in df.columns:
        df["gencCode"] = df["gencCode"].astype("string").str.upper()

    if "marketYear" in df.columns:
        df["marketYear"] = pd.to_numeric(df["marketYear"], errors="coerce").astype("Int64")

    if "value" in df.columns:
        df["value"] = pd.to_numeric(df["value"], errors="coerce").astype("float64")

    return df


df = load_map_mart()

required = {"commodityName", "marketYear", "attributeName", "unit_clean", "gencCode", "value"}
missing = required - set(df.columns)
if missing:
    st.error(
        f"mart_map.parquet is missing required columns: {sorted(missing)}.\n"
        f"Available columns: {sorted(df.columns)}\n\n"
        f"To fix: Rebuild the mart by running `python main.py` or clear Streamlit cache."
    )
    with st.expander("Debug Info"):
        st.write(f"DataFrame shape: {df.shape}")
        st.write(f"Columns: {list(df.columns)}")
        st.dataframe(df.head() if len(df) > 0 else pd.DataFrame())

    if st.button("Clear cache and reload"):
        st.cache_data.clear()
        st.rerun()
    st.stop()

# Keep only ISO-3 looking codes
df = df[df["gencCode"].notna()].copy()
df = df[df["gencCode"].str.match(r"^[A-Z]{3}$", na=False)].copy()


def default_index(options: list, preferred: str) -> int:
    try:
        return options.index(preferred)
    except ValueError:
        return 0


# =========================
# Filters (no "Filters" title)
# =========================
col1, col2, col3 = st.columns([2, 2, 1.5])

commodity_options = sorted(df["commodityName"].dropna().unique().tolist())
default_commodity_idx = (
    default_index(commodity_options, "Oil, Sunflowerseed") if "Oil, Sunflowerseed" in commodity_options else 0
)
with col1:
    commodity = st.selectbox("Commodity", commodity_options, index=default_commodity_idx, key="map_commodity")

df_c = df[df["commodityName"] == commodity].copy()
if df_c.empty:
    st.warning("No data for this commodity.")
    st.stop()

attr_options = sorted(df_c["attributeName"].dropna().unique().tolist())
default_attr_idx = default_index(attr_options, "Production") if "Production" in attr_options else 0
with col2:
    attribute = st.selectbox("Attribute", attr_options, index=default_attr_idx, key="map_attribute")

df_a = df_c[df_c["attributeName"] == attribute].copy()
if df_a.empty:
    st.warning("No data for this attribute.")
    st.stop()

unit_options = sorted(df_a["unit_clean"].dropna().unique().tolist())
with col3:
    unit = st.selectbox(
        "Unit",
        unit_options,
        index=unit_options.index("1000 MT") if "1000 MT" in unit_options else 0,
        key="map_unit",
    )

df_u = df_a[df_a["unit_clean"] == unit].copy()
if df_u.empty:
    st.warning("No data for this unit.")
    st.stop()

# =========================
# Animation dataset (all years, chronological)
# =========================
df_anim = df_u.copy()
df_anim = df_anim[df_anim["marketYear"].notna()].copy()
df_anim = df_anim[df_anim["value"].notna()].copy()
df_anim = df_anim[df_anim["value"] > 0].copy()

if df_anim.empty:
    st.warning("No positive values to display for these filters.")
    st.stop()

df_anim["marketYear"] = df_anim["marketYear"].astype(int)
df_anim = df_anim.sort_values("marketYear").copy()

years = sorted(df_anim["marketYear"].unique().tolist())
latest_year = max(years)
latest_idx = years.index(latest_year)

# Log scaling ONLY for size
df_anim["value_for_size"] = np.log10(df_anim["value"].clip(lower=1))

# Raw value color bounds (legend in real units)
vmin = float(df_anim["value"].min())
vmax = float(df_anim["value"].max())

# Stronger blue gradient (avoid near-white so it doesn't blend into land)
BLUE_STRONG = ["#6baed6", "#3182bd", "#08519c", "#08306b"]

MAP_HEIGHT = 820
transparent = "rgba(0,0,0,0)"

st.markdown(f"### {commodity} — {attribute} ({unit})")

# =========================
# Create Plotly Express animated map (keeps original Play/Pause styling)
# =========================
fig = px.scatter_geo(
    df_anim,
    locations="gencCode",
    locationmode="ISO-3",
    size="value_for_size",                 # log-size only
    color="value",                         # raw value for legend
    color_continuous_scale=BLUE_STRONG,
    range_color=(vmin, vmax),
    hover_name="countryName",
    hover_data={
        "gencCode": False,
        "value": ":,.0f",
        "unit_clean": True,
        "marketYear": True,
        "value_for_size": False,
    },
    labels={
        "value":f"{attribute}",
        "marketYear":"Marketing Year",
        "unit_clean":"Unit"
    },
    animation_frame="marketYear",
    projection="natural earth",
    basemap_visible=True,
    size_max=45,
)

# Make circles stand out more (ring + a bit more contrast)
fig.update_traces(
    marker=dict(
        opacity=0.9,
        line=dict(color="#08306b", width=1.2),  # darker outline so light blues pop
    )
)

# Transparent area between globe and rectangle + tight margins
fig.update_layout(
    title_text="",  # prevents the "undefined" artifact
    height=MAP_HEIGHT,
    margin=dict(l=0, r=0, t=10, b=0),
    paper_bgcolor=transparent,
    plot_bgcolor=transparent,
    coloraxis_colorbar=dict(
        title=f"Value ({unit})",
        ticks="outside",
        tickformat=",.0f",
    ),
)

fig.update_geos(
    scope="world",
    bgcolor=transparent,
    showland=True,
    landcolor="#f0f0f0",   # slightly darker so light circles are still visible
    showcountries=True,
    countrycolor="#d0d0d0",
    showocean=True,
    oceancolor="white",
    showcoastlines=False,
)

# =========================
# Keep years chronological BUT load the latest year by default
# (swap the base trace to the latest frame, without reordering frames/years)
# =========================
if fig.frames and len(fig.frames) > latest_idx and len(fig.data) > 0:
    latest_frame_trace = fig.frames[latest_idx].data[0]
    fig.data[0].update(latest_frame_trace)

# Move slider above the map (inside the figure) + set active to latest year
if fig.layout.sliders and len(fig.layout.sliders) > 0:
    fig.layout.sliders[0].update(
        active=latest_idx,     # chronological slider, latest selected
        y=1.10,
        x=0.12,
        len=0.86,
        xanchor="left",
        yanchor="top",
        pad=dict(t=0, b=0),
        currentvalue=dict(prefix="Year: ", font=dict(size=14)),
    )

# Move the default Plotly Express Play/Pause buttons above the map (keep original styling)
if fig.layout.updatemenus and len(fig.layout.updatemenus) > 0:
    for um in fig.layout.updatemenus:
        um.update(
            y=1.10,
            x=0.0,
            xanchor="left",
            yanchor="top",
        )

st.plotly_chart(fig, use_container_width=True)
