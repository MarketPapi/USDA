"""Country and product balance sheets: production, exports, imports, ending stocks, total use by market year."""
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(layout="wide")
st.title("Country Balance Sheet")

# =========================
# Load marts
# =========================
@st.cache_data
def load_balance_mart() -> pd.DataFrame:
    """
    Load the balance sheet mart (1000 MT only, annual aggregated).
    """
    try:
        df = pd.read_parquet("data/marts/mart_balance_sheet_qty.parquet")

        # Minimal type safety
        for c in ["commodityName", "countryName", "attributeName", "unit_clean", "unitDescription"]:
            if c in df.columns:
                df[c] = df[c].astype("string").str.strip()

        if "marketYear" in df.columns:
            df["marketYear"] = pd.to_numeric(df["marketYear"], errors="coerce").astype("Int64")

        if "value" in df.columns:
            df["value"] = pd.to_numeric(df["value"], errors="coerce").astype("float64")

        # ProductType (same idea as your old split)
        df["ProductType"] = df["commodityName"].astype("string").str.split(",").str[0].str.strip()

        return df

    except FileNotFoundError:
        st.error("Mart file not found. Please run your update pipeline to generate data/marts/mart_balance_sheet_qty.parquet")
        st.stop()
    except Exception as e:
        st.error(f"Error loading balance mart: {e}")
        st.stop()


def top_n_with_others(
    df_in: pd.DataFrame,
    name_col: str = "countryName",
    value_col: str = "value",
    n: int = 10,
    others_label: str = "Others",
) -> pd.DataFrame:
    if df_in.empty:
        return df_in

    df2 = df_in.groupby(name_col, as_index=False)[value_col].sum()
    df2 = df2.sort_values(value_col, ascending=False)

    top = df2.head(n).copy()
    others_sum = df2.iloc[n:][value_col].sum()

    if others_sum > 0:
        top = pd.concat(
            [top, pd.DataFrame({name_col: [others_label], value_col: [others_sum]})],
            ignore_index=True,
        )
    return top


def default_index(options: list, preferred: str) -> int:
    try:
        return options.index(preferred)
    except ValueError:
        return 0


# =========================
# Load data
# =========================
df = load_balance_mart()

# ---------------- Filters ----------------
c1, c2, c3 = st.columns(3)

country_options = sorted(df["countryName"].dropna().unique().tolist())
ptype_options = sorted(df["ProductType"].dropna().unique().tolist())

with c1:
    country = st.selectbox(
        "Country",
        country_options,
        index=default_index(country_options, "Russia"),
        key="f_country",
    )

with c2:
    ptype = st.selectbox(
        "Product type",
        ptype_options,
        index=default_index(ptype_options, "Oil"),
        key="f_ptype",
    )

with c3:
    product_options = sorted(df.loc[df["ProductType"] == ptype, "commodityName"].dropna().unique().tolist())
    product = st.selectbox(
        "Product",
        product_options,
        index=default_index(product_options, "Oil, Sunflowerseed"),
        key="f_product",
    )

ROW_ORDER = [
    "Beginning Stocks",
    "Production",
    "Imports",
    "Total Supply",
    "Exports",
    "Domestic Consumption",
    "Total Use",
    "Ending Stocks",
    "Total Distribution",
    "Stock-to-Use (%)",
]

# ---------------- Filtered data for BALANCE TABLE (selected country) ----------------
mask = (
    (df["countryName"] == country)
    & (df["ProductType"] == ptype)
    & (df["commodityName"] == product)
    & (df["unit_clean"] == "1000 MT")  # mart already should be 1000 MT, but keep as safety
)

dff = df.loc[mask].copy()

if dff.empty:
    st.warning("No data found for this selection.")
    st.stop()

# ---------------- Pivot: Attribute x MarketYear ----------------
table = (
    dff.groupby(["attributeName", "marketYear"], as_index=False)["value"]
       .sum()
       .pivot(index="attributeName", columns="marketYear", values="value")
)
table.index.name = None

# --- Create Domestic Consumption if not present ---
if "Domestic Consumption" not in table.index:
    if "Total Dom. Cons." in table.index:
        table.loc["Domestic Consumption"] = table.loc["Total Dom. Cons."]
    else:
        parts = [a for a in ["Food Use Dom. Cons.", "Industrial Dom. Cons.", "Feed Waste Dom. Cons.", "Feed Dom. Cons."]
                 if a in table.index]
        if parts:
            table.loc["Domestic Consumption"] = table.loc[parts].sum(axis=0)

