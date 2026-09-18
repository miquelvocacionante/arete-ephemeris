"""
Integridad del motor de efemérides (Fase 0).

Módulo puro: no importa swisseph, de modo que puede probarse sin los ficheros
de efemérides ni la librería instalada.

Responde a una pregunta que antes no podíamos responder: ¿qué motor produjo
realmente cada posición? Pedir FLG_SWIEPH no garantiza que Swiss lo use; si
faltan los ficheros, Swiss Ephemeris cae a Moshier y lo indica en los retflags
devueltos por calc_ut, no con una excepción.
"""

# Bits oficiales de Swiss Ephemeris (coinciden con swe.FLG_*)
FLG_JPLEPH = 1
FLG_SWIEPH = 2
FLG_MOSEPH = 4
FLG_SPEED = 256

# Convenciones oficiales de Areté, versionadas como política de producto.
ARETE_ASTRO_POLICY_VERSION = "v1"
ARETE_ASTRO_POLICY = {
    "version": ARETE_ASTRO_POLICY_VERSION,
    "zodiac": "tropical",
    "frame": "geocentric",
    "positions": "apparent, true equinox of date",
    "house_system": "placidus",
    "house_system_code": "P",
    "node": "true_node",
    "south_node": "north_node + 180",
    "ephemeris": "swiss",
    "required_flags": FLG_SWIEPH | FLG_SPEED,
}

# Cuerpos sin los cuales una carta natal no es válida.
REQUIRED_BODIES = (
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
    "north_node",
    "chiron",
)

# Política de Areté, no una constante astronómica. Placidus degenera al
# acercarse a las regiones polares y Swiss Ephemeris sustituye el sistema
# (habitualmente por Porphyry) sin informarlo a través de swe.houses(). Como no
# podemos leer el sistema efectivo, bloqueamos preventivamente a partir de este
# límite propio, algo antes del círculo polar, en vez de arriesgarnos a un
# fallback silencioso. El umbral exacto es una decisión nuestra y revisable.
ARETE_SAFE_PLACIDUS_LATITUDE = 66.0


class EphemerisEngineError(RuntimeError):
    """El motor efectivo no es el solicitado (por ejemplo, Moshier en vez de Swiss)."""


class BodyCalculationError(RuntimeError):
    """Un cuerpo obligatorio no se ha podido calcular."""


class TimezoneResolutionError(ValueError):
    """La zona horaria no se ha podido resolver; nunca se asume UTC."""


class HouseSystemUnavailableError(RuntimeError):
    """Latitud fuera de la política de Areté para Placidus; no entregamos casas mal etiquetadas."""


class HouseCalculationError(RuntimeError):
    """swe.houses() ha fallado: un producto de pago no degrada las casas a "sin datos"."""


class HousePlacementError(RuntimeError):
    """Una longitud no cae en ninguna de las 12 casas: datos inconsistentes, no Casa 1."""


def resolve_effective_engine(retflags):
    """Traduce los retflags devueltos por calc_ut al motor realmente usado."""
    if retflags is None:
        return "unknown"
    try:
        flags = int(retflags)
    except (TypeError, ValueError):
        return "unknown"
    if flags < 0:
        return "error"
    if flags & FLG_MOSEPH:
        return "moshier"
    if flags & FLG_JPLEPH:
        return "jpl"
    if flags & FLG_SWIEPH:
        return "swiss"
    return "unknown"


def validate_engine(body_key, requested_flags, retflags):
    """
    Comprueba que el motor efectivo coincide con el solicitado.

    Devuelve un diccionario de trazabilidad (flags pedidos, retflags reales y
    motor efectivo) o lanza EphemerisEngineError.
    """
    effective = resolve_effective_engine(retflags)
    expected = "swiss" if requested_flags & FLG_SWIEPH else effective

    if effective != expected:
        raise EphemerisEngineError(
            f"{body_key}: se solicitó el motor '{expected}' pero Swiss Ephemeris ha usado "
            f"'{effective}' (retflags={retflags}). Faltan ficheros de efemérides o la "
            f"ruta EPHE_PATH es incorrecta."
        )

    return {
        "body": body_key,
        "requested_flags": int(requested_flags),
        "retflags": int(retflags),
        "engine": effective,
    }


def is_required_body(body_key):
    return body_key in REQUIRED_BODIES


def assert_required_bodies(calculated_keys):
    """Lanza BodyCalculationError si falta algún cuerpo obligatorio."""
    missing = [k for k in REQUIRED_BODIES if k not in calculated_keys]
    if missing:
        raise BodyCalculationError(
            "Cuerpos obligatorios no calculados: " + ", ".join(missing)
        )
    return True


def placidus_status(latitude):
    """
    Estado del sistema de casas para una latitud dada.

    No modificamos la llamada a swe.houses(): declaramos de forma explícita
    cuándo su resultado deja de ser Placidus real.
    """
    try:
        lat = abs(float(latitude))
    except (TypeError, ValueError):
        return {
            "requested": "placidus",
            "reliable": False,
            "warning": "Latitud no válida: no se puede garantizar el sistema de casas.",
        }

    if lat >= ARETE_SAFE_PLACIDUS_LATITUDE:
        return {
            "requested": "placidus",
            "reliable": False,
            "warning": (
                f"Latitud {lat}° fuera del límite de seguridad de Areté para Placidus "
                f"({ARETE_SAFE_PLACIDUS_LATITUDE}°). Cerca de las regiones polares Swiss "
                f"Ephemeris puede sustituir Placidus por otro sistema sin indicarlo, así "
                f"que bloqueamos el cálculo en lugar de etiquetarlo mal."
            ),
        }

    return {"requested": "placidus", "reliable": True, "warning": None}


def assert_house_system(latitude):
    """
    Política explícita de casas (Fase 0).

    Swiss Ephemeris no expone qué sistema ha usado realmente swe.houses(). No
    intentamos adivinarlo: aplicamos un límite de seguridad propio y, por encima
    de él, bloqueamos el cálculo en vez de entregar una carta que dice "Placidus"
    sin poder garantizarlo.
    """
    status = placidus_status(latitude)
    if not status["reliable"]:
        raise HouseSystemUnavailableError(status["warning"])
    return status


def assert_house_placement(house_number, longitude):
    """
    Una longitud siempre cae en alguna de las 12 casas de un juego válido de
    cúspides. Si no cae, los datos son inconsistentes: antes se devolvía Casa 1
    por defecto y esa casa inventada llegaba al informe.
    """
    if house_number is None:
        raise HousePlacementError(
            f"La longitud {longitude}° no cae en ninguna de las 12 casas calculadas: "
            "las cúspides son inconsistentes."
        )
    return house_number