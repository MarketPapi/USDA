import pandas as pd
import streamlit as st
import plotly.express as px

# Save as: Home.py (main page)
st.set_page_config(layout="wide")
st.title("USDA Dashboard — Overview")

# ---------------- Load ----------------
@st.cache_data
def load_data() -> pd.DataFrame:
    """Load and preprocess USDA data from parquet file."""
    try:
        df = pd.read_parquet("data/latest.parquet", engine="pyarrow")
        df["MarketYear"] = df["MarketYear"].astype(int)

        for c in ["CommodityDescription", "AttributeDescription", "CountryName", "UnitDescription"]:
            df[c] = df[c].astype(str).str.strip()

        return df
    except FileNotFoundError:
        st.error("Data file not found. Please run main.py to generate data/latest.parquet")
        st.stop()
    except Exception as e:
        st.error(f"Error loading data: {e}")
        st.stop()

df = load_data()

# ---------------- Manual World (sum across all countries; exclude USDA World row if present) ----------------
@st.cache_data
def build_manual_world(df_in: pd.DataFrame) -> pd.DataFrame:
    tmp = df_in[df_in["CountryName"].str.lower() != "world"].copy()
    world = (
        tmp.groupby(
            ["MarketYear", "UnitDescription", "CommodityDescription", "AttributeDescription"],
            as_index=False
        )["Value"].sum()
    )
    world["CountryName"] = "World (manual)"
    return world

WORLD = build_manual_world(df)

# ---------------- Helpers ----------------
def top_n_with_others(df_in: pd.DataFrame, name_col: str = "CountryName",
                      value_col: str = "Value", n: int = 10,
                      others_label: str = "Others") -> pd.DataFrame:
    """
    Get top N items by value, grouping the rest as 'Others'.
    
    :param df_in: Input DataFrame
    :param name_col: Column name for grouping
    :param value_col: Column name for values to sum
    :param n: Number of top items to keep
    :param others_label: Label for the 'Others' group
    :return: DataFrame with top N items plus Others
    """
    if df_in.empty:
        return df_in
    d = df_in.groupby(name_col, as_index=False)[value_col].sum().sort_values(value_col, ascending=False)
    top = d.head(n).copy()
    others_sum = d.iloc[n:][value_col].sum()
    if others_sum > 0:
        top = pd.concat([top, pd.DataFrame({name_col: [others_label], value_col: [others_sum]})], ignore_index=True)
    return top

def ensure_int_year_axis(fig) -> object:
    """
    Ensure year axis displays as integers.
    
    :param fig: Plotly figure object
    :return: Updated figure object
    """
    fig.update_xaxes(tickmode="linear", dtick=1, tickformat="d")
    fig.update_layout(legend_title_text="")
    return fig

def default_index(options: list, preferred: str) -> int:
    """
    Get index of preferred option, or 0 if not found.
    
    :param options: List of options
    :param preferred: Preferred option value
    :return: Index of preferred option or 0
    """
    try:
        return options.index(preferred)
    except ValueError:
        return 0

# ---------------- Controls ----------------
c1, c2, c3, c4 = st.columns([1.1, 1.2, 2.4, 2.8])

with c1:
    year_options = sorted(WORLD["MarketYear"].unique())
    year = st.selectbox("Market Year", year_options, index=len(year_options) - 1)

with c2:
    unit_options = sorted(WORLD["UnitDescription"].unique())
    unit = st.selectbox("Unit", unit_options, index=default_index(unit_options, "(1000 MT)"))

with c3:
    product_options = sorted(WORLD["CommodityDescription"].unique())
    product = st.selectbox(
        "Product",
        ["All"] + product_options,
        index=default_index(["All"] + product_options, "Oil, Sunflowerseed")
    )

with c4:
    default_attrs = [a for a in ["Production", "Exports", "Imports", "Ending Stocks", "Total Use"]
                     if a in WORLD["AttributeDescription"].unique()]
    attrs = st.multiselect(
        "Headline attributes",
        sorted(WORLD["AttributeDescription"].unique()),
        default=default_attrs
    )

# Filtered WORLD slice (for KPIs)
w = WORLD[
    (WORLD["MarketYear"] == year) &
    (WORLD["UnitDescription"] == unit) &
    (WORLD["AttributeDescription"].isin(attrs))
].copy()

if product != "All":
    w = w[w["CommodityDescription"] == product]

if w.empty:
    st.warning("No World data for this selection. Try another unit/year/product.")
    st.stop()

# ---------------- KPI Row (manual World) ----------------
st.subheader("World Snapshot")

kpi = w.groupby("AttributeDescription", as_index=False)["Value"].sum()
kcols = st.columns(max(1, len(attrs)))

