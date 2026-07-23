"""
MimitDownloader — scarica i dati ufficiali MIMIT ogni giorno.
"""

import os
import requests
from datetime import datetime


# URL ufficiali MIMIT
URL_ANAGRAFICA = "https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"
URL_PREZZI     = "https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv"


class MimitDownloader:
    """
    Scarica i file CSV dal portale open data MIMIT.

    Uso:
        downloader = MimitDownloader(data_dir="data/raw")
        paths = downloader.scarica()
        print(paths['anagrafica'], paths['prezzi'])
    """

    def __init__(self, data_dir: str = "data/raw"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    def scarica(self) -> dict:
        """
        Scarica anagrafica e prezzi dal MIMIT.
        Restituisce i path dei file salvati.
        """
        oggi = datetime.now().strftime("%Y%m%d")

        path_anagrafica = os.path.join(self.data_dir, f"anagrafica_{oggi}.csv")
        path_prezzi     = os.path.join(self.data_dir, f"prezzi_{oggi}.csv")

        print("Scaricamento dati MIMIT...")
        self._scarica_file(URL_ANAGRAFICA, path_anagrafica, "Anagrafica impianti")
        self._scarica_file(URL_PREZZI,     path_prezzi,     "Prezzi alle 8")

        return {'anagrafica': path_anagrafica, 'prezzi': path_prezzi}

    def _scarica_file(self, url: str, path: str, nome: str) -> None:
        """Scarica un singolo file e lo salva su disco."""

        # Se esiste già oggi non riscarica
        if os.path.exists(path):
            print(f"  {nome} già scaricato oggi — skip")
            return

        print(f"  Scaricamento {nome}...")
        risposta = requests.get(url, timeout=30)

        if risposta.status_code != 200:
            raise ConnectionError(
                f"Errore download {nome}: HTTP {risposta.status_code}"
            )

        with open(path, 'wb') as f:
            f.write(risposta.content)

        size_kb = len(risposta.content) / 1024
        print(f"  ✅ {nome} salvato ({size_kb:.0f} KB) → {path}")