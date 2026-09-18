"""Funciones puras de la búsqueda de perfecciones de aspecto (Fase B).

Este módulo NO importa Swiss Ephemeris a propósito: contiene solo validación,
normalización, ventana temporal y deduplicación, de modo que pueda probarse sin
efemérides instaladas. El barrido astronómico vive en app.py.
"""

from datetime import datetime, timedelta
import unicodedata

TRANSIT_PLANET_ALIASES = {
    'sun': 'sun', 'sol': 'sun',
    'moon': 'moon', 'luna': 'moon',
    'mercury': 'mercury', 'mercurio': 'mercury',
    'venus': 'venus',
    'mars': 'mars', 'marte': 'mars',
    'jupiter': 'jupiter',
    'saturn': 'saturn', 'saturno': 'saturn',
    'uranus': 'uranus', 'urano': 'uranus',
    'neptune': 'neptune', 'neptuno': 'neptune',
    'pluto': 'pluto', 'pluton': 'pluto',
}

ASPECT_ALIASES = {
    'conjunction': 'conjunction', 'conjuncion': 'conjunction',
    'opposition': 'opposition', 'oposicion': 'opposition',
    'square': 'square', 'cuadratura': 'square',
    'trine': 'trine', 'trigono': 'trine',
    'sextile': 'sextile', 'sextil': 'sextile',
}

ASPECT_ANGLES = {
    'conjunction': 0.0,
    'opposition': 180.0,
    'square': 90.0,
    'trine': 120.0,
    'sextile': 60.0,
}

ASPECT_NAMES_ES = {
    'conjunction': 'Conjunción',
    'opposition': 'Oposición',
    'square': 'Cuadratura',
    'trine': 'Trígono',
    'sextile': 'Sextil',
}

MAX_WINDOW_DAYS = 20 * 366
MIN_DAYS_BETWEEN_PASSES = 2
REFINE_TOLERANCE_SECONDS = 60



def _slug(value):
    text = unicodedata.normalize('NFD', str(value or '').strip().lower())
    return ''.join(c for c in text if unicodedata.category(c) != 'Mn')


def normalize_transit_planet(value):
    """Devuelve la clave canónica del planeta en tránsito, o None."""
    return TRANSIT_PLANET_ALIASES.get(_slug(value))


def normalize_aspect(value):
    """Devuelve la clave canónica del aspecto, o None."""
    return ASPECT_ALIASES.get(_slug(value))


def target_angles(aspect_key):
    """Ángulos relativos que hay que cruzar para perfeccionar el aspecto."""
    angle = ASPECT_ANGLES[aspect_key]
    if angle in (0.0, 180.0):
        return [angle]
    return [angle, -angle]


def parse_iso_date(value):
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d')
    except (ValueError, TypeError):
        return None


def validate_window(start_date, end_date):
    """Valida la ventana. Devuelve (start, end, error)."""
    start = parse_iso_date(start_date)
    end = parse_iso_date(end_date)
    if not start or not end:
        return None, None, 'startDate y endDate deben tener formato YYYY-MM-DD'
    if end <= start:
        return None, None, 'endDate debe ser posterior a startDate'
    if (end - start).days > MAX_WINDOW_DAYS:
        return None, None, 'La ventana no puede superar 20 años'
    if start.year < 1900 or end.year > 2100:
        return None, None, 'Las fechas deben estar entre 1900 y 2100'
    return start, end, None


def dedupe_passes(hits, min_days=MIN_DAYS_BETWEEN_PASSES):
    """Ordena por fecha y elimina pasadas repetidas (mismo cruce detectado dos veces)."""
    ordered = sorted([h for h in hits if h.get('exactDate')], key=lambda h: h['exactDate'])
    result = []
    for hit in ordered:
        current = parse_iso_date(hit['exactDate'])
        if result:
            previous = parse_iso_date(result[-1]['exactDate'])
            if current and previous and abs((current - previous).days) < min_days:
                continue
        result.append(hit)
    for index, hit in enumerate(result, start=1):
        hit['passNumber'] = index
    return result


def sample_dates(start, end, step_days):
    """Fechas de muestreo inclusivas del extremo final."""
    dates = []
    current = start
    while current < end:
        dates.append(current)
        current = current + timedelta(days=step_days)
    dates.append(end)
    return dates


def signed_offset(longitude, natal_longitude, target_angle):
    """Distancia con signo al aspecto exacto; cruza cero justo en la perfección."""
    return ((longitude - natal_longitude - target_angle + 180.0) % 360.0) - 180.0


def find_crossings(dates, offset_at):
    """Pares (anterior, siguiente) de muestras entre las que el aspecto se perfecciona.

    `offset_at` recibe una fecha y devuelve la distancia con signo al aspecto.
    Un salto de 180 grados es el envoltorio del ángulo, no una perfección.
    """
    crossings = []
    if not dates:
        return crossings
    previous = dates[0]
    previous_offset = offset_at(previous)
    for current in dates[1:]:
        current_offset = offset_at(current)
        changed_sign = (current_offset >= 0) != (previous_offset >= 0)
        if changed_sign and abs(current_offset - previous_offset) < 180.0:
            crossings.append((previous, current))
        previous, previous_offset = current, current_offset
    return crossings


def refine_crossing(offset_at, low, high, tolerance_seconds=REFINE_TOLERANCE_SECONDS):
    """Bisección sobre el intervalo con cambio de signo.

    Converge hasta que el intervalo dura menos de `tolerance_seconds`
    (por defecto 60 s) y devuelve su punto medio.
    """
    f_low = offset_at(low)
    while (high - low).total_seconds() > tolerance_seconds:
        mid = low + (high - low) / 2
        f_mid = offset_at(mid)
        if (f_mid >= 0) == (f_low >= 0):
            low, f_low = mid, f_mid
        else:
            high = mid
    return low + (high - low) / 2


def find_aspect_passes(
    state_at,
    natal_longitude,
    aspect_key,
    start,
    end,
    step_days,
    tolerance_seconds=REFINE_TOLERANCE_SECONDS,
):
    """Motor puro de búsqueda de perfecciones.

    `state_at(datetime)` debe devolver `(longitud_eclíptica, velocidad_diaria)`.
    No depende de Swiss Ephemeris: el adaptador astronómico se inyecta.
    Devuelve las pasadas ordenadas y deduplicadas.
    """
    dates = sample_dates(start, end, step_days)
    hits = []
    for target_angle in target_angles(aspect_key):
        def offset_at(moment, angle=target_angle):
            longitude, _speed = state_at(moment)
            return signed_offset(longitude, natal_longitude, angle)

        for previous, current in find_crossings(dates, offset_at):
            exact = refine_crossing(offset_at, previous, current, tolerance_seconds)
            longitude, speed = state_at(exact)
            hits.append({
                'exactDate': exact.strftime('%Y-%m-%d'),
                'orb': round(abs(signed_offset(longitude, natal_longitude, target_angle)), 4),
                'transitLongitude': round(longitude % 360.0, 6),
                'retrograde': speed < 0,
            })
    return dedupe_passes(hits)