for i, a in enumerate(attrs):
    v = kpi.loc[kpi["AttributeDescription"] == a, "Value"]
    val = float(v.iloc[0]) if len(v) else 0.0
    kcols[i].metric(a, f"{val:,.0f}")

st.divider()

# ---------------- World table by Product (manual) ----------------
st.subheader("World Totals by Product")

w_table = WORLD[
    (WORLD["MarketYear"] == year) &
    (WORLD["UnitDescription"] == unit) &
    (WORLD["AttributeDescription"].isin(attrs))
].copy()

if product != "All":
    w_table = w_table[w_table["CommodityDescription"] == product]

pivot = (
    w_table.groupby(["CommodityDescription", "AttributeDescription"], as_index=False)["Value"].sum()
           .pivot(index="CommodityDescription", columns="AttributeDescription", values="Value")
           .fillna(0)
)

st.dataframe(pivot.style.format("{:,.0f}"), use_container_width=True)

st.divider()

# ---------------- Charts: Trend + Top countries ----------------
left, right = st.columns([1.35, 1.0])

with left:
    st.subheader("World Trend")

    trend_attrs = [a for a in ["Production", "Exports", "Ending Stocks"] if a in WORLD["AttributeDescription"].unique()]
    trend = WORLD[
        (WORLD["UnitDescription"] == unit) &
        (WORLD["AttributeDescription"].isin(trend_attrs))
    ].copy()

    if product != "All":
        trend = trend[trend["CommodityDescription"] == product]

    trend = trend.groupby(["MarketYear", "AttributeDescription"], as_index=False)["Value"].sum().sort_values("MarketYear")

    fig = px.line(trend, x="MarketYear", y="Value", color="AttributeDescription")
    fig.update_yaxes(title="Value")
    st.plotly_chart(ensure_int_year_axis(fig), use_container_width=True)

with right:
    st.subheader("Top Countries")

    metric_options = [a for a in ["Exports", "Imports", "Production", "Ending Stocks", "Total Use"]
                      if a in df["AttributeDescription"].unique()]
    metric = st.selectbox("Metric", metric_options, index=0)
    topn = st.slider("Top N", 5, 30, 10)

    base = df[
        (df["MarketYear"] == year) &
        (df["UnitDescription"] == unit) &
        (df["AttributeDescription"] == metric) &
        (df["CountryName"].str.lower() != "world")
    ].copy()

    if product != "All":
        base = base[base["CommodityDescription"] == product]

    by_country = base.groupby("CountryName", as_index=False)["Value"].sum()
    by_country = top_n_with_others(by_country, n=topn)

    fig2 = px.bar(by_country, x="CountryName", y="Value")
    fig2.update_layout(xaxis_title="", yaxis_title=f"{metric}", legend_title_text="")
    fig2.update_xaxes(tickangle=-35)
    st.plotly_chart(fig2, use_container_width=True)

st.divider()

# ---------------- Movers table (YoY change) ----------------
st.subheader("Big movers (YoY change)")

m1, m2, m3 = st.columns([1.2, 1.0, 2.0])
with m1:
    mover_metric_options = [a for a in ["Production", "Exports", "Imports", "Ending Stocks", "Total Use"]
                            if a in df["AttributeDescription"].unique()]
    mover_metric = st.selectbox("Mover metric", mover_metric_options, index=0)
with m2:
    movers_n = st.slider("Top N movers", 5, 30, 10)
with m3:
    st.caption("Change = current year − previous year (summed across selected product).")

prev_year = year - 1

cur = df[
    (df["MarketYear"] == year) &
    (df["UnitDescription"] == unit) &
    (df["AttributeDescription"] == mover_metric) &
    (df["CountryName"].str.lower() != "world")
].copy()

prev = df[
    (df["MarketYear"] == prev_year) &
    (df["UnitDescription"] == unit) &
    (df["AttributeDescription"] == mover_metric) &
    (df["CountryName"].str.lower() != "world")
].copy()

if product != "All":
    cur = cur[cur["CommodityDescription"] == product]
    prev = prev[prev["CommodityDescription"] == product]

cur_g = cur.groupby("CountryName", as_index=False)["Value"].sum().rename(columns={"Value": "Value_now"})
prev_g = prev.groupby("CountryName", as_index=False)["Value"].sum().rename(columns={"Value": "Value_prev"})

chg = cur_g.merge(prev_g, on="CountryName", how="left").fillna(0)
chg["Change"] = chg["Value_now"] - chg["Value_prev"]
chg = chg.sort_values("Change", ascending=False).head(movers_n)

st.dataframe(
    chg[["CountryName", "Value_prev", "Value_now", "Change"]]
      .style.format({"Value_prev": "{:,.0f}", "Value_now": "{:,.0f}", "Change": "{:,.0f}"}),
    use_container_width=True
)

st.caption("Use Balance Sheet for country/product balances, and Chart Builder for custom charts.")
