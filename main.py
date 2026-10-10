"""
Pricing Intelligence — Entry point principale.

Uso:
    python3 main.py

Cosa fa:
    1. Scarica i dati MIMIT aggiornati
    2. Parsa anagrafica e prezzi
    3. Collega ogni cliente al suo impianto MIMIT (id_impianto o indirizzo)
    4. Per ogni cliente trova TUTTI i competitor nel raggio, per carburante
    5. Analizza il posizionamento (statistiche sul raggio, tabella sul Top N)
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
from src.pricing.clienti import localizza_clienti
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

    # ── 3. Collega i clienti ai loro impianti MIMIT ────────
    print("\nSTEP 3 — Localizzazione clienti")
    clienti = carica_clienti()
    finder  = CompetitorFinder(df_mimit)
    # Il geocoder serve solo per i clienti senza id_impianto
    geo = Geocoder() if any(not c.get('id_impianto') for c in clienti) else None
    clienti_geo = localizza_clienti(clienti, df_mimit, finder, geo)

    # ── 4-5-6. Loop clienti ────────────────────────────────
    print(f"\nSTEP 4 — Elaborazione e invio report")
    analyzer = PricingAnalyzer(df_mimit)
    notifier = PricingNotifier()

    esiti = {'inviata': 0, 'saltata': 0, 'errore': 0, 'non localizzato': 0}

    for cliente in clienti_geo:
        nome = cliente['nome']

        if not cliente.get('localizzato'):
            print(f"  ⚠️  {nome} — impossibile localizzare, skip")
            esiti['non localizzato'] += 1
            continue

        print(f"\n  → {nome}")

        # TUTTI i competitor nel raggio, cliente escluso
        competitor = finder.competitor_per_carburante(
            lat_cliente = cliente['lat'],
            lon_cliente = cliente['lon'],
            raggio_km   = cliente['raggio_km'],
            carburanti  = cliente['carburanti'],
            is_self     = cliente['is_self'],
            escludi_id  = cliente.get('id_impianto'),
        )

        # Analisi posizionamento
        report = analyzer.analizza(cliente, competitor)

        # Anteprima HTML del report (cartella output/, ignorata da git)
        os.makedirs("output", exist_ok=True)
        preview_path = f"output/preview_{cliente['id']}.html"
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(notifier._template_html(report))
        print(f"     💾 Preview salvata → {preview_path}")

        # Stampa summary a console
        for riga in report['summary']:
            print(f"     {riga}")

        # Invia email
        esiti[notifier.invia_report(report)] += 1

    # ── Fine ───────────────────────────────────────────────
    print("\n" + "=" * 55)
    print(f"  COMPLETATO — {esiti['inviata']} inviate, "
          f"{esiti['saltata']} saltate (email non configurata), "
          f"{esiti['errore']} errori invio, "
          f"{esiti['non localizzato']} clienti non localizzati")
    print("=" * 55)


if __name__ == "__main__":
    main()