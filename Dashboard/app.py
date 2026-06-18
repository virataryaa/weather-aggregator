"""
Weather Aggregator Dashboard
Tabs: Ivory Coast Precip | ECMWF South America | Maxar Brazil
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
from datetime import date, timedelta
import base64

st.set_page_config(
    page_title="Weather Aggregator",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  [data-testid="stAppViewContainer"] { background-color: #0f0f1a; }
  [data-testid="stSidebar"] { background-color: #12122a; }
  h1, h2, h3 { color: #a0c4ff; }
  .kpi-card {
    background: #16213e; border-radius: 8px; padding: 16px 20px;
    border-left: 3px solid #4fc3f7; margin-bottom: 10px;
  }
  .kpi-label { font-size: 0.78em; color: #90caf9; text-transform: uppercase; letter-spacing: 1px; }
  .kpi-value { font-size: 1.6em; font-weight: 700; color: #e0e0e0; }
  .kpi-sub   { font-size: 0.82em; color: #aaaaaa; margin-top: 2px; }
  .section-divider { border-top: 1px solid #2a2a4a; margin: 18px 0; }
  .img-label { font-size: 0.82em; color: #90caf9; font-weight: 600;
               text-align: center; margin-bottom: 4px; }
</style>
""", unsafe_allow_html=True)

BASE      = Path(__file__).parent.parent
DATA_DIR  = BASE / "Database" / "Data"
ECMWF_DIR = BASE / "Database" / "Images" / "ECMWF"
MAXAR_DIR = BASE / "Database" / "Images" / "Maxar" / "BR"
PARQUET   = DATA_DIR / "civ_precipitation.parquet"


# ── helpers ───────────────────────────────────────────────────────────────────

def kpi(label, value, sub=""):
    st.markdown(
        f'<div class="kpi-card">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>'
        f'<div class="kpi-sub">{sub}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=3600)
def load_civ():
    if not PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(PARQUET)
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_images(directory: Path, pattern="*.png") -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob(pattern))


def img_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


# ── sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### Weather Aggregator")
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

    civ_ok   = PARQUET.exists()
    ecmwf_ok = any(ECMWF_DIR.glob("*.png")) if ECMWF_DIR.exists() else False
    maxar_ok = any(MAXAR_DIR.rglob("*.png")) if MAXAR_DIR.exists() else False

    def status_line(label, ok):
        dot = "&#9679;"
        color = "#4caf50" if ok else "#f44336"
        text  = "Ready" if ok else "No data"
        st.markdown(
            f'<span style="color:{color}">{dot}</span> <b>{label}</b> — {text}',
            unsafe_allow_html=True,
        )

    status_line("Ivory Coast Precip", civ_ok)
    status_line("ECMWF SA Charts",    ecmwf_ok)
    status_line("Maxar Brazil",       maxar_ok)

    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    st.caption("Run Ingestion scripts to refresh data.")


# ── tabs ───────────────────────────────────────────────────────────────────────

