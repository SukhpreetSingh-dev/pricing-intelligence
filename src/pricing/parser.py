"""
MimitParser — legge e pulisce i CSV MIMIT, produce DataFrame pronti all'uso.
"""

import pandas as pd
import numpy as np
from typing import Optional


# Carburanti standard che ci interessano — mappa nomi MIMIT → nomi nostri
CARBURANTI_MAP = {
    'Benzina':  'benzina',
    'Gasolio':  'gasolio',
    'GPL':      'gpl',
    'Metano':   'metano',
}


class MimitParser:
    """
    Legge i CSV MIMIT e produce DataFrame puliti.

    Uso:
        parser = MimitParser(path_anagrafica, path_prezzi)
        df = parser.parse()   # DataFrame unificato pronto all'uso
    """

    def __init__(self, path_anagrafica: str, path_prezzi: str):
        self.path_anagrafica = path_anagrafica
        self.path_prezzi     = path_prezzi

    def parse(self) -> pd.DataFrame:
        """
        Legge, pulisce e unisce anagrafica + prezzi.
        Restituisce un DataFrame con una riga per ogni
        combinazione (impianto, carburante, self/servito).
        """
        df_ana = self._leggi_anagrafica()
        df_prez = self._leggi_prezzi()
        df = self._merge(df_ana, df_prez)
        return df

    def anagrafica(self) -> pd.DataFrame:
        """Restituisce solo l'anagrafica pulita."""
        return self._leggi_anagrafica()

    def prezzi(self) -> pd.DataFrame:
        """Restituisce solo i prezzi puliti."""
        return self._leggi_prezzi()

    # =============================================
    # METODI PRIVATI
    # =============================================

    def _leggi_anagrafica(self) -> pd.DataFrame:
        """Legge e pulisce il file anagrafica."""
        df = pd.read_csv(
            self.path_anagrafica,
            sep='|',
            skiprows=1,
            header=0,
            on_bad_lines='skip',
            engine='python',
            dtype={'idImpianto': str}
        )

        # Pulisci nomi colonne
        df.columns = [c.strip() for c in df.columns]

        # Rinomina per comodità
        df = df.rename(columns={
            'idImpianto':   'id_impianto',
            'Gestore':      'gestore',
            'Bandiera':     'bandiera',
            'Tipo Impianto':'tipo',
            'Nome Impianto':'nome',
            'Indirizzo':    'indirizzo',
            'Comune':       'comune',
            'Provincia':    'provincia',
            'Latitudine':   'lat',
            'Longitudine':  'lon',
        })

        # Converti coordinate in float
        df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
        df['lon'] = pd.to_numeric(df['lon'], errors='coerce')

        # Rimuovi righe senza coordinate GPS
        df = df.dropna(subset=['lat', 'lon'])

        # Rimuovi duplicati
        df = df.drop_duplicates(subset=['id_impianto'])

        print(f"  Anagrafica: {len(df):,} impianti caricati")
        return df

    def _leggi_prezzi(self) -> pd.DataFrame:
        """Legge e pulisce il file prezzi."""
        df = pd.read_csv(
            self.path_prezzi,
            sep='|',
            skiprows=1,
            header=0,
            on_bad_lines='skip',
            engine='python',
            dtype={'idImpianto': str}
        )

        df.columns = [c.strip() for c in df.columns]

        df = df.rename(columns={
            'idImpianto':    'id_impianto',
            'descCarburante':'carburante_raw',
            'prezzo':        'prezzo',
            'isSelf':        'is_self',
            'dtComu':        'data_comunicazione',
        })

        # Converti prezzo in float
        df['prezzo'] = pd.to_numeric(df['prezzo'], errors='coerce')

        # Filtra solo i 4 carburanti che ci interessano
        df = df[df['carburante_raw'].isin(CARBURANTI_MAP.keys())].copy()

        # Aggiungi nome standardizzato
        df['carburante'] = df['carburante_raw'].map(CARBURANTI_MAP)

        # Rimuovi prezzi assurdi (< 0.5 o > 5.0 €/L)
        df = df[(df['prezzo'] > 0.5) & (df['prezzo'] < 5.0)]

        # Converti is_self in bool
        df['is_self'] = df['is_self'].astype(int).astype(bool)

        print(f"  Prezzi: {len(df):,} righe caricate "
              f"({df['carburante'].nunique()} carburanti)")
        return df

    def _merge(self, df_ana: pd.DataFrame,
               df_prez: pd.DataFrame) -> pd.DataFrame:
        """Unisce anagrafica e prezzi su id_impianto."""
        df = df_prez.merge(df_ana, on='id_impianto', how='inner')
        print(f"  Merge: {len(df):,} righe finali")
        return df