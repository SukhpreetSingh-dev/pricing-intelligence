"""
CompetitorFinder — trova i competitor entro un raggio usando Haversine.
"""

from typing import Optional

import numpy as np
import pandas as pd


# GPL e metano sono quasi sempre solo serviti: per questi carburanti
# il filtro self/servito va ignorato. Unica regola, usata da finder e analyzer.
SEMPRE_SERVITO = {'gpl', 'metano'}

RAGGIO_TERRA_KM = 6371.0


def filtro_self(carburante: str, is_self: Optional[bool]) -> Optional[bool]:
    """
    Restituisce il filtro self/servito da applicare per un carburante.
    None = nessun filtro (prendi sia self che servito).
    """
    return None if carburante in SEMPRE_SERVITO else is_self


def haversine_km(lat1: float, lon1: float,
                 lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    """Distanza in km tra un punto e un array di punti (vettoriale)."""
    lat1, lon1 = np.radians(lat1), np.radians(lon1)
    lat2, lon2 = np.radians(lat2), np.radians(lon2)
    a = (np.sin((lat2 - lat1) / 2) ** 2 +
         np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 2 * RAGGIO_TERRA_KM * np.arcsin(np.sqrt(a))


class CompetitorFinder:
    """
    Trova i distributori competitor entro un raggio dal cliente.

    Uso:
        finder = CompetitorFinder(df_mimit)
        per_carb = finder.competitor_per_carburante(lat, lon, 10,
                                                    ['benzina'], is_self=True,
                                                    escludi_id='12345')
    """

    def __init__(self, df_mimit: pd.DataFrame):
        """df_mimit: DataFrame unificato da MimitParser.parse()"""
        self.df = df_mimit

    def trova(self,
              lat_cliente: float,
              lon_cliente: float,
              raggio_km: float,
              carburanti: Optional[list] = None,
              is_self: Optional[bool] = True,
              escludi_id: Optional[str] = None) -> pd.DataFrame:
        """
        Tutti i distributori entro il raggio dal punto cliente.

        Args:
            is_self:    True = solo self, False = solo servito, None = entrambi
            escludi_id: id_impianto del cliente, da togliere dai competitor

        Restituisce DataFrame con colonna 'distanza_km', ordinato per distanza.
        """
        df = self.df.copy()
        df['distanza_km'] = haversine_km(lat_cliente, lon_cliente,
                                         df['lat'].values, df['lon'].values)
        df = df[df['distanza_km'] <= raggio_km]

        if is_self is not None:
            df = df[df['is_self'] == is_self]

        if carburanti:
            df = df[df['carburante'].isin(carburanti)]

        if escludi_id is not None:
            df = df[df['id_impianto'] != str(escludi_id)]

        return df.sort_values('distanza_km').reset_index(drop=True)

    def competitor_per_carburante(self,
                                  lat_cliente: float,
                                  lon_cliente: float,
                                  raggio_km: float,
                                  carburanti: list,
                                  is_self: bool = True,
                                  escludi_id: Optional[str] = None) -> dict:
        """
        Per ogni carburante: TUTTI i competitor nel raggio, ordinati per prezzo.
        Sono la base per le statistiche (posizione, media, min, max).
        Il Top N per la tabella si ottiene poi con .head(n).
        """
        risultati = {}
        for carburante in carburanti:
            df = self.trova(lat_cliente, lon_cliente, raggio_km,
                            [carburante],
                            filtro_self(carburante, is_self),
                            escludi_id)
            risultati[carburante] = (df.sort_values(['prezzo', 'distanza_km'])
                                       .reset_index(drop=True))
        return risultati

    def top_n_per_carburante(self,
                             lat_cliente: float,
                             lon_cliente: float,
                             raggio_km: float,
                             carburanti: list,
                             top_n: int = 5,
                             is_self: bool = True,
                             escludi_id: Optional[str] = None) -> dict:
        """Solo i Top N piu' economici per carburante (per la tabella)."""
        tutti = self.competitor_per_carburante(lat_cliente, lon_cliente,
                                               raggio_km, carburanti,
                                               is_self, escludi_id)
        risultati = {}
        for carburante, df in tutti.items():
            df_top = df.head(top_n).reset_index(drop=True)
            df_top.index += 1
            risultati[carburante] = df_top
        return risultati

    def impianto_piu_vicino(self, lat: float, lon: float,
                            max_km: float) -> Optional[str]:
        """
        id_impianto dell'impianto MIMIT piu' vicino al punto, se entro max_km.
        Usato quando il cliente non ha indicato il proprio id_impianto.
        """
        impianti = self.df.drop_duplicates('id_impianto')
        if impianti.empty:
            return None
        dist = haversine_km(lat, lon, impianti['lat'].values,
                            impianti['lon'].values)
        i = int(np.argmin(dist))
        return str(impianti.iloc[i]['id_impianto']) if dist[i] <= max_km else None
