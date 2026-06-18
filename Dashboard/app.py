"""
Weather Aggregator Dashboard
Tabs: Ivory Coast Precip | ECMWF South America | Maxar Brazil
ECMWF charts are fetched live from the API (cached 24h per group).
"""

import io
import re
import time
import base64
import requests
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
from datetime import date, timedelta, datetime, timezone
from PIL import Image

st.set_page_config(
    page_title="Weather Aggregator",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .kpi-card {
    background: #e8f0fe; border-radius: 8px; padding: 16px 20px;
    border-left: 3px solid #1565c0; margin-bottom: 10px;
  }
  .kpi-label { font-size: 0.78em; color: #1565c0; text-transform: uppercase; letter-spacing: 1px; }
  .kpi-value { font-size: 1.6em; font-weight: 700; color: #0d1b2a; }
  .kpi-sub   { font-size: 0.82em; color: #555; margin-top: 2px; }
  .section-divider { border-top: 1px solid #ddd; margin: 18px 0; }
  .img-label { font-size: 0.82em; color: #1565c0; font-weight: 600;
               text-align: center; margin-bottom: 4px; }
  .fetch-note { font-size: 0.80em; color: #888; font-style: italic; }
</style>
""", unsafe_allow_html=True)

BASE    = Path(__file__).parent.parent
PARQUET = BASE / "Database" / "Data" / "civ_precipitation.parquet"

# ── ECMWF API constants ────────────────────────────────────────────────────────

ECMWF_API  = "https://charts.ecmwf.int/opencharts-api/v1/products"
CROP_BOX   = (0, 260, 2000, 1600)
CPC_BASE   = "https://www.cpc.ncep.noaa.gov/products/international"
CRNG_BASE  = "https://ftp.cptec.inpe.br/modelos/tempo/CRNG/GEADA"

ECMWF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://charts.ecmwf.int/",
}
TT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://www.tropicaltidbits.com/analysis/models/",
}

ECMWF_GROUPS = [
    {
        "label":          "SA — TP Deviation (Medium Range)",
        "product":        "medium-tp-anomaly",
        "projection":     "opencharts_south_america",
        "step_increment": 24,
        "step_count":     6,
    },
    {
        "label":          "SA — Multi-Parameter EFI",
        "product":        "medium-multi-efi",
        "projection":     "opencharts_south_america",
        "step_increment": 24,
        "step_count":     7,
    },
    {
        "label":          "SA — 2m Temperature Anomaly (Weekly)",
        "product":        "extended-anomaly-2t",
        "projection":     "opencharts_south_america",
        "step_increment": 168,
        "step_count":     4,
    },
    {
        "label":          "SA — Precipitation Anomaly (Weekly)",
        "product":        "extended-anomaly-tp",
        "projection":     "opencharts_south_america",
        "step_increment": 168,
        "step_count":     4,
    },
    {
        "label":          "SA — Seasonal Precipitation (SEAS5)",
        "product":        "seasonal_system5_standard_rain",
        "projection":     None,
        "steps":          [744, 1488, 2208, 2952],
        "extra_params":   {"area": "SAME", "stats": "tsum"},
    },
    {
        "label":          "ENSO — Nino 3.4 Plumes",
        "product":        "seasonal_system5_nino_plumes",
        "projection":     None,
        "steps":          [0],
        "extra_params":   {"nino_area": "NINO3-4"},
    },
]

STATIC_GROUPS = [
    {
        "label": "Frost Risk (CPTEC Brazil)",
        "charts": [
            {"label": "Day 1", "url": f"{CRNG_BASE}/indice1.gif"},
            {"label": "Day 2", "url": f"{CRNG_BASE}/indice2.gif"},
            {"label": "Day 3", "url": f"{CRNG_BASE}/indice3.gif"},
        ],
    },
    {
        "label": "CPC Observed & GFS",
        "charts": [
            {"label": "7-Day Observed",    "url": f"{CPC_BASE}/cpcuni_gauge/cpcuni_gauge_7day_sam_obs.gif"},
            {"label": "7-Day Anomaly",     "url": f"{CPC_BASE}/cpcuni_gauge/cpcuni_gauge_7day_sam_anom.gif"},
            {"label": "30-Day % Normal",   "url": f"{CPC_BASE}/cpcuni_gauge/cpcuni_gauge_30day_sam_pnorm.gif"},
            {"label": "GFS Week 1 Precip", "url": f"{CPC_BASE}/cpci/data/00/gfs.t00z.totp.week1.samerica.gif"},
            {"label": "GFS Week 2 Precip", "url": f"{CPC_BASE}/cpci/data/00/gfs.t00z.totp.week2.samerica.gif"},
        ],
    },
    {
        "label": "GEFS Ensemble Anomaly",
        "charts": [
            {"label": "Days 1-7",  "tt": {"model": "gfs-ens", "region": "samer", "pkg": "apcpna", "fh": 168}},
            {"label": "Days 8-14", "tt": {"model": "gfs-ens", "region": "samer", "pkg": "apcpna", "fh": 344}},
        ],
    },
]


# ── ECMWF fetch utilities ──────────────────────────────────────────────────────

def _tt_runtime():
    now = datetime.now(timezone.utc)
    d   = now.date() if now.hour >= 6 else (now - timedelta(days=1)).date()
    return d.strftime("%Y%m%d") + "00"


def _tt_image_url(model, region, pkg, fh):
    runtime  = _tt_runtime()
    page_url = (
        f"https://www.tropicaltidbits.com/analysis/models/"
        f"?model={model}&region={region}&pkg={pkg}&runtime={runtime}&fh={fh}"
    )
    r = requests.get(page_url, headers=TT_HEADERS, timeout=15)
    r.raise_for_status()
    m = re.search(r'og:image["\s]+content="([^"]+\.png)"', r.text)
    if not m:
        raise ValueError(f"og:image not found for fh={fh}")
    return m.group(1)


def _crop_to_b64(raw_bytes):
    img     = Image.open(io.BytesIO(raw_bytes)).convert("RGB").crop(CROP_BOX)
    buf     = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _to_b64(raw_bytes):
    buf = io.BytesIO()
    Image.open(io.BytesIO(raw_bytes)).convert("RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _discover_first_step(product, projection, extra_params=None):
    params = {}
    if projection:
        params["projection"] = projection
    if extra_params:
        params.update(extra_params)
    r = requests.get(f"{ECMWF_API}/{product}/", params=params,
                     headers=ECMWF_HEADERS, timeout=15)
    r.raise_for_status()
    desc = r.json()["data"]["attributes"]["description"]
    m    = re.search(r"\(\+(\d+)h\)", desc)
    if not m:
        raise ValueError(f"Cannot parse step: {desc!r}")
    return int(m.group(1))


def _resolve_steps(group):
    if "steps" in group:
        return group["steps"]
    first = _discover_first_step(group["product"], group["projection"],
                                  group.get("extra_params"))
    return [first + i * group["step_increment"] for i in range(group["step_count"])]


def _fetch_one_step(product, projection, step, extra_params=None):
    params = {"step": step}
    if projection:
        params["projection"] = projection
    if extra_params:
        params.update(extra_params)
    for attempt in range(3):
        r = requests.get(f"{ECMWF_API}/{product}/", params=params,
                         headers=ECMWF_HEADERS, timeout=15)
        if r.status_code != 403:
            break
        time.sleep(8 * (attempt + 1))
    r.raise_for_status()
    data      = r.json()["data"]
    desc      = data["attributes"]["description"]
    image_url = data["link"]["href"]
    img       = requests.get(image_url, headers=ECMWF_HEADERS, timeout=30)
    img.raise_for_status()
    m = re.search(r"Valid time:\s*(.+?)\s*\(", desc)
    valid_time = m.group(1).strip() if m else desc
    return _crop_to_b64(img.content), valid_time


# ── Cached fetch functions (24h TTL) ─────────────────────────────────────────

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_ecmwf_group(product, projection, label, steps_key,
                      step_increment=None, step_count=None,
                      steps=None, extra_params=None):
    results = []
    resolved = steps if steps else None
    if resolved is None:
        try:
            first    = _discover_first_step(product, projection, extra_params)
            resolved = [first + i * step_increment for i in range(step_count)]
        except Exception as e:
            return [], str(e)

    for step in resolved:
        try:
            img_b64, valid_time = _fetch_one_step(product, projection, step, extra_params)
            results.append({"step": step, "img_b64": img_b64, "valid_time": valid_time})
            time.sleep(5)
        except Exception:
            pass
    return results, None


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_static_chart(url, label, tt_params=None):
    try:
        if tt_params:
            url = _tt_image_url(**tt_params)
        r = requests.get(url, headers=ECMWF_HEADERS if not tt_params else TT_HEADERS,
                         timeout=15)
        r.raise_for_status()
        return _to_b64(r.content), None
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=3600)
def load_civ():
    if not PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(PARQUET)
    df["date"] = pd.to_datetime(df["date"])
    return df


# ── helpers ────────────────────────────────────────────────────────────────────

def kpi(label, value, sub=""):
    st.markdown(
        f'<div class="kpi-card">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>'
        f'<div class="kpi-sub">{sub}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### Weather Aggregator")
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

    civ_ok = PARQUET.exists()

    def status_line(label, ok, note=""):
        dot   = "&#9679;"
        color = "#4caf50" if ok else "#f44336"
        text  = "Ready" if ok else "No data"
        st.markdown(
            f'<span style="color:{color}">{dot}</span> <b>{label}</b> — {text}'
            + (f'<br><span style="font-size:0.75em;color:#666">{note}</span>' if note else ""),
            unsafe_allow_html=True,
        )

    status_line("Ivory Coast Precip", civ_ok)
    status_line("ECMWF SA Charts", True, "fetched live, cached 24h")
    status_line("Maxar Brazil", False, "run maxar_brazil.py locally")

    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    st.caption("ECMWF charts load on first select (~30s per group), then instant from cache.")


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
            )
        with col_right:
            use_aggregate = st.checkbox("Regional aggregate (all stations)", value=False)
            roll_days     = st.select_slider("Rolling sum (days)", [7, 14, 30, 60, 90], value=30)

        date_min      = df["date"].min().date()
        date_max      = df["date"].max().date()
        default_start = max(date_min, date(date_max.year - 3, 1, 1))

        d_start, d_end = st.slider(
            "Date range",
            min_value=date_min, max_value=date_max,
            value=(default_start, date_max),
            format="YYYY-MM-DD",
        )

        mask = (df["date"].dt.date >= d_start) & (df["date"].dt.date <= d_end)
        dff  = df[mask].copy()

        recent_30 = dff[dff["date"].dt.date >= (date_max - timedelta(days=30))]
        k1, k2, k3, k4 = st.columns(4)
        with k1:
            kpi("30-Day Total (All)", f"{recent_30['precip_mm'].sum():,.0f} mm")
        with k2:
            kpi("30-Day Avg / Station", f"{recent_30.groupby('station')['precip_mm'].sum().mean():.1f} mm")
        with k3:
            kpi("Stations", str(len(stations)))
        with k4:
            kpi("Records", f"{len(df):,}")

        st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

        palette = ["#4fc3f7","#f48fb1","#a5d6a7","#ffcc80",
                   "#ce93d8","#80cbc4","#ef9a9a","#fff176"]

        if use_aggregate:
            agg = (dff.groupby("date")["precip_mm"].mean()
                   .reset_index().sort_values("date"))
            agg[f"roll"] = agg["precip_mm"].rolling(roll_days, min_periods=1).sum()
            fig = go.Figure()
            fig.add_trace(go.Bar(x=agg["date"], y=agg["precip_mm"],
                                 name="Daily", marker_color="#90caf9", opacity=0.6))
            fig.add_trace(go.Scatter(x=agg["date"], y=agg["roll"],
                                     name=f"{roll_days}d Rolling",
                                     line=dict(color="#4fc3f7", width=2)))
            title = "Regional Average — Daily & Rolling Sum"
        else:
            if not selected:
                st.warning("Select at least one station.")
                st.stop()
            fig = go.Figure()
            for i, station in enumerate(selected):
                s    = dff[dff["station"] == station].sort_values("date")
                roll = s["precip_mm"].rolling(roll_days, min_periods=1).sum()
                fig.add_trace(go.Scatter(x=s["date"], y=roll, name=station,
                                         line=dict(color=palette[i % len(palette)], width=1.8)))
            title = f"{roll_days}-Day Rolling Precipitation by Station"

        fig.update_layout(
            title=title,
            paper_bgcolor="white", plot_bgcolor="#f8f9fa",
            font=dict(color="#0d1b2a"),
            legend=dict(bgcolor="white"),
            xaxis=dict(gridcolor="#dee2e6"),
            yaxis=dict(gridcolor="#dee2e6", title="mm"),
            height=420, margin=dict(l=40, r=20, t=40, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

        # YoY
        st.markdown("#### Year-on-Year Comparison")
        yoy_station = st.selectbox("Station", stations, index=0)
        s_yoy = (df[df["station"] == yoy_station]
                 .sort_values("date")
                 .set_index("date")
                 .resample("D")["precip_mm"].sum()
                 .reset_index())
        s_yoy["doy"]  = s_yoy["date"].dt.dayofyear
        s_yoy["year"] = s_yoy["date"].dt.year

        years      = sorted(s_yoy["year"].unique(), reverse=True)
        show_years = st.multiselect("Years", years, default=years[:4])

        fig2 = go.Figure()
        for i, yr in enumerate(show_years):
            y   = s_yoy[s_yoy["year"] == yr].sort_values("doy")
            cum = y["precip_mm"].cumsum()
            fig2.add_trace(go.Scatter(x=y["doy"], y=cum, name=str(yr),
                                      line=dict(color=palette[i % len(palette)], width=2)))
        fig2.update_layout(
            title=f"Cumulative YTD — {yoy_station}",
            paper_bgcolor="white", plot_bgcolor="#f8f9fa",
            font=dict(color="#0d1b2a"),
            legend=dict(bgcolor="white"),
            xaxis=dict(gridcolor="#dee2e6", title="Day of Year"),
            yaxis=dict(gridcolor="#dee2e6", title="Cumulative mm"),
            height=380, margin=dict(l=40, r=20, t=40, b=40),
        )
        st.plotly_chart(fig2, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — ECMWF SOUTH AMERICA (live fetch, cached 24h)
# ══════════════════════════════════════════════════════════════════════════════
with tab_ecmwf:
    st.markdown("## ECMWF — South America Forecast Charts")
    st.markdown(
        '<p class="fetch-note">Charts are fetched live from ECMWF OpenCharts and cached for 24 hours. '
        'First load per group takes ~30 seconds.</p>',
        unsafe_allow_html=True,
    )

    all_group_labels = (
        [g["label"] for g in ECMWF_GROUPS]
        + [g["label"] for g in STATIC_GROUPS]
    )
    selected_group = st.selectbox("Chart group", all_group_labels)

    cols_per_row = st.slider("Images per row", 1, 4, 2, key="ecmwf_cols")

    # ── Dynamic ECMWF groups ───────────────────────────────────────────────
    ecmwf_match = next((g for g in ECMWF_GROUPS if g["label"] == selected_group), None)
    if ecmwf_match:
        with st.spinner(f"Fetching {selected_group} from ECMWF..."):
            cards, err = fetch_ecmwf_group(
                product        = ecmwf_match["product"],
                projection     = ecmwf_match.get("projection"),
                label          = ecmwf_match["label"],
                steps_key      = ecmwf_match["label"],
                step_increment = ecmwf_match.get("step_increment"),
                step_count     = ecmwf_match.get("step_count"),
                steps          = ecmwf_match.get("steps"),
                extra_params   = ecmwf_match.get("extra_params"),
            )

        if err:
            st.error(f"Fetch error: {err}")
        elif not cards:
            st.warning("No charts returned for this group.")
        else:
            rows = [cards[i:i+cols_per_row] for i in range(0, len(cards), cols_per_row)]
            for row in rows:
                cols = st.columns(len(row))
                for col, card in zip(cols, row):
                    with col:
                        st.markdown(
                            f'<div class="img-label">+{card["step"]}h &mdash; {card["valid_time"]}</div>',
                            unsafe_allow_html=True,
                        )
                        st.image(
                            base64.b64decode(card["img_b64"]),
                            use_container_width=True,
                        )

    # ── Static groups (CPC, CPTEC, GEFS) ──────────────────────────────────
    static_match = next((g for g in STATIC_GROUPS if g["label"] == selected_group), None)
    if static_match:
        with st.spinner(f"Fetching {selected_group}..."):
            loaded = []
            for chart in static_match["charts"]:
                img_b64, err = fetch_static_chart(
                    url       = chart.get("url", ""),
                    label     = chart["label"],
                    tt_params = chart.get("tt"),
                )
                if img_b64:
                    loaded.append({"label": chart["label"], "img_b64": img_b64})

        if not loaded:
            st.warning("Could not fetch charts for this group.")
        else:
            rows = [loaded[i:i+cols_per_row] for i in range(0, len(loaded), cols_per_row)]
            for row in rows:
                cols = st.columns(len(row))
                for col, card in zip(cols, row):
                    with col:
                        st.markdown(
                            f'<div class="img-label">{card["label"]}</div>',
                            unsafe_allow_html=True,
                        )
                        st.image(
                            base64.b64decode(card["img_b64"]),
                            use_container_width=True,
                        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — MAXAR BRAZIL
# ══════════════════════════════════════════════════════════════════════════════
with tab_maxar:
    st.markdown("## Maxar WeatherDesk — Brazil Ensemble")
    st.info(
        "Maxar images are fetched locally and not deployed to Streamlit Cloud. "
        "Run `Ingestion/maxar_brazil.py` on your local machine to populate this tab."
    )

    MAXAR_DIR = BASE / "Database" / "Images" / "Maxar" / "BR"
    if MAXAR_DIR.exists() and any(MAXAR_DIR.rglob("*.png")):
        c1, c2 = st.columns(2)
        with c1:
            model_sel = st.radio("Model", ["ecm", "gfs"], horizontal=True,
                                 format_func=str.upper)
        with c2:
            var_sel = st.radio("Variable", ["precip_mm", "precip_pct_normal"], horizontal=True,
                               format_func=lambda x: "Precip mm" if x == "precip_mm" else "% of Normal")

        img_dir = MAXAR_DIR / model_sel / var_sel
        imgs    = sorted(img_dir.glob("*.png")) if img_dir.exists() else []

        if imgs:
            window_groups = {}
            for p in imgs:
                window = p.stem.split("_")[0]
                window_groups.setdefault(window, []).append(p)

            for window, wpaths in sorted(window_groups.items()):
                st.markdown(f"#### {window.replace('-', ' ').title()}")
                cols = st.columns(len(wpaths))
                for col, img_path in zip(cols, wpaths):
                    with col:
                        st.markdown(f'<div class="img-label">{img_path.stem}</div>',
                                    unsafe_allow_html=True)
                        st.image(str(img_path), use_container_width=True)
                st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
