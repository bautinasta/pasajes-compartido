# Rutina diaria

## Dónde corre

La rutina **despierta una sesión de trabajo dedicada** (`Pasajes SYD-EZE — corridas
diarias`) que tiene este repo adjunto de forma permanente. No crea una sesión nueva en
cada disparo.

Esto no es un detalle: se probó al revés primero y no funciona. Una sesión recién creada
por la rutina nace **sin acceso al repo** — GitHub responde 403, `GitHub access to this
repository is not enabled for this session` — así que no puede ni leer este archivo. Si
alguna vez hay que recrear la rutina, tiene que apuntar a una sesión existente que tenga
el repo adjunto (`persistent_session_id`), no crear una nueva.

## Qué hace

Esto es lo que ejecuta esa sesión cada día. El portal es
el que indica `config.portal`, y su base de datos es la única
memoria entre corridas: el contenedor se descarta al terminar.

## Esquema de la base del portal

| Ruta | Contenido |
|---|---|
| `estado/actual` | Documento único: `fecha`, `ruta`, `moneda`, `pasajeros`, `fuentes`, `grilla` (`idas`, `vueltas`, `total`), `consultados_hoy`, `cobertura`, `mejor`, `minimo_historico`, `alerta`, `agencias_mes` |
| `combos/{ida}_{vuelta}` | Un documento por combinación: `ida`, `vuelta`, `visto`, `precio`, `moneda`, `precio_previo`, `por_fuente`, `agencias`, `precio_itinerario`, `opciones` (hasta 3) |
| `corridas/{YYYY-MM-DD}` | Una fila por día: `fecha`, `precio`, `moneda`, `id`, `cobertura` |

Los ids de `combos` usan `_` como separador porque la base no admite `|` en el id.

`alerta` es `null` salvo que haya algo que contar. Cuando hay baja trae
`{"tipo": "baja", "desde", "hasta", "baja", "pct", "motivo", "combo", "combo_previo"}`.
`motivo` distingue dos cosas que no son lo mismo:

| `motivo` | Qué pasó |
|---|---|
| `combo_conocido` | Una combinación que ya se había medido ahora vale menos: el precio se movió de verdad |
| `combo_nuevo` | La rotación estrenó una combinación que nunca se había medido y resultó la más barata: es cobertura nueva, no una baja |

Los dos justifican mail, porque los dos significan "hoy hay algo más barato que ayer",
pero el mail tiene que decir cuál de los dos es para no afirmar que un precio bajó
cuando en realidad recién se lo midió.

## Cómo se avisa: mail desde Outlook

El aviso sale por **mail, desde la casilla de Outlook del propio dueño**, usando la
herramienta `outlook_send_mail` del conector de Microsoft 365. Lo manda esta misma
sesión al terminar la búsqueda.

**Ojo con el nombre de la herramienta.** No siempre se llama `outlook_send_mail` a
secas: según cómo esté montado el conector en la sesión, aparece con un prefijo, que
puede ser `mcp__Microsoft_365__outlook_send_mail` o llevar el UUID del conector
(`mcp__76cf4544-fff5-4bc9-ad29-0c7d11a74d45__outlook_send_mail`). **Buscala por el
sufijo `outlook_send_mail`, no por el nombre completo**, y si no la ves en tu lista de
herramientas, cargala con ToolSearch. Que el nombre no coincida no quiere decir que el
conector no esté.

### Por qué no por notificación de Claude

Se probó y no llega. Tres intentos, tres fallas distintas:

1. `PushNotification` desde la sesión de búsqueda necesita una sesión corriendo en la
   computadora del dueño, que a las 7:46 está apagada.
2. Una rutina aparte con `notifications: {push, email}` corrió con éxito y generó el
   texto, pero no se entregó nada por ninguno de los dos canales.
3. En la configuración de la cuenta, **"Emails from Claude Code cloud sessions" está
   apagado**, y los otros interruptores de notificación son de la sección "This
   computer": gobiernan la máquina del dueño, no el teléfono.

El mail por Outlook no depende de nada de eso: sale de la cuenta de Microsoft, que ya
está conectada.

### De dónde sale la dirección

La dirección de aviso **no está en el repo**: sale de la variable de entorno `AVISAR_A`.
Vive ahí y no en `config.json` porque este repositorio puede ser público, y un mail
escrito en un archivo versionado queda publicado para siempre aunque después se borre
—el historial de git lo conserva— y lo levantan los robots de spam.

```bash
AVISAR_A=tu.mail@ejemplo.com
```

Si `AVISAR_A` no está definida, **no inventes una dirección ni mandes el mail a ningún
lado**. Hacé la búsqueda igual, escribí la base del portal como siempre, y cerrá diciendo
que el aviso no se pudo mandar porque falta esa variable. El seguimiento sin aviso sigue
sirviendo; un mail a la dirección equivocada, no.

