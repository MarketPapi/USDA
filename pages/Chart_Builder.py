import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

st.set_page_config(layout="wide")
st.title("Chart Builder")


# ---------------- Data ----------------
@st.cache_data
def load_data() -> pd.DataFrame:
    """
    Load and preprocess mart_balance_sheet_qty.

    Supports either:
      - New mart naming: commodityName/countryName/attributeName/unit_clean/marketYear/value
      - USDA-like naming: CommodityDescription/CountryName/AttributeDescription/UnitDescription/MarketYear/Value

    NOTE: mart should already be aggregated at the desired granularity (no re-aggregation here).
    """
    try:
        df = pd.read_parquet("data/marts/mart_balance_sheet_qty.parquet")

        candidates = {
            "commodityName": ["commodityName", "CommodityDescription", "commodity", "Commodity"],
            "countryName": ["countryName", "CountryName", "country", "Country"],
            "attributeName": ["attributeName", "AttributeDescription", "attribute", "Attribute"],
            "unit_clean": ["unit_clean", "UnitDescription", "unit", "Unit"],
            "marketYear": ["marketYear", "MarketYear", "year", "Year"],
            "value": ["value", "Value", "qty", "Qty", "quantity", "Quantity"],
        }

        col_map = {}
        for canon, opts in candidates.items():
            for c in opts:
                if c in df.columns:
                    col_map[c] = canon
                    break
        df = df.rename(columns=col_map)

        required = {"commodityName", "countryName", "attributeName", "unit_clean", "marketYear", "value"}
        missing = required - set(df.columns)
        if missing:
            st.error(
                "mart_balance_sheet_qty is missing required columns after normalization:\n"
                f"Missing: {sorted(missing)}\n"
                f"Available: {sorted(df.columns)}"
            )
            st.stop()

        for c in ["commodityName", "countryName", "attributeName", "unit_clean"]:
            df[c] = df[c].astype("string").str.strip()

        df["marketYear"] = pd.to_numeric(df["marketYear"], errors="coerce").astype("Int64")
        df["value"] = pd.to_numeric(df["value"], errors="coerce").astype("float64")

        df = df.dropna(
            subset=["commodityName", "countryName", "attributeName", "unit_clean", "marketYear", "value"]
        ).copy()
        df["marketYear"] = df["marketYear"].astype(int)

        return df

    except FileNotFoundError:
        st.error("Data file not found: data/marts/mart_balance_sheet_qty.parquet")
        st.stop()
    except Exception as e:
        st.error(f"Error loading data: {e}")
        st.stop()


df = load_data()


# ---------------- Helpers ----------------
def default_multi(options: list, preferred: list, fallback_n: int = 3) -> list:
    picked = [x for x in preferred if x in options]
    if picked:
        return picked
    return options[:fallback_n] if len(options) >= fallback_n else options


def apply_transform(df_plot: pd.DataFrame, *, transform: str, rolling: int, normalize: str) -> pd.DataFrame:
    """
    transform: 'None' | 'Percent change' | 'Log10'
    normalize: 'None' | 'Index (100 at start)' | 'Share of total (per year)'
    rolling: 0 means none
    """
    if df_plot.empty:
        return df_plot

    out = df_plot.copy()

    if rolling and rolling > 1:
        out["value"] = out.groupby("series")["value"].transform(lambda s: s.rolling(rolling, min_periods=1).mean())

    if normalize == "Index (100 at start)":

        def to_index(s: pd.Series) -> pd.Series:
            s2 = s.dropna()
            if s2.empty:
                return s
            base = s2.iloc[0]
            if base == 0:
                return np.nan
            return (s / base) * 100.0

        out["value"] = out.groupby("series")["value"].transform(to_index)

    elif normalize == "Share of total (per year)":
        totals = out.groupby("marketYear")["value"].transform("sum")
        out["value"] = np.where(totals != 0, out["value"] / totals * 100.0, np.nan)

    if transform == "Log10":
        out["value"] = np.log10(out["value"].clip(lower=1e-9))
    elif transform == "Percent change":
        out["value"] = out.groupby("series")["value"].pct_change() * 100.0

    return out


def y_axis_label(measure: str, unit: str, *, transform: str, normalize: str) -> str:
    if normalize == "Share of total (per year)":
        base = f"{measure} (% of total)"
    elif normalize == "Index (100 at start)":
        base = f"{measure} (Index=100)"
    else:
        base = f"{measure} ({unit})"

    if transform == "Percent change":
        base = f"{measure} (% change)"
    if transform == "Log10":
        base = f"log10({base})"
    return base


