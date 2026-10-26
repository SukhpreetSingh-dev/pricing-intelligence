"""
Pricing Intelligence — Entry point principale.

Uso:
    python3 main.py                  # lancio a mano: manda sempre il report
    python3 main.py --automatico     # da cron: una sola volta al giorno, solo
                                     # quando MIMIT ha pubblicato i prezzi di ieri
    python3 main.py --automatico --anche-se-vecchi
                                     # ultimo tentativo della mattina: manda
                                     # comunque, con i prezzi piu' recenti che ci sono

Cosa fa:
    1. Scarica i dati MIMIT aggiornati
    2. Parsa anagrafica e prezzi
    3. Collega ogni cliente al suo impianto MIMIT (id_impianto o indirizzo)
    4. Per ogni cliente trova TUTTI i competitor nel raggio, per carburante
    5. Analizza il posizionamento (statistiche sul raggio, tabella sul Top N)
    6. Manda l'email di report
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

from src.pricing.downloader import MimitDownloader, data_estrazione
from src.pricing.parser import MimitParser
from src.pricing.geocoder import Geocoder
from src.pricing.finder import CompetitorFinder
from src.pricing.clienti import localizza_clienti
from src.pricing.analyzer import PricingAnalyzer
from src.pricing.notifier import PricingNotifier


CLIENTI_PATH = "clienti.json"
CARTELLA_SEGNALI = "output"


def segnale_inviato(oggi: date) -> str:
    """File che segna 'report di oggi gia' inviato' (evita doppi invii da cron)."""
    return os.path.join(CARTELLA_SEGNALI, f".inviato_{oggi:%Y%m%d}")


def decidi_invio(oggi: date, estrazione, gia_inviato: bool,
                 anche_se_vecchi: bool) -> tuple[bool, str]:
    """
    In modalita' automatica: procedere o aspettare il prossimo tentativo?

    MIMIT pubblica ogni mattina i prezzi delle 8:00 del giorno prima, a un
    orario non dichiarato. Cron prova piu' volte: si manda appena i dati
    sono quelli di ieri, una sola volta al giorno.
    """
    if gia_inviato:
        return False, "report di oggi gia' inviato"
    aggiornati = estrazione is not None and estrazione >= oggi - timedelta(days=1)
    if aggiornati:
        return True, "prezzi di ieri disponibili"
    if anche_se_vecchi:
        return True, "ultimo tentativo: invio con i prezzi piu' recenti disponibili"
    return False, "MIMIT non ha ancora pubblicato i prezzi di ieri: riprovo al prossimo giro"


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
    args = argparse.ArgumentParser(description="Report prezzi carburanti")
    args.add_argument("--automatico", action="store_true",
                      help="una volta al giorno, solo con i prezzi di ieri (per cron)")
    args.add_argument("--anche-se-vecchi", action="store_true",
                      help="con --automatico: manda anche se i prezzi non sono di ieri")
    args = args.parse_args()
    oggi = date.today()

    if args.automatico and os.path.exists(segnale_inviato(oggi)):
        print(f"{datetime.now():%d/%m/%Y %H:%M} — report di oggi gia' inviato, niente da fare")
        return

    print("=" * 55)
    print("  PRICING INTELLIGENCE — AVVIO")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 55)

    # ── 1. Scarica dati MIMIT ───────────────────────────────
    print("\nSTEP 1 — Download dati MIMIT")
    downloader = MimitDownloader(data_dir="data/raw")
    paths = downloader.scarica()
    estrazione = data_estrazione(paths['prezzi'])
    print(f"  Prezzi MIMIT in vigore alle 8:00 del {estrazione:%d/%m/%Y}" if estrazione
          else "  ⚠️  Data dei prezzi non leggibile nel file MIMIT")
    if args.automatico:
        procedi, motivo = decidi_invio(oggi, estrazione, False, args.anche_se_vecchi)
        print(f"  Modalita' automatica: {motivo}")
        if not procedi:
            return
    elif estrazione and estrazione < oggi - timedelta(days=1):
        print("  ⚠️  MIMIT non ha ancora pubblicato i prezzi di ieri: "
              "il report usera' quelli piu' recenti disponibili")

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
        report['estrazione'] = estrazione

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

    # In automatico: segna il giorno come fatto solo se almeno una mail e' partita.
    # Se l'invio fallisce (es. rete giu'), il prossimo giro di cron riprova.
    if args.automatico and esiti['inviata'] > 0:
        os.makedirs(CARTELLA_SEGNALI, exist_ok=True)
        with open(segnale_inviato(oggi), "w") as f:
            f.write(datetime.now().isoformat())


if __name__ == "__main__":
    main()