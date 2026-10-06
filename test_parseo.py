#!/usr/bin/env python3
"""Prueba el parseo y el armado de la grilla sin tocar la red.

    python3 test_parseo.py
"""
import unittest

import gflights as gf
from buscar import (armar_combo, calcular_alerta, contar_agencias, elegir_combos,
                    hace_falta_agencias, rango_fechas, recolectar)

# Resultado tal como lo devuelve engine=google_flights con type=1: el precio es
# el TOTAL del ida y vuelta, `flights` son los tramos de la ida, `layovers` las
# escalas, y las duraciones vienen en minutos.
RESPUESTA = {
    "best_flights": [{
        "price": 1643, "total_duration": 1565,
        "layovers": [{"id": "SCL", "duration": 130}],
        "flights": [
            {"departure_airport": {"id": "SYD", "time": "2026-12-10 13:20"},
             "arrival_airport": {"id": "SCL", "time": "2026-12-10 11:10"},
             "duration": 770, "airline": "Qantas", "flight_number": "QF 27"},
            {"departure_airport": {"id": "SCL", "time": "2026-12-10 14:30"},
             "arrival_airport": {"id": "EZE", "time": "2026-12-10 17:05"},
             "duration": 155, "airline": "LATAM", "flight_number": "LA 458"},
        ],
    }],
    "other_flights": [{
        "price": 1890, "total_duration": 1780, "layovers": [],
        "flights": [
            {"departure_airport": {"id": "SYD", "time": "2026-12-10 10:50"},
             "arrival_airport": {"id": "EZE", "time": "2026-12-11 09:10"},
             "duration": 1780, "airline": "Aerolíneas Argentinas",
             "flight_number": "AR 1181"},
        ],
    }],
}
CFG = {"origen": "SYD", "destino": "EZE", "moneda": "USD"}


class FalsaApi:
    """Api de mentira: devuelve lo que se le pase y cuenta las llamadas."""

    def __init__(self, por_combo=None, error=None):
        self.por_combo = por_combo or {}
        self.error = error
        self.llamadas = []

    def buscar(self, cfg, ida, vuelta):
        self.llamadas.append(f"{ida}|{vuelta}")
        if self.error:
            raise self.error
        return self.por_combo.get(f"{ida}|{vuelta}", ([], None))


def oferta(precio, ida="2026-12-10", vuelta="2027-02-20", **extra):
    o = gf.normalizar(RESPUESTA["best_flights"][0], CFG, ida, vuelta, "http://gf")
    o["precio"] = float(precio)
    o.update(extra)
    return o


class Normalizar(unittest.TestCase):
    def setUp(self):
        crudas = RESPUESTA["best_flights"] + RESPUESTA["other_flights"]
        self.o = [gf.normalizar(x, CFG, "2026-12-10", "2027-02-22", "http://gf")
                  for x in crudas]

    def test_precio_es_numero(self):
        self.assertEqual([x["precio"] for x in self.o], [1643.0, 1890.0])
        self.assertIsInstance(self.o[0]["precio"], float)

    def test_el_precio_es_el_total_del_ida_y_vuelta(self):
        # En type=1 Google muestra el total del viaje en la lista de ida; si se
        # tomara como precio de un tramo, la grilla mostraria la mitad.
        self.assertEqual(self.o[0]["precio"], 1643.0)

    def test_escalas_desde_layovers(self):
        self.assertEqual(self.o[0]["ida"]["escalas"], 1)
        self.assertEqual(self.o[0]["ida"]["via"], ["SCL"])

    def test_vuelo_directo(self):
        self.assertEqual(self.o[1]["ida"]["escalas"], 0)
        self.assertEqual(self.o[1]["ida"]["via"], [])

    def test_duraciones_en_minutos(self):
        self.assertEqual(self.o[0]["ida"]["duracion"], "26h 05m")
        self.assertEqual(gf.duracion(45), "45m")
        self.assertEqual(gf.duracion(None), "")

    def test_segmentos_completos(self):
        segs = self.o[0]["ida"]["segmentos"]
        self.assertEqual([s["de"] for s in segs], ["SYD", "SCL"])
        self.assertEqual([s["a"] for s in segs], ["SCL", "EZE"])
        self.assertEqual(segs[0]["vuelo"], "QF 27")

    def test_la_vuelta_no_viene_en_esta_consulta(self):
        # El detalle del tramo de vuelta exige otra consulta con departure_token.
        self.assertIsNone(self.o[0]["vuelta"])

    def test_guarda_las_fechas_consultadas(self):
        self.assertEqual(self.o[0]["_ida"], "2026-12-10")
        self.assertEqual(self.o[0]["_vuelta"], "2027-02-22")

    def test_sin_precio_queda_en_none(self):
        self.assertIsNone(gf.normalizar({"flights": []}, CFG, "a", "b")["precio"])


