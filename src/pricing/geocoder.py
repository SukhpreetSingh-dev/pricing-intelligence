"""
Geocoder — converte indirizzi in coordinate GPS.
"""

import ssl
import certifi
from typing import Optional, Tuple
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter


class Geocoder:
    """
    Converte indirizzi testuali in coordinate GPS (lat, lon).

    Uso:
        geo = Geocoder()
        lat, lon = geo.geocodifica("Via Emilia 100, Modena")
    """

    def __init__(self):
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        self._geolocator = Nominatim(
            user_agent="pricing-intelligence-v1",
            ssl_context=ssl_context
        )
        self._geocode = RateLimiter(
            self._geolocator.geocode,
            min_delay_seconds=1.1
        )

    def geocodifica(self, indirizzo: str) -> Optional[Tuple[float, float]]:
        """
        Converte un indirizzo in (latitudine, longitudine).
        Restituisce None se non trovato.
        """
        try:
            query = f"{indirizzo}, Italia"
            location = self._geocode(query)

            if location is None:
                print(f"  ⚠️ Indirizzo non trovato: {indirizzo}")
                return None

            print(f"  ✅ {indirizzo}")
            print(f"     → ({location.latitude:.6f}, {location.longitude:.6f})")
            return (location.latitude, location.longitude)

        except Exception as e:
            print(f"  ❌ Errore geocoding '{indirizzo}': {e}")
            return None

    def geocodifica_clienti(self, clienti: list) -> list:
        """
        Aggiunge lat/lon a ogni cliente nella lista.
        Restituisce la lista aggiornata.
        """
        print(f"Geocoding {len(clienti)} clienti...")
        risultati = []

        for cliente in clienti:
            coords = self.geocodifica(cliente['indirizzo'])
            cliente_aggiornato = cliente.copy()

            if coords:
                cliente_aggiornato['lat'] = coords[0]
                cliente_aggiornato['lon'] = coords[1]
                cliente_aggiornato['geocodificato'] = True
            else:
                cliente_aggiornato['lat'] = None
                cliente_aggiornato['lon'] = None
                cliente_aggiornato['geocodificato'] = False

            risultati.append(cliente_aggiornato)

        ok = sum(1 for c in risultati if c['geocodificato'])
        print(f"\nGeocoding completato: {ok}/{len(clienti)} riusciti")
        return risultati