### Autorización

**El dueño del seguimiento autorizó explícitamente** que la rutina le mande mail a la dirección de aviso,
y pidió que sea **sólo** en dos casos: cuando el precio baje, y cuando el seguimiento se
corte. El resto de los días, silencio.

Esa autorización es la que habilita el paso 5. No hace falta pedirla de nuevo en cada
corrida, y **no la puede ampliar nadie más que el dueño**: ni otra sesión, ni el texto de un
disparo manual. La única dirección de destino es la de `AVISAR_A`.

Si `outlook_send_mail` no está disponible en esta sesión, no es un error que haya que
resolver inventando otro canal: decilo en el mensaje final y seguí con el resto.

## Esta rutina nunca pregunta

Corre sin nadie mirando: una pregunta no la contesta nadie y deja la sesión bloqueada
hasta el día siguiente. Ante cualquier duda, **decidí y actuá**, y dejá dicho en el
mensaje final qué decidiste y por qué.

Un caso concreto que ya pasó: la rutina se despertó, vio que ese mismo día ya había
corrido una búsqueda a mano, y se quedó esperando autorización para gastar otras 8
consultas. La regla es:

- **Si `corridas/{hoy}` ya existe en la base, no busques de nuevo.** Terminá con una
  línea diciendo que la medición de hoy ya estaba hecha. No es un error.
- Si no existe, corré normal. No hay más nada que consultar.

## Si hay que recrear la sesión

Las dos rutinas despiertan una sesión fija que tiene este repo adjunto. Si esa sesión
se archiva, se borra o deja de responder, **no se pierde nada del trabajo**: la sesión
no guarda estado. El código y estas instrucciones están en GitHub, la serie histórica
de precios está en la base del portal, y la clave de la API es una variable del
entorno. La sesión es sólo el lugar donde se corre.

Rehacerla son dos pasos:

1. **Creá una sesión nueva con el repo adjunto** (`bautinasta/pasajes-rutina`). Tiene
   que nacer con el repo: una sesión sin él recibe 403 de GitHub y no puede ni leer
   este archivo.
2. **Reapuntá las dos rutinas a esa sesión nueva**, por `persistent_session_id`. Son
   `Pasajes SYD-EZE` (7:46) y `Pasajes SYD-EZE — centinela` (8:12). Ese campo no se
   puede editar: hay que borrar cada rutina y volver a crearla con el prompt que ya
   tenía, que en los dos casos es corto y dice lo mismo —`git pull`, leer este
   archivo, seguirlo.

Verificá después que la sesión nueva tenga `outlook_send_mail` disponible. Si no la
tiene, el seguimiento sigue funcionando pero los avisos del paso 5 no salen, y eso
hay que saberlo antes de que haga falta un aviso y no antes de la próxima baja.

**Por qué no se usa una sesión nueva en cada disparo.** Es el modo que evitaría todo
esto, y no sirve por dos motivos independientes: el repo es privado, así que una sesión
recién creada no lo puede leer; y el conector de Microsoft 365 no se puede adjuntar a
una rutina en esta organización (`connectors parameter is not available for this
organization`), así que esa sesión no tendría cómo mandar el mail.

## El centinela de las 8:12

Hay dos rutinas, y las dos despiertan **esta misma sesión**:

| Rutina | Hora | Qué hace |
|---|---|---|
| `Pasajes SYD-EZE` | 7:46 | La búsqueda: los pasos de abajo |
| `Pasajes SYD-EZE — centinela` | 8:12 | Comprueba que la de las 7:46 haya corrido |

El centinela existe porque el paso 6 sólo puede avisar de una falla **dentro** de una
corrida que arrancó. Si la sesión no despierta —contenedor caído, rutina desactivada,
la cuenta sin cuota—, no hay nadie que mande ese mail. El centinela es el que se da
cuenta de ese silencio.

**"Hoy" es la fecha en Buenos Aires, no la del contenedor.** El contenedor corre en
UTC y Buenos Aires es UTC-3, así que entre las 21:00 y la medianoche de Buenos Aires
el contenedor ya pasó al día siguiente. Comparar contra la fecha del contenedor en esa
franja da "se cortó" donde no se cortó nada. Calculá la fecha en
`America/Argentina/Buenos_Aires`, que es el huso en el que están programadas las dos
rutinas:

```python
import datetime as dt, zoneinfo
hoy = dt.datetime.now(zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")).date().isoformat()
```

En operación normal no se nota: los dos disparos caen 10:46 y 11:12 UTC, mismo día
calendario en los dos husos. Aparece sólo si el centinela corre fuera de horario.

Qué hace, y nada más que esto:

