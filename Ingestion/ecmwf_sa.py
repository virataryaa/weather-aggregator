"""
ecmwf_sa.py
Fetch ECMWF OpenCharts forecast imagery for South America.
Saves individual PNGs to: ../Database/Images/ECMWF/
Also writes a self-contained HTML deck for browser review.
Sources: ECMWF OpenCharts API (free), NOAA/CPC (free), TropicalTidbits (free)
"""

import base64
import io
import re
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image

API_BASE = "https://charts.ecmwf.int/opencharts-api/v1/products"
_ROOT    = Path(__file__).parent.parent
OUT_DIR  = _ROOT / "Database" / "Images" / "ECMWF"
CROP_BOX = (0, 260, 2000, 1600)

CPC_BASE  = "https://www.cpc.ncep.noaa.gov/products/international"
CRNG_BASE = "https://ftp.cptec.inpe.br/modelos/tempo/CRNG/GEADA"

STATIC_CHARTS = [
    {
        "label": "CPTEC — Frost Forecast Day 1",
        "slug":  "cptec_geada_d1",
        "url":   f"{CRNG_BASE}/indice1.gif",
    },
    {
        "label": "CPTEC — Frost Forecast Day 2",
        "slug":  "cptec_geada_d2",
        "url":   f"{CRNG_BASE}/indice2.gif",
    },
    {
        "label": "CPTEC — Frost Forecast Day 3",
        "slug":  "cptec_geada_d3",
        "url":   f"{CRNG_BASE}/indice3.gif",
    },
    {
        "label": "CPC — 7-Day Observed Precipitation",
        "slug":  "cpc_7d_obs",
        "url":   f"{CPC_BASE}/cpcuni_gauge/cpcuni_gauge_7day_sam_obs.gif",
    },
    {
        "label": "CPC — 7-Day Precipitation Anomaly",
        "slug":  "cpc_7d_anom",
        "url":   f"{CPC_BASE}/cpcuni_gauge/cpcuni_gauge_7day_sam_anom.gif",
    },
    {
        "label": "CPC — 30-Day % of Normal",
        "slug":  "cpc_30d_pnorm",
        "url":   f"{CPC_BASE}/cpcuni_gauge/cpcuni_gauge_30day_sam_pnorm.gif",
    },
    {
        "label": "GFS — Week 1 Total Precipitation",
        "slug":  "gfs_w1_precip",
        "url":   f"{CPC_BASE}/cpci/data/00/gfs.t00z.totp.week1.samerica.gif",
    },
    {
        "label": "GFS — Week 2 Total Precipitation",
        "slug":  "gfs_w2_precip",
        "url":   f"{CPC_BASE}/cpci/data/00/gfs.t00z.totp.week2.samerica.gif",
    },
    {
        "label": "GEFS — Precip Anomaly Days 1-7",
        "slug":  "gefs_anom_d1_7",
        "tt": {"model": "gfs-ens", "region": "samer", "pkg": "apcpna", "fh": 168},
    },
    {
        "label": "GEFS — Precip Anomaly Days 8-14",
        "slug":  "gefs_anom_d8_14",
        "tt": {"model": "gfs-ens", "region": "samer", "pkg": "apcpna", "fh": 344},
    },
]

SEASONAL_STEPS = [744, 1488, 2208, 2952]

CHARTS = [
    {
        "product":        "medium-tp-anomaly",
        "projection":     "opencharts_south_america",
        "label":          "SA — TP Deviation (Medium Range)",
        "slug":           "medium_tp_anom",
        "step_increment": 24,
        "step_count":     6,
    },
    {
        "product":        "medium-multi-efi",
        "projection":     "opencharts_south_america",
        "label":          "SA — Multi-Parameter EFI",
        "slug":           "medium_efi",
        "step_increment": 24,
        "step_count":     7,
    },
    {
        "product":        "extended-anomaly-2t",
        "projection":     "opencharts_south_america",
        "label":          "SA — 2m Temperature Anomaly (Weekly)",
        "slug":           "ext_t2m_anom",
        "step_increment": 168,
        "step_count":     4,
    },
    {
        "product":        "extended-anomaly-tp",
        "projection":     "opencharts_south_america",
        "label":          "SA — Total Precipitation Anomaly (Weekly)",
        "slug":           "ext_tp_anom",
        "step_increment": 168,
        "step_count":     4,
    },
    {
        "product":        "seasonal_system5_standard_rain",
        "projection":     None,
        "label":          "SA — Seasonal Precipitation SEAS5",
        "slug":           "seas5_rain",
        "steps":          SEASONAL_STEPS,
        "extra_params":   {"area": "SAME", "stats": "tsum"},
    },
    {
        "product":        "seasonal_system5_nino_plumes",
        "projection":     None,
        "label":          "ENSO — Nino 3.4 Plumes",
        "slug":           "enso_nino34",
        "steps":          [0],
        "extra_params":   {"nino_area": "NINO3-4"},
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://charts.ecmwf.int/",
}
TT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://www.tropicaltidbits.com/analysis/models/",
}


def tt_runtime():
    now = datetime.now(timezone.utc)
    d = now.date() if now.hour >= 6 else (now - timedelta(days=1)).date()
    return d.strftime("%Y%m%d") + "00"


def tt_image_url(model, region, pkg, fh):
    runtime  = tt_runtime()
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


