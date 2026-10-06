# pasajes-rutina

Seguimiento diario del precio de un pasaje de ida y vuelta, que corre solo en la nube y
avisa por mail cuando baja. La ruta y las fechas salen de `config.json`: cambiando ese
archivo sirve para cualquier viaje.

**Para armar el tuyo desde cero, leé [`INSTALAR.md`](INSTALAR.md).**

La configuración que está hoy en el repo sigue un **Sydney (SYD) → Buenos Aires / Ezeiza (EZE)**.

- **Ida:** 10 al 20 de diciembre de 2026
- **Vuelta:** 20 al 25 de febrero de 2027
- **Pasajeros:** 1 adulto, clase económica
- **Fuente:** Google Flights, vía SerpApi
- **Portal:** el que indique `config.portal` (se publica al instalar)

Una rutina diaria consulta los precios, guarda el resultado en la base del portal y
manda un mail cuando el precio de hoy es **menor** al de la corrida anterior. Cualquier
baja cuenta: no hay umbral de porcentaje. Los días sin baja no manda nada.

El mail sale por Outlook, desde la casilla del propio dueño, porque las notificaciones
de Claude no llegaban: ver la sección "Cómo se avisa" en `RUTINA.md`.

## Archivos

| Archivo | Para qué |
|---|---|
| `config.json` | Ruta, rango de fechas, pasajeros, moneda y presupuesto de consultas |
| `gflights.py` | Cliente de Google Flights vía SerpApi, con reintentos ante 5xx |
| `edreams.py` | Fuente eDreams por navegador (hoy inactiva, ver más abajo) |
| `buscar.py` | Recorre la grilla de fechas y escribe un JSON con el resultado |
| `test_parseo.py` | Tests del parseo y del armado de la grilla, sin red |
| `RUTINA.md` | Los pasos exactos que ejecuta la rutina diaria |
| `portal/index.html` | Fuente del portal publicado |

## Requisitos

Sólo la biblioteca estándar de Python 3.9+.

Dos variables de entorno, cargadas en el entorno del sandbox y nunca en el repo:

```
SERPAPI_KEY    la clave de la API de precios
AVISAR_A       la dirección de mail que recibe los avisos
```

La dirección va ahí y no en `config.json` porque este repositorio puede ser público: un
mail escrito en un archivo versionado queda publicado aunque después se borre, porque el
historial de git lo conserva.

Si falta `AVISAR_A`, la búsqueda corre igual y el portal se actualiza; lo único que no
sale es el aviso, y la corrida lo dice.

Y que la política de red del entorno permita estos dominios:

| Dominio | Para qué |
|---|---|
| `serpapi.com` | La API de Google Flights |
| `www.edreams.com` | El buscador de eDreams (cuando se active esa fuente) |
| `pypi.org`, `files.pythonhosted.org` | Instalar Playwright (ídem) |

## Uso manual

```bash
python3 buscar.py --plan                      # qué consultaría, sin gastar cuota
python3 buscar.py --presupuesto 1             # una sola consulta, para probar
python3 buscar.py --estado estado.json \
                  --salida salida/hoy.json    # corrida real
python3 test_parseo.py                        # los tests
```

## El presupuesto de consultas

Son 11 fechas de ida × 6 de vuelta = **66 combinaciones**, y Google Flights no tiene
búsqueda por rango de fechas: cada par cuesta **una consulta**. La grilla entera no
entra en un día dentro de ningún plan razonable, así que cada corrida gasta un
presupuesto fijo (`presupuesto_consultas`) y reparte las consultas por rotación:
primero el mejor combo conocido, para que ese precio sea siempre el de hoy, y después
los que hace más tiempo que no se miden.

| Plan de SerpApi | Consultas/mes | `presupuesto_consultas` | Grilla al día cada |
|---|---|---|---|
| Gratuito | 250 | **7** (por omisión) | ~10 días |
| USD 25/mes | 1.000 | 30 | ~2 días |

A eso se le suman **2 consultas** cuando hay que averiguar qué agencia vende la
combinación más barata, lo que no pasa todos los días.

La cuenta del plan gratuito: 7 × 31 = 217 de grilla, quedan 33. A 2 por consulta de
agencias, el techo son 16 disparos al mes. `agencias_max_mes` lo corta en 12 (24
consultas), para dejar margen a una corrida manual o un reintento.

Pedir las agencias todos los días daría 62 consultas mensuales para repetir casi
siempre la misma respuesta, y el mes cerraría en 279 de 250.

Si el plan se agota a mitad de mes la API responde 429 y la corrida **corta ahí**, en
vez de seguir gastando tiempo. Lo ya medido se conserva.

## Nota sobre los precios

Son los mismos precios que verías entrando a Google Flights: lo que aerolíneas y
agencias publican en ese momento, eDreams entre ellas. El portal guarda el enlace de
cada búsqueda para confirmar el valor antes de comprar.

En una búsqueda de ida y vuelta, Google devuelve el **precio total del viaje** junto
con el detalle del tramo de ida. El detalle del tramo de vuelta exige una segunda
consulta, que duplicaría el gasto, así que no se pide: para seguir un precio no hace
falta, y la fecha de vuelta se conoce igual porque es la que se consultó.

## Qué agencia vende cada vuelo

Google no dice en la búsqueda quién vende el pasaje. Para saberlo hay que elegir un
itinerario de ida (`departure_token`), lo que devuelve los vuelos de vuelta con un
`booking_token`, y recién ese token trae `booking_options` con el nombre de cada
agencia y su precio. Son dos consultas encadenadas, así que corre sólo sobre la
combinación más barata del día.

