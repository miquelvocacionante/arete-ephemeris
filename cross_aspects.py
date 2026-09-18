"""
Aspectos entre dos cartas (Fase 2).

Módulo puro: sin swisseph, sin Flask. Calcula geometría real sobre longitudes
absolutas 0-360, que es exactamente lo que faltaba cuando un informe afirmó una
"conjunción" entre Luna progresada en Virgo 1°34' y Quirón natal en Cáncer
1°22'. Esas dos posiciones están separadas 60°12': es un sextil, no una
conjunción. Restar grados dentro del signo no es geometría.

Las políticas de orbes viven aquí, versionadas, y nunca en los prompts.
"""

ORB_POLICY_VERSION = "v1"

ASPECT_DEFS = (
    {"key": "conjunction", "angle": 0, "name": "Conjunción"},
    {"key": "opposition", "angle": 180, "name": "Oposición"},
    {"key": "trine", "angle": 120, "name": "Trígono"},
    {"key": "square", "angle": 90, "name": "Cuadratura"},
    {"key": "sextile", "angle": 60, "name": "Sextil"},
)

ASPECT_ANGLES = {d["key"]: d["angle"] for d in ASPECT_DEFS}
ASPECT_NAMES = {d["key"]: d["name"] for d in ASPECT_DEFS}

# Orbes de tránsito -> natal (más cerrados que los natales).
TRANSIT_ORBS = {
    'sun':       {'conjunction': 1, 'opposition': 1, 'trine': 1, 'square': 1, 'sextile': 1},
    'moon':      {'conjunction': 1, 'opposition': 1, 'trine': 1, 'square': 1, 'sextile': 1},
    'mercury':   {'conjunction': 2, 'opposition': 2, 'trine': 2, 'square': 2, 'sextile': 1},
    'venus':     {'conjunction': 2, 'opposition': 2, 'trine': 2, 'square': 2, 'sextile': 1},
    'mars':      {'conjunction': 2, 'opposition': 2, 'trine': 2, 'square': 2, 'sextile': 1},
    'jupiter':   {'conjunction': 4, 'opposition': 4, 'trine': 4, 'square': 4, 'sextile': 2},
    'saturn':    {'conjunction': 4, 'opposition': 4, 'trine': 4, 'square': 4, 'sextile': 2},
    'uranus':    {'conjunction': 4, 'opposition': 4, 'trine': 4, 'square': 4, 'sextile': 2},
    'neptune':   {'conjunction': 4, 'opposition': 4, 'trine': 4, 'square': 4, 'sextile': 2},
    'pluto':     {'conjunction': 4, 'opposition': 4, 'trine': 4, 'square': 4, 'sextile': 2},
    'north_node': {'conjunction': 2, 'opposition': 2, 'trine': 2, 'square': 2, 'sextile': 1},
    'south_node': {'conjunction': 2, 'opposition': 2, 'trine': 2, 'square': 2, 'sextile': 1},
    'chiron':    {'conjunction': 3, 'opposition': 3, 'trine': 3, 'square': 3, 'sextile': 2},
}

DEFAULT_TRANSIT_ORBS = {'conjunction': 2, 'opposition': 2, 'trine': 2, 'square': 2, 'sextile': 1}

# Progresiones secundarias -> natal: política v1, 1° para todos los aspectos.
PROGRESSION_ORB = 1.0
PROGRESSION_ORBS = {key: PROGRESSION_ORB for key in ASPECT_ANGLES}

# Revolución solar -> natal: reutiliza la política de tránsitos ya en uso.
SOLAR_RETURN_ORBS = TRANSIT_ORBS
DEFAULT_SOLAR_RETURN_ORBS = DEFAULT_TRANSIT_ORBS

ORB_POLICY = {
    "version": ORB_POLICY_VERSION,
    "natal": {"conjunction": 8, "opposition": 8, "trine": 8, "square": 8, "sextile": 6},
    "transit_to_natal": "per-body (TRANSIT_ORBS)",
    "progression_to_natal": PROGRESSION_ORBS,
    "solar_return_to_natal": "per-body (reutiliza TRANSIT_ORBS)",
}


