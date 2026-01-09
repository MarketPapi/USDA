import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# Save as: pages/2_Chart_Builder.py
st.set_page_config(layout="wide")
st.title("Chart Builder")

# ---------------- Data ----------------
@st.cache_data
def load_data() -> pd.DataFrame:
    df = pd.read_parquet("data/latest.parquet")
    df["MarketYear"] = df["MarketYear"].astype(int)
    # Ensure consistent string columns (prevents weird legend/title issues)
    for c in ["CommodityDescription", "CountryName", "AttributeDescription", "UnitDescription"]:
        df[c] = df[c].astype(str).str.strip()
    return df

df = load_data()

def default_multi(options, preferred, fallback_n=3):
    picked = [x for x in preferred if x in options]
    if picked:
        return picked
    return options[:fallback_n] if len(options) >= fallback_n else options

def prep_series(dff: pd.DataFrame, attr: str, series_by: str, agg_func: str) -> pd.DataFrame:
    tmp = dff[dff["AttributeDescription"] == attr]
    if tmp.empty:
        return tmp
    out = getattr(tmp.groupby(["MarketYear", series_by], as_index=False)["Value"], agg_func)()
    out["MarketYear"] = out["MarketYear"].astype(int)
    out[series_by] = out[series_by].astype(str).replace({"": "Other"}).fillna("Other")
    return out.sort_values([series_by, "MarketYear"])

# ---------------- UI ----------------
tab_builder, tab_data = st.tabs(["Builder", "Data"])