class Rotacion(unittest.TestCase):
    GRILLA = [f"d{i}|v{j}" for i in range(3) for j in range(3)]

    def test_prioriza_los_nunca_vistos(self):
        estado = {"combos": {"d0|v0": {"visto": "2026-10-01"},
                             "d0|v1": {"visto": "2026-09-01"}}}
        self.assertEqual(elegir_combos(self.GRILLA, estado, 3),
                         ["d0|v2", "d1|v0", "d1|v1"])

    def test_despues_los_mas_viejos(self):
        estado = {"combos": {c: {"visto": "2026-10-0" + str(i % 9 + 1)}
                             for i, c in enumerate(self.GRILLA)}}
        elegidos = elegir_combos(self.GRILLA, estado, 2)
        self.assertEqual(elegidos, ["d0|v0", "d0|v1"])

    def test_el_mejor_va_siempre_primero(self):
        estado = {"combos": {c: {"visto": "2026-10-02"} for c in self.GRILLA},
                  "mejor": {"id": "d2|v1"}}
        self.assertEqual(elegir_combos(self.GRILLA, estado, 3)[0], "d2|v1")

    def test_un_mejor_que_ya_no_esta_en_la_grilla_no_rompe(self):
        # Si cambian las fechas en config, el mejor guardado puede no existir.
        estado = {"combos": {}, "mejor": {"id": "viejo|combo"}}
        self.assertEqual(len(elegir_combos(self.GRILLA, estado, 4)), 4)

    def test_nunca_devuelve_vacio(self):
        self.assertEqual(len(elegir_combos(self.GRILLA, {}, 0)), 1)

    def test_no_pide_mas_que_la_grilla(self):
        self.assertEqual(len(elegir_combos(self.GRILLA, {}, 99)), len(self.GRILLA))


class Recolectar(unittest.TestCase):
    TANDA = ["2026-12-10|2027-02-20", "2026-12-11|2027-02-20"]

    def test_una_consulta_por_combinacion(self):
        api = FalsaApi({c: ([oferta(1700)], None) for c in self.TANDA})
        combos, _, _, n = recolectar(api, CFG, self.TANDA, log=lambda *a, **k: None)
        self.assertEqual(n, 2)
        self.assertEqual(api.llamadas, self.TANDA)
        self.assertEqual(sorted(combos), sorted(self.TANDA))

    def test_sin_cuota_corta_la_corrida(self):
        # Seguir pidiendo con el plan agotado solo gasta tiempo.
        api = FalsaApi(error=gf.SinCuota("sin cuota"))
        combos, _, errores, n = recolectar(api, CFG, self.TANDA * 5,
                                           log=lambda *a, **k: None)
        self.assertEqual(len(api.llamadas), 1)
        self.assertEqual(combos, {})
        self.assertEqual(len(errores), 1)
        self.assertEqual(n, 1)

    def test_un_error_comun_no_corta(self):
        api = FalsaApi(error=gf.SerpApiError("500"))
        _, _, errores, n = recolectar(api, CFG, self.TANDA, log=lambda *a, **k: None)
        self.assertEqual(len(api.llamadas), 2)
        self.assertEqual(len(errores), 2)
        self.assertEqual(n, 2)

    def test_sin_ofertas_no_crea_combo(self):
        api = FalsaApi({self.TANDA[0]: ([], None)})
        combos, _, _, _ = recolectar(api, CFG, self.TANDA[:1],
                                     log=lambda *a, **k: None)
        self.assertEqual(combos, {})

    def test_guarda_el_price_insight(self):
        api = FalsaApi({self.TANDA[0]: ([oferta(1700)], {"price_level": "low"})})
        _, insights, _, _ = recolectar(api, CFG, self.TANDA[:1],
                                       log=lambda *a, **k: None)
        self.assertEqual(insights[self.TANDA[0]], {"price_level": "low"})