def normalize_longitude(longitude):
    """Longitud absoluta en el rango [0, 360)."""
    return float(longitude) % 360.0


def angular_separation(lon1, lon2):
    """Separación angular real entre dos longitudes: 0-180, cruzando 359°/0°."""
    diff = abs(normalize_longitude(lon1) - normalize_longitude(lon2)) % 360.0
    return 360.0 - diff if diff > 180.0 else diff


def orbs_for_body(body_key, orb_table, default_orbs):
    if isinstance(orb_table, dict) and body_key in orb_table:
        return orb_table[body_key]
    if isinstance(orb_table, dict) and all(k in ASPECT_ANGLES for k in orb_table):
        # Tabla plana: mismos orbes para todos los cuerpos (progresiones).
        return orb_table
    return default_orbs


def classify_aspect(lon1, lon2, orbs):
    """
    Devuelve el aspecto más ceñido entre dos longitudes, o None.

    Es la única definición de "hay aspecto" del sistema: separación angular real
    comparada con el ángulo exacto, nunca diferencia de grados dentro del signo.

    Precisión: `orbExact` y `separationExact` conservan el valor completo; `orb`
    y `separation` son la versión redondeada para presentación. La comparación
    con el orbe permitido y la elección del aspecto más ceñido usan siempre el
    valor exacto.

    No se marca aplicativo ni separativo: eso exige velocidades relativas
    fiables de ambos puntos y aquí solo hay longitudes. Antes que una etiqueta
    dudosa, ninguna.
    """
    separation = angular_separation(lon1, lon2)
    best = None
    for definition in ASPECT_DEFS:
        allowed = orbs.get(definition["key"])
        if allowed is None:
            continue
        orb = abs(separation - definition["angle"])
        if orb <= allowed and (best is None or orb < best["orbExact"]):
            best = {
                "aspectKey": definition["key"],
                "aspect": definition["name"],
                "angle": definition["angle"],
                "orbExact": orb,
                "separationExact": separation,
                "orb": round(orb, 2),
                "separation": round(separation, 4),
                "maxOrb": allowed,
                "motion": "unknown",
            }
    return best


def calculate_cross_aspects(
    source_points,
    target_points,
    orb_table,
    default_orbs=DEFAULT_TRANSIT_ORBS,
    source_suffix="",
    target_suffix="natal",
):
    """
    Aspectos entre dos conjuntos de puntos (progresiones->natal, RS->natal).

    source_points / target_points: dict clave -> {'name', 'longitude'}.
    Devuelve una lista ordenada por orbe ascendente.
    """
    results = []
    for source_key, source in (source_points or {}).items():
        source_lon = _longitude_of(source)
        if source_lon is None:
            continue
        orbs = orbs_for_body(source_key, orb_table, default_orbs)

        for target_key, target in (target_points or {}).items():
            target_lon = _longitude_of(target)
            if target_lon is None:
                continue

            match = classify_aspect(source_lon, target_lon, orbs)
            if not match:
                continue

            results.append({
                "sourceKey": source_key,
                "sourcePoint": _label(source, source_key, source_suffix),
                "targetKey": target_key,
                "targetPoint": _label(target, target_key, target_suffix),
                "sourceLongitude": normalize_longitude(source_lon),
                "targetLongitude": normalize_longitude(target_lon),
                "orbPolicyVersion": ORB_POLICY_VERSION,
                **match,
            })

    results.sort(key=lambda a: a["orbExact"])
    return results


def _longitude_of(point):
    if point is None:
        return None
    if isinstance(point, dict):
        value = point.get("longitude")
    else:
        value = point
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _label(point, key, suffix):
    name = point.get("name") if isinstance(point, dict) else None
    base = name or key
    return f"{base} {suffix}".strip()