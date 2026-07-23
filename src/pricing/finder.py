"""
CompetitorFinder — trova i competitor entro un raggio usando Haversine.
"""

import numpy as np
import pandas as pd
from typing import Optional


class CompetitorFinder:
    """
    Trova i distributori competitor entro un raggio dal cliente.

    Uso:
        finder = CompetitorFinder(df_mimit)
        competitor = finder.trova(lat, lon, raggio_km=10)
    """

    RAGGIO_TERRA_KM = 6371.0

    def __init__(self, df_mimit: pd.DataFrame):
        """
        df_mimit: DataFrame unificato da MimitParser.parse()
        """
        self.df = df_mimit
        # Pre-converti coordinate in radianti per velocità
        self._lat_rad = np.radians(df_mimit['lat'].values)
        self._lon_rad = np.radians(df_mimit['lon'].values)

    def trova(self,
              lat_cliente: float,
              lon_cliente: float,
              raggio_km: float,
              carburanti: Optional[list] = None,
              is_self: Optional[bool] = True) -> pd.DataFrame:
        """
        Trova tutti i distributori entro il raggio dal punto cliente.

        Args:
            lat_cliente: latitudine del cliente
            lon_cliente: longitudine del cliente
            raggio_km:   raggio di ricerca in km
            carburanti:  lista carburanti da filtrare (None = tutti)
            is_self:     True = solo self-service, False = solo servito

        Restituisce DataFrame con colonna 'distanza_km' aggiunta.
        """
        # Calcola distanze con Haversine vettoriale
        distanze = self._haversine_vettoriale(lat_cliente, lon_cliente)

        # Filtra per raggio
        df = self.df.copy()
        df['distanza_km'] = distanze
        df = df[df['distanza_km'] <= raggio_km].copy()

        # Filtra per tipo (self/servito)
        if is_self is not None:
            df = df[df['is_self'] == is_self]

        # Filtra per carburanti
        if carburanti:
            df = df[df['carburante'].isin(carburanti)]

        # Ordina per distanza
        df = df.sort_values('distanza_km').reset_index(drop=True)

        return df
    def top_n_per_carburante(self,
                              lat_cliente: float,
                              lon_cliente: float,
                              raggio_km: float,
                              carburanti: list,
                              top_n: int = 5,
                              is_self: bool = True) -> dict:
        """
        Per ogni carburante restituisce i Top N più economici
        entro il raggio.
        GPL e Metano ignorano il filtro is_self — quasi sempre servito.
        """
        # Carburanti che non hanno self-service — ignora filtro
        SEMPRE_SERVITO = {'gpl', 'metano'}

        risultati = {}
        for carburante in carburanti:
            # Per GPL e Metano prendi sia self che servito
            is_self_filtro = None if carburante in SEMPRE_SERVITO else is_self

            competitor = self.trova(
                lat_cliente, lon_cliente,
                raggio_km,
                [carburante],
                is_self_filtro
            )

            if competitor.empty:
                risultati[carburante] = pd.DataFrame()
                continue

            df_carb = competitor.sort_values('prezzo').head(top_n)
            df_carb = df_carb.reset_index(drop=True)
            df_carb.index += 1

            risultati[carburante] = df_carb

        return risultati

    def _haversine_vettoriale(self,
                               lat1: float,
                               lon1: float) -> np.ndarray:
        """
        Calcola la distanza in km tra (lat1, lon1) e tutti
        i punti del DataFrame in modo vettoriale con NumPy.
        """
        lat1_rad = np.radians(lat1)
        lon1_rad = np.radians(lon1)

        dlat = self._lat_rad - lat1_rad
        dlon = self._lon_rad - lon1_rad

        a = (np.sin(dlat / 2) ** 2 +
             np.cos(lat1_rad) * np.cos(self._lat_rad) *
             np.sin(dlon / 2) ** 2)

        c = 2 * np.arcsin(np.sqrt(a))
        return self.RAGGIO_TERRA_KM * c