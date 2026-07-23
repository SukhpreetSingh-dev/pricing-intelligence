"""
PricingAnalyzer — analizza il posizionamento del cliente vs competitor.
"""

import pandas as pd
import numpy as np
from typing import Optional


class PricingAnalyzer:
    """
    Analizza il posizionamento prezzi del cliente rispetto ai competitor.

    Uso:
        analyzer = PricingAnalyzer()
        report = analyzer.analizza(cliente, risultati_finder, df_mimit)
    """

    def analizza(self,
                 cliente: dict,
                 top_n: dict,
                 df_mimit: pd.DataFrame) -> dict:
        """
        Produce il report completo di posizionamento per un cliente.

        Args:
            cliente:    dict con dati cliente (lat, lon, carburanti...)
            top_n:      output di CompetitorFinder.top_n_per_carburante()
            df_mimit:   DataFrame completo MIMIT

        Restituisce dict con analisi per ogni carburante.
        """
        report = {
            'cliente':    cliente,
            'carburanti': {},
            'summary':    [],
        }

        for carburante in cliente['carburanti']:
            df_top = top_n.get(carburante, pd.DataFrame())
            analisi = self._analizza_carburante(
                carburante, df_top, cliente, df_mimit
            )
            report['carburanti'][carburante] = analisi

            # Summary testuale
            if analisi['prezzo_cliente'] is not None:
                report['summary'].append(
                    self._genera_summary(carburante, analisi)
                )

        return report

    def _analizza_carburante(self,
                              carburante: str,
                              df_top: pd.DataFrame,
                              cliente: dict,
                              df_mimit: pd.DataFrame) -> dict:
        """Analizza un singolo carburante."""

        # Trova il prezzo del cliente nel dataset MIMIT
        prezzo_cliente = self._trova_prezzo_cliente(
            cliente, carburante, df_mimit
        )

        if df_top.empty:
            return {
                'prezzo_cliente':   prezzo_cliente,
                'n_competitor':     0,
                'prezzo_min':       None,
                'prezzo_medio':     None,
                'prezzo_max':       None,
                'posizione':        None,
                'totale':           None,
                'diff_vs_min':      None,
                'diff_vs_media':    None,
                'raccomandazione':  '⚠️ Nessun competitor trovato nel raggio',
                'top_n':            df_top,
            }

        # Trova tutti competitor nel raggio per statistiche complete
        df_zona = df_mimit[
            df_mimit['carburante'] == carburante
        ].copy()

        prezzo_min   = df_top['prezzo'].min()
        prezzo_medio = df_top['prezzo'].mean()
        prezzo_max   = df_top['prezzo'].max()
        n_competitor = len(df_top)

        # Calcola posizione e differenziali se abbiamo il prezzo cliente
        posizione       = None
        diff_vs_min     = None
        diff_vs_media   = None
        raccomandazione = ''

        if prezzo_cliente is not None:
            diff_vs_min   = round((prezzo_cliente - prezzo_min) * 100, 1)
            diff_vs_media = round((prezzo_cliente - prezzo_medio) * 100, 1)

            # Calcola posizione nella classifica completa zona
            prezzi_zona = df_zona['prezzo'].dropna().sort_values().values
            posizione   = int(np.searchsorted(prezzi_zona, prezzo_cliente)) + 1
            totale      = len(prezzi_zona)

            raccomandazione = self._raccomandazione(
                posizione, totale, diff_vs_min, diff_vs_media
            )
        else:
            totale = None
            raccomandazione = '⚠️ Prezzo cliente non trovato nei dati MIMIT'

        return {
            'prezzo_cliente':  prezzo_cliente,
            'n_competitor':    n_competitor,
            'prezzo_min':      round(prezzo_min, 3),
            'prezzo_medio':    round(prezzo_medio, 3),
            'prezzo_max':      round(prezzo_max, 3),
            'posizione':       posizione,
            'totale':          totale,
            'diff_vs_min':     diff_vs_min,
            'diff_vs_media':   diff_vs_media,
            'raccomandazione': raccomandazione,
            'top_n':           df_top,
        }

    def _trova_prezzo_cliente(self,
                               cliente: dict,
                               carburante: str,
                               df_mimit: pd.DataFrame) -> Optional[float]:
        """
        Cerca il prezzo del cliente nel dataset MIMIT usando
        le sue coordinate GPS — trova l'impianto più vicino.
        """
        if 'lat' not in cliente or cliente['lat'] is None:
            return None

        df_carb = df_mimit[
            (df_mimit['carburante'] == carburante) &
            (df_mimit['is_self'] == cliente.get('is_self', True))
        ].copy()

        if df_carb.empty:
            return None

        # Trova l'impianto MIMIT più vicino alle coordinate del cliente
        lat_c = cliente['lat']
        lon_c = cliente['lon']

        df_carb['dist_tmp'] = np.sqrt(
            (df_carb['lat'] - lat_c) ** 2 +
            (df_carb['lon'] - lon_c) ** 2
        )

        idx_min = df_carb['dist_tmp'].idxmin()
        dist_min = df_carb.loc[idx_min, 'dist_tmp']

        # Accetta solo se la distanza è ragionevole (< 0.05 gradi ~ 5km)
        if dist_min > 0.05:
            return None

        return float(df_carb.loc[idx_min, 'prezzo'])

    def _raccomandazione(self,
                          posizione: int,
                          totale: int,
                          diff_vs_min: float,
                          diff_vs_media: float) -> str:
        """Genera una raccomandazione testuale basata sul posizionamento."""
        pct_pos = posizione / totale * 100 if totale > 0 else 50

        if pct_pos <= 20:
            return '🟢 Ottimo posizionamento — sei tra i più economici della zona'
        elif pct_pos <= 40:
            return '🟡 Buon posizionamento — leggermente sotto la media'
        elif pct_pos <= 60:
            return f'🟠 Posizionamento medio — +{diff_vs_media:.1f} cent vs media zona'
        elif pct_pos <= 80:
            return f'🔴 Posizionamento alto — +{diff_vs_min:.1f} cent vs più economico'
        else:
            return f'🔴 Attenzione — sei tra i più cari della zona (+{diff_vs_min:.1f} cent)'

    def _genera_summary(self, carburante: str, analisi: dict) -> str:
        """Genera una riga di summary per il carburante."""
        if analisi['prezzo_cliente'] is None:
            return f"{carburante.upper()}: prezzo non disponibile"

        pos  = analisi['posizione']
        tot  = analisi['totale']
        diff = analisi['diff_vs_min']

        return (
            f"{carburante.upper()}: "
            f"€{analisi['prezzo_cliente']:.3f}/L — "
            f"posizione {pos}/{tot} — "
            f"{'+' if diff >= 0 else ''}{diff:.1f} cent vs più economico"
        )