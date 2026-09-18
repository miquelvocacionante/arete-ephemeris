"""
Progresiones secundarias: utilidades deterministas (Fase 2).

Módulo puro e inyectable: no importa swisseph. Aquí vive la búsqueda del
próximo cambio de signo, que antes se estimaba con una velocidad media fija de
12,2°/año y se presentaba como si fuese una fecha calculada.

Convención de tiempo: en progresiones secundarias un día después del nacimiento
equivale a un año de vida, así que un día de día juliano progresado es un año.
"""

SIGN_ARC = 30.0
DEFAULT_STEP_DAYS = 0.25
DEFAULT_MAX_DAYS = 40.0
BISECTION_ITERATIONS = 60
CONVERGENCE_DAYS = 1e-6

# El Ascendente progresado NO está soportado: existen varias convenciones
# (arco solar, arco de ascensión recta, naibod...) y ninguna la decide el motor.
# Preferimos declararlo no soportado antes que inventar una precisión falsa.
PROGRESSED_ASCENDANT_SUPPORTED = False


def signed_difference(longitude, target):
    """Diferencia angular con signo en (-180, 180]."""
    diff = (longitude - target) % 360.0
    if diff > 180.0:
        diff -= 360.0
    return diff


def next_sign_boundary(longitude):
    """Longitud absoluta del siguiente inicio de signo."""
    return ((int(longitude % 360.0 // SIGN_ARC) + 1) * SIGN_ARC) % 360.0


def find_next_sign_change(
    longitude_at,
    start_jd,
    step_days=DEFAULT_STEP_DAYS,
    max_days=DEFAULT_MAX_DAYS,
):
    """
    Día juliano progresado del próximo cambio de signo, o None si no ocurre
    dentro de la ventana.

    Args:
        longitude_at: callable(jd) -> longitud eclíptica (0-360).
        start_jd: día juliano progresado de partida.
    """
    boundary = next_sign_boundary(longitude_at(start_jd))

    def f(jd):
        return signed_difference(longitude_at(jd), boundary)

    previous_jd = start_jd
    previous = f(previous_jd)
    if previous >= 0.0:
        # Ya está en el signo siguiente (o justo en la cúspide): nada que buscar.
        return start_jd

    steps = int(max_days / step_days)
    for i in range(1, steps + 1):
        current_jd = start_jd + i * step_days
        current = f(current_jd)
        if current >= 0.0 and abs(current - previous) < 90.0:
            return _bisect(f, previous_jd, current_jd)
        previous_jd, previous = current_jd, current

    return None


def years_to_sign_change(longitude_at, progressed_jd, **kwargs):
    """
    Años hasta el próximo cambio de signo, calculados con el motor.

    Devuelve None cuando no puede determinarse: mejor omitir el dato que
    presentar una media como si fuese la fecha real.
    """
    change_jd = find_next_sign_change(longitude_at, progressed_jd, **kwargs)
    if change_jd is None:
        return None
    return round(change_jd - progressed_jd, 3)


def _bisect(f, low, high):
    for _ in range(BISECTION_ITERATIONS):
        if high - low < CONVERGENCE_DAYS:
            break
        mid = (low + high) / 2.0
        if f(mid) < 0.0:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0