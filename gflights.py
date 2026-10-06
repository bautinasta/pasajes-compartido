"""Fuente Google Flights, vía SerpApi.

La clave va en la variable de entorno SERPAPI_KEY y nunca se imprime.

Una consulta cubre un par de fechas (una ida y una vuelta): Google Flights no
tiene búsqueda por rango, así que la grilla se recorre por rotación con un
presupuesto diario. Ver `recolectar()` en buscar.py.

Qué devuelve: en una búsqueda de ida y vuelta (`type=1`), cada resultado trae el
**precio total del ida y vuelta** y el detalle del tramo de ida. El detalle del
tramo de vuelta exige una segunda consulta con `departure_token`, que duplicaría
el gasto; para seguir un precio no hace falta, así que no se pide. La fecha de
vuelta se conoce igual: es la que se consultó.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://serpapi.com/search"

CLASES = {"ECONOMY": 1, "PREMIUM_ECONOMY": 2, "BUSINESS": 3, "FIRST": 4}


class SerpApiError(RuntimeError):
    """Error de la API o de red al hablar con SerpApi."""


class SinCuota(SerpApiError):
    """Se agotó el plan del mes. No tiene sentido reintentar hoy."""


def duracion(minutos):
    if not minutos:
        return ""
    h, m = divmod(int(minutos), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


class GoogleFlights:
    def __init__(self, pausa=1.0):
        self.pausa = pausa

    def _clave(self):
        k = os.environ.get("SERPAPI_KEY")
        if not k:
            raise SerpApiError("Falta SERPAPI_KEY en el entorno.")
        return k

    def _base(self, cfg, ida, vuelta):
        return {
            "engine": "google_flights",
            "api_key": self._clave(),
            "departure_id": cfg["origen"],
            "arrival_id": cfg["destino"],
            "type": 1,                       # ida y vuelta
            "outbound_date": ida,
            "return_date": vuelta,
            "currency": cfg.get("moneda", "USD"),
            "travel_class": CLASES.get(cfg.get("clase", "ECONOMY"), 1),
            "adults": cfg.get("adultos", 1),
            "sort_by": 2,                    # por precio
            "hl": cfg.get("idioma", "es"),
            "gl": cfg.get("mercado", "ar"),
        }

    def _consulta(self, params):
        url = f"{BASE}?" + urllib.parse.urlencode(params)
        espera = 3.0
        for intento in range(4):
            try:
                time.sleep(self.pausa)
                with urllib.request.urlopen(url, timeout=90) as r:
                    datos = json.load(r)
                break
            except urllib.error.HTTPError as e:
                cuerpo = e.read()[:300].decode("utf8", "replace")
                if e.code == 401:
                    raise SerpApiError(f"clave rechazada (401): {cuerpo}")
                if e.code == 429:
                    raise SinCuota(f"sin cuota (429): {cuerpo}")
                if e.code in (500, 502, 503, 504) and intento < 3:
                    time.sleep(espera)
                    espera *= 2
                    continue
                raise SerpApiError(f"consulta falló ({e.code}): {cuerpo}")
            except OSError as e:
                if intento < 3:
                    time.sleep(espera)
                    espera *= 2
                    continue
                raise SerpApiError(f"red: {e}")
        else:
            raise SerpApiError("se agotaron los reintentos")

        # SerpApi devuelve 200 con un error adentro cuando la búsqueda no corrió.
        if datos.get("error"):
            texto = str(datos["error"])
            if "run out" in texto.lower() or "exceed" in texto.lower():
                raise SinCuota(texto)
            raise SerpApiError(texto)
        return datos

    def buscar(self, cfg, ida, vuelta):
        datos = self._consulta(self._base(cfg, ida, vuelta))
        enlace = (datos.get("search_metadata") or {}).get("google_flights_url")
        crudas = (datos.get("best_flights") or []) + (datos.get("other_flights") or [])
        ofertas = [normalizar(o, cfg, ida, vuelta, enlace) for o in crudas]
        ofertas = [o for o in ofertas if o["precio"]]
        ofertas.sort(key=lambda o: o["precio"])
        return ofertas, datos.get("price_insights") or None


    def agencias(self, cfg, ida, vuelta, departure_token):
        """Quién vende el vuelo y a cuánto: eDreams, la aerolínea, etc.

        Google no entrega las agencias en la búsqueda inicial. Hay que elegir un
        itinerario de ida (`departure_token`), lo que devuelve los vuelos de vuelta
        con un `booking_token`, y recién ese token trae las opciones de reserva. Son
        **dos consultas** además de la búsqueda que ya se hizo, así que esto corre
        sólo sobre la combinación más barata del día.
        """
        if not departure_token:
            return {"agencias": [], "precio_itinerario": None}, 0

        vueltas = self._consulta(
            dict(self._base(cfg, ida, vuelta), departure_token=departure_token))
        ofertas = (vueltas.get("best_flights") or []) + (vueltas.get("other_flights") or [])
        ofertas = [o for o in ofertas if o.get("booking_token") and o.get("price")]
        if not ofertas:
            return {"agencias": [], "precio_itinerario": None}, 1
        elegida = min(ofertas, key=lambda o: o["price"])

        reserva = self._consulta(
            dict(self._base(cfg, ida, vuelta), booking_token=elegida["booking_token"]))
        agencias = extraer_agencias(reserva)
        return {
            "agencias": agencias,
            # El itinerario que se termina cotizando puede no ser exactamente el
            # que dio el precio de la grilla; guardarlo evita mostrar una lista
            # de agencias que no cierra con el precio de al lado.
            "precio_itinerario": float(elegida["price"]),
            # Si el parseo no sacó nada, guardar el crudo para poder corregirlo
            # sin tener que gastar otra consulta reproduciendo el caso.
            "crudo": None if agencias else (reserva.get("booking_options") or [])[:3],
        }, 2


def extraer_agencias(datos):
    """Normaliza `booking_options`, más barata primero.

    Una opción puede venir como `together` (una agencia vende el viaje entero) o
    partida en `departing` / `returning`, cuando cada tramo se compra por separado.
    """
    mejor_por_agencia = {}
    for opcion in datos.get("booking_options") or []:
        if not isinstance(opcion, dict):
            continue
        for clave, tramo in (("together", "todo"), ("departing", "ida"),
                             ("returning", "vuelta")):
            bloque = opcion.get(clave)
            if not isinstance(bloque, dict):
                continue
            nombre = (bloque.get("book_with") or "").strip()
            precio = bloque.get("price")
            # bool es int en Python: sin este guard, True entraria como 1.0 y
            # quedaria primero en el orden.
            if not nombre or isinstance(precio, bool) or not isinstance(precio, (int, float)):
                continue
            llave = (nombre.lower(), tramo)
            anterior = mejor_por_agencia.get(llave)
            # Una misma agencia puede aparecer varias veces y no necesariamente
            # ordenada de barata a cara: hay que quedarse con la menor, no con
            # la primera que aparezca.
            if anterior is None or precio < anterior["precio"]:
                mejor_por_agencia[llave] = {"agencia": nombre, "precio": float(precio),
                                            "tramo": tramo}
    return sorted(mejor_por_agencia.values(), key=lambda a: a["precio"])


def _tramo(segmentos, escalas_info, total_min):
    if not segmentos:
        return None
    return {
        "duracion": duracion(total_min),
        "escalas": max(len(segmentos) - 1, 0),
        "via": [e.get("id") for e in (escalas_info or []) if e.get("id")],
        "sale": (segmentos[0].get("departure_airport") or {}).get("time"),
        "llega": (segmentos[-1].get("arrival_airport") or {}).get("time"),
        "segmentos": [
            {
                "de": (s.get("departure_airport") or {}).get("id", ""),
                "a": (s.get("arrival_airport") or {}).get("id", ""),
                "sale": (s.get("departure_airport") or {}).get("time"),
                "llega": (s.get("arrival_airport") or {}).get("time"),
                "vuelo": s.get("flight_number", ""),
                "aerolinea": s.get("airline", ""),
                "duracion": duracion(s.get("duration")),
            }
            for s in segmentos
        ],
    }


def normalizar(o, cfg, ida, vuelta, enlace=None):
    """Pasa un resultado de google_flights a la forma que usa el proyecto."""
    segmentos = o.get("flights") or []
    primera = segmentos[0] if segmentos else {}
    return {
        "fuente": "google-flights",
        "precio": float(o["price"]) if o.get("price") else None,
        "moneda": cfg.get("moneda", "USD"),
        "aerolinea": primera.get("airline", ""),
        "aerolinea_nombre": primera.get("airline", "—"),
        "enlace": enlace,
        "_ida": ida,
        "_vuelta": vuelta,
        "_departure_token": o.get("departure_token"),
        "ida": _tramo(segmentos, o.get("layovers"), o.get("total_duration")),
        # El detalle de la vuelta exige otra consulta; la fecha sí se conoce.
        "vuelta": None,
    }
