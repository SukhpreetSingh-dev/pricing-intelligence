"""
Diagnostica — controlla i dati MIMIT e i calcoli per i clienti in clienti.json.

Non manda email e non modifica niente: legge, calcola e stampa.
Serve a verificare che il report dica il vero prima di automatizzarlo.

Uso (dalla cartella del progetto, con il venv attivo):
    python strumenti/diagnostica.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.pricing.analyzer import MAX_ETA_GIORNI_DEFAULT, data_riferimento, eta_giorni
from src.pricing.clienti import localizza_clienti
from src.pricing.downloader import MimitDownloader
from src.pricing.finder import CompetitorFinder
from src.pricing.parser import CARBURANTI_MAP, MimitParser

FASCE = [-1, 0, 1, 2, 3, 7, 14, 10**6]
NOMI_FASCE = ['oggi', '1 g', '2 g', '3 g', '4-7 g', '8-14 g', '>14 g']


def titolo(testo: str) -> None:
    print(f"\n{'=' * 70}\n{testo}\n{'=' * 70}")


def prima_riga(path: str) -> str:
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.readline().strip()


def leggi_prezzi_grezzi(path: str) -> pd.DataFrame:
    """Il file prezzi cosi' com'e', senza filtri: serve a vedere cosa scartiamo."""
    df = pd.read_csv(path, sep='|', skiprows=1, header=0, on_bad_lines='skip',
                     engine='python', dtype=str)
    df.columns = [c.strip() for c in df.columns]
    return df


def controlli_dataset(paths: dict, df: pd.DataFrame, grezzi: pd.DataFrame) -> pd.Timestamp:
    titolo("1. DATASET MIMIT")
    print(f"Anagrafica: {prima_riga(paths['anagrafica'])}")
    print(f"Prezzi:     {prima_riga(paths['prezzi'])}")

    date = df['data_comunicazione']
    rif = data_riferimento(date)
    print(f"\nRighe prezzi grezze: {len(grezzi):,}  ->  usate (4 carburanti, unite all'anagrafica): {len(df):,}")
    print(f"Date di comunicazione non leggibili: {date.isna().sum():,}"
          f"  (se sono tante, il formato data MIMIT e' cambiato)")
    print(f"Comunicazione piu' vecchia: {date.min()}")
    print(f"Comunicazione piu' recente: {date.max()}")
    print(f"Riferimento usato come 'oggi': {rif}  (la piu' recente non nel futuro)")
    oggi = pd.Timestamp.now()
    futuro = (date > oggi).sum()
    print(f"Date nel futuro rispetto all'orologio del computer: {futuro}"
          f"  (dovrebbe essere 0)")

    eta = eta_giorni(date, rif)
    fasce = pd.cut(eta, FASCE, labels=NOMI_FASCE).value_counts(sort=False)
    print("\nEta' dei prezzi in tutta Italia (quanti giorni fa sono stati comunicati):")
    for nome, n in fasce.items():
        print(f"  {nome:>10}: {n:>7,}  ({n / len(df) * 100:4.1f}%)")

    dup = df.duplicated(['id_impianto', 'carburante', 'is_self'], keep=False).sum()
    print(f"\nRighe doppie (stesso impianto, carburante, self/servito): {dup:,}"
          f"  (dovrebbe essere 0)")

    simili = grezzi['descCarburante'].str.contains('benzina|gasolio|diesel|gpl|metano',
                                                   case=False, na=False)
    ignorati = grezzi.loc[simili & ~grezzi['descCarburante'].isin(CARBURANTI_MAP.keys()),
                          'descCarburante'].value_counts().head(12)
    print("\nNomi di carburante simili che IGNORIAMO (usiamo solo "
          f"{', '.join(CARBURANTI_MAP)}):")
    for nome, n in ignorati.items():
        print(f"  {n:>6,}  {nome}")
    return rif


