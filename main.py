"""
Pricing Intelligence — Entry point principale.

Uso:
    python3 main.py

Cosa fa:
    1. Scarica i dati MIMIT aggiornati
    2. Parsa anagrafica e prezzi
    3. Geocodifica i clienti
    4. Per ogni cliente trova i Top N competitor per carburante
    5. Analizza il posizionamento
    6. Manda l'email di report
"""

import json
import os
import sys
from datetime import datetime

from src.pricing.downloader import MimitDownloader
from src.pricing.parser import MimitParser
from src.pricing.geocoder import Geocoder
from src.pricing.finder import CompetitorFinder
from src.pricing.analyzer import PricingAnalyzer
from src.pricing.notifier import PricingNotifier


CLIENTI_PATH = "clienti.json"


def carica_clienti() -> list:
    """Carica la lista clienti dal file JSON."""
    if not os.path.exists(CLIENTI_PATH):
        print(f"❌ File clienti non trovato: {CLIENTI_PATH}")
        sys.exit(1)

    with open(CLIENTI_PATH, "r", encoding="utf-8") as f:
        clienti = json.load(f)

    print(f"✅ {len(clienti)} clienti caricati")
    return clienti


def main():
    print("=" * 55)
    print("  PRICING INTELLIGENCE — AVVIO")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 55)

    # ── 1. Scarica dati MIMIT ───────────────────────────────
    print("\nSTEP 1 — Download dati MIMIT")
    downloader = MimitDownloader(data_dir="data/raw")
    paths = downloader.scarica()

    # ── 2. Parsa dati ──────────────────────────────────────
    print("\nSTEP 2 — Parsing dati")
    parser  = MimitParser(paths['anagrafica'], paths['prezzi'])
    df_mimit = parser.parse()

    # ── 3. Carica e geocodifica clienti ────────────────────
    print("\nSTEP 3 — Geocoding clienti")
    clienti     = carica_clienti()
    geo         = Geocoder()
    clienti_geo = geo.geocodifica_clienti(clienti)

    # ── 4-5-6. Loop clienti ────────────────────────────────
    print(f"\nSTEP 4 — Elaborazione e invio report")
    finder   = CompetitorFinder(df_mimit)
    analyzer = PricingAnalyzer()
    notifier = PricingNotifier()

    ok = 0
    ko = 0

    for cliente in clienti_geo:
        nome = cliente['nome']

        if not cliente.get('geocodificato'):
            print(f"  ⚠️  {nome} — geocoding fallito, skip")
            ko += 1
            continue

        print(f"\n  → {nome}")

        # Top N competitor per carburante
        top_n = finder.top_n_per_carburante(
            lat_cliente = cliente['lat'],
            lon_cliente  = cliente['lon'],
            raggio_km    = cliente['raggio_km'],
            carburanti   = cliente['carburanti'],
            top_n        = cliente['top_n'],
            is_self      = cliente['is_self']
        )

        # Analisi posizionamento
        report = analyzer.analizza(cliente, top_n, df_mimit)

        # Debug: salva anteprima HTML per screenshot
        os.makedirs("output", exist_ok=True)
        preview_path = f"output/preview_{cliente['id']}.html"
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(notifier._template_html(report))
        print(f"     💾 Preview salvata → {preview_path}")

        # Stampa summary a console
        for riga in report['summary']:
            print(f"     {riga}")

        # Invia email
        inviata = notifier.invia_report(report)
        if inviata:
            ok += 1
        else:
            ko += 1

    # ── Fine ───────────────────────────────────────────────
    print("\n" + "=" * 55)
    print(f"  COMPLETATO — {ok} email inviate, {ko} errori")
    print("=" * 55)


if __name__ == "__main__":
    main()