def add_traces(
    fig: go.Figure,
    plot_df: pd.DataFrame,
    *,
    chart_type: str,
    yaxis: str,
    line_shape: str,
    marker_size: int,
):
    if plot_df is None or plot_df.empty:
        return

    for series, sdf in plot_df.groupby("series"):
        name = str(series)

        # Bars: categorical year labels prevent overlap
        x = sdf["marketYear"].astype(str) if chart_type == "Bar" else sdf["marketYear"]
        y = sdf["value"]

        if chart_type == "Line":
            fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name=name, yaxis=yaxis, line_shape=line_shape))
        elif chart_type == "Scatter":
            fig.add_trace(go.Scatter(x=x, y=y, mode="markers", name=name, yaxis=yaxis, marker=dict(size=marker_size)))
        elif chart_type == "Area":
            fig.add_trace(go.Scatter(x=x, y=y, mode="lines", fill="tozeroy", name=name, yaxis=yaxis))
        elif chart_type == "Bar":
            # ✅ FIX: use offsetgroup=name so bars never overlap for the same year
            fig.add_trace(
                go.Bar(
                    x=x,
                    y=y,
                    name=name,
                    yaxis=yaxis,
                    offsetgroup=name,
                    legendgroup=name,
                    marker=dict(line=dict(width=1, color="rgba(255,255,255,0.35)"), opacity=0.90),
                )
            )


# ---------------- Layout ----------------
tab_builder, tab_data = st.tabs(["Builder", "Data"])