with tab_builder:
    with st.form("chart_builder_form", clear_on_submit=False):
        st.subheader("Filters")

        r1 = st.columns([2.4, 1.1, 1.7], gap="large")

        all_products = sorted(df["CommodityDescription"].unique())
        with r1[0]:
            products = st.multiselect(
                "Products",
                all_products,
                default=default_multi(all_products, ["Meal, Sunflowerseed", "Oil, Sunflowerseed"], fallback_n=2),
                key="cb_products"
            )

        base = df[df["CommodityDescription"].isin(products)] if products else df

        unit_options = sorted(base["UnitDescription"].unique())
        with r1[1]:
            unit = st.selectbox("Unit", unit_options, key="cb_unit")

        base = base[base["UnitDescription"] == unit]
        year_options = sorted(base["MarketYear"].unique())
        with r1[2]:
            years = st.multiselect(
                "Market Years",
                year_options,
                default=year_options[-6:] if len(year_options) >= 6 else year_options,
                key="cb_years"
            )

        base2 = base[base["MarketYear"].isin(years)] if years else base

        r2 = st.columns([1.4, 2.6], gap="large")
        with r2[0]:
            country_options = sorted(base2["CountryName"].unique())
            countries = st.multiselect(
                "Countries",
                country_options,
                default=default_multi(country_options, ["Russia", "Ukraine", "World"], fallback_n=3),
                key="cb_countries"
            )

        with r2[1]:
            attr_options = sorted(base2["AttributeDescription"].unique())
            attributes = st.multiselect(
                "Attributes (measures)",
                attr_options,
                default=default_multi(attr_options, ["Production", "Exports"], fallback_n=2),
                key="cb_attrs"
            )

        st.subheader("Chart settings")

        s1 = st.columns([1.0, 1.2, 1.2, 0.9, 1.2], gap="large")
        with s1[0]:
            chart_type = st.selectbox("Chart type", ["Line", "Bar", "Area", "Scatter"], key="cb_chart_type")
        with s1[1]:
            series_by = st.selectbox("Series by (color)", ["CountryName", "AttributeDescription"], key="cb_series_by")
        y_choices = attributes if attributes else attr_options
        with s1[2]:
            y1 = st.selectbox("Y1 (left axis)", y_choices, key="cb_y1")
        with s1[3]:
            use_dual = st.checkbox("Dual axis", value=False, key="cb_dual")
        with s1[4]:
            agg_method = st.selectbox("Aggregation", ["Sum", "Mean"], key="cb_agg")

        y2 = None
        if use_dual:
            y2_choices = [a for a in y_choices if a != y1]
            y2_row = st.columns([1.0, 1.2, 1.2, 0.9, 1.2], gap="large")
            with y2_row[2]:
                y2 = st.selectbox("Y2 (right axis)", y2_choices, key="cb_y2")

        with st.expander("Advanced options"):
            a1, a2 = st.columns([1.2, 2.8], gap="large")
            with a1:
                limit_top = st.checkbox("Limit to Top N countries (by latest year of Y1)", value=False, key="cb_limit_top")
            with a2:
                top_n = st.slider("Top N", 5, 40, 10, key="cb_topn") if limit_top else None

        apply = st.form_submit_button("Apply")

    # ---------------- Filtered DF ----------------
    agg_func = "sum" if st.session_state.get("cb_agg", "Sum") == "Sum" else "mean"
    sel_products = st.session_state.get("cb_products", [])
    sel_unit = st.session_state.get("cb_unit", "")
    sel_years = st.session_state.get("cb_years", [])
    sel_countries = st.session_state.get("cb_countries", [])
    sel_attrs = st.session_state.get("cb_attrs", [])
    series_col = st.session_state.get("cb_series_by", "CountryName")
    ct = st.session_state.get("cb_chart_type", "Line")
    y1_name = st.session_state.get("cb_y1", None)
    y2_name = st.session_state.get("cb_y2", None) if st.session_state.get("cb_dual", False) else None

    mask = df["UnitDescription"] == str(sel_unit)
    if sel_products:
        mask &= df["CommodityDescription"].isin(sel_products)
    if sel_years:
        mask &= df["MarketYear"].isin(sel_years)
    if sel_countries:
        mask &= df["CountryName"].isin(sel_countries)
    if sel_attrs:
        mask &= df["AttributeDescription"].isin(sel_attrs)

    dff = df.loc[mask].copy()

    if dff.empty or not y1_name:
        st.warning("No data for this selection. Broaden filters and ensure Y1 exists.")
        st.stop()

    prod_label = ", ".join(sel_products) if sel_products else "All products"
    years_label = f"{min(sel_years)}–{max(sel_years)}" if sel_years else "All years"
    st.caption(f"{prod_label} · Unit: {sel_unit} · Years: {years_label}")

    # Dynamic title requested: "Production — Meal, Sunflowerseed, Oil, Sunflowerseed"
    if y2_name:
        chart_title = f"{y1_name} vs {y2_name} — {prod_label}"
    else:
        chart_title = f"{y1_name} — {prod_label}"

    # Prep series data
    plot1 = prep_series(dff, y1_name, series_col, agg_func)

    # Optional Top N reduction (only meaningful when series are countries)
    if st.session_state.get("cb_limit_top", False) and series_col == "CountryName" and not plot1.empty:
        latest_year = int(plot1["MarketYear"].max())
        latest = plot1[plot1["MarketYear"] == latest_year].sort_values("Value", ascending=False)
        keep = latest["CountryName"].head(int(st.session_state["cb_topn"])).tolist()
        dff = dff[dff["CountryName"].isin(keep)]
        plot1 = plot1[plot1["CountryName"].isin(keep)]

    plot2 = prep_series(dff, y2_name, series_col, agg_func) if y2_name else None

    # ---------------- Chart ----------------
    fig = go.Figure()

    def add_traces(plot_df: pd.DataFrame, label: str, secondary: bool):
        if plot_df is None or plot_df.empty:
            return
        for s, sdf in plot_df.groupby(series_col):
            s = str(s) if s is not None and str(s).strip() != "" else "Other"
            x = sdf["MarketYear"]
            y = sdf["Value"]

            # Legend names: keep compact & consistent
            name = f"{s} — {label}" if series_col == "CountryName" else f"{s}"

            yaxis = "y2" if secondary else "y"

            if ct == "Line":
                fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name=name, yaxis=yaxis))
            elif ct == "Scatter":
                fig.add_trace(go.Scatter(x=x, y=y, mode="markers", name=name, yaxis=yaxis))
            elif ct == "Area":
                fig.add_trace(go.Scatter(x=x, y=y, mode="lines", fill="tozeroy", name=name, yaxis=yaxis))
            elif ct == "Bar":
                # Key fix: separate bar groups by axis so they don't overlap in dual-axis
                offset_group = "y2" if secondary else "y1"
                fig.add_trace(go.Bar(x=x, y=y, name=name, yaxis=yaxis, offsetgroup=offset_group))

    add_traces(plot1, y1_name, secondary=False)
    if plot2 is not None and not plot2.empty:
        add_traces(plot2, y2_name, secondary=True)

    # Layout / axes / "undefined" fix
    fig.update_layout(
        title=chart_title,
        xaxis_title=None,
        yaxis_title=f"{y1_name} {sel_unit}",
        legend=dict(
            orientation="h",
            yanchor="bottom", y=0.98,
            xanchor="left", x=0,
            title_text=""  # remove legend title (prevents "undefined")
        ),
        legend_title_text="",
        margin=dict(l=20, r=20, t=60, b=20),
        height=560,
        barmode="group" if ct == "Bar" else None
    )

    # Right axis if dual
    if plot2 is not None and not plot2.empty:
        fig.update_layout(
            yaxis2=dict(
                title=f"{y2_name} {sel_unit}",
                overlaying="y",
                side="right",
                showgrid=False
            )
        )

    # Integer ticks for MarketYear
    fig.update_xaxes(tickmode="linear", dtick=1, tickformat="d")

    st.plotly_chart(fig, use_container_width=True)

with tab_data:
    st.subheader("Filtered data preview")

    # Reuse session-state filters
    sel_products = st.session_state.get("cb_products", [])
    sel_unit = st.session_state.get("cb_unit", "")
    sel_years = st.session_state.get("cb_years", [])
    sel_countries = st.session_state.get("cb_countries", [])
    sel_attrs = st.session_state.get("cb_attrs", [])

    mask = df["UnitDescription"] == str(sel_unit)
    if sel_products:
        mask &= df["CommodityDescription"].isin(sel_products)
    if sel_years:
        mask &= df["MarketYear"].isin(sel_years)
    if sel_countries:
        mask &= df["CountryName"].isin(sel_countries)
    if sel_attrs:
        mask &= df["AttributeDescription"].isin(sel_attrs)

    dff_preview = df.loc[mask].copy()
    st.dataframe(dff_preview, use_container_width=True)

    st.download_button(
        "Download filtered data as CSV",
        data=dff_preview.to_csv(index=False).encode("utf-8"),
        file_name="chart_builder_filtered_data.csv",
        mime="text/csv",
    )
