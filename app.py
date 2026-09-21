from flask import Flask, request, jsonify
from flask_cors import CORS
import swisseph as swe
from datetime import datetime
import os
import re
import pytz
from aspect_search import (
    ASPECT_NAMES_ES,
    find_aspect_passes,
    find_crossings,
    dedupe_passes,
    normalize_aspect,
    normalize_transit_planet,
    sample_dates,
    signed_offset,
    target_angles,
    validate_window,
)
from cross_aspects import (
    DEFAULT_TRANSIT_ORBS,
    ORB_POLICY,
    PROGRESSION_ORBS,
    SOLAR_RETURN_ORBS,
    TRANSIT_ORBS,
    calculate_cross_aspects,
)
from progressions import (
    PROGRESSED_ASCENDANT_SUPPORTED,
    years_to_sign_change,
)
from solar_return import (
    SolarReturnSearchError,
    approximate_return_jd,
    find_solar_return_jd,
)
from engine_integrity import (
    HouseCalculationError,
    HousePlacementError,
    assert_house_placement,
    ARETE_ASTRO_POLICY,
    BodyCalculationError,
    EphemerisEngineError,
    HouseSystemUnavailableError,
    REQUIRED_BODIES,
    TimezoneResolutionError,
    assert_house_system,
    assert_required_bodies,
    is_required_body,
    placidus_status,
    resolve_effective_engine,
    validate_engine,
)

app = Flask(__name__)
CORS(app)

def _resolve_ephe_path() -> str:
    """
    Resolve ephemeris path in order of priority:
    1. Environment variable EPHE_PATH
    2. Docker default /app/ephe
    3. Local ephe directory
    """
    env_path = os.environ.get("EPHE_PATH")
    if env_path:
        return env_path

    docker_default = "/app/ephe"
    if os.path.isdir(docker_default):
        return docker_default

    return os.path.join(os.path.dirname(__file__), "ephe")

EPHE_PATH = _resolve_ephe_path()
swe.set_ephe_path(EPHE_PATH)

def _log_ephe_status():
    """Log ephemeris path and file status on startup"""
    try:
        files = []
        if os.path.isdir(EPHE_PATH):
            files = sorted([f for f in os.listdir(EPHE_PATH) if not f.startswith(".")])
        print(f"[ephe] Using EPHE_PATH={EPHE_PATH} | files={len(files)}")
        if files:
            print(f"[ephe] Sample files: {files[:10]}")
        else:
            print("[ephe] WARNING: No ephemeris files found. Outer bodies may work, but Chiron can be missing.")
    except Exception as e:
        print(f"[ephe] ERROR reading EPHE_PATH={EPHE_PATH}: {e}")

_log_ephe_status()

PLANETS = {
    'sun': swe.SUN,
    'moon': swe.MOON,
    'mercury': swe.MERCURY,
    'venus': swe.VENUS,
    'mars': swe.MARS,
    'jupiter': swe.JUPITER,
    'saturn': swe.SATURN,
    'uranus': swe.URANUS,
    'neptune': swe.NEPTUNE,
    'pluto': swe.PLUTO,
    'north_node': swe.TRUE_NODE,
    'south_node': None,  # Calculated as opposite of North Node
    'chiron': swe.CHIRON,
}

PLANET_NAMES = {
    'sun': 'Sol',
    'moon': 'Luna',
    'mercury': 'Mercurio',
    'venus': 'Venus',
    'mars': 'Marte',
    'jupiter': 'Júpiter',
    'saturn': 'Saturno',
    'uranus': 'Urano',
    'neptune': 'Neptuno',
    'pluto': 'Plutón',
    'north_node': 'Nodo Norte',
    'south_node': 'Nodo Sur',
    'chiron': 'Quirón',
}

SIGNS = [
    'Aries', 'Tauro', 'Géminis', 'Cáncer', 'Leo', 'Virgo',
    'Libra', 'Escorpio', 'Sagitario', 'Capricornio', 'Acuario', 'Piscis'
]

def get_sign(longitude):
    """Get zodiac sign and degree from ecliptic longitude"""
    normalized_lon = longitude % 360
    if normalized_lon < 0:
        normalized_lon += 360
    
    sign_index = int(normalized_lon / 30)
    degree = normalized_lon % 30
    
    # 'degree' se mantiene a 2 decimales por compatibilidad con los consumidores
    # existentes; 'degree_exact' conserva la precisión real para DMS y geometría.
    return {
        'sign': SIGNS[sign_index],
        'degree': round(degree, 2),
        'degree_exact': round(degree, 6),
    }

def dms_of(sign_info):
    """DMS a partir del grado exacto: redondear antes perdía hasta 18 segundos."""
    return format_dms(sign_info.get('degree_exact', sign_info['degree']))


def format_dms(decimal_degrees):
    """
    Grados, minutos y segundos con redondeo correcto y acarreo.

    Truncar los segundos perdía hasta 1'' en cada posición: 10.008333° son
    10°00\'30" y salía 10°00\'29". El acarreo importa en los bordes: 59.6" pasa a
    00" y suma un minuto; 59\'59.6" suma un grado.
    """
    sign = -1 if decimal_degrees < 0 else 1
    value = abs(decimal_degrees)
    total_seconds = round(value * 3600)
    d, rest = divmod(total_seconds, 3600)
    m, sec = divmod(rest, 60)
    return f"{sign * d if d else 0}°{m:02d}'{sec:02d}\""

_BIRTH_TIME_RE = re.compile(
    r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2})(?:\.(?P<fraction>\d{1,6}))?)?$"
)


def parse_birth_time(value):
    """
    Parse the local birth time contract accepted by /calculate.

    PostgreSQL TIME values commonly arrive as HH:MM:SS, while older clients
    send HH:MM. Fractional seconds are also valid. The motor owns this temporal
    contract so every caller gets the same validation and precision.
    """
    if not isinstance(value, str):
        raise ValueError("birthTime debe ser una cadena HH:MM, HH:MM:SS o HH:MM:SS.ffffff.")

    match = _BIRTH_TIME_RE.fullmatch(value.strip())
    if not match:
        raise ValueError("birthTime debe tener formato HH:MM, HH:MM:SS o HH:MM:SS.ffffff.")

    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    second = int(match.group("second") or 0)
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError("birthTime contiene una hora imposible.")

    fraction = match.group("fraction") or ""
    microsecond = int(fraction.ljust(6, "0")) if fraction else 0
    return hour, minute, second, microsecond


