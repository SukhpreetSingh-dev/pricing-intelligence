"""
MimitDownloader — scarica i dati ufficiali MIMIT ogni giorno.
"""

import os
import glob
import re
import requests
from datetime import date, datetime, timedelta
from requests.exceptions import RequestException

URL_ANAGRAFICA = "https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"
URL_PREZZI = "https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv"


def data_estrazione(path: str):
    """
    Data dei prezzi contenuti nel file, letta dalla prima riga
    ('Estrazione del 2026-10-25'). MIMIT pubblica ogni giorno i prezzi
    in vigore alle 8:00 del giorno PRIMA. None se la riga non c'e'.
    """
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            m = re.search(r'(\d{4}-\d{2}-\d{2})', f.readline())
        return datetime.strptime(m.group(1), '%Y-%m-%d').date() if m else None
    except OSError:
        return None


class DownloadError(Exception):
    """Sollevata quando il download fallisce e non esiste una cache utilizzabile."""


class MimitDownloader:
    """
    Scarica i file CSV dal portale open data MIMIT.

    Uso:
        downloader = MimitDownloader(data_dir="data/raw")
        paths = downloader.scarica()
    """

    def __init__(self, data_dir: str = "data/raw"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    def scarica(self) -> dict:
        """Scarica anagrafica e prezzi. Restituisce i path dei file utilizzati."""
        oggi = datetime.now().strftime("%Y%m%d")

        path_anagrafica = os.path.join(self.data_dir, f"anagrafica_{oggi}.csv")
        path_prezzi = os.path.join(self.data_dir, f"prezzi_{oggi}.csv")

        print("Scaricamento dati MIMIT...")
        anagrafica = self._scarica_file(
            URL_ANAGRAFICA, path_anagrafica, "Anagrafica impianti", "anagrafica"
        )
        prezzi = self._scarica_file(
            URL_PREZZI, path_prezzi, "Prezzi alle 8", "prezzi"
        )

        return {'anagrafica': anagrafica, 'prezzi': prezzi}

    def _scarica_file(self, url: str, path: str, nome: str, prefisso: str) -> str:
        """
        Scarica un file e lo salva. In caso di errore di rete ripiega
        sul file più recente già presente in cache.
        """
        if os.path.exists(path):
            if self._cache_aggiornata(path):
                print(f"  {nome} già scaricato oggi — skip")
                return path
            # Scaricato stamattina prima che MIMIT pubblicasse i dati nuovi:
            # lo riscarichiamo, altrimenti resteremmo indietro tutto il giorno.
            print(f"  {nome}: la copia di oggi ha ancora i dati vecchi — riscarico")

        print(f"  Scaricamento {nome}...")
        try:
            risposta = requests.get(url, timeout=30)
            risposta.raise_for_status()
        except RequestException as errore:
            print(f"  ⚠️  {nome}: download non riuscito ({type(errore).__name__})")
            cache = self._cache_piu_recente(prefisso)
            if cache:
                print(f"      Uso i dati in cache: {os.path.basename(cache)}")
                return cache
            raise DownloadError(
                f"{nome} non scaricabile e nessuna cache disponibile"
            ) from errore

        with open(path, 'wb') as f:
            f.write(risposta.content)

        size_kb = len(risposta.content) / 1024
        print(f"  ✅ {nome} salvato ({size_kb:.0f} KB) → {path}")
        return path

    @staticmethod
    def _cache_aggiornata(path: str) -> bool:
        """True se il file contiene i prezzi di ieri, cioe' gli ultimi pubblicabili."""
        estrazione = data_estrazione(path)
        return estrazione is not None and estrazione >= date.today() - timedelta(days=1)

    def _cache_piu_recente(self, prefisso: str) -> str | None:
        """Restituisce il file più recente in cache per il prefisso dato."""
        candidati = glob.glob(os.path.join(self.data_dir, f"{prefisso}_*.csv"))
        return max(candidati, key=os.path.getmtime) if candidati else None