"""
maxar_brazil.py
Fetch Maxar WeatherDesk ensemble precipitation period-summary images for Brazil.
Models : ECM + GFS  |  Type: EN (ensemble)  |  Run: 00Z
Variables : PS (precip mm)  |  PPDP (% of normal)
Windows   : day 1-5 / 6-10 / 11-15

Saves to: ../Database/Images/Maxar/BR/{model}/{variable}/
Requires MAXAR_ACCOUNT_ID env var (or hardcoded fallback).

Usage:
    python maxar_brazil.py [--dry-run]
"""

import argparse
import os
from datetime import datetime
from pathlib import Path
import requests

ACCOUNT_ID = os.environ.get("MAXAR_ACCOUNT_ID", "23f9d5e5-60a3-4a9b-a1be-600755674225")
API_BASE   = f"https://api.weatherdesk.xweather.com/{ACCOUNT_ID}/services/models/v1/main"
IMG_BASE   = f"https://img.weatherdesk.xweather.com/{ACCOUNT_ID}"

_ROOT   = Path(__file__).parent.parent
OUT_DIR = _ROOT / "Database" / "Images" / "Maxar" / "BR"

MODELS    = ["ecm", "gfs"]
VARIABLES = {
    "PS":   "precip_mm",
    "PPDP": "precip_pct_normal",
}
WINDOWS = [
    ("day01-05",  5),
    ("day06-10", 10),
    ("day11-15", 15),
]


def fetch_metadata(session, model, variable, run="00", region="BR", model_type="EN"):
    params = {"model": model, "type": model_type, "run": run,
              "region": region, "variable": variable}
    r = session.get(API_BASE, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def parse_dt(s):
    return datetime.fromisoformat(s[:19].replace("Z", ""))


def find_window_frame(models_by_path, init_time_str, day_end):
    init_dt = parse_dt(init_time_str)
    for path, info in models_by_path.items():
        if not info.get("available"):
            continue
        if "dr-0005_" not in Path(path).name:
            continue
        vt_str = info.get("validTime", "")
        if not vt_str:
            continue
        days_out = (parse_dt(vt_str) - init_dt).total_seconds() / 86400
        if abs(days_out - day_end) < 0.1:
            return path, info
    return None, None


def download_image(session, path, dest):
    url  = IMG_BASE + path
    r    = session.get(url, timeout=30)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return len(r.content)


def main():
    parser = argparse.ArgumentParser(description="Maxar Brazil ensemble precip fetcher")
    parser.add_argument("--dry-run", action="store_true", help="List frames without downloading")
    args = parser.parse_args()

    session = requests.Session()
    saved = skipped = 0
    errors = []

    for model in MODELS:
        for variable, var_label in VARIABLES.items():
            label = f"{model.upper()}-EN / {variable} ({var_label})"
            print(f"\n{'='*60}\n  {label}\n{'='*60}")

            try:
                data = fetch_metadata(session, model, variable)
            except requests.HTTPError as e:
                print(f"  ERROR: {e}")
                errors.append(f"{label}: {e}")
                continue

            init_time = data.get("initTime", "")
            pct       = data.get("status", {}).get("percentComplete", "?")
            print(f"  Init: {init_time}  |  Complete: {pct}%")

            models_by_path = data.get("models", {}).get("byPath", {})
            dest_dir = OUT_DIR / model / var_label

            for window_label, day_end in WINDOWS:
                path, info = find_window_frame(models_by_path, init_time, day_end)
                if path is None:
                    print(f"  [{window_label}]  NOT FOUND")
                    continue

                valid_date = info.get("validTime", "")[:10]
                filename   = Path(path).name
                dest       = dest_dir / f"{window_label}_{filename}"

                if not args.dry_run and dest.exists():
                    print(f"  [{window_label}]  skip   {filename}  valid={valid_date}")
                    skipped += 1
                    continue

                if args.dry_run:
                    print(f"  [{window_label}]  would fetch  {filename}  valid={valid_date}")
                    continue

                dest_dir.mkdir(parents=True, exist_ok=True)
                try:
                    size = download_image(session, path, dest)
                    print(f"  [{window_label}]  saved  {dest.name}  ({size//1024} KB)  valid={valid_date}")
                    saved += 1
                except requests.HTTPError as e:
                    print(f"  [{window_label}]  ERROR  {e}")
                    errors.append(f"{label} {window_label}: {e}")

    print(f"\n{'='*60}")
    if args.dry_run:
        print("Dry run — no files written.")
    else:
        print(f"Saved: {saved}  |  Skipped: {skipped}  |  Output: {OUT_DIR}")
        if errors:
            print("Errors:")
            for e in errors:
                print(f"  {e}")


if __name__ == "__main__":
    main()