def convert_local_to_utc(
    year, month, day, hour, minute, timezone_str, second=0, microsecond=0
):
    """
    Convert local time to UTC.

    Args:
        year, month, day, hour, minute, second, microsecond: Local time components
        timezone_str: IANA timezone string (e.g., 'Europe/Madrid')

    Returns:
        tuple: (year, month, day, hour, minute) in UTC; minute may be fractional
        so seconds are preserved in the Julian Day.
    """
    try:
        # Create a timezone-aware datetime in the local timezone
        local_tz = pytz.timezone(timezone_str)
        local_dt = local_tz.localize(
            datetime(year, month, day, hour, minute, second, microsecond)
        )

        # Convert to UTC
        utc_dt = local_dt.astimezone(pytz.UTC)

        print(
            f"[time] Local: {local_dt.strftime('%Y-%m-%d %H:%M:%S %Z')} "
            f"-> UTC: {utc_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )

        return (
            utc_dt.year,
            utc_dt.month,
            utc_dt.day,
            utc_dt.hour,
            utc_dt.minute + utc_dt.second / 60.0 + utc_dt.microsecond / 60_000_000.0
        )
    except Exception as e:
        # Fase 0: nunca interpretar la hora local como UTC. Un fallo aquí podía
        # desplazar el Ascendente y las casas hasta dos horas en silencio.
        print(f"[time] ERROR converting timezone '{timezone_str}': {e}")
        raise TimezoneResolutionError(
            f"No se ha podido resolver la zona horaria '{timezone_str}': {e}"
        )

def calculate_julian_day(year, month, day, hour, minute):
    """Calculate Julian Day from UTC time"""
    decimal_time = hour + minute / 60.0
    jd = swe.julday(year, month, day, decimal_time)
    return jd

REQUESTED_FLAGS = swe.FLG_SWIEPH | swe.FLG_SPEED

def calc_ut_validated(julian_day, planet_id, body_key=None):
    """
    Única puerta de entrada a swe.calc_ut (Fase 0).

    Pedir FLG_SWIEPH no garantiza que Swiss lo use: si faltan los ficheros de
    efemérides cae a Moshier sin lanzar excepción y lo indica solo en los
    retflags. Todo hecho objetivo del sistema pasa por aquí, no solo la carta
    natal, para que ningún dato salga de un motor degradado.

    Devuelve (values, provenance) o lanza EphemerisEngineError.
    """
    label = body_key or str(planet_id)
    result = swe.calc_ut(julian_day, planet_id, REQUESTED_FLAGS)
    values = result[0]
    retflags = result[1] if len(result) > 1 else None
    provenance = validate_engine(label, REQUESTED_FLAGS, retflags)
    return values, provenance


def calculate_planet_position(julian_day, planet_id, body_key=None):
    """
    Calculate planet position using Swiss Ephemeris.

    Un cuerpo obligatorio que falla es un error de servicio: no puede
    desaparecer en silencio de una carta, unos tránsitos o una revolución solar.
    """
    label = body_key or str(planet_id)
    try:
        values, provenance = calc_ut_validated(julian_day, planet_id, label)

        longitude = values[0]
        latitude = values[1]
        distance = values[2]
        speed = values[3]
        
        sign_info = get_sign(longitude)
        
        return {
            'longitude': round(longitude, 6),
            'latitude': round(latitude, 6),
            'distance': round(distance, 6),
            'speed': round(speed, 6),
            'retrograde': speed < 0,
            'degree_dms': dms_of(sign_info),
            'provenance': provenance,
            **sign_info
        }
    except EphemerisEngineError:
        # Se propaga: no se puede entregar una carta calculada con otro motor.
        raise
    except Exception as e:
        print(f"[calc] ERROR calculating planet {label}: {e}")
        if is_required_body(label):
            raise BodyCalculationError(
                f"No se ha podido calcular el cuerpo obligatorio '{label}': {e}"
            )
        return None


def calculate_houses(julian_day, latitude, longitude):
    """
    Casas por Placidus.

    Fase 0: Swiss Ephemeris no informa de qué sistema ha usado realmente y
    sustituye Placidus cerca de los polos. Bloqueamos esas latitudes antes de
    calcular en lugar de entregar casas etiquetadas como Placidus sin serlo.
    """
    house_system = assert_house_system(latitude)
    try:
        # 'P' = Placidus, 'K' = Koch, 'E' = Equal, etc.
        houses, ascmc = swe.houses(julian_day, latitude, longitude, b'P')
        
        house_list = []
        house_names = [
            'Casa 1 (AC)', 'Casa 2', 'Casa 3', 'Casa 4 (FC)',
            'Casa 5', 'Casa 6', 'Casa 7 (DC)', 'Casa 8',
            'Casa 9', 'Casa 10 (MC)', 'Casa 11', 'Casa 12'
        ]
        
        for i in range(12):
            cusp = houses[i]
            sign_info = get_sign(cusp)
            house_list.append({
                'house': house_names[i],
                'house_number': i + 1,
                'cusp': round(cusp, 6),
                'degree_dms': dms_of(sign_info),
                **sign_info
            })
        
        # ascmc contains: [Ascendant, MC, ARMC, Vertex, Equatorial Ascendant, ...]
        ascendant = ascmc[0]
        mc = ascmc[1]
        vertex = ascmc[3]
        
        asc_sign = get_sign(ascendant)
        mc_sign = get_sign(mc)
        vertex_sign = get_sign(vertex)
        
        return {
            'houses': house_list,
            'ascendant': {
                'longitude': round(ascendant, 6),
                'degree_dms': dms_of(asc_sign),
                **asc_sign
            },
            'mc': {
                'longitude': round(mc, 6),
                'degree_dms': dms_of(mc_sign),
                **mc_sign
            },
            'vertex': {
                'longitude': round(vertex, 6),
                'degree_dms': dms_of(vertex_sign),
                **vertex_sign
            },
            'houseSystem': house_system
        }
    except HouseSystemUnavailableError:
        raise
    except Exception as e:
        # Un fallo de casas no puede degradarse a "sin datos": sin Ascendente ni
        # cúspides no hay carta que entregar.
        print(f"[calc] ERROR calculating houses: {e}")
        raise HouseCalculationError(f"Swiss Ephemeris no ha podido calcular las casas: {e}")

def get_house_for_planet(planet_longitude, houses):
    """Determine which house a planet is in based on its longitude"""
    cusps = [h['cusp'] for h in houses or []]
    if len(cusps) != 12:
        raise HousePlacementError(
            f"Se esperaban 12 cúspides para situar la longitud {planet_longitude}, "
            f"se han recibido {len(cusps)}."
        )

    
    for i in range(12):
        cusp_start = cusps[i]
        cusp_end = cusps[(i + 1) % 12]
        
        # Handle the case where the house spans 0° Aries
        if cusp_start > cusp_end:
            if planet_longitude >= cusp_start or planet_longitude < cusp_end:
                return i + 1
        else:
            if cusp_start <= planet_longitude < cusp_end:
                return i + 1

    # Antes se devolvía Casa 1 por defecto: una casa inventada que llegaba al
    # informe como si fuese un hecho calculado.
    return assert_house_placement(None, planet_longitude)

def normalize_angle(angle):
    """Normalize angle to -180 to +180 range"""
    angle = angle % 360
    if angle > 180:
        angle -= 360
    return angle

def is_aspect_applying(planet1_lon, planet1_speed, planet2_lon, planet2_speed, aspect_angle):
    """
    Determine if an aspect is applying (A) or separating (S).
    An aspect is applying when planets are moving toward exactitude.
    
    Args:
        planet1_lon: Longitude of first planet (degrees)
        planet1_speed: Speed of first planet (degrees/day)
        planet2_lon: Longitude of second planet (degrees)
        planet2_speed: Speed of second planet (degrees/day)
        aspect_angle: Exact angle of the aspect (0, 60, 90, 120, 180)
    
    Returns:
        str: 'A' for applying, 'S' for separating
    """
    # Current angular difference (normalized to -180 to +180)
    current_diff = normalize_angle(planet1_lon - planet2_lon)
    
    # Relative speed (positive if planet1 is catching up)
    relative_speed = planet1_speed - planet2_speed
    
    # Calculate distance to exact aspect
    if aspect_angle == 0:  # Conjunction
        current_distance = abs(current_diff)
    elif aspect_angle == 180:  # Opposition
        current_distance = abs(abs(current_diff) - 180)
    else:  # Trine (120), Square (90), Sextile (60)
        # Find minimum distance to aspect (could be ± aspect_angle)
        dist_positive = abs(current_diff - aspect_angle)
        dist_negative = abs(current_diff + aspect_angle)
        current_distance = min(dist_positive, dist_negative)
    
    # Calculate future position (0.1 days = ~2.4 hours ahead)
    future_diff = normalize_angle(
        (planet1_lon + relative_speed * 0.1) - planet2_lon
    )
    
    # Calculate future distance to exact aspect
    if aspect_angle == 0:
        future_distance = abs(future_diff)
    elif aspect_angle == 180:
        future_distance = abs(abs(future_diff) - 180)
    else:
        dist_positive = abs(future_diff - aspect_angle)
        dist_negative = abs(future_diff + aspect_angle)
        future_distance = min(dist_positive, dist_negative)
    
    # Aspect is applying if future distance is smaller
    return 'A' if future_distance < current_distance else 'S'

def calculate_aspects(planets, ascendant_lon=None, mc_lon=None):
    """Calculate aspects between planets and to angles"""
    aspects = []
    planet_keys = list(planets.keys())
    
    # Traditional orbs
    aspect_orbs = {
        'conjunction': {'angle': 0, 'orb': 8, 'name': 'Conjunción'},
        'opposition': {'angle': 180, 'orb': 8, 'name': 'Oposición'},
        'trine': {'angle': 120, 'orb': 8, 'name': 'Trígono'},
        'square': {'angle': 90, 'orb': 8, 'name': 'Cuadratura'},
        'sextile': {'angle': 60, 'orb': 6, 'name': 'Sextil'},  # Increased from 4° to 6° (professional standard)
    }
    
    # Aspects between planets
    for i in range(len(planet_keys)):
        for j in range(i + 1, len(planet_keys)):
            planet1_key = planet_keys[i]
            planet2_key = planet_keys[j]
            
            if not planets[planet1_key] or not planets[planet2_key]:
                continue
            
            lon1 = planets[planet1_key]['longitude']
            lon2 = planets[planet2_key]['longitude']
            speed1 = planets[planet1_key].get('speed', 0)
            speed2 = planets[planet2_key].get('speed', 0)
            
            # Calculate angular separation
            diff = abs(lon1 - lon2)
            if diff > 180:
                diff = 360 - diff
            
            # Check each aspect type
            for aspect_type, aspect_data in aspect_orbs.items():
                orb = abs(diff - aspect_data['angle'])
                if orb <= aspect_data['orb']:
                    applying = is_aspect_applying(lon1, speed1, lon2, speed2, aspect_data['angle'])
                    # Field naming convention:
                    #   'aspect' = human-readable name ("Trígono", "Oposición") — consumed by AI/frontend
                    #   'category' = technical classification ("planet-planet", "planet-angle") — internal filtering only
                    aspects.append({
                        'planet1': PLANET_NAMES[planet1_key],
                        'planet2': PLANET_NAMES[planet2_key],
                        'aspect': aspect_data['name'],
                        'orb': round(orb, 2),
                        'angle': aspect_data['angle'],
                        'applying': applying,
                        'category': 'planet-planet'
                    })
    
    # Aspects to Ascendant
    if ascendant_lon is not None:
        for planet_key in planet_keys:
            if not planets[planet_key]:
                continue
            
            lon = planets[planet_key]['longitude']
            speed = planets[planet_key].get('speed', 0)
            
            diff = abs(lon - ascendant_lon)
            if diff > 180:
                diff = 360 - diff
            
            for aspect_type, aspect_data in aspect_orbs.items():
                orb = abs(diff - aspect_data['angle'])
                if orb <= aspect_data['orb']:
                    # Ascendant doesn't move, so only planet speed matters
                    applying = is_aspect_applying(lon, speed, ascendant_lon, 0, aspect_data['angle'])
                    aspects.append({
                        'planet1': PLANET_NAMES[planet_key],
                        'planet2': 'Ascendente',
                        'aspect': aspect_data['name'],
                        'orb': round(orb, 2),
                        'angle': aspect_data['angle'],
                        'applying': applying,
                        'category': 'planet-angle'
                    })
    
    # Aspects to MC
    if mc_lon is not None:
        for planet_key in planet_keys:
            if not planets[planet_key]:
                continue
            
            lon = planets[planet_key]['longitude']
            speed = planets[planet_key].get('speed', 0)
            
            diff = abs(lon - mc_lon)
            if diff > 180:
                diff = 360 - diff
            
            for aspect_type, aspect_data in aspect_orbs.items():
                orb = abs(diff - aspect_data['angle'])
                if orb <= aspect_data['orb']:
                    applying = is_aspect_applying(lon, speed, mc_lon, 0, aspect_data['angle'])
                    aspects.append({
                        'planet1': PLANET_NAMES[planet_key],
                        'planet2': 'Medio Cielo',
                        'aspect': aspect_data['name'],
                        'orb': round(orb, 2),
                        'angle': aspect_data['angle'],
                        'applying': applying,
                        'category': 'planet-angle'
                    })
    
    return aspects

def _engine_diagnostics():
    """
    Diagnóstico verificable del motor (Fase 0).

    Comprueba, con una fecha conocida (2000-01-01 12:00 UT), qué motor usa
    realmente Swiss Ephemeris para el Sol y para Quirón, y si los ficheros de
    efemérides están presentes.
    """
    ephe_path = _resolve_ephe_path()
    files = []
    if os.path.isdir(ephe_path):
        files = sorted(f for f in os.listdir(ephe_path) if not f.startswith('.'))

    jd = swe.julday(2000, 1, 1, 12.0)
    bodies = {}
    for key, planet_id in (('sun', swe.SUN), ('chiron', swe.CHIRON)):
        try:
            # Única excepción permitida a calc_ut_validated: el diagnóstico debe
            # observar los retflags de un motor degradado sin abortar, que es
            # justo lo que se está midiendo. Todo cálculo funcional pasa por
            # calc_ut_validated.
            result = swe.calc_ut(jd, planet_id, REQUESTED_FLAGS)
            retflags = result[1] if len(result) > 1 else None
            engine = resolve_effective_engine(retflags)
            bodies[key] = {
                'status': 'ok' if engine == 'swiss' else 'degraded',
                'engine': engine,
                'requested_flags': int(REQUESTED_FLAGS),
                'retflags': retflags,
                'longitude': round(result[0][0], 6),
            }
        except Exception as e:
            bodies[key] = {'status': 'error', 'message': str(e)}

    healthy = all(b.get('status') == 'ok' for b in bodies.values())

    return {
        'healthy': healthy,
        'policy': ARETE_ASTRO_POLICY,
        'ephe_path': ephe_path,
        'files': files,
        'file_count': len(files),
        'expected_files': ['seas_18.se1', 'sepl_18.se1'],
        'required_bodies': list(REQUIRED_BODIES),
        'bodies': bodies,
        'swisseph_version': getattr(swe, 'version', 'unknown'),
    }


def _effective_engine_of(planets):
    """Motor efectivo común a todos los cuerpos de la carta, o 'mixed'."""
    engines = {
        p['provenance']['engine']
        for p in planets.values()
        if isinstance(p, dict) and isinstance(p.get('provenance'), dict)
    }
    if not engines:
        return 'unknown'
    return engines.pop() if len(engines) == 1 else 'mixed'


@app.route('/health', methods=['GET'])
def health():
    """
    Health check.

    Fase 0: el estado refleja el motor real. Se mantiene el código 200 para no
    provocar reinicios en cascada del contenedor (cada cálculo ya falla por sí
    mismo si el motor está degradado), pero el estado deja de mentir.
    """
    try:
        diagnostics = _engine_diagnostics()
        healthy = diagnostics['healthy']
        summary = {
            'engine': {
                'healthy': healthy,
                'ephePath': diagnostics['ephe_path'],
                'fileCount': diagnostics['file_count'],
                'bodies': {k: v.get('engine', v.get('status')) for k, v in diagnostics['bodies'].items()},
                'swissephVersion': diagnostics['swisseph_version'],
            }
        }
    except Exception as e:
        healthy = False
        summary = {'engine': {'healthy': False, 'error': str(e)}}

    return jsonify({
        'status': 'healthy' if healthy else 'degraded',
        'service': 'swiss-ephemeris',
        **summary,
    })


@app.route('/health/engine', methods=['GET'])
def health_engine():
    """Health check del motor: efemérides, motor efectivo y capacidad de calcular Quirón"""
    diagnostics = _engine_diagnostics()
    return jsonify(diagnostics), (200 if diagnostics['healthy'] else 503)


@app.route('/debug/ephe', methods=['GET'])
def debug_ephe():
    """Debug endpoint to check ephemeris files (compatibilidad con la respuesta anterior)"""
    diagnostics = _engine_diagnostics()
    chiron = diagnostics['bodies'].get('chiron', {})
    return jsonify({
        'ephe_path': diagnostics['ephe_path'],
        'files': diagnostics['files'],
        'file_count': diagnostics['file_count'],
        'chiron_test': {
            'status': 'success' if chiron.get('status') == 'ok' else 'error',
            'longitude': chiron.get('longitude'),
            'sign': get_sign(chiron['longitude'])['sign'] if chiron.get('longitude') is not None else None,
            'engine': chiron.get('engine'),
            'message': chiron.get('message'),
        },
        'expected_files': diagnostics['expected_files'],
        'engine': diagnostics,
    })

def build_natal_points(planets, houses_data=None):
    """Puntos natales utilizables como objetivo de aspectos entre cartas."""
    points = {
        key: {'name': planet.get('name', key), 'longitude': planet['longitude']}
        for key, planet in (planets or {}).items()
        if isinstance(planet, dict) and planet.get('longitude') is not None
    }
    if houses_data:
        if houses_data.get('ascendant'):
            points['ascendant'] = {'name': 'Ascendente', 'longitude': houses_data['ascendant']['longitude']}
        if houses_data.get('mc'):
            points['mc'] = {'name': 'Medio Cielo', 'longitude': houses_data['mc']['longitude']}
    return points


PROGRESSED_BODIES = (
    ('sun', swe.SUN, 'Sol Progresado'),
    ('moon', swe.MOON, 'Luna Progresada'),
    ('mercury', swe.MERCURY, 'Mercurio Progresado'),
    ('venus', swe.VENUS, 'Venus Progresado'),
    ('mars', swe.MARS, 'Marte Progresado'),
)


def _progressed_julian_day(birth_jd, current_date_str):
    """Un día después del nacimiento equivale a un año de vida."""
    current_year, current_month, current_day = map(int, current_date_str.split('-'))
    current_jd = swe.julday(current_year, current_month, current_day, 12.0)
    years_since_birth = (current_jd - birth_jd) / 365.25
    return birth_jd + years_since_birth, years_since_birth


def calculate_secondary_progressions(birth_jd, current_date_str, natal_points=None):
    """
    Progresiones secundarias deterministas: Sol, Luna, Mercurio, Venus y Marte
    sobre una única fecha progresada, con sus aspectos a la carta natal.

    El Ascendente progresado queda oficialmente no soportado: hay varias
    convenciones astrológicas y el motor no decide por nosotros cuál es la
    correcta. Antes que una precisión falsa, preferimos declararlo ausente.
    """
    try:
        progressed_jd, years_since_birth = _progressed_julian_day(birth_jd, current_date_str)

        points = {}
        for key, planet_id, display_name in PROGRESSED_BODIES:
            position = calculate_planet_position(progressed_jd, planet_id, body_key=key)
            if not position:
                continue
            points[key] = {'name': display_name, **position}

        if 'moon' not in points:
            return None

        # Aspectos progresado -> natal sobre longitudes absolutas: sin esto el
        # modelo solo veía signo y grado, y de ahí salió la falsa "conjunción"
        # del caso Marta Alí (Virgo 1°34\' y Cáncer 1°22\' son un sextil).
        aspects = calculate_cross_aspects(
            {k: {'name': v['name'], 'longitude': v['longitude']} for k, v in points.items()},
            natal_points or {},
            PROGRESSION_ORBS,
            source_suffix='',
        )

        def moon_longitude_at(jd):
            return calc_ut_validated(jd, swe.MOON, 'moon')[0][0]

        # Cambio de signo buscado con el motor. Antes se dividía por una
        # velocidad media de 12,2°/año y se presentaba como fecha real.
        years_to_change = years_to_sign_change(moon_longitude_at, progressed_jd)

        return {
            'yearsToSignChange': years_to_change,
            'progressedJulianDay': round(progressed_jd, 6),
            'yearsSinceBirth': round(years_since_birth, 2),
            'points': points,
            'aspects': aspects,
            'orbPolicy': {'version': ORB_POLICY['version'], 'maxOrb': PROGRESSION_ORBS['conjunction']},
            'progressedAscendant': {
                'supported': PROGRESSED_ASCENDANT_SUPPORTED,
                'reason': 'Sin convención única validada; Areté no lo calcula.',
            },
        }
    except (EphemerisEngineError, BodyCalculationError, HouseSystemUnavailableError,
            HouseCalculationError, HousePlacementError):
        raise
    except Exception as e:
        print(f"[calc] ERROR calculating secondary progressions: {e}")
        return None


def progressed_moon_from(progressions):
    """
    Salida de compatibilidad `progressedMoon`, derivada de las progresiones.

    No recalcula nada: los consumidores existentes siguen recibiendo la misma
    forma, pero de una única fuente.
    """
    if not progressions:
        return None
    moon = progressions['points'].get('moon')
    if not moon:
        return None

    prev_sign_index = (SIGNS.index(moon['sign']) - 1) % 12
    moon_aspects = [a for a in progressions['aspects'] if a['sourceKey'] == 'moon']

    return {
        'name': 'Luna Progresada',
        'longitude': moon['longitude'],
        'aspects': moon_aspects,
        'orbPolicy': progressions['orbPolicy'],
        'sign': moon['sign'],
        'degree': moon['degree'],
        'degree_dms': moon['degree_dms'],
        'previousSign': SIGNS[prev_sign_index],
        'yearsToSignChange': progressions.get('yearsToSignChange'),
        'progressedJulianDay': progressions['progressedJulianDay'],
        'yearsSinceBirth': progressions['yearsSinceBirth'],
    }


def calculate_solar_return(birth_jd, birth_sun_longitude, current_year, sr_latitude, sr_longitude, natal_points=None):
    """
    Calculate Solar Return chart for a given year.
    Solar Return is when the Sun returns to its exact natal position.
    
    Args:
        birth_jd: Julian Day of birth (for reference)
        birth_sun_longitude: Natal Sun longitude in degrees
        current_year: Year for which to calculate SR
        sr_latitude: Latitude where the birthday is spent
        sr_longitude: Longitude where the birthday is spent
    
    Returns:
        dict with Solar Return chart data
    """
    try:
        # El retorno se busca alrededor del cumpleaños en el año pedido, no
        # biseccionando un año entero sobre una función angular discontinua:
        # ese algoritmo podía elegir el retorno equivocado para cumpleaños de
        # principios de enero.
        birth_calendar = swe.revjul(birth_jd)
        birth_month, birth_day = int(birth_calendar[1]), int(birth_calendar[2])
        approx_jd = approximate_return_jd(swe.julday, birth_month, birth_day, current_year, 12.0)

        def sun_longitude_at(jd):
            return calc_ut_validated(jd, swe.SUN, 'sun')[0][0]

        sr_jd = find_solar_return_jd(sun_longitude_at, approx_jd, birth_sun_longitude)

        # Calculate houses for SR location
        sr_houses = calculate_houses(sr_jd, sr_latitude, sr_longitude)
        if not sr_houses:
            return None
        
        # Calculate all planets at SR moment. El Nodo Sur no se calcula con
        # calc_ut (su planet_id es None): se deriva del Nodo Norte, igual que en
        # la carta natal y en los tránsitos.
        sr_planets = {}
        for planet_key, planet_id in PLANETS.items():
            if planet_key == 'south_node':
                continue
            position = calculate_planet_position(sr_jd, planet_id, body_key=planet_key)
            if position:
                house_num = get_house_for_planet(position['longitude'], sr_houses['houses'])
                sr_planets[planet_key] = {
                    'name': PLANET_NAMES[planet_key],
                    'house': house_num,
                    **position
                }

        if 'north_node' in sr_planets:
            nn = sr_planets['north_node']
            sn_lon = (nn['longitude'] + 180) % 360
            sn_sign = get_sign(sn_lon)
            sr_planets['south_node'] = {
                'name': PLANET_NAMES['south_node'],
                'house': get_house_for_planet(sn_lon, sr_houses['houses']),
                'longitude': round(sn_lon, 6),
                'speed': nn['speed'],
                'retrograde': nn.get('retrograde', False),
                'degree_dms': dms_of(sn_sign),
                **sn_sign
            }
        
        # Calculate aspects in SR
        sr_aspects = calculate_aspects(
            sr_planets,
            ascendant_lon=sr_houses['ascendant']['longitude'],
            mc_lon=sr_houses['mc']['longitude']
        )
        
        # Convert SR Julian Day back to calendar date using swe.revjul
        sr_date = swe.revjul(sr_jd)
        sr_date_str = f"{int(sr_date[0])}-{int(sr_date[1]):02d}-{int(sr_date[2]):02d}"
        # Use revjul's decimal hour (index 3) — NOT (sr_jd % 1) * 24 which is wrong
        sr_time_decimal = sr_date[3]
        sr_hour = int(sr_time_decimal)
        sr_minute = int((sr_time_decimal - sr_hour) * 60)
        sr_time_str = f"{sr_hour:02d}:{sr_minute:02d}"
        
        print(f"[SR] Exact moment: {sr_date_str} {sr_time_str} UT (JD={sr_jd:.6f})")
        print(f"[SR] Location: lat={sr_latitude}, lon={sr_longitude}")
        print(f"[SR] Houses: AC={sr_houses['ascendant']['sign']} {sr_houses['ascendant']['degree_dms']}, MC={sr_houses['mc']['sign']} {sr_houses['mc']['degree_dms']}")
        
        # Fase 2: los aspectos internos de la RS ya se calculaban pero se
        # descartaban al construir la respuesta, y los aspectos RS -> natal no
        # existían. Ambos se entregan ahora como hecho determinista.
        sr_natal_aspects = calculate_cross_aspects(
            {k: {'name': v.get('name', k), 'longitude': v['longitude']} for k, v in sr_planets.items()},
            natal_points or {},
            SOLAR_RETURN_ORBS,
            default_orbs=DEFAULT_TRANSIT_ORBS,
            source_suffix='RS',
        )

        return {
            'year': current_year,
            'aspects': sr_aspects,
            'natalAspects': sr_natal_aspects,
            'orbPolicy': {'version': ORB_POLICY['version'], 'solarReturnToNatal': 'transit_orbs'},
            'exactMoment': {
                'julianDay': round(sr_jd, 6),
                'date': sr_date_str,
                'time': sr_time_str
            },
            'planets': sr_planets,
            'houses': sr_houses['houses'],
            'ascendant': sr_houses['ascendant'],
            'mc': sr_houses['mc'],
            'location': {
                'latitude': sr_latitude,
                'longitude': sr_longitude
            }
        }
    except (EphemerisEngineError, BodyCalculationError, HouseSystemUnavailableError,
            HouseCalculationError, HousePlacementError, SolarReturnSearchError):
        # Fase 0: un motor degradado, un cuerpo obligatorio ausente o un fallo
        # de casas nunca se degradan a "sin resultado"; se propagan al endpoint.
        raise
    except Exception as e:
        print(f"[calc] ERROR calculating Solar Return: {e}")
        import traceback
        traceback.print_exc()
        return None


# ============ TRANSIT CALCULATION ============

TRANSIT_ASPECT_DEFS = [
    {'key': 'conjunction', 'angle': 0,   'name': 'Conjunción'},
    {'key': 'opposition',  'angle': 180, 'name': 'Oposición'},
    {'key': 'trine',       'angle': 120, 'name': 'Trígono'},
    {'key': 'square',      'angle': 90,  'name': 'Cuadratura'},
    {'key': 'sextile',     'angle': 60,  'name': 'Sextil'},
]

def normalize_natal_cusps(natal_houses):
    """
    Acepta las cúspides natales tal y como las guarda la carta y devuelve la
    forma que espera get_house_for_planet, o None si no son utilizables.
    """
    if not natal_houses:
        return None
    cusps = []
    for item in natal_houses:
        if isinstance(item, dict):
            value = item.get('cusp', item.get('degree'))
        else:
            value = item
        try:
            cusps.append({'cusp': float(value) % 360.0})
        except (TypeError, ValueError):
            return None
    return cusps if len(cusps) == 12 else None


def calculate_transits(natal_planets_data, target_date_str=None, natal_houses=None):
    """
    Calculate current transiting planets and their aspects to natal chart.

    Las cúspides natales dependen del momento y del lugar de nacimiento y no se
    pueden reconstruir con el día juliano del tránsito: antes se hacía como
    "aproximación" y producía una casa natal falsa. Ahora `natalHouse` solo
    aparece si el llamante aporta las cúspides natales reales.

    Args:
        natal_planets_data: dict of natal planets with longitude values
        target_date_str: date string YYYY-MM-DD (default: today UTC)
        natal_houses: lista de 12 cúspides natales reales (o None para omitir la casa)

    Returns:
        dict with transitPlanets, transitAspects, date
    """
    try:
        if target_date_str:
            year, month, day = map(int, target_date_str.split('-'))
        else:
            now = datetime.utcnow()
            year, month, day = now.year, now.month, now.day
        
        # Use noon UT for transit date
        transit_jd = swe.julday(year, month, day, 12.0)
        
        # Calculate current transit positions
        transit_planets = {}
        for planet_key, planet_id in PLANETS.items():
            if planet_key == 'south_node':
                continue
            position = calculate_planet_position(transit_jd, planet_id, body_key=planet_key)
            if position:
                transit_planets[planet_key] = {
                    'name': PLANET_NAMES[planet_key],
                    **position
                }
        
        # Add south node
        if 'north_node' in transit_planets:
            nn_lon = transit_planets['north_node']['longitude']
            sn_lon = (nn_lon + 180) % 360
            sn_sign = get_sign(sn_lon)
            transit_planets['south_node'] = {
                'name': PLANET_NAMES['south_node'],
                'longitude': round(sn_lon, 6),
                'speed': transit_planets['north_node']['speed'],
                'degree_dms': dms_of(sn_sign),
                **sn_sign
            }
        
        # Casa natal del tránsito: solo con cúspides natales reales aportadas
        # por el llamante. Sin ellas se omite el dato en lugar de estimarlo.
        natal_cusps = normalize_natal_cusps(natal_houses)
        if natal_cusps:
            for pk in transit_planets:
                lon = transit_planets[pk]['longitude']
                transit_planets[pk]['natalHouse'] = get_house_for_planet(lon, natal_cusps)
        
        # Build transit aspects against natal planets
        transit_aspects = []
        
        for t_key, t_planet in transit_planets.items():
            t_lon = t_planet['longitude']
            t_speed = t_planet.get('speed', 0)
            t_orbs = TRANSIT_ORBS.get(t_key, {'conjunction': 2, 'opposition': 2, 'trine': 2, 'square': 2, 'sextile': 1})
            
            for n_key, n_planet in natal_planets_data.items():
                # natal_planets_data may contain longitude as a float or as a dict
                if isinstance(n_planet, dict):
                    n_lon = n_planet.get('longitude')
                else:
                    n_lon = n_planet
                
                if n_lon is None:
                    continue
                
                n_lon = float(n_lon)
                n_name = PLANET_NAMES.get(n_key, n_key)
                
                diff = abs(t_lon - n_lon)
                if diff > 180:
                    diff = 360 - diff
                
                for asp in TRANSIT_ASPECT_DEFS:
                    orb_allowed = t_orbs.get(asp['key'], 2)
                    orb = abs(diff - asp['angle'])
                    if orb <= orb_allowed:
                        applying = is_aspect_applying(t_lon, t_speed, n_lon, 0, asp['angle'])
                        transit_aspects.append({
                            'transitPlanet': t_planet['name'],
                            'transitPlanetKey': t_key,
                            'natalPlanet': n_name,
                            'natalPlanetKey': n_key,
                            'aspect': asp['name'],
                            'orb': round(orb, 2),
                            'angle': asp['angle'],
                            'applying': applying,
                            'natalHouse': transit_planets[t_key].get('natalHouse'),
                        })
        
        # Sort by orb (tightest first)
        transit_aspects.sort(key=lambda x: x['orb'])
        
        date_str = f"{year}-{month:02d}-{day:02d}"
        print(f"[transits] Calculated {len(transit_aspects)} transit aspects for {date_str}")
        
        return {
            'transitPlanets': transit_planets,
            'transitAspects': transit_aspects,
            'date': date_str,
        }
    except (EphemerisEngineError, BodyCalculationError, HouseSystemUnavailableError):
        # Fase 0: un motor degradado o un cuerpo obligatorio ausente nunca se
        # degradan a "sin resultado"; se propagan hasta el endpoint.
        raise
    except Exception as e:
        print(f"[transits] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


@app.route('/transits', methods=['POST'])
def get_transits():
    """Calculate current transit aspects against a natal chart"""
    try:
        data = request.get_json()
        
        natal_planets = data.get('natalPlanets', {})
        target_date = data.get('targetDate', None)
        # latitude/longitude ya no sirven para estimar casas natales: si el
        # llamante quiere natalHouse, debe enviar las cúspides natales reales.
        natal_houses = data.get('natalHouses')

        if not natal_planets:
            return jsonify({'error': 'natalPlanets is required'}), 400

        result = calculate_transits(natal_planets, target_date, natal_houses)
        
        if not result:
            return jsonify({'error': 'Failed to calculate transits'}), 500
        
        return jsonify({'success': True, **result})
        
    except HouseSystemUnavailableError as e:
        return jsonify({'error': str(e), 'code': 'house_system_unavailable'}), 422
    except EphemerisEngineError as e:
        return jsonify({'error': str(e), 'code': 'ephemeris_engine_mismatch'}), 503
    except BodyCalculationError as e:
        return jsonify({'error': str(e), 'code': 'required_body_missing'}), 503
    except Exception as e:
        print(f"[transits] ERROR in endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def calculate_current_positions(target_date_str=None):
    """
    Calculate planetary positions for a given date (default: today UTC),
    without requiring a natal chart. Used by the daily global snapshot cron.
    """
    try:
        if target_date_str:
            year, month, day = map(int, target_date_str.split('-'))
        else:
            now = datetime.utcnow()
            year, month, day = now.year, now.month, now.day

        jd = swe.julday(year, month, day, 12.0)

        planets = {}
        for planet_key, planet_id in PLANETS.items():
            if planet_key == 'south_node':
                continue
            position = calculate_planet_position(jd, planet_id, body_key=planet_key)
            if position:
                planets[planet_key] = {
                    'name': PLANET_NAMES[planet_key],
                    **position,
                }

        if 'north_node' in planets:
            nn_lon = planets['north_node']['longitude']
            sn_lon = (nn_lon + 180) % 360
            sn_sign = get_sign(sn_lon)
            planets['south_node'] = {
                'name': PLANET_NAMES['south_node'],
                'longitude': round(sn_lon, 6),
                'speed': planets['north_node']['speed'],
                'degree_dms': dms_of(sn_sign),
                **sn_sign,
            }

        date_str = f"{year}-{month:02d}-{day:02d}"
        print(f"[current-positions] Calculated {len(planets)} planets for {date_str}")
        return {'planets': planets, 'date': date_str}
    except (EphemerisEngineError, BodyCalculationError, HouseSystemUnavailableError):
        # Fase 0: un motor degradado o un cuerpo obligatorio ausente nunca se
        # degradan a "sin resultado"; se propagan hasta el endpoint.
        raise
    except Exception as e:
        print(f"[current-positions] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


@app.route('/current-positions', methods=['POST', 'GET'])
def get_current_positions():
    """Return today's (or targetDate's) planetary positions, no natal required."""
    try:
        target_date = None
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            target_date = data.get('targetDate')
        else:
            target_date = request.args.get('targetDate')

        result = calculate_current_positions(target_date)
        if not result:
            return jsonify({'error': 'Failed to calculate current positions'}), 500
        return jsonify({'success': True, **result})
    except HouseSystemUnavailableError as e:
        return jsonify({'error': str(e), 'code': 'house_system_unavailable'}), 422
    except EphemerisEngineError as e:
        return jsonify({'error': str(e), 'code': 'ephemeris_engine_mismatch'}), 503
    except BodyCalculationError as e:
        return jsonify({'error': str(e), 'code': 'required_body_missing'}), 503
    except Exception as e:
        print(f"[current-positions] ERROR in endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500



def calculate_yearly_transits(natal_planets_data, year, latitude=None, longitude=None):
    SLOW_PLANET_KEYS = ['jupiter', 'saturn', 'uranus', 'neptune', 'pluto']
    SLOW_PLANET_IDS = {'jupiter': swe.JUPITER, 'saturn': swe.SATURN, 'uranus': swe.URANUS, 'neptune': swe.NEPTUNE, 'pluto': swe.PLUTO}
    try:
        from datetime import timedelta
        monthly_positions = []
        for month in range(1, 13):
            jd = swe.julday(year, month, 1, 12.0)
            planets = {}
            for pk in SLOW_PLANET_KEYS:
                pos = calculate_planet_position(jd, SLOW_PLANET_IDS[pk], body_key=pk)
                if pos:
                    planets[pk] = {'name': PLANET_NAMES[pk], **pos}
            monthly_positions.append({'month': month, 'date': f"{year}-{month:02d}-01", 'planets': planets})
        transit_aspects = []
        seen_aspects = set()
        sample_dates = []
        for day_offset in range(0, 366, 10):
            base = datetime(year, 1, 1) + timedelta(days=day_offset)
            if base.year > year:
                break
            sample_dates.append(base)
        for pk in SLOW_PLANET_KEYS:
            pid = SLOW_PLANET_IDS[pk]
            t_orbs = TRANSIT_ORBS.get(pk, {'conjunction': 4, 'opposition': 4, 'trine': 4, 'square': 4, 'sextile': 2})
            for sample_date in sample_dates:
                jd = swe.julday(sample_date.year, sample_date.month, sample_date.day, 12.0)
                t_pos = calculate_planet_position(jd, pid, body_key=pk)
                if not t_pos:
                    continue
                t_lon = t_pos['longitude']
                for n_key, n_planet in natal_planets_data.items():
                    n_lon = n_planet.get('longitude') if isinstance(n_planet, dict) else n_planet
                    if n_lon is None:
                        continue
                    n_lon = float(n_lon)
                    diff = abs(t_lon - n_lon)
                    if diff > 180:
                        diff = 360 - diff
                    for asp in TRANSIT_ASPECT_DEFS:
                        orb_allowed = t_orbs.get(asp['key'], 2)
                        orb = abs(diff - asp['angle'])
                        if orb <= orb_allowed * 0.75:
                            aspect_key = f"{pk}-{asp['key']}-{n_key}"
                            if aspect_key in seen_aspects:
                                continue
                            seen_aspects.add(aspect_key)
                            exact_date_str = _refine_aspect_date(pid, n_lon, asp['angle'], sample_date, year)
                            transit_aspects.append({
                                'transitPlanet': PLANET_NAMES[pk], 'transitPlanetKey': pk,
                                'natalPlanet': PLANET_NAMES.get(n_key, n_key), 'natalPlanetKey': n_key,
                                'aspect': asp['name'], 'orb': round(orb, 2), 'angle': asp['angle'],
                                'exactDate': exact_date_str or sample_date.strftime('%Y-%m-%d'),
                            })
        transit_aspects.sort(key=lambda x: x.get('exactDate', ''))
        sign_changes = []
        for pk in SLOW_PLANET_KEYS:
            pid = SLOW_PLANET_IDS[pk]
            prev_sign = None
            prev_jd = None
            for month in range(1, 14):
                if month <= 12:
                    jd = swe.julday(year, month, 1, 12.0)
                else:
                    jd = swe.julday(year + 1, 1, 1, 12.0)
                pos = calculate_planet_position(jd, pid, body_key=pk)
                if not pos:
                    continue
                if prev_sign and pos['sign'] != prev_sign and prev_jd is not None:
                    exact_iso = _refine_sign_change_date(pid, prev_jd, jd)
                    sign_changes.append({
                        'planet': PLANET_NAMES[pk],
                        'planetKey': pk,
                        'fromSign': prev_sign,
                        'toSign': pos['sign'],
                        'exactDate': exact_iso,
                        'approximateDate': exact_iso or f"{year}-{min(month,12):02d}-01",
                    })
                prev_sign = pos['sign']
                prev_jd = jd
        print(f"[yearly-transits] Year {year}: {len(transit_aspects)} aspects, {len(sign_changes)} sign changes")
        return {'year': year, 'monthlyPositions': monthly_positions, 'transitAspects': transit_aspects, 'signChanges': sign_changes, 'totalAspects': len(transit_aspects)}
    except (EphemerisEngineError, BodyCalculationError, HouseSystemUnavailableError):
        # Fase 0: un motor degradado o un cuerpo obligatorio ausente nunca se
        # degradan a "sin resultado"; se propagan hasta el endpoint.
        raise
    except Exception as e:
        print(f"[yearly-transits] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


def _refine_aspect_date(planet_id, natal_lon, aspect_angle, approx_date, year):
    try:
        from datetime import timedelta
        low_date = max(approx_date - timedelta(days=15), datetime(year, 1, 1))
        high_date = min(approx_date + timedelta(days=15), datetime(year, 12, 31))
        low_jd = swe.julday(low_date.year, low_date.month, low_date.day, 12.0)
        high_jd = swe.julday(high_date.year, high_date.month, high_date.day, 12.0)
        mid_jd = low_jd
        for _ in range(30):
            mid_jd = (low_jd + high_jd) / 2
            t_lon = calc_ut_validated(mid_jd, planet_id, 'transit')[0][0]
            diff = t_lon - natal_lon
            if diff > 180: diff -= 360
            elif diff < -180: diff += 360
            if aspect_angle == 0: distance = abs(diff)
            elif aspect_angle == 180: distance = abs(abs(diff) - 180)
            else: distance = min(abs(diff - aspect_angle), abs(diff + aspect_angle))
            if distance < 0.01:
                break
            t_lon_plus = calc_ut_validated(mid_jd + 0.5, planet_id, 'transit')[0][0]
            diff_plus = t_lon_plus - natal_lon
            if diff_plus > 180: diff_plus -= 360
            elif diff_plus < -180: diff_plus += 360
            if aspect_angle == 0: dist_plus = abs(diff_plus)
            elif aspect_angle == 180: dist_plus = abs(abs(diff_plus) - 180)
            else: dist_plus = min(abs(diff_plus - aspect_angle), abs(diff_plus + aspect_angle))
            if dist_plus < distance: low_jd = mid_jd
            else: high_jd = mid_jd
        result = swe.revjul(mid_jd)
        return f"{int(result[0])}-{int(result[1]):02d}-{int(result[2]):02d}"
    except EphemerisEngineError:
        raise
    except Exception:
        return None


def _refine_sign_change_date(planet_id, low_jd, high_jd):
    """Binary-search the exact JD where the planet crosses into a new sign (30-deg boundary)."""
    try:
        low = low_jd
        high = high_jd
        start_sign = int(calc_ut_validated(low, planet_id, 'transit')[0][0] // 30)
        for _ in range(40):
            mid = (low + high) / 2
            mid_sign = int(calc_ut_validated(mid, planet_id, 'transit')[0][0] // 30)
            if mid_sign == start_sign:
                low = mid
            else:
                high = mid
            if (high - low) < (1.0 / 1440.0):  # ~1 minute
                break
        result = swe.revjul(high)
        return f"{int(result[0])}-{int(result[1]):02d}-{int(result[2]):02d}"
    except EphemerisEngineError:
        raise
    except Exception:
        return None


# ============ BÚSQUEDA DE PERFECCIONES DE ASPECTO (Fase B) ============

# Paso de muestreo por planeta: suficientemente fino para no saltarse un cruce.
_SEARCH_STEP_DAYS = {
    'moon': 0.2, 'sun': 2.0, 'mercury': 1.0, 'venus': 1.0, 'mars': 2.0,
    'jupiter': 4.0, 'saturn': 4.0, 'uranus': 6.0, 'neptune': 6.0, 'pluto': 6.0,
}


def _jd_of(dt):
    """Día juliano preservando la fracción horaria (necesaria para el refinado)."""
    hours = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
    return swe.julday(dt.year, dt.month, dt.day, hours)


def _state_at_factory(planet_id):
    """Adaptador astronómico: única parte que depende de Swiss Ephemeris."""
    def state_at(moment):
        values, _ = calc_ut_validated(_jd_of(moment), planet_id, 'transit')
        return values[0], values[3]
    return state_at


def search_transit_aspect(transit_planet_key, natal_longitude, aspect_key, start, end):
    """Devuelve todas las pasadas exactas del aspecto dentro de la ventana."""
    return find_aspect_passes(
        _state_at_factory(PLANETS[transit_planet_key]),
        natal_longitude,
        aspect_key,
        start,
        end,
        _SEARCH_STEP_DAYS.get(transit_planet_key, 2.0),
    )




@app.route('/search-transit-aspect', methods=['POST'])
def get_transit_aspect_search():
    """Busca las fechas exactas en que un tránsito perfecciona un aspecto natal."""
    try:
        data = request.get_json(silent=True) or {}
        transit_planet = normalize_transit_planet(data.get('transitPlanet'))
        aspect = normalize_aspect(data.get('aspect'))
        if not transit_planet:
            return jsonify({'error': 'transitPlanet no soportado'}), 400
        if not aspect:
            return jsonify({'error': 'aspect no soportado'}), 400

        natal_longitude = data.get('natalLongitude')
        try:
            natal_longitude = float(natal_longitude) % 360.0
        except (TypeError, ValueError):
            return jsonify({'error': 'natalLongitude es obligatorio y numérico'}), 400

        start, end, window_error = validate_window(data.get('startDate'), data.get('endDate'))
        if window_error:
            return jsonify({'error': window_error}), 400

        passes = search_transit_aspect(transit_planet, natal_longitude, aspect, start, end)
        return jsonify({
            'success': True,
            'transitPlanet': PLANET_NAMES[transit_planet],
            'transitPlanetKey': transit_planet,
            'natalPlanet': data.get('natalPlanet'),
            'natalLongitude': round(natal_longitude, 6),
            'aspect': ASPECT_NAMES_ES[aspect],
            'aspectKey': aspect,
            'startDate': start.strftime('%Y-%m-%d'),
            'endDate': end.strftime('%Y-%m-%d'),
            'passes': passes,
            'totalPasses': len(passes),
        })
    except HouseSystemUnavailableError as e:
        return jsonify({'error': str(e), 'code': 'house_system_unavailable'}), 422
    except EphemerisEngineError as e:
        return jsonify({'error': str(e), 'code': 'ephemeris_engine_mismatch'}), 503
    except BodyCalculationError as e:
        return jsonify({'error': str(e), 'code': 'required_body_missing'}), 503
    except Exception as e:
        print(f"[search-transit-aspect] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500



@app.route('/yearly-transits', methods=['POST'])
def get_yearly_transits():
    try:
        data = request.get_json()
        natal_planets = data.get('natalPlanets', {})
        year = data.get('year', datetime.utcnow().year)
        if not natal_planets:
            return jsonify({'error': 'natalPlanets is required'}), 400
        result = calculate_yearly_transits(natal_planets, int(year), data.get('latitude'), data.get('longitude'))
        if not result:
            return jsonify({'error': 'Failed to calculate yearly transits'}), 500
        return jsonify({'success': True, **result})
    except HouseSystemUnavailableError as e:
        return jsonify({'error': str(e), 'code': 'house_system_unavailable'}), 422
    except EphemerisEngineError as e:
        return jsonify({'error': str(e), 'code': 'ephemeris_engine_mismatch'}), 503
    except BodyCalculationError as e:
        return jsonify({'error': str(e), 'code': 'required_body_missing'}), 503
    except Exception as e:
        print(f"[yearly-transits] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/calculate', methods=['POST'])
def calculate_natal_chart():
    """Calculate natal chart from birth data"""
    try:
        data = request.get_json()
        
        # Parse input
        birth_date = data.get('birthDate')  # YYYY-MM-DD
        birth_time = data.get('birthTime')  # HH:MM[:SS[.ffffff]] (LOCAL TIME)
        latitude = float(data.get('latitude'))
        longitude = float(data.get('longitude'))
        timezone = data.get('timezone', 'UTC')
        
        # Optional: Solar Return location (if different from birth)
        sr_latitude = data.get('solarReturnLatitude', latitude)
        sr_longitude = data.get('solarReturnLongitude', longitude)
        sr_year = data.get('solarReturnYear', datetime.utcnow().year)
        include_progressions = data.get('includeProgressions', True)
        include_solar_return = data.get('includeSolarReturn', True)
        
        # Parse date and time (LOCAL)
        year, month, day = map(int, birth_date.split('-'))
        try:
            hour, minute, second, microsecond = parse_birth_time(birth_time)
        except ValueError as e:
            return jsonify({'error': str(e), 'code': 'invalid_birth_time'}), 400

        fractional = f".{microsecond:06d}" if microsecond else ""
        print(
            f"[calc] Input LOCAL time: {year}-{month:02d}-{day:02d} "
            f"{hour:02d}:{minute:02d}:{second:02d}{fractional} ({timezone})"
        )
        print(f"[calc] Coordinates: lat={latitude}, lon={longitude}")
        
        # Convert local time to UTC for ephemeris calculations
        utc_year, utc_month, utc_day, utc_hour, utc_minute = convert_local_to_utc(
            year,
            month,
            day,
            hour,
            minute,
            timezone,
            second=second,
            microsecond=microsecond,
        )
        
        print(f"[calc] Converted to UTC: {utc_year}-{utc_month:02d}-{utc_day:02d} {int(utc_hour):02d}:{utc_minute:05.2f}")
        
        # Calculate Julian Day using UTC time
        julian_day = calculate_julian_day(utc_year, utc_month, utc_day, utc_hour, utc_minute)
        print(f"[calc] Julian Day: {julian_day:.6f}")
        
        # Calculate houses first (needed for planet house placement)
        houses_data = calculate_houses(julian_day, latitude, longitude)
        if not houses_data:
            return jsonify({'error': 'Failed to calculate houses'}), 500
        
        print(f"[calc] Houses calculated successfully")
        
        # Calculate planets with house placement
        planets = {}
        failed_planets = []
        north_node_position = None  # Store for calculating South Node
        
        for planet_key, planet_id in PLANETS.items():
            # Skip south_node for now, calculate after north_node
            if planet_key == 'south_node':
                continue
                
            position = calculate_planet_position(julian_day, planet_id, body_key=planet_key)
            if position:
                # Add house placement
                house_num = get_house_for_planet(position['longitude'], houses_data['houses'])
                planets[planet_key] = {
                    'name': PLANET_NAMES[planet_key],
                    'house': house_num,
                    **position
                }
                # Store north node position for south node calculation
                if planet_key == 'north_node':
                    north_node_position = position
            else:
                failed_planets.append(planet_key)
                print(f"[calc] WARNING: Failed to calculate {planet_key}")
        
        # Calculate South Node as opposite of North Node (180° apart)
        if north_node_position:
            south_lon = (north_node_position['longitude'] + 180) % 360
            south_sign_info = get_sign(south_lon)
            south_house = get_house_for_planet(south_lon, houses_data['houses'])
            planets['south_node'] = {
                'name': PLANET_NAMES['south_node'],
                'house': south_house,
                'longitude': round(south_lon, 6),
                'latitude': round(-north_node_position['latitude'], 6),  # Opposite latitude
                'distance': north_node_position['distance'],
                'speed': north_node_position['speed'],  # Same speed as north node
                'retrograde': north_node_position.get('retrograde', False),
                'degree_dms': dms_of(south_sign_info),
                **south_sign_info
            }
        
        print(f"[calc] Calculated {len(planets)}/{len(PLANETS)} planets successfully")
        if failed_planets:
            print(f"[calc] FAILED planets: {failed_planets}")

        # Fase 0: un cuerpo obligatorio (en especial Quirón) no puede desaparecer
        # en silencio y dejar una carta incompleta.
        assert_required_bodies(planets.keys())

        
        # Calculate aspects (including to angles)
        aspects = calculate_aspects(
            planets, 
            ascendant_lon=houses_data['ascendant']['longitude'],
            mc_lon=houses_data['mc']['longitude']
        )
        print(f"[calc] Calculated {len(aspects)} aspects")
        
        # Prepare base response
        chart_data = {
            'birthInfo': {
                'date': birth_date,
                'time': birth_time,
                'latitude': latitude,
                'longitude': longitude,
                'timezone': timezone,
                'julianDay': round(julian_day, 6),
                'utcTime': f"{utc_year}-{utc_month:02d}-{utc_day:02d} {int(utc_hour):02d}:{int(utc_minute):02d} UT"
            },
            'planets': planets,
            'houses': houses_data['houses'],
            'ascendant': houses_data['ascendant'],
            'mc': houses_data['mc'],
            'vertex': houses_data['vertex'],
            'aspects': aspects,
            'calculatedAt': datetime.utcnow().isoformat() + 'Z',
            'precision': 'high',
            'ephemeris': 'Swiss Ephemeris',
            # Fase 0: trazabilidad del motor que produjo realmente cada posición.
            'provenance': {
                'policy': ARETE_ASTRO_POLICY,
                'ephePath': EPHE_PATH,
                'swissephVersion': getattr(swe, 'version', 'unknown'),
                'requestedFlags': int(REQUESTED_FLAGS),
                'engine': _effective_engine_of(planets),
                'nodeConvention': ARETE_ASTRO_POLICY['node'],
                'orbPolicy': ORB_POLICY,
                'houseSystem': houses_data.get('houseSystem'),
                'bodies': {
                    k: v.get('provenance')
                    for k, v in planets.items()
                    if isinstance(v, dict) and v.get('provenance')
                },
            }
        }

        
        natal_points = build_natal_points(planets, houses_data)

        # Progresiones secundarias (Sol, Luna, Mercurio, Venus y Marte) con sus
        # aspectos a la carta natal. `progressedMoon` se deriva de aquí.
        if include_progressions:
            current_date = datetime.utcnow().strftime('%Y-%m-%d')
            progressions = calculate_secondary_progressions(julian_day, current_date, natal_points)
            if progressions:
                chart_data['secondaryProgressions'] = progressions
                progressed_moon = progressed_moon_from(progressions)
                if progressed_moon:
                    chart_data['progressedMoon'] = progressed_moon
                    print(f"[calc] Progressed Moon: {progressed_moon['sign']} {progressed_moon['degree_dms']}")
        
        # Calculate Solar Return for specified year
        if include_solar_return and planets.get('sun'):
            natal_sun_longitude = planets['sun']['longitude']
            solar_return = calculate_solar_return(
                julian_day,
                natal_sun_longitude,
                int(sr_year),
                float(sr_latitude),
                float(sr_longitude),
                natal_points,
            )
            if solar_return:
                chart_data['solarReturn'] = solar_return
                print(f"[calc] Solar Return {sr_year}: ASC {solar_return['ascendant']['sign']}")
        
        return jsonify({'success': True, 'chartData': chart_data})
        
    except TimezoneResolutionError as e:
        print(f"[calc] ERROR zona horaria: {e}")
        return jsonify({'error': str(e), 'code': 'timezone_unresolved'}), 400
    except HouseSystemUnavailableError as e:
        print(f"[calc] ERROR sistema de casas: {e}")
        return jsonify({'error': str(e), 'code': 'house_system_unavailable'}), 422
    except HouseCalculationError as e:
        print(f"[calc] ERROR cálculo de casas: {e}")
        return jsonify({'error': str(e), 'code': 'house_calculation_failed'}), 503
    except HousePlacementError as e:
        print(f"[calc] ERROR posición en casas: {e}")
        return jsonify({'error': str(e), 'code': 'house_placement_failed'}), 500
    except SolarReturnSearchError as e:
        print(f"[calc] ERROR retorno solar: {e}")
        return jsonify({'error': str(e), 'code': 'solar_return_search_failed'}), 500
    except EphemerisEngineError as e:
        print(f"[calc] ERROR motor de efemérides: {e}")
        return jsonify({'error': str(e), 'code': 'ephemeris_engine_mismatch'}), 503
    except BodyCalculationError as e:
        print(f"[calc] ERROR cuerpo obligatorio: {e}")
        return jsonify({'error': str(e), 'code': 'required_body_missing'}), 503
    except Exception as e:
        print(f"[calc] ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"[server] Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)