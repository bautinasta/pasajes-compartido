# Instalación

Este archivo es para **Claude Code**: son los pasos para dejar el seguimiento andando
en la cuenta de quien lo esté instalando. Si sos una persona leyendo esto, lo único que
tenés que hacer es pegarle a Claude Code un mensaje como éste:

> Cloná este repositorio y seguí `INSTALAR.md`. Quiero seguir el precio de
> **Buenos Aires → Madrid**, ida entre el **1 y el 10 de julio de 2027**, vuelta entre
> el **20 y el 30 de agosto**, **2 adultos**, clase económica.

Cambiá la ruta, las fechas y los pasajeros por los tuyos. Claude hace el resto y te va a
pedir sólo lo que no puede conseguir por su cuenta.

---

## Qué es esto

Una rutina que corre todos los días **en la nube** —no en tu computadora, que puede
estar apagada—, consulta el precio de un pasaje de ida y vuelta, lo guarda en un portal
que se actualiza solo, y te manda un mail **únicamente** cuando el precio baja o cuando
el seguimiento se corta.

Leé `README.md` para entender el diseño y `RUTINA.md` para saber qué ejecuta cada día.

## Antes de empezar: lo que tiene que conseguir la persona

Claude no puede hacer estos tres pasos por nadie. Pedíselos al principio, juntos, y
esperá a tenerlos antes de seguir.

1. **Una cuenta en [serpapi.com](https://serpapi.com) y su API key.** El plan gratuito
   da 250 búsquedas por mes y alcanza. **No le pidas que te pegue la clave en el chat:**
   tiene que cargarla como variable de entorno del entorno de ejecución, con el nombre
   `SERPAPI_KEY`.
2. **La variable `AVISAR_A`** con la dirección de mail donde quiere recibir los avisos.
   Va en el mismo lugar que la anterior.
3. **Habilitar `serpapi.com`** en la política de red del entorno. Sin eso, todas las
   consultas fallan sin un error claro.

Después de cargar las variables hay que **arrancar una sesión nueva**: las que ya estaban
corriendo no las ven.

## Pasos

### 1. Configurar el viaje

Editá `config.json` con lo que pidió la persona:

| Campo | Qué es |
|---|---|
| `origen` / `destino` | Códigos IATA de aeropuerto, por ejemplo `EZE`, `MAD` |
| `fechas_ida` / `fechas_vuelta` | Rangos `desde` / `hasta` en formato `AAAA-MM-DD` |
| `adultos`, `clase` | Pasajeros y cabina (`ECONOMY`, `BUSINESS`, …) |
| `moneda`, `mercado`, `idioma` | En qué moneda y para qué mercado cotizar |
| `zona_horaria` | Zona IANA donde vive la persona, por ejemplo `Europe/Madrid` |
| `presupuesto_consultas` | Cuántas consultas gastar por día. Ver la cuenta de abajo |
| `portal` | Dejalo como está: se completa en el paso 3 |

**Calculá el presupuesto antes de seguir.** La grilla son (días de ida) × (días de
vuelta) combinaciones, y cada una cuesta una consulta. Con el plan gratuito de 250 al mes:

```
presupuesto_consultas × 31  +  agencias_max_mes × 2  ≤  250
```

Con 7 por día son 217 + 24 = 241, que entra con margen. Si la grilla de la persona es
mucho más chica, bajalo; no tiene sentido gastar consultas de más.

Verificá sin gastar nada:

```bash
python3 buscar.py --plan
```

### 2. Probar que la clave anda

Una sola consulta real, para confirmar que `SERPAPI_KEY` está bien cargada:

```bash
python3 buscar.py --presupuesto 1 --salida /tmp/prueba.json
```

Si responde que falta la clave, la variable no está o la sesión es anterior a cargarla.
Si da 401, la clave está mal. No sigas hasta que esto funcione.

Corré también los tests, que no usan red ni gastan cuota:

```bash
python3 test_parseo.py
```

### 3. Publicar el portal

Publicá `portal/index.html` como artifact **con base de datos habilitada** (capacidad
`db`). Esa base no es decorativa: es la única memoria entre corridas, porque el
contenedor donde corre la rutina se descarta cuando termina.

Guardá la URL que te devuelve en `config.json` → `portal`, commiteá y pusheá. Ofrecé
fijar el portal en la barra lateral.

### 4. Crear la sesión de trabajo

La rutina necesita una sesión **con este repositorio adjunto**, que va a despertar todos
los días.

Creala con el repo como `source_url` y **con la rama fijada** (`source_revision: "main"`).
Si no fijás la rama, la sesión no se agrupa bajo el repositorio en la barra lateral.

> **No uses una rutina que cree una sesión nueva en cada disparo.** Una sesión recién
> creada nace sin acceso al repositorio: GitHub le responde 403 y no puede ni leer
> `RUTINA.md`. Esto está probado, no es precaución teórica.

### 5. Crear las dos rutinas

Las dos apuntan a la sesión del paso 4 (`persistent_session_id`) y llevan la zona horaria
en el cron, para que el horario de verano se resuelva solo:

| Rutina | Cron | Prompt |
|---|---|---|
| Búsqueda | `CRON_TZ=<zona> 46 7 * * *` | `git pull`, leer `RUTINA.md`, seguirlo |
| Centinela | `CRON_TZ=<zona> 12 8 * * *` | `git pull`, seguir la sección "El centinela" |

**Usá minutos desplazados, no la hora en punto.** Casi todo el mundo programa a las 8:00
y esos minutos están congestionados; 7:46 arranca puntual.

El prompt de la rutina tiene que ser corto a propósito: todo lo que hace vive en
`RUTINA.md`. Así, cambiar el comportamiento es un commit y no editar una tarea a mano.

### 6. Verificar antes de confiar

Sin gastar cuota, confirmá que la sesión del paso 4:

- tiene el repositorio y puede leer `RUTINA.md`
- corre los tests en verde
- **puede leer la base del portal** con `ArtifactData`, las tres colecciones
- tiene disponible la herramienta de mail

Sobre lo último: **buscala por el sufijo `outlook_send_mail`, no por el nombre completo.**
Según cómo esté montado el conector aparece con prefijos distintos, incluido el UUID del
conector. Que el nombre no coincida no significa que el conector no esté.

Si la persona usa otro proveedor de correo, adaptá el paso 5 de `RUTINA.md` a la
herramienta que tenga. El resto del diseño no cambia.

### 7. Contarle cómo quedó

Decile en qué horario corre, que no depende de su computadora, que sólo va a recibir mail
cuando el precio baje o cuando el seguimiento se corte, y pasale el link del portal.

Avisale también que la grilla tarda unos días en llenarse: durante ese tiempo el "mejor
precio" puede bajar porque se estrena una combinación que nunca se había medido, que no
es lo mismo que una baja real. El mail distingue los dos casos.

## Si algo falla

| Síntoma | Causa casi segura |
|---|---|
| `Falta SERPAPI_KEY en el entorno` | La variable no está, o la sesión es anterior a cargarla |
| 401 de SerpApi | La clave está mal copiada |
| 429 de SerpApi | Se acabó el plan del mes. La corrida corta sola y conserva lo medido |
| La consulta muere sin error claro | `serpapi.com` no está habilitado en la política de red |
| GitHub responde 403 | La sesión no tiene el repositorio adjunto |
| El aviso no sale pero la búsqueda anduvo | El nombre de la herramienta de mail lleva prefijo |