Sólo se pregunta cuando puede haber cambiado la respuesta:

- la primera vez,
- cuando otro combo pasa a ser el más barato,
- cuando el precio de ese combo se movió **al menos `agencias_umbral_pct`** (5% por
  omisión), para arriba o para abajo.

Ese umbral no es un detalle: la rotación vuelve a medir el mejor combo todos los días,
así que disparar ante cualquier diferencia de un dólar haría que se pregunte casi
siempre y el ahorro desaparece. Y por encima de todo está `agencias_max_mes`, un techo
duro por si un mes sale especialmente movido.

Si nada de eso pasó, se arrastra la lista del día anterior sin gastar nada.

El resultado queda en `combos/{id}.agencias` y el portal lo muestra bajo "Vendido por".
Junto a él va `precio_itinerario`: el total del itinerario que se terminó cotizando,
que puede no ser exactamente el de la grilla. Cuando difieren, el portal lo aclara en
vez de mostrar dos números que no cierran.
Una opción puede venir entera (`together`: una agencia vende el viaje completo) o
partida en `departing` / `returning`, cuando cada tramo se compra por separado; el
portal marca esas con "sólo ida" o "sólo vuelta".

## eDreams por scraping

eDreams no publica una API abierta, así que `edreams.py` pasa por el sitio con un
navegador headless e intercepta las respuestas JSON del buscador, en vez de leer el
HTML con selectores CSS que se rompen con cada rediseño.

**Hoy no puede correr**, pero el motivo cambió. Probado en vivo el 6/10/2026:

1. **TLS: resuelto.** El sandbox intercepta TLS con su propia autoridad y el Chromium del
   contenedor no la tenía cargada, de ahí el `ERR_CERT_AUTHORITY_INVALID`. Se arregla así,
   y está verificado —Chromium abre `www.edreams.com` y devuelve 200:

   ```bash
   apt-get install -y libnss3-tools
   certutil -d "sql:$HOME/.pki/nssdb" -A -t "C,," \
            -n ccr-agent-proxy -i /root/.ccr/agent-proxy-ca.crt
   ```

   Usar `agent-proxy-ca.crt`, que es un certificado solo, y **no** `ca-bundle.crt`, que
   son 197 KB y tarda muchísimo en importarse entero. Esto no sobrevive al contenedor:
   va en el script de arranque del entorno, o al principio de la corrida.

2. **Red: no es el problema.** `www.edreams.com` está permitido en la política del
   entorno y responde 200.

3. **La URL de búsqueda ya no sirve. Éste es el bloqueo real.** `PLANTILLA` arma
   `…/travel/#results/type=R;from=SYD;to=EZE;…`, un deep link con fragmento, y eDreams
   lo ignora: carga el home. Se probaron cuatro formatos —`#results/`, `#/results/`,
   `#search/` y la ruta por nombre de ciudad— y ninguno llega a resultados; los tres
   primeros dan el home y el cuarto un 404. Una corrida de calibración capturó 54
   respuestas JSON y son todas del home: ofertas a San Francisco y Londres, con
   `flightDetailsDTO.segments` vacío.

   Resolverlo es reconstruir el esquema de URLs actual de eDreams, o manejar el
   formulario del sitio paso a paso. No es un ajuste de parseo: el parseo nunca llegó a
   ver una tarifa.

**Y hay algo más que conviene saber antes de invertir ahí:** eDreams no es una fuente
independiente. `verificar_con_edreams()` sólo revisa los combos que **ya encontró
Google**, así que no sirve para descubrir precios que Google no ve. Corriendo con
`--fuentes edreams` a secas no hace nada, porque no tiene qué verificar.

Mientras tanto `fuentes` no lo incluye y la corrida va sólo con Google Flights, que de
todos modos muestra agencias entre sus opciones de compra.

El código y sus tests quedan listos para cuando eso se resuelva. Falta además calibrar
los nombres de campo contra el sitio real, para lo que está el modo:

```bash
python3 buscar.py --fuentes edreams --calibrar calib/
```

Guarda el HTML, una captura y todas las respuestas JSON de una búsqueda.

## Fuentes que se descartaron

**Amadeus** fue la fuente original. Cerró su portal self-service el 17 de julio de 2026
y lo que queda requiere contrato comercial.

**Travelpayouts / Aviasales** se probó en vivo el 5 de octubre de 2026, con token válido,
y falla por dos motivos independientes:

1. **Tope de 30 días entre ida y vuelta.** `prices_for_dates` y `grouped_prices`
   rechazan con 400 cualquier ida y vuelta con más diferencia:
   `diff between max depart date and min return date exceeds supported maximum of 30`.
   Este viaje son ~74 días. Con 20 días de gap la consulta pasa.

2. **El cache está vacío para esta ruta.** Como control, `JFK→LHR` devuelve 12 tarifas
   para diciembre y `MAD→EZE` devuelve 23. `SYD→EZE` devuelve **1**, para todo el mes, y
   es del 24 de diciembre: fuera del rango buscado. No cambia con `market` (`ar`, `au`,
   `us`, sin especificar) ni usando el código de ciudad `BUE` en vez de `EZE`. Sus
   precios son los que encontraron usuarios de Aviasales en las últimas 48 h, y
   Sydney–Buenos Aires casi no se busca ahí.
