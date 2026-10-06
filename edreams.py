"""Fuente eDreams, vía navegador.

eDreams no publica una API abierta, así que hay que pasar por el sitio. En vez de
leer el HTML renderizado con selectores CSS —que cambian seguido y se rompen sin
aviso— esto intercepta las respuestas JSON que el propio buscador pide por XHR y
saca los precios de ahí. Es bastante más estable: el markup cambia mucho más
seguido que la forma de la respuesta.

Requiere Playwright y un Chromium. El contenedor ya trae Chromium en
PLAYWRIGHT_BROWSERS_PATH; falta el paquete de Python:

    pip install playwright

Si no está, `disponible()` devuelve False y `buscar()` no se llama: la corrida
sigue con Amadeus sola. eDreams nunca puede hacer fallar la corrida.

PENDIENTE DE CALIBRACIÓN: `extraer()` recorre el JSON buscando objetos con forma
de oferta. Los nombres de campo de abajo son los habituales en el buscador de
eDreams, pero hasta no correr `--calibrar` una vez contra el sitio real no están
confirmados. `--calibrar` guarda todas las respuestas capturadas en disco para
poder ajustarlos mirando datos de verdad, en vez de adivinando.
"""

import json
import pathlib
import re
import time

# El contenedor trae Chromium preinstalado; Playwright puede pedir otro build.
# Se usa el que esta, en vez de bajar uno nuevo.
import glob as _glob


def chromium_local():
    for patron in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome",
                   "/opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell"):
        hallados = sorted(_glob.glob(patron))
        if hallados:
            return hallados[-1]
    return None


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Deeplink de resultados. `host` se cambia por mercado (.com, .com.ar, .es).
PLANTILLA = ("https://{host}/travel/#results/type=R;from={origen};to={destino};"
             "dep={ida};ret={vuelta};adults={adultos};cabinClass={clase}")

CLASES = {"ECONOMY": "ECONOMIC", "PREMIUM_ECONOMY": "PREMIUM",
          "BUSINESS": "BUSINESS", "FIRST": "FIRST"}

# Campos donde suele venir el precio total en las respuestas de eDreams.
CAMPOS_PRECIO = ("totalPrice", "price", "amount", "totalAmount", "fareTotal",
                 "displayPrice", "pricePerPassenger")
# Marcadores de que un objeto JSON es una oferta y no cualquier otra cosa.
MARCAS_OFERTA = ("itinerary", "itineraries", "segments", "legs", "outbound", "inbound")


def disponible():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def url(cfg, ida, vuelta):
    return PLANTILLA.format(
        host=cfg.get("edreams_host", "www.edreams.com"),
        origen=cfg["origen"], destino=cfg["destino"], ida=ida, vuelta=vuelta,
        adultos=cfg.get("adultos", 1),
        clase=CLASES.get(cfg.get("clase", "ECONOMY"), "ECONOMIC"),
    )


# Dentro de un objeto de precio, dónde suele estar el número.
CAMPOS_MONTO = ("amount", "value", "total", "price", "units", "gross")


def _num(v, profundidad=0):
    """Saca un número de 1.234,56 / 1,234.56 / '1234.56' / {"amount": ...}."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        # El precio suele venir envuelto: {"amount": "1.899,30", "currency": "USD"}.
        if profundidad < 3:
            for c in CAMPOS_MONTO:
                if c in v:
                    n = _num(v[c], profundidad + 1)
                    if n:
                        return n
        return None
    if not isinstance(v, str):
        return None
    s = re.sub(r"[^\d,.\-]", "", v)
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") \
            else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _caminar(nodo, salida, profundidad=0):
    """Recorre el JSON juntando objetos que parezcan una oferta de vuelo."""
    if profundidad > 14:
        return
    if isinstance(nodo, dict):
        claves = set(nodo)
        tiene_precio = any(c in claves for c in CAMPOS_PRECIO)
        tiene_vuelo = any(c in claves for c in MARCAS_OFERTA)
        if tiene_precio and tiene_vuelo:
            precio = next((_num(nodo[c]) for c in CAMPOS_PRECIO
                           if c in nodo and _num(nodo[c])), None)
            if precio and 50 < precio < 100000:
                salida.append({"precio": precio, "crudo": nodo})
        for v in nodo.values():
            _caminar(v, salida, profundidad + 1)
    elif isinstance(nodo, list):
        for v in nodo[:400]:
            _caminar(v, salida, profundidad + 1)


def extraer(respuestas):
    """De las respuestas capturadas saca ofertas normalizadas, más baratas primero."""
    crudas = []
    for cuerpo in respuestas:
        try:
            _caminar(json.loads(cuerpo), crudas)
        except (ValueError, TypeError):
            continue
    vistos, ofertas = set(), []
    for o in sorted(crudas, key=lambda x: x["precio"]):
        if o["precio"] in vistos:
            continue
        vistos.add(o["precio"])
        ofertas.append({
            "precio": round(o["precio"], 2),
            "fuente": "edreams",
            "aerolinea": _aerolinea(o["crudo"]) or "",
            "aerolinea_nombre": _aerolinea(o["crudo"]) or "eDreams",
            "ida": None, "vuelta": None,  # se completan tras calibrar
        })
    return ofertas


def _aerolinea(nodo):
    for clave in ("carrier", "airline", "marketingCarrier", "validatingCarrier",
                  "mainAirline", "carrierName"):
        v = nodo.get(clave)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            for k in ("name", "code", "iataCode"):
                if isinstance(v.get(k), str) and v[k].strip():
                    return v[k].strip()
    return None


def buscar(cfg, ida, vuelta, espera=22, calibrar_en=None):
    """Abre la búsqueda y devuelve las ofertas encontradas.

    Ante cualquier problema (sitio caído, bloqueo de bots, markup nuevo) devuelve
    una lista vacía: la corrida sigue con las otras fuentes.
    """
    from playwright.sync_api import sync_playwright

    destino = url(cfg, ida, vuelta)
    respuestas = []

    with sync_playwright() as p:
        exe = chromium_local()
        navegador = p.chromium.launch(
            executable_path=exe,
            args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = navegador.new_context(user_agent=UA, locale="es-AR",
                                    viewport={"width": 1440, "height": 900})
        pagina = ctx.new_page()

        def al_responder(r):
            tipo = (r.headers or {}).get("content-type", "")
            if "json" not in tipo or r.status >= 400:
                return
            try:
                respuestas.append(r.text())
            except Exception:
                pass

        pagina.on("response", al_responder)
        try:
            pagina.goto(destino, wait_until="domcontentloaded", timeout=45000)
            # El buscador va completando resultados; se le da tiempo a asentarse.
            fin = time.time() + espera
            ultimo = -1
            while time.time() < fin:
                pagina.wait_for_timeout(1500)
                if len(respuestas) == ultimo and len(respuestas) > 2:
                    break
                ultimo = len(respuestas)
        except Exception as e:
            print(f"    edreams: {type(e).__name__}: {e}")
        finally:
            if calibrar_en:
                d = pathlib.Path(calibrar_en)
                d.mkdir(parents=True, exist_ok=True)
                (d / "pagina.html").write_text(pagina.content(), errors="replace")
                pagina.screenshot(path=str(d / "pagina.png"), full_page=True)
                for n, cuerpo in enumerate(respuestas):
                    (d / f"respuesta-{n:03d}.json").write_text(cuerpo, errors="replace")
                print(f"    edreams: {len(respuestas)} respuestas guardadas en {d}")
            ctx.close()
            navegador.close()

    return extraer(respuestas)
