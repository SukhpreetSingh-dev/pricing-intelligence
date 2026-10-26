"""
PricingAnalyzer — analizza il posizionamento del cliente vs competitor nel raggio.
"""

from typing import Optional

import pandas as pd

from src.pricing.finder import filtro_self


# Prezzi comunicati da piu' di questi giorni non entrano nelle statistiche
# (sovrascrivibile per cliente con "max_eta_giorni" in clienti.json).
# 7 e non meno: sui dati reali (ottobre 2026) il 18% dei prezzi italiani ha
# 4-7 giorni ed e' ancora valido (impianti che non cambiano prezzo spesso);
# oltre i 7 giorni resta solo il 2%.
MAX_ETA_GIORNI_DEFAULT = 7


def calcola_posizionamento(prezzo_cliente: float,
                           df_raggio: pd.DataFrame) -> dict:
    """
    Posizione e statistiche del cliente rispetto a TUTTI i competitor passati.

    Regole:
      - prezzo piu' basso = meglio -> posizione 1 = il piu' economico
      - pari merito: chi ha il tuo stesso prezzo NON ti sta davanti
      - posizione e totale includono il cliente: "3 su 19" = 18 competitor + te
      - differenziali in centesimi, 1 decimale
    """
    chiavi = ['posizione', 'prezzo_min', 'prezzo_medio', 'prezzo_max',
              'diff_vs_min', 'diff_vs_media']
    if df_raggio.empty or df_raggio['prezzo'].dropna().empty:
        return {**{k: None for k in chiavi}, 'totale': 0}

    prezzi = df_raggio['prezzo'].dropna()

    return {
        'posizione':     int((prezzi < prezzo_cliente).sum()) + 1,
        'totale':        len(prezzi) + 1,
        'prezzo_min':    round(prezzi.min(), 3),
        'prezzo_medio':  round(prezzi.mean(), 3),
        'prezzo_max':    round(prezzi.max(), 3),
        'diff_vs_min':   round((prezzo_cliente - prezzi.min()) * 100, 1),
        'diff_vs_media': round((prezzo_cliente - prezzi.mean()) * 100, 1),
    }


def aggiungi_rank(df: pd.DataFrame, prezzo_cliente: Optional[float]) -> pd.DataFrame:
    """
    Aggiunge a ogni competitor (gia' ordinati per prezzo):
      - 'rank': posizione nella classifica che INCLUDE il cliente,
                con pari merito (stesso prezzo = stesso numero)
      - 'diff_vs_cliente': centesimi rispetto al cliente
                           (negativo = il competitor costa meno di te)
    """
    df = df.copy()
    if df.empty or 'prezzo' not in df.columns:
        df['rank'] = pd.Series(dtype=int)
        df['diff_vs_cliente'] = pd.Series(dtype=float)
        return df
    prezzi = df['prezzo'].values
    # quanti competitor costano strettamente meno di ogni riga
    piu_economici = [int((prezzi < p).sum()) for p in prezzi]
    if prezzo_cliente is None:
        df['rank'] = [n + 1 for n in piu_economici]
        df['diff_vs_cliente'] = None
    else:
        df['rank'] = [n + 1 + (1 if prezzo_cliente < p else 0)
                      for n, p in zip(piu_economici, prezzi)]
        df['diff_vs_cliente'] = ((df['prezzo'] - prezzo_cliente) * 100).round(1)
    return df


def eta_giorni(date: pd.Series, riferimento: pd.Timestamp) -> pd.Series:
    """
    Giorni trascorsi da ogni data al riferimento (NaN se data mancante).
    Una data nel futuro (errore del gestore) conta come 'oggi', non come negativa.
    """
    return (riferimento.normalize() - date.dt.normalize()).dt.days.clip(lower=0)


def data_riferimento(date: pd.Series, adesso: Optional[pd.Timestamp] = None) -> pd.Timestamp:
    """
    Il 'giorno di oggi' dei dati: la comunicazione piu' recente NON nel futuro.

    Basta un solo gestore che scrive una data sbagliata (es. 2027) per far
    sembrare vecchi tutti gli altri prezzi d'Italia: quelle date le ignoriamo.
    """
    adesso = adesso or pd.Timestamp.now()
    valide = date[date <= adesso]
    return valide.max() if not valide.empty else adesso


