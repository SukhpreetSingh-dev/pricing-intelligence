"""
Test su dati sintetici (nessun download, nessuna email).

    python -m pytest -q
"""

import pandas as pd
import pytest

from src.pricing.analyzer import PricingAnalyzer, calcola_posizionamento
from src.pricing.clienti import localizza_clienti
from src.pricing.finder import CompetitorFinder
from src.pricing.notifier import PricingNotifier, nome_distributore, pulisci_indirizzo

OGGI = pd.Timestamp('2026-10-09 07:30:00')

# Modena centro ~ (44.6471, 10.9252). 0.01° di latitudine ~ 1.1 km
CLIENTE_ID = '1000'
IMPIANTI = [
    # id,     lat,     lon,     bandiera,   prezzo benzina, eta' (giorni)
    ('1000', 44.6471, 10.9252, 'Q8',        1.849, 0),   # il cliente
    ('1001', 44.6560, 10.9252, 'Esso',      1.799, 0),   # ~1 km
    ('1002', 44.6650, 10.9252, 'Api-Ip',    1.849, 1),   # ~2 km, pari merito
    ('1003', 44.6740, 10.9252, 'Agip Eni',  1.899, 0),   # ~3 km
    ('1004', 44.6830, 10.9252, 'Tamoil',    1.929, 2),   # ~4 km
    ('1005', 44.6650, 10.9300, 'Retitalia', 1.699, 6),   # economico ma VECCHIO
    ('1006', 44.9000, 10.9252, 'Pompe B.',  1.599, 0),   # ~28 km, fuori raggio
]


def _df_mimit() -> pd.DataFrame:
    righe = []
    for id_, lat, lon, band, prezzo, eta in IMPIANTI:
        data = OGGI - pd.Timedelta(days=eta)
        ana = dict(id_impianto=id_, lat=lat, lon=lon, bandiera=band,
                   gestore=f'GESTORE {id_} S.R.L.', nome=id_,
                   indirizzo=f'VIA  EMILIA {id_[-1]} 41121', comune='MODENA')
        righe.append(dict(**ana, carburante='benzina', is_self=True,
                          prezzo=prezzo, data_comunicazione=data))
        # stesso impianto, servito: piu' caro, non deve entrare nei conti self
        righe.append(dict(**ana, carburante='benzina', is_self=False,
                          prezzo=prezzo + 0.2, data_comunicazione=data))
    # GPL: solo servito
    righe.append(dict(id_impianto=CLIENTE_ID, lat=44.6471, lon=10.9252,
                      bandiera='Q8', gestore='GESTORE 1000 S.R.L.', nome='1000',
                      indirizzo='VIA  EMILIA 0 41121', comune='MODENA', carburante='gpl',
                      is_self=False, prezzo=0.699, data_comunicazione=OGGI))
    righe.append(dict(id_impianto='1001', lat=44.6560, lon=10.9252,
                      bandiera='Esso', gestore='GESTORE 1001 S.R.L.', nome='1001',
                      indirizzo='VIA  EMILIA 1 41121', comune='MODENA', carburante='gpl',
                      is_self=False, prezzo=0.679, data_comunicazione=OGGI))
    return pd.DataFrame(righe)


def _cliente(**extra) -> dict:
    c = dict(id='c1', nome='Test', email=['x@example.com'], id_impianto=CLIENTE_ID,
             indirizzo='', raggio_km=10, carburanti=['benzina', 'gpl'],
             top_n=3, is_self=True, max_eta_giorni=3)
    c.update(extra)
    return c


def _report(**extra):
    df = _df_mimit()
    finder = CompetitorFinder(df)
    cliente = localizza_clienti([_cliente(**extra)], df, finder)[0]
    competitor = finder.competitor_per_carburante(
        cliente['lat'], cliente['lon'], cliente['raggio_km'],
        cliente['carburanti'], cliente['is_self'], cliente['id_impianto'])
    return PricingAnalyzer(df).analizza(cliente, competitor)


# ── calcola_posizionamento ──────────────────────────────────────

def test_posizionamento_base():
    raggio = pd.DataFrame({'prezzo': [1.899, 1.799, 1.849, 1.929, None]})
    r = calcola_posizionamento(1.849, raggio)
    assert r['posizione'] == 2          # solo 1.799 e' piu' economico
    assert r['totale'] == 5             # 4 competitor validi + cliente
    assert r['prezzo_medio'] == pytest.approx(1.869)
    assert r['diff_vs_min'] == pytest.approx(5.0)
    assert r['diff_vs_media'] == pytest.approx(-2.0)


def test_posizionamento_raggio_vuoto():
    r = calcola_posizionamento(1.849, pd.DataFrame({'prezzo': []}))
    assert r['totale'] == 0 and r['posizione'] is None


