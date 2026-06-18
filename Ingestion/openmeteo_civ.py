"""
openmeteo_civ.py
Fetch Ivory Coast daily precipitation from Open-Meteo (free, no key needed).
  Historical : ERA5 reanalysis via archive-api (~5-day lag)
  Recent gap : GFS/IFS forecast blend fills through today
Upserts into: ../Database/Data/civ_precipitation.parquet
"""

import time
import requests
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

START_DATE   = date(1970, 1, 1)
ERA5_LAG     = 5
_ROOT        = Path(__file__).parent.parent
OUT_FILE     = _ROOT / "Database" / "Data" / "civ_precipitation.parquet"
ARCHIVE_URL  = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

LOCATIONS = [
    # Southern core
    ("Abidjan",         5.3548,  -4.0083),
    ("Daloa",           6.8900,  -6.4500),
    ("Gagnoa",          5.9333,  -5.9333),
    ("San-Pedro",       4.7500,  -6.6300),
    ("Yamoussoukro",    6.8276,  -5.2893),
    # Southeast
    ("Aboisso",         5.4667,  -3.2000),
    ("Niable",          5.9000,  -3.1000),
    ("Abengourou",      6.7333,  -3.4833),
    ("Adzope",          6.1000,  -3.8667),
    ("Agboville",       5.9333,  -4.2167),
    ("Bonoua",          5.2667,  -3.6000),
    ("Alepe",           5.5000,  -3.6667),
    ("Bianouan",        5.4833,  -3.4833),
    ("Agnibilekrou",    7.1167,  -3.2000),
    # South-central
    ("Tiassale",        5.8978,  -4.8231),
    ("Grand-Lahou",     5.1333,  -5.0167),
    ("Toumodi",         6.5500,  -5.0167),
    ("Divo",            5.8333,  -5.3667),
    ("Oume",            6.3833,  -5.4167),
    ("Bongouanou",      6.6500,  -4.2000),
    ("Dimbokro",        6.6500,  -4.7000),
    ("Bocanda",         7.0667,  -4.5167),
    ("Sikensi",         5.6667,  -4.5667),
    ("Taabo",           6.2167,  -5.0500),
    ("Daoukro",         7.0600,  -3.9700),
    # Southwest
    ("Fresco",          5.0500,  -5.5167),
    ("Lakota",          5.8500,  -5.6833),
    ("Sinfra",          6.6167,  -5.9167),
    ("Issia",           6.4833,  -6.5833),
    ("Soubre",          5.7833,  -6.5917),
    ("Hire",            5.7167,  -5.7167),
    ("Guitry",          5.5667,  -5.8333),
    ("Gueyo",           5.4333,  -6.0667),
    ("Meagui",          5.2667,  -6.9333),
    ("Buyo",            6.2500,  -7.1667),
    ("Bouafle",         6.9833,  -5.7333),
    ("Zuenhoula",       7.3667,  -6.0500),
    # Far west
    ("Sassandra",       4.9500,  -6.0833),
    ("Grand-Drewin",    4.8000,  -6.8500),
    ("Tai",             5.8500,  -7.4500),
    ("Guiglo",          6.5333,  -7.4833),
    ("Tabou",           4.4167,  -7.3500),
    ("Bangolo",         7.0167,  -7.4833),
    ("Danane",          7.2667,  -8.1667),
    ("Grabo",           4.9333,  -7.5833),
    ("Touleupleu",      6.5833,  -8.4167),
    ("Zouan-Hounien",   6.9167,  -8.0500),
    ("Douandrou",       6.2000,  -8.5000),
]


def _get(url, params, retries=4):
    for attempt in range(retries):
        r = requests.get(url, params=params, timeout=120)
        if r.status_code == 429:
            wait = 65 * (attempt + 1)
            print(f"rate-limited, waiting {wait}s ...", end=" ", flush=True)
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return r.json()


def fetch_station(city, lat, lon, today):
    hist_end       = today - timedelta(days=ERA5_LAG)
    forecast_start = hist_end + timedelta(days=1)
    rows = []

    data = _get(ARCHIVE_URL, {
        "latitude": lat, "longitude": lon,
        "start_date": START_DATE.isoformat(), "end_date": hist_end.isoformat(),
        "daily": "precipitation_sum", "timezone": "Africa/Abidjan",
        "precipitation_unit": "mm",
    })
    for d, p in zip(data["daily"]["time"], data["daily"]["precipitation_sum"]):
        rows.append({"station": city, "date": d, "precip_mm": p, "source": "ERA5"})

    if forecast_start <= today:
        data = _get(FORECAST_URL, {
            "latitude": lat, "longitude": lon,
            "start_date": forecast_start.isoformat(), "end_date": today.isoformat(),
            "daily": "precipitation_sum", "timezone": "Africa/Abidjan",
            "precipitation_unit": "mm",
        })
        for d, p in zip(data["daily"]["time"], data["daily"]["precipitation_sum"]):
            rows.append({"station": city, "date": d, "precip_mm": p, "source": "forecast"})

    return rows


def main():
    today = date.today()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    print(f"Fetching {len(LOCATIONS)} stations  |  {START_DATE} to {today}")

    existing = pd.read_parquet(OUT_FILE) if OUT_FILE.exists() else pd.DataFrame(
        columns=["station", "date", "precip_mm", "source"]
    )
    if not existing.empty:
        print(f"Existing records: {len(existing):,}")

    all_rows, errors = [], []

    for i, (city, lat, lon) in enumerate(LOCATIONS, 1):
        print(f"  [{i:2d}/{len(LOCATIONS)}] {city:<20}", end=" ", flush=True)
        try:
            rows = fetch_station(city, lat, lon, today)
            all_rows.extend(rows)
            valid = sum(1 for r in rows if r["precip_mm"] is not None)
            print(f"{len(rows):6d} days  ({valid} non-null)")
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append((city, str(e)))
        time.sleep(2.0)

    if all_rows:
        new_df = pd.DataFrame(all_rows)
        new_df["date"] = pd.to_datetime(new_df["date"])
        existing["date"] = pd.to_datetime(existing["date"])

        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["station", "date"], keep="last")
        combined = combined.sort_values(["station", "date"]).reset_index(drop=True)
        combined.to_parquet(OUT_FILE, index=False)
        print(f"\nSaved {len(combined):,} records to {OUT_FILE}")

    if errors:
        print(f"\nFailed ({len(errors)}):")
        for city, msg in errors:
            print(f"  {city}: {msg}")


if __name__ == "__main__":
    main()
