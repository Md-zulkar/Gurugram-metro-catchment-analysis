"""
Gurugram Metro Station Catchment Extractor
--------------------------------------------
Scrapes Rapid Metro Gurgaon station names from a public source (Wikipedia),
geocodes each one, and calculates its distance from a reference point
(IFFCO Chowk, a central Gurugram Delhi Metro interchange) to produce a
catchment-style dataset -- the kind of output used in real estate/location
research to assess metro-connectivity coverage.

This mirrors a real location-research workflow: collect locations -> geocode ->
calculate distance/catchment coverage -> output a clean, structured dataset.

Run locally (not in a sandboxed environment with restricted network access):
    pip install requests beautifulsoup4 geopy
    python gurugram_locality_catchment.py
"""

import csv
import time
import logging
import requests
from bs4 import BeautifulSoup
from geopy.distance import geodesic

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

WIKI_URL = "https://en.wikipedia.org/wiki/Rapid_Metro_Gurgaon"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "GurugramLocalityResearch/1.0 (student project; contact: husainyawar09@gmail.com)"

# Reference point for catchment distance: IFFCO Chowk, a well-known central Gurugram landmark
REFERENCE_POINT_NAME = "IFFCO Chowk, Gurugram"
REFERENCE_COORDS = (28.4729, 77.0719)  # (lat, lon)

OUTPUT_FILE = "gurugram_locality_catchment.csv"


def fetch_locality_list():
    """
    Scrape Rapid Metro Gurgaon station names from Wikipedia's wikitable.
    Falls back to a hardcoded list if the page structure changes or the
    request fails, so the pipeline still produces output.
    """
    fallback_localities = [
        "Sector 55-56, Gurugram", "Sector 54 Chowk, Gurugram", "Sector 53-54, Gurugram",
        "Sector 42-43, Gurugram", "DLF Phase 1, Gurugram", "Sikanderpur, Gurugram",
        "DLF Phase 2, Gurugram", "Belvedere Towers, Gurugram", "Cyber City, Gurugram",
        "Moulsari Avenue, Gurugram", "DLF Phase 3, Gurugram",
    ]

    try:
        resp = requests.get(WIKI_URL, headers={"User-Agent": USER_AGENT}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # The page has multiple wikitables (existing stations + a separate
        # "planned lines" table). Find the one whose header row actually
        # contains "Station Name" so we don't pull rows from the wrong table.
        target_table = None
        for table in soup.find_all("table", class_="wikitable"):
            header_text = table.get_text(" ", strip=True)[:300].lower()
            if "station name" in header_text:
                target_table = table
                break

        if target_table is None:
            logger.warning("Station table not found on page; using fallback list")
            return fallback_localities

        localities = []
        rows = target_table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            first_cell_text = cells[0].get_text(strip=True)
            # Real data rows start with a row number (1, 2, 3, ...);
            # this skips header rows and the stray "English | Hindi" subheader row
            if not first_cell_text.isdigit():
                continue
            station_name = cells[1].get_text(strip=True)
            if station_name and 2 < len(station_name) < 40:
                localities.append(f"{station_name}, Gurugram")

        # De-duplicate while preserving order
        seen = set()
        unique_localities = []
        for loc in localities:
            if loc not in seen:
                seen.add(loc)
                unique_localities.append(loc)

        if unique_localities:
            logger.info(f"Scraped {len(unique_localities)} stations from Wikipedia")
            return unique_localities
        else:
            logger.warning("No stations found on page; using fallback list")
            return fallback_localities

    except requests.RequestException as e:
        logger.warning(f"Scrape failed ({e}); using fallback list")
        return fallback_localities


def geocode_locality(name, retries=2):
    """
    Geocode a single locality name using Nominatim (OpenStreetMap), which is
    free and requires no API key. Nominatim's usage policy requires max 1
    request/second, so we rate-limit between calls.
    """
    params = {"q": name, "format": "json", "limit": 1}
    headers = {"User-Agent": USER_AGENT}

    for attempt in range(retries + 1):
        try:
            resp = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            results = resp.json()
            if results:
                lat = float(results[0]["lat"])
                lon = float(results[0]["lon"])
                return lat, lon
            else:
                logger.warning(f"No geocode result for: {name}")
                return None, None
        except requests.RequestException as e:
            logger.warning(f"Geocode attempt {attempt + 1} failed for {name}: {e}")
            time.sleep(1)

    return None, None


def build_catchment_dataset(localities):
    """
    Geocode each locality and compute its distance from the reference point.
    Returns a list of dicts, ready to write to CSV. Skips and logs any
    locality that fails to geocode rather than silently dropping it.
    """
    rows = []
    seen = set()

    for name in localities:
        clean_name = name.strip()
        if clean_name in seen:
            continue  # de-duplicate
        seen.add(clean_name)

        lat, lon = geocode_locality(clean_name)
        time.sleep(1.1)  # respect Nominatim's 1 req/sec rate limit

        if lat is None or lon is None:
            rows.append({
                "locality": clean_name,
                "latitude": "",
                "longitude": "",
                "distance_from_reference_km": "",
                "reference_point": REFERENCE_POINT_NAME,
                "status": "geocode_failed",
            })
            continue

        distance_km = round(geodesic(REFERENCE_COORDS, (lat, lon)).km, 2)
        rows.append({
            "locality": clean_name,
            "latitude": lat,
            "longitude": lon,
            "distance_from_reference_km": distance_km,
            "reference_point": REFERENCE_POINT_NAME,
            "status": "ok",
        })
        logger.info(f"{clean_name}: {distance_km} km from {REFERENCE_POINT_NAME}")

    return rows


def write_csv(rows, filename):
    fieldnames = ["locality", "latitude", "longitude", "distance_from_reference_km",
                  "reference_point", "status"]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"Wrote {len(rows)} rows to {filename}")


def main():
    localities = fetch_locality_list()
    rows = build_catchment_dataset(localities)
    write_csv(rows, OUTPUT_FILE)

    ok_count = sum(1 for r in rows if r["status"] == "ok")
    logger.info(f"Done. {ok_count}/{len(rows)} localities successfully geocoded.")


if __name__ == "__main__":
    main()