class CuandoPreguntarAgencias(unittest.TestCase):
    """Preguntarlo todos los dias gastaria 62 consultas al mes de 250, casi
    siempre para repetir la misma respuesta."""

    MEJOR = {"id": "2026-12-10|2027-02-24", "precio": 2282.0}
    CFG = {"agencias_umbral_pct": 5.0, "agencias_max_mes": 12}
    HOY = "2026-10-06"

    def est(self, **kw):
        base = {"mejor": {"id": self.MEJOR["id"]},
                "combos": {self.MEJOR["id"]: {"agencias": [{"agencia": "eDreams"}],
                                              "precio": 2282.0}}}
        base.update(kw)
        return base

    def falta(self, estado):
        return hace_falta_agencias(self.MEJOR, estado, self.CFG, self.HOY)

    def test_la_primera_vez_siempre(self):
        self.assertEqual(self.falta({}), "primera vez")

    def test_sin_cambios_no_se_pregunta(self):
        self.assertIsNone(self.falta(self.est()))

    def test_un_movimiento_chico_no_alcanza(self):
        # La rotacion vuelve a medir el mejor combo todos los dias: si cualquier
        # diferencia disparara, se gastarian las 2 consultas casi siempre.
        e = self.est()
        e["combos"][self.MEJOR["id"]]["precio"] = 2300.0   # 0,8%
        self.assertIsNone(self.falta(e))

    def test_un_movimiento_real_si(self):
        e = self.est()
        e["combos"][self.MEJOR["id"]]["precio"] = 2450.0   # 6,9%
        self.assertIn("se movió", self.falta(e))

    def test_tambien_dispara_si_baja(self):
        e = self.est()
        e["combos"][self.MEJOR["id"]]["precio"] = 2100.0
        self.assertIn("se movió", self.falta(e))

    def test_si_otro_combo_paso_a_ser_el_mejor(self):
        self.assertEqual(self.falta(self.est(mejor={"id": "2026-12-15|2027-02-22"})),
                         "cambió el mejor combo")

    def test_lista_vacia_cuenta_como_nunca_preguntado(self):
        e = self.est()
        e["combos"][self.MEJOR["id"]]["agencias"] = []
        self.assertEqual(self.falta(e), "primera vez")

    def test_el_techo_del_mes_frena_todo(self):
        e = self.est(agencias_mes={"mes": "2026-10", "veces": 12})
        e["combos"][self.MEJOR["id"]]["precio"] = 2450.0
        self.assertIsNone(self.falta(e))

    def test_el_techo_se_reinicia_cada_mes(self):
        e = self.est(agencias_mes={"mes": "2026-09", "veces": 12})
        e["combos"][self.MEJOR["id"]]["precio"] = 2450.0
        self.assertIn("se movió", self.falta(e))

    def test_el_techo_tambien_frena_la_primera_vez(self):
        e = {"agencias_mes": {"mes": "2026-10", "veces": 12}}
        self.assertIsNone(self.falta(e))

    def test_contador(self):
        self.assertEqual(contar_agencias({}, self.HOY), {"mes": "2026-10", "veces": 1})
        self.assertEqual(contar_agencias({"agencias_mes": {"mes": "2026-10", "veces": 3}},
                                         self.HOY), {"mes": "2026-10", "veces": 4})
        self.assertEqual(contar_agencias({"agencias_mes": {"mes": "2026-09", "veces": 9}},
                                         self.HOY), {"mes": "2026-10", "veces": 1})


class Grilla(unittest.TestCase):
    def test_rango_inclusivo(self):
        self.assertEqual(len(rango_fechas("2026-12-10", "2026-12-20")), 11)
        self.assertEqual(len(rango_fechas("2027-02-20", "2027-02-25")), 6)

    def test_rango_invertido_falla(self):
        with self.assertRaises(ValueError):
            rango_fechas("2026-12-20", "2026-12-10")


