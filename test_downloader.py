import json
from src.pricing.downloader import MimitDownloader
from src.pricing.parser import MimitParser
from src.pricing.geocoder import Geocoder
from src.pricing.finder import CompetitorFinder
from src.pricing.analyzer import PricingAnalyzer
from src.pricing.notifier import PricingNotifier

# Scarica e parsa
downloader = MimitDownloader(data_dir="data/raw")
paths = downloader.scarica()

print("\nParsing dati MIMIT...")
parser = MimitParser(paths['anagrafica'], paths['prezzi'])
df_mimit = parser.parse()

# Geocodifica
with open("clienti.json", "r", encoding="utf-8") as f:
    clienti = json.load(f)

geo = Geocoder()
clienti_geo = geo.geocodifica_clienti(clienti)

# Loop su tutti i clienti
finder   = CompetitorFinder(df_mimit)
analyzer = PricingAnalyzer()
notifier = PricingNotifier()

print(f"\nElaborazione {len(clienti_geo)} clienti...")
for cliente in clienti_geo:
    if not cliente['geocodificato']:
        print(f"  ⚠️ {cliente['nome']} — geocoding fallito, skip")
        continue

    print(f"\n--- {cliente['nome']} ---")
    top_n = finder.top_n_per_carburante(
        lat_cliente = cliente['lat'],
        lon_cliente  = cliente['lon'],
        raggio_km    = cliente['raggio_km'],
        carburanti   = cliente['carburanti'],
        top_n        = cliente['top_n'],
        is_self      = cliente['is_self']
    )
    report = analyzer.analizza(cliente, top_n, df_mimit)
    notifier.invia_report(report)