def controlli_cliente(c: dict, df: pd.DataFrame, grezzi: pd.DataFrame,
                      finder: CompetitorFinder, rif: pd.Timestamp) -> None:
    titolo(f"CLIENTE: {c['nome']}  (id_impianto {c.get('id_impianto')})")
    if not c.get('localizzato'):
        print("  NON localizzato: controlla id_impianto in clienti.json")
        return

    info = c.get('impianto') or {}
    print(f"Impianto MIMIT: {info.get('bandiera')} - {info.get('gestore')}")
    print(f"                {info.get('indirizzo')}, {info.get('comune')} ({info.get('provincia')})")
    print(f"Raggio {c['raggio_km']} km, top {c['top_n']}, "
          f"{'self' if c.get('is_self', True) else 'servito'}, "
          f"prezzi piu' vecchi di {c.get('max_eta_giorni', MAX_ETA_GIORNI_DEFAULT)} gg esclusi")

    print("\nTUTTI i prezzi comunicati da questo impianto (file grezzo):")
    suoi = grezzi[grezzi['idImpianto'] == str(c['id_impianto'])]
    if suoi.empty:
        print("  nessuno!")
    for _, r in suoi.iterrows():
        tipo = 'self   ' if str(r['isSelf']).strip() == '1' else 'servito'
        print(f"  {r['descCarburante']:<28} {tipo} {r['prezzo']:>7}  comunicato {r['dtComu']}")

    max_eta = c.get('max_eta_giorni', MAX_ETA_GIORNI_DEFAULT)
    tutti = finder.competitor_per_carburante(c['lat'], c['lon'], c['raggio_km'],
                                             c['carburanti'], c.get('is_self', True),
                                             c['id_impianto'])
    for carb in c['carburanti']:
        comp = tutti[carb].copy()
        print(f"\n--- {carb.upper()}: {len(comp)} righe di competitor nel raggio ---")
        if comp.empty:
            continue
        comp['eta'] = eta_giorni(comp['data_comunicazione'], rif)
        fasce = pd.cut(comp['eta'], FASCE, labels=NOMI_FASCE).value_counts(sort=False)
        print("  Eta' dei prezzi: " + ", ".join(f"{k} {v}" for k, v in fasce.items() if v))
        esclusi = (comp['eta'] > max_eta).sum()
        print(f"  Esclusi perche' piu' vecchi di {max_eta} gg: {esclusi} su {len(comp)}")
        senza_data = comp['eta'].isna().sum()
        if senza_data:
            print(f"  Senza data leggibile (esclusi dal report): {senza_data}")
        print("  I 5 piu' economici (anche quelli esclusi), da confrontare col sito MIMIT:")
        for _, r in comp.head(5).iterrows():
            tipo = 'self' if r['is_self'] else 'serv'
            print(f"    {r['prezzo']:.3f}  {tipo}  {r['eta']:>3.0f} gg  "
                  f"{r['distanza_km']:4.1f} km  id {r['id_impianto']:<6} "
                  f"{r['bandiera']} - {r['indirizzo']}, {r['comune']}")


def main() -> None:
    if not os.path.exists('clienti.json'):
        sys.exit("clienti.json non trovato: lancia lo script dalla cartella del progetto")

    paths = MimitDownloader(data_dir='data/raw').scarica()
    df = MimitParser(paths['anagrafica'], paths['prezzi']).parse()
    grezzi = leggi_prezzi_grezzi(paths['prezzi'])
    rif = controlli_dataset(paths, df, grezzi)

    with open('clienti.json', encoding='utf-8') as f:
        clienti = json.load(f)
    finder = CompetitorFinder(df)
    for c in localizza_clienti(clienti, df, finder, geocoder=None):
        controlli_cliente(c, df, grezzi, finder, rif)

    print("\nFine diagnostica: nessuna email inviata, nessun file modificato.")


if __name__ == '__main__':
    main()