class ArmarCombo(unittest.TestCase):
    CID = "2026-12-10|2027-02-20"

    def test_se_queda_con_la_mas_barata_y_guarda_tres(self):
        ofertas = [oferta(p) for p in (2100, 1643, 1890, 2400)]
        c = armar_combo(self.CID, ofertas, {}, "2026-10-05")
        self.assertEqual(c["precio"], 1643.0)
        self.assertEqual([o["precio"] for o in c["opciones"]], [1643.0, 1890.0, 2100.0])

    def test_precio_por_fuente(self):
        a = oferta(1700)
        b = oferta(1590, fuente="edreams")
        c = armar_combo(self.CID, [a, b], {}, "2026-10-05")
        self.assertEqual(c["por_fuente"], {"edreams": 1590.0, "google-flights": 1700.0})
        self.assertEqual(c["precio"], 1590.0)

    def test_arrastra_el_precio_anterior(self):
        c = armar_combo(self.CID, [oferta(1643)], {"precio": 1890.0}, "2026-10-05")
        self.assertEqual(c["precio_previo"], 1890.0)

    def test_no_filtra_campos_internos(self):
        c = armar_combo(self.CID, [oferta(1643)], {}, "2026-10-05")
        self.assertFalse([k for k in c["opciones"][0] if k.startswith("_")])


class EdreamsParseo(unittest.TestCase):
    """eDreams devuelve el precio de formas distintas segun el endpoint."""

    def test_numero_plano_y_string(self):
        import edreams
        self.assertEqual(edreams._num(1899.3), 1899.3)
        self.assertEqual(edreams._num("1704.55"), 1704.55)

    def test_formato_es_y_en(self):
        import edreams
        self.assertEqual(edreams._num("US$ 1.899,30"), 1899.30)   # es-AR
        self.assertEqual(edreams._num("US$ 1,899.30"), 1899.30)   # en-US
        self.assertEqual(edreams._num("$2 450"), 2450.0)

    def test_precio_anidado(self):
        # La forma mas comun: {"totalPrice": {"amount": ..., "currency": ...}}.
        import edreams
        self.assertEqual(edreams._num({"amount": "1.899,30", "currency": "USD"}), 1899.30)
        self.assertEqual(edreams._num({"value": 1704.55}), 1704.55)

    def test_booleano_no_es_precio(self):
        import edreams
        self.assertIsNone(edreams._num(True))

    def test_extrae_ambas_formas_y_ordena(self):
        import edreams, json as _json
        payload = _json.dumps({"results": [
            {"totalPrice": {"amount": "1.899,30", "currency": "USD"},
             "itineraries": [{"x": 1}], "carrier": {"name": "Qantas"}},
            {"price": 1704.55, "segments": [{"x": 1}], "airline": "LATAM"},
        ]})
        ofertas = edreams.extraer([payload])
        self.assertEqual([o["precio"] for o in ofertas], [1704.55, 1899.30])
        self.assertEqual(ofertas[0]["aerolinea_nombre"], "LATAM")
        self.assertTrue(all(o["fuente"] == "edreams" for o in ofertas))

    def test_ignora_objetos_sin_forma_de_vuelo(self):
        # Un precio suelto (un hotel, un seguro) no es una oferta de vuelo.
        import edreams, json as _json
        self.assertEqual(edreams.extraer([_json.dumps({"price": 320, "hotel": "x"})]), [])

    def test_json_invalido_no_rompe(self):
        import edreams
        self.assertEqual(edreams.extraer(["no es json", ""]), [])

    def test_url_lleva_las_fechas_y_la_clase(self):
        import edreams
        u = edreams.url({"origen": "SYD", "destino": "EZE", "adultos": 1,
                         "clase": "ECONOMY"}, "2026-12-10", "2027-02-20")
        self.assertIn("from=SYD", u)
        self.assertIn("to=EZE", u)
        self.assertIn("dep=2026-12-10", u)
        self.assertIn("ret=2027-02-20", u)
        self.assertIn("cabinClass=ECONOMIC", u)