class PricingAnalyzer:
    """
    Uso:
        analyzer = PricingAnalyzer(df_mimit)
        report = analyzer.analizza(cliente, competitor_per_carburante)
    """

    def __init__(self, df_mimit: pd.DataFrame):
        self.df = df_mimit
        # Riferimento = comunicazione piu' recente nel dataset, non "adesso":
        # cosi' l'eta' resta corretta anche se si usano dati in cache.
        self.riferimento = data_riferimento(df_mimit['data_comunicazione'])

    def analizza(self, cliente: dict, competitor: dict) -> dict:
        """
        Args:
            cliente:    dict cliente (id_impianto, carburanti, top_n, is_self...)
            competitor: output di CompetitorFinder.competitor_per_carburante()
        """
        report = {
            'cliente':     cliente,
            'carburanti':  {},
            'summary':     [],
            'riferimento': self.riferimento,
        }

        for carburante in cliente['carburanti']:
            df_raggio = competitor.get(carburante, pd.DataFrame())
            analisi = self._analizza_carburante(carburante, df_raggio, cliente)
            report['carburanti'][carburante] = analisi
            report['summary'].append(self._genera_summary(carburante, analisi,
                                                          cliente))
        return report

    def _analizza_carburante(self, carburante: str,
                             df_raggio: pd.DataFrame, cliente: dict) -> dict:
        max_eta = cliente.get('max_eta_giorni', MAX_ETA_GIORNI_DEFAULT)

        prezzo_cliente, eta_cliente = self._prezzo_cliente(cliente, carburante)

        # Separa prezzi aggiornati da prezzi vecchi
        n_esclusi = 0
        if not df_raggio.empty:
            df_raggio = df_raggio.copy()
            df_raggio['eta_giorni'] = eta_giorni(df_raggio['data_comunicazione'],
                                                 self.riferimento)
            aggiornati = df_raggio['eta_giorni'] <= max_eta
            n_esclusi = int((~aggiornati).sum())
            df_raggio = df_raggio[aggiornati]

        df_raggio = aggiungi_rank(df_raggio, prezzo_cliente)
        top_n = df_raggio.head(cliente['top_n']).reset_index(drop=True)
        top_n.index += 1

        base = {
            'prezzo_cliente': prezzo_cliente,
            'eta_cliente':    eta_cliente,
            'n_competitor':   len(df_raggio),
            'n_esclusi':      n_esclusi,
            'max_eta_giorni': max_eta,
            'top_n':          top_n,
        }

        if df_raggio.empty:
            return {**base, **calcola_posizionamento(0, df_raggio),
                    'raccomandazione': '⚠️ Nessun prezzo aggiornato dei concorrenti nel raggio'}

        if prezzo_cliente is None:
            stats = calcola_posizionamento(0, df_raggio)
            stats.update(posizione=None, totale=len(df_raggio),
                         diff_vs_min=None, diff_vs_media=None)
            return {**base, **stats,
                    'raccomandazione': '⚠️ Il tuo prezzo non è presente nei dati MIMIT'}

        stats = calcola_posizionamento(prezzo_cliente, df_raggio)
        return {**base, **stats,
                'raccomandazione': self._raccomandazione(stats['posizione'],
                                                         stats['totale'])}

    def _prezzo_cliente(self, cliente: dict,
                        carburante: str) -> tuple[Optional[float], Optional[int]]:
        """Prezzo e eta' (giorni) del cliente, cercati per id_impianto esatto."""
        id_impianto = cliente.get('id_impianto')
        if not id_impianto:
            return None, None

        df = self.df[(self.df['id_impianto'] == str(id_impianto)) &
                     (self.df['carburante'] == carburante)]
        is_self = filtro_self(carburante, cliente.get('is_self', True))
        if is_self is not None:
            df = df[df['is_self'] == is_self]
        if df.empty:
            return None, None

        # Se ci sono piu' righe (es. GPL self e servito) prendi la piu' recente
        riga = df.sort_values('data_comunicazione').iloc[-1]
        eta = eta_giorni(pd.Series([riga['data_comunicazione']]),
                         self.riferimento).iloc[0]
        return float(riga['prezzo']), (None if pd.isna(eta) else int(eta))

    def _raccomandazione(self, posizione: int, totale: int) -> str:
        """Valutazione in base al percentile nel raggio (1 = piu' economico)."""
        pct = posizione / totale * 100
        if pct <= 20:
            return '🟢 Ottimo — tra i più economici della zona'
        if pct <= 40:
            return '🟡 Buono — più economico della maggior parte dei concorrenti'
        if pct <= 60:
            return '🟠 Nella media — a metà tra i concorrenti della zona'
        if pct <= 80:
            return '🔴 Alto — più caro della maggior parte dei concorrenti'
        return '🔴 Attenzione — tra i più cari della zona'

    def _genera_summary(self, carburante: str, analisi: dict,
                        cliente: dict) -> str:
        nome = carburante.upper()
        if analisi['prezzo_cliente'] is None:
            return f"{nome}: il tuo prezzo non è disponibile"
        prezzo = f"€ {analisi['prezzo_cliente']:.3f}".replace('.', ',')
        if analisi['posizione'] is None:
            return (f"{nome}: {prezzo} — nessun concorrente aggiornato "
                    f"entro {cliente['raggio_km']} km")
        cent = lambda v: f"{v:+.1f}".replace('.', ',')
        return (f"{nome}: {prezzo} — posizione {analisi['posizione']}/{analisi['totale']} "
                f"entro {cliente['raggio_km']} km — "
                f"{cent(analisi['diff_vs_min'])} cent dal più economico, "
                f"{cent(analisi['diff_vs_media'])} dalla media")