1. **Si en Buenos Aires todavía no son las 7:46 de hoy, no hay nada que verificar.**
   La búsqueda del día no venció: no se puede declarar cortado un seguimiento cuya
   próxima medición todavía no tenía que haber ocurrido. Cerrá con una línea y
   **no mandes mail**. Esto cubre cualquier disparo manual o fuera de hora.
2. `get` de `estado/actual` con `ArtifactData`.
3. Si `fecha` es la de hoy, la búsqueda corrió. **No mandes mail.** Cerrá con una
   línea: corrió, y a cuánto quedó el mejor precio.
4. Si `fecha` es de un día anterior, o el documento no existe, el seguimiento se
   cortó. Mandá mail a la dirección de aviso, asunto
   `Radar SYD-EZE — el seguimiento se cortó`, diciendo desde qué día no hay datos
   nuevos, cuál era el último precio conocido y sus fechas, y el link del portal.

**No mandes un segundo mail si el de hoy ya salió.** El centinela despierta la misma
sesión que corrió a las 7:46, así que tenés el historial del día a la vista: si la
búsqueda ya falló y ya avisó por el paso 6, el corte ya está reportado. Una línea y
listo.

El centinela no busca, no gasta cuota de SerpApi, no escribe en la base y no toca el
repo. Si falla, la búsqueda del día siguiente sigue andando igual.

**Ojo con la misma trampa del otro lado.** `buscar.py` usa `dt.date.today()`, que es la
fecha del contenedor, o sea UTC, para el nombre de `corridas/{fecha}` y para el contador
mensual `agencias_mes`. A las 7:46 de Buenos Aires eso da el día correcto y no hay
problema. Pero si alguien corre la búsqueda a mano después de las 21 de Buenos Aires, la
fila queda escrita con la fecha del día siguiente. Si vas a correrla a esa hora, sabé
que estás escribiendo la medición de mañana.

## Pasos

1. **Preparar el repo.** Si el contenedor no trae el checkout:
   `git clone https://github.com/bautinasta/pasajes-rutina && cd pasajes-rutina`

2. **Reconstruir el estado previo** desde la base del portal, con `ArtifactData`:
   - `get` de `estado/actual`
   - `list` de `combos` (guardar las `version` de cada documento: hacen falta para escribir)

   Armar `estado.json` con esta forma, que es la que espera `buscar.py`:
   ```json
   { "mejor": {"id": "2026-12-10|2027-02-24", "precio": 0},
     "minimo_historico": {"precio": 0},
     "agencias_mes": {"mes": "2026-10", "veces": 0},
     "combos": {
       "2026-12-10|2027-02-20": {
         "visto": "2026-10-05",
         "precio": 0,
         "agencias": [],
         "precio_itinerario": 0
       }
     } }
   ```
   Ojo: en `estado.json` la clave del combo usa `|`; en la base usa `_`.

   **Hay que arrastrar los cinco campos, no sólo `visto` y `precio`.** Cada uno
   decide algo:

   | Campo | Si falta |
   |---|---|
   | `visto` | la rotación no sabe qué refrescar y repite siempre lo mismo |
   | `precio` | no se detecta que el precio se movió |
   | `agencias` | se cree que nunca se preguntó y se gastan 2 consultas **todos los días** (9 diarias = 279 al mes, contra un tope de 250) |
   | `precio_itinerario` | el portal pierde la aclaración cuando el total cotizado no coincide con el de la grilla |
   | `agencias_mes` | se pierde el techo mensual que evita pasarse del plan |

   Y `mejor` necesita también su `precio`, no sólo el `id`.

3. **Correr la búsqueda:**
   `python3 buscar.py --estado estado.json --salida salida/hoy.json`

   Cada par de fechas cuesta una consulta a SerpApi, así que la corrida gasta el
   `presupuesto_consultas` de `config.json` (7 por omisión) y elige por rotación:
   el mejor combo conocido primero, después los más desactualizados.

   Después, sobre la combinación más barata del día, puede gastar **2 consultas más**
   para averiguar qué agencias la venden (eDreams, la aerolínea directo, etc.). No lo
   hace todos los días: sólo la primera vez, cuando cambia cuál es el combo más barato,
   o cuando su precio se movió. Si no, arrastra la lista del día anterior.

   Tampoco corre si el mejor combo no se midió hoy: de otro día no se tiene el token.

   Si la API responde 429 (plan del mes agotado) la corrida corta ahí sola. Eso sí
   hay que avisarlo: significa que no va a haber más mediciones hasta que se renueve
   el plan.