# --- Create Total Use ---
if "Total Use" not in table.index:
    if ("Domestic Consumption" in table.index) and ("Exports" in table.index):
        table.loc["Total Use"] = table.loc["Domestic Consumption"] + table.loc["Exports"]

# --- Create Total Distribution ---
if "Total Distribution" not in table.index:
    if ("Total Use" in table.index) and ("Ending Stocks" in table.index):
        table.loc["Total Distribution"] = table.loc["Total Use"] + table.loc["Ending Stocks"]

# --- Create Stock-to-Use (%) ---
if "Stock-to-Use (%)" not in table.index:
    if ("Ending Stocks" in table.index) and ("Total Use" in table.index):
        denom = table.loc["Total Use"].replace(0, pd.NA)
        table.loc["Stock-to-Use (%)"] = (table.loc["Ending Stocks"] / denom) * 100

# Fill missing with 0 for quantities; keep % as NaN where denom=0
qty_rows = [r for r in ROW_ORDER if r != "Stock-to-Use (%)"]
table.loc[table.index.intersection(qty_rows)] = table.loc[table.index.intersection(qty_rows)].fillna(0)

# Sort years & keep only your rows in your order (but don’t crash if some rows missing)
table = table.reindex(sorted(table.columns), axis=1)
ordered_present = [r for r in ROW_ORDER if r in table.index]
table = table.reindex(ordered_present)

st.subheader(f"{product} — {country}")

# ✅ Old style: Streamlit dataframe with pandas Styler formatting
styled = table.style.format(lambda v: "" if pd.isna(v) else f"{v:,.0f}")
if "Stock-to-Use (%)" in table.index:
    styled = styled.format(
        lambda v: "" if pd.isna(v) else f"{v:.1f}%",
        subset=pd.IndexSlice[["Stock-to-Use (%)"], :],
    )

st.dataframe(styled, use_container_width=True)

# ===================== RANKING CHARTS (across ALL countries) =====================
st.markdown("## Top Countries by Measure")

# Controls
cA, cB = st.columns([2, 3])

with cA:
    year_options = sorted(df["marketYear"].dropna().unique().tolist())
    year = st.selectbox("Market Year", year_options, index=len(year_options) - 1, key="top_year")

with cB:
    top_n_options = list(range(5, 41, 5))  # 5,10,15,...,40
    top_n = st.selectbox(
        "Top N",
        top_n_options,
        index=top_n_options.index(10),
        key="top_n",
    )

# Base slice for rankings (all countries, same product/year/unit)
rank_base = df[
    (df["ProductType"] == ptype)
    & (df["commodityName"] == product)
    & (df["marketYear"] == year)
    & (df["unit_clean"] == "1000 MT")
].copy()

# Add a synthetic "Domestic Consumption" series if needed
if "Domestic Consumption" not in set(rank_base["attributeName"].dropna().unique()):
    if "Total Dom. Cons." in set(rank_base["attributeName"].dropna().unique()):
        tmp = rank_base[rank_base["attributeName"] == "Total Dom. Cons."].copy()
        tmp["attributeName"] = "Domestic Consumption"
        rank_base = pd.concat([rank_base, tmp], ignore_index=True)
    else:
        parts = [a for a in ["Food Use Dom. Cons.", "Industrial Dom. Cons.", "Feed Waste Dom. Cons.", "Feed Dom. Cons."]
                 if a in set(rank_base["attributeName"].dropna().unique())]
        if parts:
            tmp = (rank_base[rank_base["attributeName"].isin(parts)]
                   .groupby(["countryName"], as_index=False)["value"].sum())
            tmp["attributeName"] = "Domestic Consumption"
            tmp["marketYear"] = year
            tmp["commodityName"] = product
            tmp["ProductType"] = ptype
            tmp["unit_clean"] = "1000 MT"
            rank_base = pd.concat([rank_base, tmp], ignore_index=True)

def get_top(attribute_name: str) -> pd.DataFrame:
    tmp = rank_base[
        (rank_base["attributeName"] == attribute_name)
        & (rank_base["countryName"].astype("string").str.upper() != "WORLD")
        ]
    out = tmp.groupby("countryName", as_index=False)["value"].sum()
    return top_n_with_others(out, n=top_n)

def draw_bar(df_top: pd.DataFrame, title: str) -> None:
    if df_top.empty:
        st.info(f"No data for {title}.")
        return
    fig = px.bar(df_top, x="countryName", y="value", title=title)
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
