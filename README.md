# Areté Ephemeris

Servicio astronómico de Areté basado en Swiss Ephemeris y desplegado en Railway.

## Estado del motor

La rama de producción debe cumplir estas garantías:

- Swiss Ephemeris es el motor efectivo; un fallback a Moshier se rechaza.
- Quirón y el resto de cuerpos obligatorios deben estar disponibles.
- La zona horaria debe resolverse; nunca se interpreta silenciosamente la hora local como UTC.
- Placidus solo se entrega cuando Areté puede garantizar esa metodología.
- Las casas inconsistentes son error, nunca se convierten en Casa 1.
- Los aspectos cruzados se calculan con longitudes 0–360 y orbes versionados.
- Las progresiones secundarias incluyen Sol, Luna, Mercurio, Venus y Marte.
- El Ascendente progresado está explícitamente no soportado.
- La Revolución Solar se resuelve alrededor del cumpleaños del año pedido.

## Datos Swiss reproducibles

Los binarios `.se1` no se mantienen dentro de este repositorio de Areté.

`download_ephemeris.py` descarga exactamente:

- `sepl_18.se1`
- `semo_18.se1`
- `seas_18.se1`

desde el repositorio público oficial `aloistr/swisseph`, fijado al commit:

```text
9083a12d59e98034fb2337061481ac8800c16e64
```

Cada fichero se valida contra su Git blob SHA oficial antes de escribirse. Después,
`verify_swiss_real.py` comprueba que el motor efectivo sea realmente Swiss.

La fuente pública oficial de los ficheros está documentada por Swiss Ephemeris.
El uso comercial de Swiss Ephemeris debe estar cubierto por la licencia aplicable
de Areté; este repositorio no sustituye esa obligación.

## Railway

Este repositorio es el servicio independiente que Railway debe construir.

El `Dockerfile`:

1. instala las dependencias Python;
2. copia todos los módulos del motor;
3. descarga las efemérides fijadas;
4. ejecuta `verify_swiss_real.py`;
5. solo si todo pasa, crea la imagen que arranca Gunicorn.

Gunicorn escucha:

```text
0.0.0.0:${PORT:-8080}
```

Railway inyecta `PORT`, por lo que no debe fijarse un puerto distinto en el dashboard.

### Healthcheck

El healthcheck de Railway debe ser:

```text
/health/engine
```

No usar `/health` como readiness gate: `/health/engine` devuelve 503 cuando el
motor real está degradado y evita activar una release incorrecta.

## Endpoints

- `GET /health`
- `GET /health/engine`
- `GET /debug/ephe`
- `POST /calculate`
- `POST /transits`
- `GET|POST /current-positions`
- `POST /search-transit-aspect`
- `POST /yearly-transits`

## Tests

GitHub Actions ejecuta en cada PR y en cada push a `main`:

- compilación de todos los módulos;
- integridad del motor;
- geometría de aspectos cruzados;
- caso Marta Alí: sextil 0°12′, nunca conjunción;
- conjunciones atravesando límites de signo;
- progresiones secundarias;
- retorno solar;
- búsqueda determinista de aspectos;
- validación real con los tres ficheros Swiss;
- build completo de la imagen Docker.

Localmente:

```bash
pip install -r requirements.txt
python download_ephemeris.py
EPHE_PATH="$PWD/ephe" python verify_swiss_real.py
```

La última línea debe terminar con:

```text
VALIDACIÓN REAL SUPERADA: motor Swiss efectivo en todos los cálculos.
```

## Flujo de publicación

Railway puede seguir observando únicamente `main`.

1. Los cambios se preparan en una rama.
2. El PR ejecuta CI sin afectar producción.
3. Se revisa el diff y las comprobaciones.
4. Al hacer merge a `main`, Railway inicia el deployment automático.
5. Railway solo debe activar la nueva release cuando `/health/engine` responda 2xx.