class Agencias(unittest.TestCase):
    """`booking_options` dice quien vende el vuelo y a cuanto."""

    def test_opcion_entera(self):
        a = gf.extraer_agencias({"booking_options": [
            {"together": {"book_with": "eDreams", "price": 2282}}]})
        self.assertEqual(a, [{"agencia": "eDreams", "precio": 2282.0, "tramo": "todo"}])

    def test_ordena_por_precio(self):
        a = gf.extraer_agencias({"booking_options": [
            {"together": {"book_with": "Qantas", "price": 2401}},
            {"together": {"book_with": "eDreams", "price": 2282}}]})
        self.assertEqual([x["agencia"] for x in a], ["eDreams", "Qantas"])

    def test_tramos_por_separado(self):
        # Cuando cada tramo se compra en un lado distinto vienen los dos.
        a = gf.extraer_agencias({"booking_options": [
            {"departing": {"book_with": "Kiwi.com", "price": 1180},
             "returning": {"book_with": "Gotogate", "price": 1240}}]})
        self.assertEqual([(x["agencia"], x["tramo"]) for x in a],
                         [("Kiwi.com", "ida"), ("Gotogate", "vuelta")])

    def test_no_repite_la_misma_agencia(self):
        a = gf.extraer_agencias({"booking_options": [
            {"together": {"book_with": "eDreams", "price": 2282}},
            {"together": {"book_with": "eDreams", "price": 2282}}]})
        self.assertEqual(len(a), 1)

    def test_descarta_incompletas(self):
        a = gf.extraer_agencias({"booking_options": [
            {"together": {"book_with": "", "price": 999}},
            {"together": {"book_with": "Sin precio"}},
            {"together": {"book_with": "Precio raro", "price": "2282"}},
            "basura"]})
        self.assertEqual(a, [])

    def test_sin_opciones(self):
        self.assertEqual(gf.extraer_agencias({}), [])
        self.assertEqual(gf.extraer_agencias({"booking_options": None}), [])

    def test_sin_token_no_gasta_consultas(self):
        # Si el combo no se midio hoy no hay token, y no hay que gastar nada.
        api = gf.GoogleFlights()
        datos, gastadas = api.agencias(CFG, "2026-12-10", "2027-02-20", None)
        self.assertEqual(gastadas, 0)
        self.assertEqual(datos["agencias"], [])

    def test_se_queda_con_el_precio_menor_de_cada_agencia(self):
        # Google puede repetir una agencia sin ordenarla de barata a cara.
        # Deduplicar por el primero que aparece publica el caro y tira el barato.
        a = gf.extraer_agencias({"booking_options": [
            {"together": {"book_with": "eDreams", "price": 2450}},
            {"together": {"book_with": "eDreams", "price": 2282}}]})
        self.assertEqual(a, [{"agencia": "eDreams", "precio": 2282.0, "tramo": "todo"}])

    def test_un_booleano_no_es_precio(self):
        # bool es int en Python: True entraria como 1.0 y quedaria primero.
        a = gf.extraer_agencias({"booking_options": [
            {"together": {"book_with": "Trampa", "price": True}},
            {"together": {"book_with": "eDreams", "price": 2282}}]})
        self.assertEqual([x["agencia"] for x in a], ["eDreams"])

    def test_la_oferta_guarda_el_token(self):
        # Sin el token no se puede llegar a las agencias.
        cruda = dict(RESPUESTA["best_flights"][0], departure_token="tok123")
        o = gf.normalizar(cruda, CFG, "2026-12-10", "2027-02-20")
        self.assertEqual(o["_departure_token"], "tok123")

    def test_el_token_no_llega_al_portal(self):
        cruda = dict(RESPUESTA["best_flights"][0], departure_token="tok123")
        c = armar_combo("2026-12-10|2027-02-20",
                        [gf.normalizar(cruda, CFG, "2026-12-10", "2027-02-20")],
                        {}, "2026-10-05")
        self.assertNotIn("_departure_token", c["opciones"][0])


