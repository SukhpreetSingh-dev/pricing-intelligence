"""
Localizzazione clienti — collega ogni cliente al SUO impianto nei dati MIMIT.

Due strade, in ordine di affidabilita':
  1. id_impianto in clienti.json  -> coordinate prese direttamente da MIMIT
  2. solo indirizzo               -> geocoding + impianto MIMIT entro MAX_MATCH_KM
                                     (se non c'e' nessun impianto cosi' vicino,
                                      il prezzo cliente resta "non trovato")
"""

from typing import Optional

import pandas as pd

from src.pricing.finder import CompetitorFinder


# Oltre questa distanza l'impianto trovato NON e' considerato quello del cliente.
# In citta' a 1-2 km ci sono gia' altri distributori: meglio "non trovato"
# che il prezzo di un concorrente spacciato per il tuo.
MAX_MATCH_KM = 0.3


def localizza_clienti(clienti: list, df_mimit: pd.DataFrame,
                      finder: CompetitorFinder, geocoder=None) -> list:
    """
    Aggiunge a ogni cliente: lat, lon, id_impianto (o None), localizzato (bool).

    geocoder serve solo per i clienti senza id_impianto (puo' essere None se
    tutti i clienti hanno l'id).
    """
    impianti = df_mimit.drop_duplicates('id_impianto').set_index('id_impianto')
    risultati = []

    for cliente in clienti:
        c = cliente.copy()
        id_impianto = str(c['id_impianto']) if c.get('id_impianto') else None

        if id_impianto:
            if id_impianto in impianti.index:
                c['lat'] = float(impianti.loc[id_impianto, 'lat'])
                c['lon'] = float(impianti.loc[id_impianto, 'lon'])
                c['id_impianto'] = id_impianto
                c['impianto'] = _info_impianto(impianti.loc[id_impianto])
                c['localizzato'] = True
                print(f"  ✅ {c['nome']} → impianto MIMIT {id_impianto}")
            else:
                print(f"  ⚠️  {c['nome']} — id_impianto {id_impianto} "
                      f"non presente nei dati MIMIT")
                c.update(lat=None, lon=None, id_impianto=None, impianto=None,
                         localizzato=False)
        else:
            c.update(_localizza_da_indirizzo(c, finder, geocoder))

        risultati.append(c)

    ok = sum(1 for c in risultati if c['localizzato'])
    print(f"  Localizzati {ok}/{len(clienti)} clienti")
    return risultati


def _localizza_da_indirizzo(cliente: dict, finder: CompetitorFinder,
                            geocoder) -> dict:
    if geocoder is None:
        print(f"  ⚠️  {cliente['nome']} — senza id_impianto e senza geocoder")
        return dict(lat=None, lon=None, id_impianto=None, impianto=None,
                    localizzato=False)

    coords = geocoder.geocodifica(cliente['indirizzo'])
    if coords is None:
        return dict(lat=None, lon=None, id_impianto=None, impianto=None,
                    localizzato=False)

    lat, lon = coords
    id_trovato: Optional[str] = finder.impianto_piu_vicino(lat, lon, MAX_MATCH_KM)
    if id_trovato:
        print(f"     → impianto MIMIT {id_trovato} (entro {MAX_MATCH_KM*1000:.0f} m). "
              f"Aggiungi \"id_impianto\": \"{id_trovato}\" in clienti.json "
              f"per renderlo definitivo.")
    else:
        print(f"     ⚠️ nessun impianto MIMIT entro {MAX_MATCH_KM*1000:.0f} m "
              f"dall'indirizzo: il prezzo cliente non sara' disponibile")
    info = None
    if id_trovato:
        riga = finder.df[finder.df['id_impianto'] == id_trovato].iloc[0]
        info = _info_impianto(riga)
    return dict(lat=lat, lon=lon, id_impianto=id_trovato, impianto=info,
                localizzato=True)


def _info_impianto(riga) -> dict:
    """Dati anagrafici MIMIT dell'impianto del cliente, per il report."""
    return {k: riga.get(k) for k in
            ('bandiera', 'gestore', 'nome', 'indirizzo', 'comune', 'provincia')}
