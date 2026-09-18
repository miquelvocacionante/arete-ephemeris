# Areté Ephemeris

Servicio astronómico de Areté basado en Swiss Ephemeris y desplegado en Railway.

## Garantías de producción

El servicio falla cerrado. No entrega una carta si:

- Swiss Ephemeris cae a Moshier;
- falta un cuerpo obligatorio como Quirón;
- la zona horaria no puede resolverse;
- Placidus no puede garantizarse según la política de Areté;
- las casas son inconsistentes.

El endpoint de readiness es:

```text
GET /health/engine
```

Devuelve HTTP 200 únicamente cuando el motor real está sano.

## Efemérides obligatorias

La imagen necesita estos tres ficheros en `ephe/`:

```text
sepl_18.se1
semo_18.se1
seas_18.se1
```

`verify_swiss_real.py` comprueba los tres y además valida que el motor efectivo sea Swiss.

**Importante:** este repositorio es público. No añadas nuevos ficheros de Swiss Ephemeris sin confirmar que la licencia de Areté permite esa forma de distribución. Si no deben vivir en GitHub, deben incorporarse al build desde una fuente privada/autorizada.

## Railway

Railway despliega este repositorio directamente.

Configuración recomendada:

- Builder: Dockerfile
- Start command: usar el `CMD` del Dockerfile
- Healthcheck path: `/health/engine`
- `EPHE_PATH=/app/ephe`
- No fijar `PORT`: Railway lo inyecta y Gunicorn escucha `${PORT:-8080}`

El Dockerfile ejecuta durante el build:

```bash
EPHE_PATH=/app/ephe python verify_swiss_real.py
```

Si la validación falla, la imagen no se construye.

## Endpoints

- `GET /health`
- `GET /health/engine`
- `GET /debug/ephe`
- `POST /calculate`
- `POST /transits`
- `GET|POST /current-positions`
- `POST /search-transit-aspect`
- `POST /yearly-transits`

## Verificación manual

En el mismo entorno que Railway:

```bash
EPHE_PATH=/app/ephe python verify_swiss_real.py
```

La ejecución válida termina con:

```text
VALIDACIÓN REAL SUPERADA: motor Swiss efectivo en todos los cálculos.
```

## Tests

Los módulos de precisión incluyen tests para:

- integridad del motor y retflags;
- geometría de aspectos cruzados;
- caso Marta Alí: sextil 0°12′, nunca conjunción;
- conjunciones atravesando el límite de signo;
- progresiones secundarias;
- retorno solar;
- búsqueda determinista de tránsitos.