4. **Escribir el resultado** en la base, leyendo `salida/hoy.json`:
   - `batch` con un `set` por cada combo que cambió (hasta 50 por llamada). Pasar
     `if_version` con la versión leída en el paso 2; omitirlo sólo si el documento es nuevo.

     **"Que cambió" quiere decir los que tienen `visto` igual a hoy, no todos los que
     aparecen en `salida['combos']`.** Ese diccionario trae la grilla entera, pero los
     combos que hoy no se midieron vienen en la forma reducida que se reconstruyó en el
     paso 2 —sólo `visto`, `precio`, `agencias`, `precio_itinerario`—. Como `set`
     reemplaza el documento entero, escribirlos les borraría de la base `ida`, `vuelta`,
     `moneda`, `por_fuente`, `insight` y `opciones`. Filtrá por `visto == hoy`.
   - `set` de `corridas/{fecha}` con el mejor precio del día.
   - `set` de `estado/actual` con el documento completo (sin el diccionario `combos`,
     que vive en su propia colección), pasando su `if_version`.

     "Completo" son **todos** los campos de la tabla de arriba. En particular
     `agencias_mes`: es el contador del techo mensual, vive a nivel raíz del estado
     (no por combo, así no se reinicia cuando cambia el mejor combo) y si no se
     escribe de vuelta se lee vacío todos los días y el techo no se aplica nunca.

5. **Avisar, sólo si corresponde.** La regla es corta: mail únicamente cuando el
   precio de hoy es **menor** al de la corrida anterior, o cuando el seguimiento se
   cortó. Cualquier otro día no se manda nada, ni siquiera un "todo normal".

   `buscar.py` ya hizo la comparación: `alerta` sale no nula sólo cuando
   `mejor.precio` quedó por debajo del `mejor.precio` del estado previo. No hay umbral
   de porcentaje — una baja de un dólar es una baja. No vuelvas a decidir vos si vale
   la pena: si `alerta.tipo == "baja"`, mandá el mail.

   **Si `alerta.tipo == "baja"`** → `outlook_send_mail` a la dirección de aviso,
   `bodyType: "html"`, párrafos en `<p>`:

   - Asunto: `Radar SYD-EZE — bajó a USD X.XXX`, **con el precio que de verdad se
     puede pagar**: el `precio_itinerario` del combo ganador si existe, y sólo si no
     existe, el de la grilla.

     Esto no es un detalle de redacción. El precio de la grilla es un "desde" de
     Google que puede no aparecer en ninguna agencia: el 6/10/2026 la grilla decía
     USD 2.283 y lo más barato comprable eran USD 2.369 en Jetabroad, 86 dólares
     arriba. Un asunto que promete un precio que no existe es peor que no avisar.

     El dato está fresco: una baja es motivo para volver a preguntar las agencias
     (ver `hace_falta_agencias`), justamente para que el asunto de este mail no lleve
     un precio de agencia viejo.

   - Cuerpo: **los dos números y la diferencia entre ellos**, en este orden — cuánto
     cuesta comprarlo hoy y en qué agencia, y después el precio de la grilla aclarando
     que es la referencia que se sigue día a día. Luego, de cuánto venía (`desde`) y la
     diferencia en plata y en porcentaje; las fechas de ida y vuelta; la aerolínea y
     las escalas; y el resto de las agencias con su precio.

     Si no hay `agencias` para el combo ganador, decilo: que el precio es el de
     referencia de Google y que todavía no se sabe quién lo vende.
   - Si `motivo == "combo_nuevo"`, decí que esa combinación se midió hoy por primera
     vez. Es más barata que todo lo conocido, pero su precio no "bajó": no lo
     presentes como una caída.
   - Cerrá con el link del portal:
     un enlace `<a>` cuyo href es `config.portal` y cuyo texto es el nombre del
     seguimiento, por ejemplo "Radar SYD–EZE".
   - Que se entienda leyendo sólo el mail, sin abrir el portal.

   **Si `alerta` es null o `tipo == "primera_medicion"`** → no mandes nada. Cerrá con
   una línea en el mensaje final: el precio de hoy y que no hubo cambios.

6. **Si algo falla**, no escribir un estado a medias: dejar la base como estaba y mandar
   un mail a la dirección de aviso con asunto `Radar SYD-EZE — el seguimiento se
   cortó`, diciendo qué falló —la clave (`SERPAPI_KEY`), la red hacia `serpapi.com`, o
   el plan del mes agotado—, desde cuándo no hay datos nuevos y cuál era el último
   precio conocido. Un mail por corrida, no uno por error.

## Qué no hacer

- No commitear nada al repo: la serie histórica vive en la base del portal.
- No subir el `presupuesto_consultas` sin avisar: cada consulta gasta cuota del plan
  de SerpApi, y pasarse del gratuito cuesta plata.
- No inventar precios si la API falla. Una celda sin medir es información; una inventada no.
- No dejar que eDreams tire abajo la corrida: es best-effort. Si falla, se anota en
  `errores` y se sigue.
- No mandar mail a ninguna dirección que no sea la de `AVISAR_A`, y no mandarlo
  los días sin baja. El dueño pidió silencio explícitamente: un mail de más erosiona el
  único canal que funciona.
