import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(layout="wide")
st.title("Country Balance Sheet")

@st.cache_data
def load_data() -> pd.DataFrame:
    """Load and preprocess USDA data."""
    try:
        df = pd.read_parquet("data/latest.parquet")
        # Ensure string columns are properly typed and stripped
        df["CommodityDescription"] = df["CommodityDescription"].astype(str).str.strip()
        df["UnitDescription"] = df["UnitDescription"].astype(str).str.strip()
        df["ProductType"] = df["CommodityDescription"].str.split(",").str[0].str.strip()
        df["MarketYear"] = df["MarketYear"].astype(int)
        return df
    except FileNotFoundError:
        st.error("Data file not found. Please run main.py to generate data/latest.parquet")
        st.stop()
    except Exception as e:
        st.error(f"Error loading data: {e}")
        st.stop()

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
    
    df2 = df_in.groupby(name_col, as_index=False)[value_col].sum()
    df2 = df2.sort_values(value_col, ascending=False)

    top = df2.head(n).copy()
    others_sum = df2.iloc[n:][value_col].sum()

    if others_sum > 0:
        top = pd.concat(
            [top, pd.DataFrame({name_col: [others_label], value_col: [others_sum]})],
            ignore_index=True
        )
    return top

df = load_data()

# ---------------- Filters ----------------
c1, c2, c3 = st.columns(3)

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

country_options = sorted(df["CountryName"].unique())
ptype_options = sorted(df["ProductType"].unique())

with c1:
    country = st.selectbox(
        "Country",
        country_options,
        index=default_index(country_options, "Russia"),
        key="f_country"
    )

with c2:
    ptype = st.selectbox(
        "Product type",
        ptype_options,
        index=default_index(ptype_options, "Oil"),
        key="f_ptype"
    )

with c3:
    product_options = sorted(df.loc[df["ProductType"] == ptype, "CommodityDescription"].unique())
    product = st.selectbox(
        "Product",
        product_options,
        index=default_index(product_options, "Oil, Sunflowerseed"),
        key="f_product"
    )

ROW_ORDER = [
    "Beginning Stocks",
    "Production",
    "Imports",
    "Total Supply",
    "Exports",
    "Domestic Consumption",
    "Total Use",              # <-- custom row
    "Ending Stocks",
    "Total Distribution",     # <-- optional balance identity
    "Stock-to-Use (%)",
]

# ---------------- Filtered data for BALANCE TABLE (selected country) ----------------  
mask = (
    (df["CountryName"] == country) &
    (df["ProductType"] == ptype) &
    (df["CommodityDescription"] == product) &
    (df["UnitDescription"].str.contains(r"1000\s*MT", case=False, na=False))
)
dff = df.loc[mask].copy()

if dff.empty:
    st.warning("No data found for this selection with UnitDescription containing '1000 MT'.")
    st.stop()

# ---------------- Pivot: Attribute x MarketYear ----------------
table = (
    dff.groupby(["AttributeDescription", "MarketYear"], as_index=False)["Value"].sum()
       .pivot(index="AttributeDescription", columns="MarketYear", values="Value")
)

# --- Create Domestic Consumption if not present ---
if "Domestic Consumption" not in table.index:
    if "Total Dom. Cons." in table.index:
        table.loc["Domestic Consumption"] = table.loc["Total Dom. Cons."]
    else:
        parts = [a for a in ["Food Use Dom. Cons.", "Industrial Dom. Cons.", "Feed Waste Dom. Cons.", "Feed Dom. Cons."]
                 if a in table.index]
        if parts:
            table.loc["Domestic Consumption"] = table.loc[parts].sum(axis=0)

# --- Create Total Use (custom) ---
# Prefer USDA's "Total Use" if present; otherwise Domestic Consumption + Exports
if "Total Use" not in table.index:
    if ("Domestic Consumption" in table.index) and ("Exports" in table.index):
        table.loc["Total Use"] = table.loc["Domestic Consumption"] + table.loc["Exports"]

# --- Create Total Distribution (balance identity) ---
# Common identity: Total Distribution = Total Use + Ending Stocks
if "Total Distribution" not in table.index:
    if ("Total Use" in table.index) and ("Ending Stocks" in table.index):
        table.loc["Total Distribution"] = table.loc["Total Use"] + table.loc["Ending Stocks"]