class CuandoAvisar(unittest.TestCase):
    """el dueño pidio mail SOLO si el precio de hoy es menor al de la corrida anterior.

    No hay umbral: un dolar menos es menos. Y no hay mail los dias sin baja, ni
    siquiera un 'todo normal' — pidio silencio explicitamente.
    """

    def mejor(self, precio, cid="2026-12-10|2027-02-24"):
        ida, vuelta = cid.split("|")
        return {"id": cid, "ida": ida, "vuelta": vuelta, "precio": precio}

    def estado(self, precio, cid="2026-12-10|2027-02-24", combos=None):
        ida, vuelta = cid.split("|")
        return {"mejor": {"id": cid, "ida": ida, "vuelta": vuelta, "precio": precio},
                "combos": combos if combos is not None else {cid: {"precio": precio}}}

    def test_baja_de_un_dolar_avisa(self):
        # El umbral del 5% quedo atras a proposito: cualquier baja cuenta.
        a = calcular_alerta(self.mejor(2281.0), self.estado(2282.0))
        self.assertEqual(a["tipo"], "baja")
        self.assertEqual(a["baja"], 1.0)
        self.assertEqual(a["desde"], 2282.0)
        self.assertEqual(a["hasta"], 2281.0)

    def test_mismo_precio_no_avisa(self):
        self.assertIsNone(calcular_alerta(self.mejor(2282.0), self.estado(2282.0)))

    def test_suba_no_avisa(self):
        self.assertIsNone(calcular_alerta(self.mejor(2400.0), self.estado(2282.0)))

    def test_compara_contra_la_corrida_anterior_no_contra_el_minimo(self):
        # Ayer 2500, el piso historico 2000: hoy 2400 es mas caro que el piso pero
        # mas barato que ayer, y es lo que el dueño pidio que le avisen.
        estado = self.estado(2500.0)
        estado["minimo_historico"] = {"precio": 2000.0}
        a = calcular_alerta(self.mejor(2400.0), estado)
        self.assertEqual(a["tipo"], "baja")
        self.assertEqual(a["desde"], 2500.0)

    def test_primera_medicion_no_es_baja(self):
        a = calcular_alerta(self.mejor(2282.0), {})
        self.assertEqual(a["tipo"], "primera_medicion")

    def test_sin_resultados_no_hay_alerta(self):
        self.assertIsNone(calcular_alerta(None, self.estado(2282.0)))

    def test_distingue_baja_real_de_cobertura_nueva(self):
        # Combo ya medido que ahora vale menos: el precio se movio.
        viejo = "2026-12-10|2027-02-24"
        a = calcular_alerta(self.mejor(2100.0, viejo), self.estado(2282.0, viejo))
        self.assertEqual(a["motivo"], "combo_conocido")

        # Combo que la rotacion estrena hoy: es mas barato que todo lo conocido,
        # pero su precio no bajo, recien se lo midio. El mail no puede decir que cayo.
        nuevo = "2026-12-18|2027-02-21"
        a = calcular_alerta(self.mejor(2100.0, nuevo), self.estado(2282.0, viejo))
        self.assertEqual(a["motivo"], "combo_nuevo")
        self.assertEqual(a["combo"], nuevo)
        self.assertEqual(a["combo_previo"], viejo)

    def test_porcentaje_redondeado(self):
        a = calcular_alerta(self.mejor(2000.0), self.estado(2500.0))
        self.assertEqual(a["pct"], 20.0)


class AgenciasCuandoBaja(unittest.TestCase):
    """Una baja obliga a refrescar las agencias, para que el asunto del mail
    lleve un precio comprable y no uno medido hace una semana."""

    CFG = {"agencias_umbral_pct": 5.0, "agencias_max_mes": 12}
    MEJOR = {"id": "a|b", "precio": 2000.0}
    BAJA = {"tipo": "baja", "desde": 2010.0, "hasta": 2000.0}

    def estado(self, precio=2010.0):
        # Agencias ya preguntadas: sin la baja, hoy no haria falta preguntar.
        return {"mejor": {"id": "a|b", "precio": precio},
                "combos": {"a|b": {"precio": precio, "agencias": [{"agencia": "X"}]}}}

    def test_una_baja_chica_igual_dispara(self):
        # 0,5% esta muy por debajo del umbral del 5%, pero es una baja.
        self.assertIsNone(
            hace_falta_agencias(self.MEJOR, self.estado(), self.CFG, "2026-10-06"))
        self.assertEqual(
            hace_falta_agencias(self.MEJOR, self.estado(), self.CFG, "2026-10-06", self.BAJA),
            "bajó el precio")

    def test_sin_baja_sigue_sin_preguntar(self):
        for alerta in (None, {"tipo": "primera_medicion"}):
            self.assertIsNone(
                hace_falta_agencias(self.MEJOR, self.estado(), self.CFG, "2026-10-06", alerta))

    def test_el_techo_mensual_gana_sobre_la_baja(self):
        # El techo protege el plan de SerpApi: ni una baja lo perfora.
        estado = dict(self.estado(), agencias_mes={"mes": "2026-10", "veces": 12})
        self.assertIsNone(
            hace_falta_agencias(self.MEJOR, estado, self.CFG, "2026-10-06", self.BAJA))


if __name__ == "__main__":
    unittest.main(verbosity=1)