tab_civ, tab_ecmwf, tab_maxar = st.tabs([
    "Ivory Coast Precip",
    "ECMWF South America",
    "Maxar Brazil",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — IVORY COAST
# ══════════════════════════════════════════════════════════════════════════════
with tab_civ:
    st.markdown("## Ivory Coast — Daily Precipitation")

    df = load_civ()

    if df.empty:
        st.info("No data found. Run `Ingestion/openmeteo_civ.py` to fetch.")
    else:
        stations = sorted(df["station"].unique().tolist())

        col_left, col_right = st.columns([2, 1])
        with col_left:
            selected = st.multiselect(
                "Stations", stations,
                default=["Abidjan", "Daloa", "San-Pedro", "Soubre"],
                help="Select one or more stations, or use Regional Average below",
            )
        with col_right:
            use_aggregate = st.checkbox("Regional aggregate (all stations)", value=False)
            roll_days     = st.select_slider("Rolling sum (days)", [7, 14, 30, 60, 90], value=30)

        date_min = df["date"].min().date()
        date_max = df["date"].max().date()
        default_start = max(date_min, date(date_max.year - 3, 1, 1))

        d_start, d_end = st.slider(
            "Date range",
            min_value=date_min, max_value=date_max,
            value=(default_start, date_max),
            format="YYYY-MM-DD",
        )

        mask = (df["date"].dt.date >= d_start) & (df["date"].dt.date <= d_end)
        dff  = df[mask].copy()

        # KPI row
        recent_30 = dff[dff["date"].dt.date >= (date_max - timedelta(days=30))]
        k1, k2, k3, k4 = st.columns(4)
        with k1:
            total_mm = recent_30["precip_mm"].sum()
            kpi("30-Day Total (All Stations)", f"{total_mm:,.0f} mm")
        with k2:
            avg_mm = recent_30.groupby("station")["precip_mm"].sum().mean()
            kpi("30-Day Avg per Station", f"{avg_mm:.1f} mm")
        with k3:
            kpi("Stations tracked", str(len(stations)))
        with k4:
            kpi("Records loaded", f"{len(df):,}")

        st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

        if use_aggregate:
            agg = (
                dff.groupby("date")["precip_mm"]
                .mean()
                .reset_index()
                .sort_values("date")
            )
            agg[f"roll_{roll_days}d"] = agg["precip_mm"].rolling(roll_days, min_periods=1).sum()

            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=agg["date"], y=agg["precip_mm"],
                name="Daily", marker_color="#1e3a5f", opacity=0.5,
            ))
            fig.add_trace(go.Scatter(
                x=agg["date"], y=agg[f"roll_{roll_days}d"],
                name=f"{roll_days}d Rolling Sum",
                line=dict(color="#4fc3f7", width=2),
            ))
            fig.update_layout(
                title="Regional Average — Daily & Rolling Sum",
                paper_bgcolor="#0f0f1a", plot_bgcolor="#0f0f1a",
                font=dict(color="#e0e0e0"),
                legend=dict(bgcolor="#16213e"),
                xaxis=dict(gridcolor="#1e1e3a"),
                yaxis=dict(gridcolor="#1e1e3a", title="mm"),
                height=420, margin=dict(l=40, r=20, t=40, b=40),
            )
            st.plotly_chart(fig, use_container_width=True)

        else:
            if not selected:
                st.warning("Select at least one station.")
            else:
                fig = go.Figure()
                palette = [
                    "#4fc3f7","#f48fb1","#a5d6a7","#ffcc80",
                    "#ce93d8","#80cbc4","#ef9a9a","#fff176",
                ]
                for i, station in enumerate(selected):
                    s = dff[dff["station"] == station].sort_values("date")
                    roll = s["precip_mm"].rolling(roll_days, min_periods=1).sum()
                    color = palette[i % len(palette)]
                    fig.add_trace(go.Scatter(
                        x=s["date"], y=roll,
                        name=station, line=dict(color=color, width=1.8),
                    ))
                fig.update_layout(
                    title=f"{roll_days}-Day Rolling Precipitation by Station",
                    paper_bgcolor="#0f0f1a", plot_bgcolor="#0f0f1a",
                    font=dict(color="#e0e0e0"),
                    legend=dict(bgcolor="#16213e"),
                    xaxis=dict(gridcolor="#1e1e3a"),
                    yaxis=dict(gridcolor="#1e1e3a", title="mm"),
                    height=420, margin=dict(l=40, r=20, t=40, b=40),
                )
                st.plotly_chart(fig, use_container_width=True)

        # YoY comparison
        st.markdown("#### Year-on-Year Comparison")
        yoy_station = st.selectbox("Station for YoY", stations, index=0)
        s_yoy = df[df["station"] == yoy_station].sort_values("date")
        s_yoy = s_yoy.set_index("date").resample("D")["precip_mm"].sum().reset_index()
        s_yoy["doy"]  = s_yoy["date"].dt.dayofyear
        s_yoy["year"] = s_yoy["date"].dt.year

        years = sorted(s_yoy["year"].unique(), reverse=True)
        show_years = st.multiselect("Years", years, default=years[:4])

        fig2 = go.Figure()
        palette2 = ["#4fc3f7","#f48fb1","#a5d6a7","#ffcc80","#ce93d8","#80cbc4"]
        for i, yr in enumerate(show_years):
            y = s_yoy[s_yoy["year"] == yr].sort_values("doy")
            cum = y["precip_mm"].cumsum()
            fig2.add_trace(go.Scatter(
                x=y["doy"], y=cum,
                name=str(yr),
                line=dict(color=palette2[i % len(palette2)], width=2),
            ))
        fig2.update_layout(
            title=f"Cumulative YTD Precipitation — {yoy_station}",
            paper_bgcolor="#0f0f1a", plot_bgcolor="#0f0f1a",
            font=dict(color="#e0e0e0"),
            legend=dict(bgcolor="#16213e"),
            xaxis=dict(gridcolor="#1e1e3a", title="Day of Year"),
            yaxis=dict(gridcolor="#1e1e3a", title="Cumulative mm"),
            height=380, margin=dict(l=40, r=20, t=40, b=40),
        )
        st.plotly_chart(fig2, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — ECMWF SOUTH AMERICA
# ══════════════════════════════════════════════════════════════════════════════
with tab_ecmwf:
    st.markdown("## ECMWF — South America Forecast Charts")

    if not ECMWF_DIR.exists() or not any(ECMWF_DIR.glob("*.png")):
        st.info("No ECMWF images found. Run `Ingestion/ecmwf_sa.py` to fetch.")
    else:
        # Group slugs into sections
        ECMWF_GROUPS = {
            "Medium Range — TP Deviation":          "medium_tp_anom",
            "Medium Range — Multi-Parameter EFI":   "medium_efi",
            "Extended — 2m Temperature Anomaly":    "ext_t2m_anom",
            "Extended — Precipitation Anomaly":     "ext_tp_anom",
            "Seasonal SEAS5 — Precipitation":       "seas5_rain",
            "ENSO — Nino 3.4 Plumes":               "enso_nino34",
            "Frost Risk (CPTEC)":                   "cptec_geada",
            "CPC Observed & GFS":                   "cpc_",
            "GEFS Ensemble Anomaly":                "gefs_anom",
        }

        selected_group = st.selectbox("Chart group", list(ECMWF_GROUPS.keys()))
        slug_prefix    = ECMWF_GROUPS[selected_group]

        imgs = sorted(ECMWF_DIR.glob(f"{slug_prefix}*.png"))

        if not imgs:
            st.warning(f"No images found for '{selected_group}'.")
        else:
            cols_per_row = st.slider("Images per row", 1, 4, 2)
            rows = [imgs[i:i+cols_per_row] for i in range(0, len(imgs), cols_per_row)]
            for row in rows:
                cols = st.columns(len(row))
                for col, img_path in zip(cols, row):
                    with col:
                        label = img_path.stem.replace("_", " ").upper()
                        st.markdown(f'<div class="img-label">{label}</div>', unsafe_allow_html=True)
                        st.image(str(img_path), use_container_width=True)

        st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
        html_path = ECMWF_DIR / "dashboard.html"
        if html_path.exists():
            st.caption(f"Full HTML deck: `{html_path}`")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — MAXAR BRAZIL
# ══════════════════════════════════════════════════════════════════════════════
with tab_maxar:
    st.markdown("## Maxar WeatherDesk — Brazil Ensemble")

    if not MAXAR_DIR.exists() or not any(MAXAR_DIR.rglob("*.png")):
        st.info("No Maxar images found. Run `Ingestion/maxar_brazil.py` to fetch.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            model_sel = st.radio("Model", ["ecm", "gfs"], horizontal=True,
                                 format_func=lambda x: x.upper())
        with c2:
            var_sel = st.radio("Variable", ["precip_mm", "precip_pct_normal"], horizontal=True,
                               format_func=lambda x: "Precip mm" if x == "precip_mm" else "% of Normal")

        img_dir = MAXAR_DIR / model_sel / var_sel
        imgs    = sorted(img_dir.glob("*.png")) if img_dir.exists() else []

        if not imgs:
            st.warning(f"No images for {model_sel.upper()} / {var_sel}.")
        else:
            window_groups = {}
            for p in imgs:
                window = p.stem.split("_")[0]
                window_groups.setdefault(window, []).append(p)

            for window, wpaths in sorted(window_groups.items()):
                st.markdown(f"#### {window.replace('-', ' ').title()}")
                cols = st.columns(len(wpaths))
                for col, img_path in zip(cols, wpaths):
                    with col:
                        label = img_path.stem
                        st.markdown(f'<div class="img-label">{label}</div>', unsafe_allow_html=True)
                        st.image(str(img_path), use_container_width=True)
                st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