# ── fix 1+2: statistiche sul raggio, non su Italia ne' sul Top N ──

def test_statistiche_solo_nel_raggio():
    b = _report()['carburanti']['benzina']
    # Competitor validi: 1001, 1002, 1003, 1004 (1005 vecchio, 1006 fuori raggio)
    assert b['n_competitor'] == 4
    assert b['totale'] == 5
    assert b['posizione'] == 2                       # pari merito con Api-Ip
    assert b['prezzo_medio'] == pytest.approx((1.799 + 1.849 + 1.899 + 1.929) / 4, abs=1e-3)


def test_media_non_dipende_dal_top_n():
    stretto = _report(top_n=1)['carburanti']['benzina']
    largo = _report(top_n=10)['carburanti']['benzina']
    assert stretto['prezzo_medio'] == largo['prezzo_medio']
    assert len(stretto['top_n']) == 1


# ── fix 3: prezzo del cliente esatto e cliente escluso dai competitor ──

def test_prezzo_cliente_per_id_e_escluso():
    b = _report()['carburanti']['benzina']
    assert b['prezzo_cliente'] == pytest.approx(1.849)
    assert CLIENTE_ID not in set(b['top_n']['id_impianto'])


def test_indirizzo_senza_impianto_vicino_non_inventa_prezzi():
    class GeoFinto:
        def geocodifica(self, _):
            return (44.6520, 10.9252)               # ~550 m dal cliente: troppo lontano

    df = _df_mimit()
    finder = CompetitorFinder(df)
    c = localizza_clienti([_cliente(id_impianto=None)], df, finder, GeoFinto())[0]
    assert c['localizzato'] and c['id_impianto'] is None
    r = PricingAnalyzer(df).analizza(c, finder.competitor_per_carburante(
        c['lat'], c['lon'], 10, ['benzina'], True, None))
    assert r['carburanti']['benzina']['prezzo_cliente'] is None


# ── fix 4: GPL ignora il filtro self anche per il prezzo cliente ──

def test_gpl_trova_prezzo_cliente():
    g = _report()['carburanti']['gpl']
    assert g['prezzo_cliente'] == pytest.approx(0.699)
    assert g['posizione'] == 2 and g['totale'] == 2


# ── fix 5: prezzi vecchi esclusi dalle statistiche ──

def test_prezzi_vecchi_esclusi():
    b = _report()['carburanti']['benzina']
    assert b['n_esclusi'] == 1
    assert '1005' not in set(b['top_n']['id_impianto'])
    assert b['prezzo_min'] == pytest.approx(1.799)    # non 1.699 (vecchio)

    tutti = _report(max_eta_giorni=30)['carburanti']['benzina']
    assert tutti['n_esclusi'] == 0 and tutti['prezzo_min'] == pytest.approx(1.699)


# ── classifica: rank con pari merito e differenza vs cliente ──

def test_rank_e_diff_vs_cliente():
    top = _report()['carburanti']['benzina']['top_n']
    # Esso 1.799 -> 1° ; Api-Ip 1.849 = cliente -> pari merito 2° ; Agip 1.899 -> 4°
    assert list(top['rank']) == [1, 2, 4]
    assert list(top['diff_vs_cliente']) == [-5.0, 0.0, 5.0]


# ── pulizia campi MIMIT ──

def test_pulizia_campi_mimit():
    assert pulisci_indirizzo('VIA ROMA  NORD 33 46025', 'POGGIO RUSCO') == \
        'Via Roma Nord 33, Poggio Rusco'
    assert pulisci_indirizzo('NAZIONALE 69 46036', None) == 'Nazionale 69'
    assert nome_distributore({'bandiera': 'Esso', 'gestore': 'EGI-2GO S.R.L.'}) == \
        'Esso · Egi-2Go S.R.L.'
    assert nome_distributore({'bandiera': None, 'gestore': None}) == 'Station n/a'


# ── il report HTML ──

def test_template_html():
    html = PricingNotifier()._template_html(_report())
    assert 'within 10 km' in html
    assert 'YOU — Test' in html                       # riga cliente in classifica
    assert 'Via Emilia 1, Modena' in html             # indirizzo competitor pulito
    assert 'Gestore 1001 S.R.L.' in html              # chi e' il competitor
    assert 'left out' in html                         # prezzi vecchi segnalati


def test_cliente_fuori_dal_top_n_compare_in_fondo():
    html = PricingNotifier()._template_html(_report(top_n=1))
    b = html.split('Petrol')[1].split('LPG')[0]
    assert b.index('Gestore 1001') < b.index('YOU — Test')
    assert 'YOU — Test' in b
