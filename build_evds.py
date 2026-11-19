"""Fetch EVDS series at their native frequency and render the static dashboard."""

import json
import math
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "archive/evds.json"
TEMPLATE = ROOT / "evds.html"
OUTPUT = ROOT / "dist/index.html"
BASE_URL = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
SERIES = (
    ("TP.DK.USD.A.YTL", 190),
    ("TP.APIFON3", 190),
    ("TP.AB.TOPLAM", 370),
    ("TP.MKNETHAR.M8", 370),
)


def fetch_series(code, since, today, key):
    url = (f"{BASE_URL}series={code}&startDate={since:%d-%m-%Y}"
           f"&endDate={today:%d-%m-%Y}&type=json")
    request = Request(url, headers={"key": key, "Accept": "application/json"})
    with urlopen(request, timeout=25) as response:
        rows = json.load(response)["items"]

    field = code.replace(".", "_")
    observations = {}
    for row in rows:
        raw = row[field]
        if raw is None or raw == "":
            continue
        day = datetime.strptime(row["Tarih"], "%d-%m-%Y").date()
        value = float(raw)
        if not math.isfinite(value) or not since <= day <= today:
            raise ValueError(f"Geçersiz gözlem: {code}")
        observations[day.isoformat()] = value
    if len(observations) < 2:
        raise ValueError(f"Yetersiz gözlem: {code}")
    return sorted(observations.items())


def refresh(previous, key, now):
    today = now.date()
    fresh = {}
    for code, days in SERIES:
        points = fetch_series(code, today - timedelta(days=days), today, key)
        prior = previous["series"].get(code, [])
        if prior and points[-1][0] < prior[-1][0]:
            raise ValueError(f"Son gözlem tarihi geriye gitti: {code}")
        fresh[code] = points
    return {"source": "api", "checked": now.isoformat(timespec="seconds"), "series": fresh}


def save(snapshot):
    temporary = ARCHIVE.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(ARCHIVE)


def main():
    snapshot = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    key = os.getenv("EVDS_API_KEY", "").strip()
    status = "ready"
    if key:
        try:
            snapshot = refresh(snapshot, key, datetime.now(ZoneInfo("Europe/Istanbul")))
        except (HTTPError, URLError, TimeoutError, TypeError, ValueError, KeyError) as error:
            detail = f"HTTP {error.code}" if isinstance(error, HTTPError) else type(error).__name__
            print(f"::warning::EVDS sorgusu tamamlanamadı ({detail}). Son kayıt yayımlanıyor.", file=sys.stderr)
            status = "cached"
        else:
            save(snapshot)
    else:
        status = "setup"
        print("::warning::EVDS_API_KEY tanımlı değil. Son kayıt yayımlanıyor.", file=sys.stderr)
    payload = json.dumps({**snapshot, "status": status}, separators=(",", ":"), allow_nan=False)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__EVDS_PAYLOAD__", payload.replace("<", "\\u003c")), encoding="utf-8")
    print("EVDS: " + ", ".join(f"{code} {rows[-1][0]}" for code, rows in snapshot["series"].items()))


if __name__ == "__main__":
    main()
