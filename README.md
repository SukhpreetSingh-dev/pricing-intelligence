# Competitive Pricing Intelligence

Python system that ingests public government datasets daily, computes
competitive positioning on a geographic basis, and delivers automated
reports by email.

## The problem

Businesses operating across multiple locations need to know how their prices
compare to nearby competitors, every day. Public data exists, but it is raw,
high-volume and unusable without processing — so the comparison is either
done manually or not at all.

## What it does

- **Automated daily ingestion** of the Italian MIMIT open dataset
  (locations registry + price feed)
- **Parsing and merging** of heterogeneous sources into a single dataset
- **Exact client matching**: each location is linked to its own MIMIT station
  (`id_impianto`), with address geocoding as a fallback
- **Geospatial analysis**: identifies all competitors within a configurable
  radius of each location (the client's own station excluded)
- **Competitive ranking**: position within the radius, gap vs the cheapest
  and vs the average competitor, per fuel type
- **Data freshness control**: competitor prices not updated in the last
  N days are excluded and reported, since many stations report late
- **Automated email delivery**, one report per client, multiple recipients
- **Graceful degradation**: falls back to cached data when the source is unreachable


## Sample output

![Report example](docs/report-example.png)

*Demo data with fictional stations — the real report reads the daily MIMIT dataset.*

## Results

- Processes **23,700+ locations** and **74,900+ daily price records**
- Ranks each location against every competitor within its radius
- Runs end to end with no manual intervention
- Reports delivered within minutes of data availability

## Stack

Python 3.14 · pandas · NumPy · Requests · Geopy · SMTP · pytest

## Use case

Built for the fuel retail market, where prices are published by law.
The architecture applies to any sector with open pricing data and
location-based competition.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                      # SMTP credentials
cp clienti.example.json clienti.json      # your locations

python main.py
python -m pytest -q                       # tests on synthetic data
```

### Client configuration (`clienti.json`)

| Field | Meaning |
|---|---|
| `id_impianto` | MIMIT station id of the client. Recommended: gives the exact price. If `null`, the address is geocoded and matched to a MIMIT station within 300 m — the run prints the id found, so you can paste it in. |
| `raggio_km` | Competitor search radius |
| `top_n` | Rows in the report table (statistics always use every competitor in the radius) |
| `is_self` | `true` = self-service prices, `false` = full-service (LPG and CNG always use both) |
| `max_eta_giorni` | Competitor prices older than this many days are excluded (default 3) |

## Data

All data is retrieved from public open-data sources.
No proprietary or client data is included in this repository.