def discover_first_step(product, projection, extra_params=None):
    params = {}
    if projection:
        params["projection"] = projection
    if extra_params:
        params.update(extra_params)
    r = requests.get(f"{API_BASE}/{product}/", params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    desc = r.json()["data"]["attributes"]["description"]
    m = re.search(r"\(\+(\d+)h\)", desc)
    if not m:
        raise ValueError(f"Cannot parse step from: {desc!r}")
    return int(m.group(1))


def resolve_steps(chart):
    if "steps" in chart:
        return chart["steps"]
    first = discover_first_step(chart["product"], chart["projection"], chart.get("extra_params"))
    return [first + i * chart["step_increment"] for i in range(chart["step_count"])]


def fetch_ecmwf_image(product, projection, step, extra_params=None):
    params = {"step": step}
    if projection:
        params["projection"] = projection
    if extra_params:
        params.update(extra_params)
    for attempt in range(3):
        r = requests.get(f"{API_BASE}/{product}/", params=params, headers=HEADERS, timeout=15)
        if r.status_code != 403:
            break
        time.sleep(8 * (attempt + 1))
    r.raise_for_status()
    data        = r.json()["data"]
    description = data["attributes"]["description"]
    image_url   = data["link"]["href"]
    img = requests.get(image_url, headers=HEADERS, timeout=30)
    img.raise_for_status()
    cropped = Image.open(io.BytesIO(img.content)).crop(CROP_BOX)
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue(), description


def fetch_static_image(url, hdrs=None):
    r = requests.get(url, headers=hdrs or HEADERS, timeout=15)
    r.raise_for_status()
    buf = io.BytesIO()
    Image.open(io.BytesIO(r.content)).convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def parse_valid_time(description):
    m = re.search(r"Valid time:\s*(.+?)\s*\(", description)
    return m.group(1).strip() if m else description


def save_png(data: bytes, slug: str, suffix: str = "") -> Path:
    name = f"{slug}{suffix}.png"
    path = OUT_DIR / name
    path.write_bytes(data)
    return path


def build_html(sections, static_sections):
    cards_html = ""
    for section in sections:
        cards_html += f'<h2 class="section-title">{section["label"]}</h2>\n<div class="row">\n'
        for step, img_b64, valid_time in section["cards"]:
            cards_html += f"""
  <div class="card">
    <div class="card-header">+{step}h &mdash; {valid_time}</div>
    <img src="data:image/png;base64,{img_b64}" alt="+{step}h">
  </div>
"""
        cards_html += "</div>\n"

    if static_sections:
        cards_html += '<h2 class="section-title">CPC / NOAA / GFS / CPTEC</h2>\n<div class="row">\n'
        for item in static_sections:
            cards_html += f"""
  <div class="card">
    <div class="card-header">{item["label"]}</div>
    <img src="data:image/png;base64,{item["img_b64"]}" alt="{item["label"]}">
  </div>
"""
        cards_html += "</div>\n"

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ECMWF Weather Deck</title>
<style>
  body {{ font-family: sans-serif; background: #1a1a2e; color: #e0e0e0; margin: 0; padding: 20px; }}
  h1 {{ text-align: center; color: #a0c4ff; margin-bottom: 4px; }}
  .generated {{ text-align: center; color: #888; font-size: 0.85em; margin-bottom: 30px; }}
  .section-title {{ color: #a0c4ff; border-bottom: 1px solid #333; padding-bottom: 6px; margin-top: 30px; }}
  .row {{ display: flex; flex-wrap: wrap; gap: 16px; }}
  .card {{ background: #16213e; border-radius: 8px; padding: 12px; flex: 1 1 400px; max-width: 520px; }}
  .card-header {{ font-size: 0.9em; color: #90caf9; margin-bottom: 8px; font-weight: bold; }}
  .card img {{ width: 100%; border-radius: 4px; }}
</style>
</head>
<body>
<h1>ECMWF South America Deck</h1>
<p class="generated">Generated: {generated}</p>
{cards_html}
</body>
</html>"""


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sections = []

    for chart in CHARTS:
        print(f"\n{chart['label']}")
        cards = []
        steps = resolve_steps(chart)
        for step in steps:
            print(f"  +{step}h ...", end=" ", flush=True)
            try:
                img_bytes, description = fetch_ecmwf_image(
                    chart["product"], chart["projection"], step, chart.get("extra_params")
                )
                valid_time = parse_valid_time(description)
                save_png(img_bytes, chart["slug"], f"_{step:04d}h")
                img_b64 = base64.b64encode(img_bytes).decode()
                cards.append((step, img_b64, valid_time))
                print("ok")
            except Exception as e:
                print(f"skipped ({e})")
            time.sleep(5)
        sections.append({"label": chart["label"], "cards": cards})

    print("\nStatic charts")
    static_sections = []
    for item in STATIC_CHARTS:
        print(f"  {item['label']} ...", end=" ", flush=True)
        try:
            if "tt" in item:
                p   = item["tt"]
                url = tt_image_url(p["model"], p["region"], p["pkg"], p["fh"])
                img_bytes = fetch_static_image(url, TT_HEADERS)
            else:
                img_bytes = fetch_static_image(item["url"])
            save_png(img_bytes, item["slug"])
            static_sections.append({"label": item["label"], "img_b64": base64.b64encode(img_bytes).decode()})
            print("ok")
        except Exception as e:
            print(f"skipped ({e})")

    html = build_html(sections, static_sections)
    html_path = OUT_DIR / "dashboard.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"\nDeck saved: {html_path}")


if __name__ == "__main__":
    main()