# --- Create Stock-to-Use (%) = Ending Stocks / Total Use * 100 ---
if "Stock-to-Use (%)" not in table.index:
    if ("Ending Stocks" in table.index) and ("Total Use" in table.index):
        denom = table.loc["Total Use"].replace(0, pd.NA)
        table.loc["Stock-to-Use (%)"] = (table.loc["Ending Stocks"] / denom) * 100

# Fill missing with 0 for quantities; keep % as NaN where denom=0
qty_rows = [r for r in ROW_ORDER if r != "Stock-to-Use (%)"]
table.loc[table.index.intersection(qty_rows)] = table.loc[table.index.intersection(qty_rows)].fillna(0)

# Sort years & keep only your rows in your order
table = table.reindex(sorted(table.columns), axis=1)
table = table.reindex(ROW_ORDER)

st.subheader(f"{product} — {country}")

# Format: quantities vs %
styled = table.style.format(lambda v: f"{v:,.0f}")
if "Stock-to-Use (%)" in table.index:
    styled = styled.format(lambda v: "" if pd.isna(v) else f"{v:.1f}%", subset=pd.IndexSlice[["Stock-to-Use (%)"], :])

st.dataframe(styled, use_container_width=True)

with st.expander("Show available attributes for this selection"):
    st.write(sorted(dff["AttributeDescription"].unique()))

# ===================== RANKING CHARTS (across ALL countries) =====================
st.markdown("## Top Countries")

# Controls
cA, cB = st.columns([2, 3])

with cA:
    year_options = sorted(df["MarketYear"].unique())
    year = st.selectbox("Market Year", year_options, index=len(year_options) - 1, key="top_year")

with cB:
    top_n = st.slider("Top N", 5, 40, 10, key="top_n")

# Base slice for rankings (all countries, same product/year/unit)
rank_base = df[
    (df["ProductType"] == ptype) &
    (df["CommodityDescription"] == product) &
    (df["MarketYear"] == year) &
    (df["UnitDescription"].str.contains(r"1000\s*MT", case=False, na=False))
].copy()

# Add a synthetic "Domestic Consumption" series if needed
if "Domestic Consumption" not in set(rank_base["AttributeDescription"].unique()):
    if "Total Dom. Cons." in set(rank_base["AttributeDescription"].unique()):
        tmp = rank_base[rank_base["AttributeDescription"] == "Total Dom. Cons."].copy()
        tmp["AttributeDescription"] = "Domestic Consumption"
        rank_base = pd.concat([rank_base, tmp], ignore_index=True)
    else:
        parts = [a for a in ["Food Use Dom. Cons.", "Industrial Dom. Cons.", "Feed Waste Dom. Cons.", "Feed Dom. Cons."]
                 if a in set(rank_base["AttributeDescription"].unique())]
        if parts:
            tmp = (rank_base[rank_base["AttributeDescription"].isin(parts)]
                   .groupby(["CountryName"], as_index=False)["Value"].sum())
            tmp["AttributeDescription"] = "Domestic Consumption"
            rank_base = pd.concat([rank_base, tmp], ignore_index=True)

def get_top(attribute_name: str) -> pd.DataFrame:
    """
    Get top countries for a specific attribute.
    
    :param attribute_name: Name of the attribute to rank by
    :return: DataFrame with top N countries plus Others
    """
    tmp = rank_base[rank_base["AttributeDescription"] == attribute_name]
    out = tmp.groupby("CountryName", as_index=False)["Value"].sum()
    return top_n_with_others(out, n=top_n)

def draw_bar(df_top: pd.DataFrame, title: str) -> None:
    """
    Draw a bar chart from the top countries DataFrame.
    
    :param df_top: DataFrame with CountryName and Value columns
    :param title: Chart title
    """
    if df_top.empty:
        st.info(f"No data for {title}.")
        return
    fig = px.bar(df_top, x="CountryName", y="Value", title=title)
    fig.update_yaxes(title="Value (1000 MT)")
    fig.update_xaxes(title="")
    st.plotly_chart(fig, use_container_width=True)

# 2x2 layout
cc1, cc2 = st.columns(2)
cc3, cc4 = st.columns(2)

with cc1:
    draw_bar(get_top("Production"), f"Top {top_n} Producers — {year}")

with cc2:
    draw_bar(get_top("Exports"), f"Top {top_n} Exporters — {year}")

with cc3:
    draw_bar(get_top("Imports"), f"Top {top_n} Importers — {year}")

with cc4:
    draw_bar(get_top("Domestic Consumption"), f"Top {top_n} Consumers — {year}")
