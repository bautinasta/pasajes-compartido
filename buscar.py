#!/usr/bin/env python3
"""Busca pasajes SYD -> EZE sobre una grilla de fechas de ida y vuelta.

Fuente: Google Flights, vía SerpApi. Cada consulta cubre un par de fechas, así
que la grilla de 66 combinaciones no entra en un día: cada corrida gasta un
presupuesto fijo y reparte las consultas por rotación. Siempre refresca el mejor
combo conocido, para que ese precio sea el de hoy, y después los que hace más
tiempo que no se miden. La grilla entera queda al día en unos días.

Uso:
    python3 buscar.py --estado estado.json --salida salida/resultado.json
"""

import argparse
import collections
import datetime as dt
import json
import pathlib
import sys

import edreams
from gflights import GoogleFlights, SerpApiError, SinCuota

RAIZ = pathlib.Path(__file__).resolve().parent


def rango_fechas(desde, hasta):
    a = dt.date.fromisoformat(desde)
    b = dt.date.fromisoformat(hasta)
    if b < a:
        raise ValueError(f"rango invertido: {desde} > {hasta}")
    return [(a + dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]




def elegir_combos(combos, estado, presupuesto):
    """Ordena la grilla por urgencia y devuelve los primeros `presupuesto`.

    Nunca vistos primero, después los de lectura más vieja. El mejor combo
    conocido se adelanta al frente para que su precio sea siempre de hoy.
    """
    previos = estado.get("combos", {})
    nunca, vistos = [], []
    for c in combos:
        prev = previos.get(c)
        (vistos if prev else nunca).append((prev.get("visto", "") if prev else "", c))
    vistos.sort(key=lambda par: par[0])
    orden = nunca and [c for _, c in nunca] or []
    orden = [c for _, c in nunca] + [c for _, c in vistos]

    mejor_id = (estado.get("mejor") or {}).get("id")
    if mejor_id in combos:
        orden.sort(key=lambda c: c != mejor_id)
    return orden[: max(presupuesto, 1)]


def recolectar(api, cfg, tanda, log=print):
    """Consulta cada combinación de la tanda. Una consulta por par de fechas."""
    por_combo, insights, errores = {}, {}, []
    consultas = 0

    for cid in tanda:
        ida, vuelta = cid.split("|")
        consultas += 1
        try:
            ofertas, pi = api.buscar(cfg, ida, vuelta)
        except SinCuota as e:
            # El plan del mes se acabó: seguir sólo gasta tiempo.
            errores.append({"combo": cid, "fuente": "google-flights", "error": str(e)})
            log(f"  ! {cid}: sin cuota, corto la corrida acá", archivo=sys.stderr)
            break
        except SerpApiError as e:
            errores.append({"combo": cid, "fuente": "google-flights", "error": str(e)})
            log(f"  ! {cid}: {e}", archivo=sys.stderr)
            continue

        if not ofertas:
            log(f"  - {cid}: sin ofertas")
            continue
        por_combo[cid] = ofertas
        if pi:
            insights[cid] = pi
        log(f"  + {cid}: {cfg.get('moneda','USD')} {ofertas[0]['precio']:,.0f} "
            f"({ofertas[0]['aerolinea_nombre']}, {len(ofertas)} opciones)")

    return por_combo, insights, errores, consultas


def verificar_con_edreams(cfg, por_combo, cuantas, calibrar_en=None, log=print):
    """Cruza en vivo las combinaciones más baratas. Best-effort: nunca corta la corrida."""
    errores = []
    if not cuantas or not por_combo:
        return errores
    if not edreams.disponible():
        log("  . edreams: falta playwright; sigo sin verificación en vivo")
        return errores

    ranking = sorted(por_combo.items(), key=lambda kv: min(o["precio"] for o in kv[1]))
    for cid, _ in ranking[:cuantas]:
        ida, vuelta = cid.split("|")
        try:
            ofertas = edreams.buscar(cfg, ida, vuelta, calibrar_en=calibrar_en)
            por_combo[cid].extend(ofertas)
            log(f"  + edreams {cid}: {len(ofertas)} tarifas")
        except Exception as e:
            errores.append({"combo": cid, "fuente": "edreams",
                            "error": f"{type(e).__name__}: {e}"})
            log(f"  ! edreams {cid}: {type(e).__name__}: {e}", archivo=sys.stderr)
    return errores


def hace_falta_agencias(mejor, estado, cfg, hoy, alerta=None):
    """Decide si vale gastar las 2 consultas que cuesta saber quién lo vende.

    Preguntarlo todos los días gastaría 62 consultas al mes de las 250 del plan
    para repetir casi siempre la misma respuesta, y la grilla se quedaría sin
    presupuesto. Se pregunta sólo cuando puede haber cambiado la respuesta.

    El movimiento de precio pide un mínimo propio y no cualquier diferencia: la
    rotación vuelve a medir el mejor combo todos los días, así que un umbral de
    un dólar dispara casi siempre y el ahorro desaparece. Y por si un mes sale
    especialmente movido, hay un techo mensual: el plan tiene 250 consultas y la
    grilla ya se lleva 217.

    Una baja de precio entra aunque no llegue al umbral. Es el unico dia en que
    el dato se usa de verdad: el mail lleva en el asunto lo que de verdad se
    puede pagar, y `precio_itinerario` solo se refresca cuando se pregunta. Sin
    esto, el asunto podria anunciar una baja con un precio de agencia medido
    hace una semana.
    """
    contador = estado.get("agencias_mes") or {}
    if (contador.get("mes") == hoy[:7]
            and contador.get("veces", 0) >= cfg.get("agencias_max_mes", 12)):
        # El techo mensual es duro, tambien para las bajas: protege el plan.
        return None

    if alerta and alerta.get("tipo") == "baja":
        return "bajó el precio"

    previo = (estado.get("combos") or {}).get(mejor["id"], {})
    if not previo.get("agencias"):
        return "primera vez"
    if (estado.get("mejor") or {}).get("id") != mejor["id"]:
        return "cambió el mejor combo"

    antes = previo.get("precio")
    if antes:
        movimiento = abs(mejor["precio"] - antes) / antes * 100
        if movimiento >= cfg.get("agencias_umbral_pct", 5.0):
            return f"el precio se movió {movimiento:.1f}%"
    return None


def contar_agencias(estado, hoy):
    """Suma una al contador mensual de consultas de agencias."""
    contador = estado.get("agencias_mes") or {}
    if contador.get("mes") != hoy[:7]:
        return {"mes": hoy[:7], "veces": 1}
    return {"mes": hoy[:7], "veces": contador.get("veces", 0) + 1}


def calcular_alerta(mejor, estado):
    """Decide si la corrida de hoy merece un mail.

    Compara contra la corrida anterior, no contra el minimo historico: el dueño quiere
    enterarse cuando el precio de hoy es menor al de ayer, aunque siga por encima del
    piso de la serie. Cualquier baja cuenta, sin umbral de porcentaje.
    """
    if not mejor:
        return None
    mejor_previo = estado.get("mejor") or {}
    precio_previo = mejor_previo.get("precio")
    if not precio_previo:
        return {"tipo": "primera_medicion", "hasta": mejor["precio"]}
    if mejor["precio"] >= precio_previo:
        return None
    baja = precio_previo - mejor["precio"]
    # El mejor precio tambien cae cuando la rotacion estrena un combo que nunca se
    # habia medido. Eso es cobertura nueva, no un precio que se movio, y el mail
    # tiene que poder decir la diferencia.
    medidos_antes = set((estado.get("combos") or {}).keys())
    return {
        "tipo": "baja",
        "desde": precio_previo,
        "hasta": mejor["precio"],
        "baja": round(baja, 2),
        "pct": round(baja / precio_previo * 100, 1),
        "motivo": "combo_conocido" if mejor["id"] in medidos_antes else "combo_nuevo",
        "combo": mejor["id"],
        "combo_previo": mejor_previo.get("id"),
    }


def armar_combo(cid, ofertas, previo, hoy, insight=None):
    ida, vuelta = cid.split("|")
    ofertas = sorted(ofertas, key=lambda o: o["precio"])
    mejor = ofertas[0]
    por_fuente = {}
    for o in ofertas:
        por_fuente.setdefault(o["fuente"], o["precio"])
    return {
        "ida": ida, "vuelta": vuelta, "visto": hoy,
        "precio": mejor["precio"], "moneda": mejor["moneda"],
        "precio_previo": previo.get("precio"),
        "por_fuente": por_fuente,
        "insight": insight,
        "opciones": [{k: v for k, v in o.items() if not k.startswith("_")}
                     for o in ofertas[:3]],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(RAIZ / "config.json"))
    ap.add_argument("--estado", help="JSON con la corrida anterior (opcional)")
    ap.add_argument("--salida", default=str(RAIZ / "salida" / "resultado.json"))
    ap.add_argument("--presupuesto", type=int,
                    help="consultas de esta corrida; pisa config.presupuesto_consultas")
    ap.add_argument("--fuentes", help="lista separada por comas; pisa config.fuentes")
    ap.add_argument("--plan", action="store_true", help="muestra qué consultaría y sale")
    ap.add_argument("--calibrar", metavar="DIR",
                    help="guarda lo que devuelve eDreams en DIR para ajustar el parseo")
    args = ap.parse_args()

    cfg = json.loads(pathlib.Path(args.config).read_text())
    estado = {}
    if args.estado and pathlib.Path(args.estado).exists():
        estado = json.loads(pathlib.Path(args.estado).read_text()) or {}

    idas = rango_fechas(**cfg["fechas_ida"])
    vueltas = rango_fechas(**cfg["fechas_vuelta"])
    fuentes = [f.strip() for f in (args.fuentes or "").split(",") if f.strip()] \
        or cfg.get("fuentes", ["gflights"])
    presupuesto = args.presupuesto or cfg.get("presupuesto_consultas", 8)
    grilla = [f"{i}|{v}" for i in idas for v in vueltas]
    tanda = elegir_combos(grilla, estado, presupuesto)

    if args.plan:
        print(f"grilla: {len(grilla)} combinaciones "
              f"({len(idas)} idas x {len(vueltas)} vueltas)")
        print(f"fuentes: {', '.join(fuentes)}")
        print(f"esta corrida consultaría {len(tanda)} (1 consulta cada una):")
        for cid in tanda:
            print("  " + cid.replace("|", " -> "))
        if cfg.get("buscar_agencias", True):
            if not estado:
                detalle = " (con --estado se puede saber si hoy haría falta)"
            else:
                motivo = hace_falta_agencias(estado.get("mejor") or {"id": "", "precio": 0},
                                             estado, cfg, dt.date.today().isoformat())
                detalle = f" ({motivo})" if motivo else ", hoy no haría falta"
            print("+ 2 consultas para ver qué agencias venden la más barata" + detalle)
        return 0

    def log(msg, archivo=sys.stdout):
        print(msg, file=archivo)

    hoy = dt.date.today().isoformat()
    agencias_mes = estado.get("agencias_mes")
    api = GoogleFlights()
    por_combo, insights, errores, consultas = ({}, {}, [], 0)
    if "gflights" in fuentes:
        por_combo, insights, errores, consultas = recolectar(api, cfg, tanda, log=log)
    if "edreams" in fuentes:
        errores += verificar_con_edreams(
            cfg, por_combo, cfg.get("edreams_verificar_top", 3),
            calibrar_en=args.calibrar, log=log)

    previos = estado.get("combos", {})
    combos = dict(previos)
    for cid, ofertas in por_combo.items():
        if ofertas:
            combos[cid] = armar_combo(cid, ofertas, previos.get(cid, {}), hoy,
                                      insights.get(cid))

    con_precio = [v for v in combos.values() if v.get("precio")]
    mejor = None
    if con_precio:
        m = min(con_precio, key=lambda v: v["precio"])
        mejor = dict(m, id=f"{m['ida']}|{m['vuelta']}")

    # Antes de decidir si se preguntan las agencias, porque una baja es motivo.
    alerta = calcular_alerta(mejor, estado)

    if cfg.get("buscar_agencias", True) and mejor and por_combo.get(mejor["id"]):
        motivo = hace_falta_agencias(mejor, estado, cfg, hoy, alerta)
        if motivo:
            token = por_combo[mejor["id"]][0].get("_departure_token")
            try:
                datos, gastadas = api.agencias(cfg, mejor["ida"], mejor["vuelta"], token)
                consultas += gastadas
                if gastadas:
                    agencias_mes = contar_agencias(estado, hoy)
                if datos.get("agencias"):
                    combos[mejor["id"]]["agencias"] = datos["agencias"]
                    combos[mejor["id"]]["precio_itinerario"] = datos["precio_itinerario"]
                    mejor["agencias"] = datos["agencias"]
                    mejor["precio_itinerario"] = datos["precio_itinerario"]
                    log(f"  + agencias ({motivo}): " + ", ".join(
                        f"{a['agencia']} {a['precio']:,.0f}"
                        for a in datos["agencias"][:4]))
                else:
                    log("  - agencias: Google no devolvió opciones de reserva")
                    if datos.get("crudo"):
                        errores.append({"combo": mejor["id"], "fuente": "agencias",
                                        "error": "booking_options con forma inesperada",
                                        "crudo": datos["crudo"]})
            except SerpApiError as e:
                errores.append({"combo": mejor["id"], "fuente": "agencias",
                                "error": str(e)})
                log(f"  ! agencias: {e}", archivo=sys.stderr)
        else:
            # Arrastrar lo que ya se sabía: la lista no caducó, sólo no cambió.
            previo = (estado.get("combos") or {}).get(mejor["id"], {})
            if previo.get("agencias"):
                combos[mejor["id"]]["agencias"] = previo["agencias"]
                combos[mejor["id"]]["precio_itinerario"] = previo.get("precio_itinerario")
                mejor["agencias"] = previo["agencias"]
            log("  . agencias: sin cambios en el mejor precio, no se vuelven a pedir")

    minimo_previo = (estado.get("minimo_historico") or {}).get("precio")
    minimo = estado.get("minimo_historico")
    if mejor and (not minimo_previo or mejor["precio"] < minimo_previo):
        minimo = {"precio": mejor["precio"], "moneda": mejor["moneda"],
                  "fecha": hoy, "id": mejor["id"]}

    salida = {
        "fecha": hoy,
        "ruta": f"{cfg['origen']}-{cfg['destino']}",
        "moneda": cfg.get("moneda", "USD"),
        "pasajeros": f"{cfg.get('adultos', 1)} adulto"
                     + ("s" if cfg.get("adultos", 1) > 1 else ""),
        "fuentes": fuentes,
        "grilla": {"idas": idas, "vueltas": vueltas, "total": len(grilla)},
        "consultados_hoy": consultas,
        "cobertura": len(con_precio),
        "mejor": mejor,
        "minimo_historico": minimo,
        "agencias_mes": agencias_mes,
        "alerta": alerta,
        "combos": combos,
        "errores": errores,
    }

    destino = pathlib.Path(args.salida)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(salida, indent=2, ensure_ascii=False))
    print(f"\n-> {destino}")
    if mejor:
        print(f"   mejor: {mejor['moneda']} {mejor['precio']:,.0f}  "
              f"ida {mejor['ida']} / vuelta {mejor['vuelta']}  "
              f"({mejor['opciones'][0]['aerolinea_nombre']})")
    else:
        print("   sin resultados")
    return 0 if (con_precio or not errores) else 1


if __name__ == "__main__":
    sys.exit(main())