with tab_builder:
    # ===== Sidebar: most important (what data) =====
    with st.sidebar:
        st.header("Data")

        commodity_options = sorted(df["commodityName"].dropna().unique().tolist())
        commodities = st.multiselect(
            "Commodities",
            commodity_options,
            default=default_multi(commodity_options, ["Oil, Sunflowerseed"], fallback_n=2),
            key="cb_commodities",
        )

        base = df[df["commodityName"].isin(commodities)] if commodities else df

        unit_options = sorted(base["unit_clean"].dropna().unique().tolist())
        unit = st.selectbox("Unit", unit_options, key="cb_unit")

        base = base[base["unit_clean"] == unit]

        year_options = sorted(base["marketYear"].dropna().astype(int).unique().tolist())
        if not year_options:
            st.warning("No years available for this selection.")
            st.stop()

        yr_min, yr_max = min(year_options), max(year_options)
        default_low = max(yr_min, yr_max - 10)
        year_range = st.slider(
            "Year range",
            min_value=int(yr_min),
            max_value=int(yr_max),
            value=(int(default_low), int(yr_max)),
            step=1,
            key="cb_year_range",
        )

        base = base[(base["marketYear"] >= year_range[0]) & (base["marketYear"] <= year_range[1])]

        country_options = sorted(base["countryName"].dropna().unique().tolist())
        countries = st.multiselect(
            "Countries",
            country_options,
            default=default_multi(country_options, ["Russia"], fallback_n=3),
            key="cb_countries",
        )

        measure_options = sorted(base["attributeName"].dropna().unique().tolist())
        measures = st.multiselect(
            "Measures",
            measure_options,
            default=default_multi(measure_options, ["Production"], fallback_n=2),
            key="cb_measures",
        )

        st.divider()

    # ===== Main: left = design, right = chart =====
    left, right = st.columns([1.05, 1.95], gap="large")

    # ---------------- Build filtered DF once ----------------
    mask = (df["unit_clean"] == str(unit)) & (df["marketYear"].between(year_range[0], year_range[1]))
    if commodities:
        mask &= df["commodityName"].isin(commodities)
    if countries:
        mask &= df["countryName"].isin(countries)
    if measures:
        mask &= df["attributeName"].isin(measures)

    dff = df.loc[mask].copy()
    if dff.empty:
        st.warning("No data for this selection. Broaden filters.")
        st.stop()

    prod_label = ", ".join(commodities) if commodities else "All commodities"

    # ---------------- Main-left: chart controls (design) ----------------
    with left:
        st.subheader("Chart Settings", divider=True)

        chart_type_ui = st.selectbox(
            "Chart type",
            ["Line chart", "Bar chart", "Area chart", "Scatter chart"],
            key="cb_chart_type_ui",
        )
        chart_type = {"Line chart": "Line", "Bar chart": "Bar", "Area chart": "Area", "Scatter chart": "Scatter"}[
            chart_type_ui
        ]

        series_by_ui = st.selectbox("Split series by", ["Country", "Measure"], key="cb_series_by_ui")
        series_by = "countryName" if series_by_ui == "Country" else "attributeName"

        st.subheader("Axes", divider=True)

        available_measures = measures if measures else sorted(dff["attributeName"].unique().tolist())
        default_y1 = available_measures.index("Production") if "Production" in available_measures else 0
        y1 = st.selectbox("Left axis (Y1)", available_measures, index=default_y1, key="cb_y1")

        use_dual = st.checkbox("Secondary Axis (Y2)", value=False, key="cb_dual")
        y2 = None
        if use_dual:
            y2_choices = [m for m in available_measures if m != y1]
            default_y2 = y2_choices.index("Exports") if "Exports" in y2_choices else (0 if y2_choices else 0)
            y2 = st.selectbox("Right axis (Y2)", y2_choices, index=default_y2, key="cb_y2")

        st.subheader("Transforms", divider=True)

        normalize = st.selectbox(
            "Normalize",
            ["None", "Index (100 at start)", "Share of total (per year)"],
            key="cb_normalize",
        )
        transform = st.selectbox("Transform", ["None", "Percent change", "Log10"], key="cb_transform")
        rolling = st.slider("Smoothing (Rolling AVG)", 0, 10, 0, key="cb_rolling")

        st.subheader("Styling", divider=True)

        line_shape = "linear"
        if chart_type == "Line":
            line_style = st.selectbox("Line style", ["Straight", "Smooth"], key="cb_line_style")
            line_shape = "spline" if line_style == "Smooth" else "linear"

        marker_size = 7
        if chart_type == "Scatter":
            marker_size = st.slider("Marker size", 3, 14, 7, key="cb_marker_size")

        palette_map = {
            "Plotly (default)": px.colors.qualitative.Plotly,
            "Bold": px.colors.qualitative.Bold,
            "Pastel": px.colors.qualitative.Pastel,
            "Dark": px.colors.qualitative.Dark24,
            "Alphabet": px.colors.qualitative.Alphabet,
            "Safe (colorblind)": px.colors.qualitative.Safe,
        }
        palette_name = st.selectbox("Colors", list(palette_map.keys()), key="cb_palette")
        palette = palette_map[palette_name]

        show_legend = st.checkbox("Show Legend", value=True, key="cb_legend")
        show_grid = st.checkbox("Show Grid", value=True, key="cb_grid")

        st.subheader("Focus", divider=True)
        limit_top = st.checkbox("Limit to N Series", value=False, key="cb_limit_top")
        top_n = st.slider("Top N", 3, 40, 10, key="cb_topn") if limit_top else 10

    # ---------------- Prepare plot data (no aggregation) ----------------
    dff = dff.copy()
    dff["series_base"] = dff[series_by].astype("string").replace({"": "Other"}).fillna("Other")

    keep_attrs = [y1] + ([y2] if y2 else [])
    dff = dff[dff["attributeName"].isin([k for k in keep_attrs if k])].copy()
    if dff.empty:
        st.warning("No data after selecting Y1/Y2.")
        st.stop()

    def label_series(df_in: pd.DataFrame, measure: str) -> pd.DataFrame:
        out = df_in.copy()
        if series_by == "countryName":
            out["series"] = out["series_base"].astype(str) + f" — {measure}"
        else:
            out["series"] = out["series_base"]
        return out

    df_y1 = label_series(dff[dff["attributeName"] == y1].copy(), y1)
    df_y2 = label_series(dff[dff["attributeName"] == y2].copy(), y2) if y2 else pd.DataFrame()

    # Top N on latest year of Y1
    if limit_top and not df_y1.empty:
        latest_year = int(df_y1["marketYear"].max())
        latest = df_y1[df_y1["marketYear"] == latest_year].sort_values("value", ascending=False)
        keep_series = latest["series"].head(int(top_n)).tolist()
        df_y1 = df_y1[df_y1["series"].isin(keep_series)]
        if not df_y2.empty and series_by == "countryName":
            keep_series_y2 = [s.replace(f" — {y1}", f" — {y2}") for s in keep_series]
            df_y2 = df_y2[df_y2["series"].isin(keep_series_y2)]

    # Apply transforms
    df_y1_plot = apply_transform(
        df_y1[["marketYear", "series", "value"]].copy(),
        transform=transform,
        rolling=int(rolling),
        normalize=normalize,
    )
    df_y2_plot = (
        apply_transform(
            df_y2[["marketYear", "series", "value"]].copy(),
            transform=transform,
            rolling=int(rolling),
            normalize=normalize,
        )
        if (y2 and not df_y2.empty)
        else pd.DataFrame()
    )

    # ---------------- Build figure ----------------
    title = f"{y1} vs {y2} — {prod_label}" if y2 else f"{y1} — {prod_label}"

    fig = go.Figure()
    add_traces(fig, df_y1_plot, chart_type=chart_type, yaxis="y", line_shape=line_shape, marker_size=marker_size)
    if y2 and not df_y2_plot.empty:
        add_traces(fig, df_y2_plot, chart_type=chart_type, yaxis="y2", line_shape=line_shape, marker_size=marker_size)

    # Palette assignment
    series_list = list(dict.fromkeys([str(t.name) for t in fig.data if getattr(t, "name", None)]))
    color_map = {s: palette[i % len(palette)] for i, s in enumerate(series_list)}
    for tr in fig.data:
        if getattr(tr, "name", None) in color_map:
            if tr.type == "bar":
                tr.marker.color = color_map[tr.name]
            else:
                tr.line.color = color_map[tr.name]
                if hasattr(tr, "marker") and tr.mode and "markers" in tr.mode:
                    tr.marker.color = color_map[tr.name]

    # Layout fixes + bar readability
    fig.update_layout(
        title=dict(text=title, x=0.0, xanchor="left", y=0.995, yanchor="top", pad=dict(b=14)),
        legend=dict(orientation="h", yanchor="top", y=0.965, xanchor="left", x=0.0, title_text=""),
        showlegend=show_legend,
        margin=dict(l=20, r=20, t=90, b=20),
        height=680,
        barmode="group" if chart_type == "Bar" else None,
        bargap=0.25 if chart_type == "Bar" else None,
        bargroupgap=0.10 if chart_type == "Bar" else None,
    )

    # Axes
    if chart_type == "Bar":
        fig.update_xaxes(type="category", categoryorder="category ascending", showgrid=show_grid)
    else:
        fig.update_xaxes(tickmode="linear", dtick=1, tickformat="d", showgrid=show_grid)

    fig.update_yaxes(title=y_axis_label(y1, unit, transform=transform, normalize=normalize), showgrid=show_grid)

    if y2 and not df_y2_plot.empty:
        fig.update_layout(
            yaxis2=dict(
                title=y_axis_label(y2, unit, transform=transform, normalize=normalize),
                overlaying="y",
                side="right",
                showgrid=False,
            )
        )

    # ---------------- Render chart + downloads (right panel) ----------------
    with right:
        st.plotly_chart(fig, use_container_width=True)

        with st.expander("Downloads"):
            export_df = pd.concat(
                [
                    df_y1_plot.assign(axis="Y1"),
                    (df_y2_plot.assign(axis="Y2") if (y2 and not df_y2_plot.empty) else pd.DataFrame()),
                ],
                ignore_index=True,
            )
            st.download_button(
                "Download chart data (CSV)",
                data=export_df.to_csv(index=False).encode("utf-8"),
                file_name="chart_builder_chart_data.csv",
                mime="text/csv",
            )
            st.download_button(
                "Download chart (HTML)",
                data=fig.to_html(include_plotlyjs="cdn").encode("utf-8"),
                file_name="chart_builder_chart.html",
                mime="text/html",
            )

with tab_data:
    st.subheader("Filtered data preview")

    commodities = st.session_state.get("cb_commodities", [])
    unit = st.session_state.get("cb_unit", "")
    year_range = st.session_state.get("cb_year_range", None)
    countries = st.session_state.get("cb_countries", [])
    measures = st.session_state.get("cb_measures", [])

    mask = df["unit_clean"] == str(unit)
    if year_range:
        mask &= df["marketYear"].between(int(year_range[0]), int(year_range[1]))
    if commodities:
        mask &= df["commodityName"].isin(commodities)
    if countries:
        mask &= df["countryName"].isin(countries)
    if measures:
        mask &= df["attributeName"].isin(measures)

    dff_preview = df.loc[mask].copy()
    st.dataframe(dff_preview, use_container_width=True, height=560)

    st.download_button(
        "Download filtered data (CSV)",
        data=dff_preview.to_csv(index=False).encode("utf-8"),
        file_name="chart_builder_filtered_data.csv",
        mime="text/csv",
    )
