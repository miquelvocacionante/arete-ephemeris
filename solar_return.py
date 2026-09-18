"""
Retorno solar: búsqueda del instante exacto (Fase 2).

Módulo puro e inyectable: no importa swisseph, así que puede probarse con una
efeméride solar sintética.

Por qué no basta una bisección de un año entero: la diferencia angular entre el
Sol y su posición natal es discontinua (salta de +180 a -180 una vez al año).
Bisecar sobre esa discontinuidad puede converger al punto equivocado, y ahí
estaba el riesgo real para los cumpleaños de principios de enero, cuyo retorno
puede caer en el 31 de diciembre del año anterior o en el 1 de enero siguiente.

Aquí se hace lo contrario: se parte de la fecha aproximada del cumpleaños en el
año pedido y se busca el cruce en una ventana pequeña donde la función es
continua y monótona (el Sol avanza ~0,9856°/día).
"""

MAX_BRACKET_DAYS = 6.0
BRACKET_STEP_DAYS = 0.5
BISECTION_ITERATIONS = 60
# Tolerancia de convergencia en días (~0,09 segundos de tiempo).
CONVERGENCE_DAYS = 1e-6


class SolarReturnSearchError(RuntimeError):
    """No se ha podido acotar el retorno solar alrededor del cumpleaños."""


def signed_difference(longitude, target):
    """Diferencia angular con signo en (-180, 180]."""
    diff = (longitude - target) % 360.0
    if diff > 180.0:
        diff -= 360.0
    return diff


def approximate_return_jd(julday, birth_month, birth_day, target_year, hour=0.0):
    """
    Día juliano aproximado del cumpleaños en el año pedido.

    El 29 de febrero se ancla al 28 en años no bisiestos: la ventana de búsqueda
    es de varios días, así que el retorno real se encuentra igual.
    """
    day = birth_day
    if birth_month == 2 and birth_day == 29 and not _is_leap(target_year):
        day = 28
    return julday(target_year, birth_month, day, hour)


def _is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def find_solar_return_jd(sun_longitude_at, approx_jd, target_longitude):
    """
    Instante exacto en que el Sol vuelve a `target_longitude`, cerca de `approx_jd`.

    Args:
        sun_longitude_at: callable(jd) -> longitud eclíptica del Sol (0-360).
        approx_jd: día juliano aproximado del cumpleaños en el año objetivo.
        target_longitude: longitud del Sol natal.

    Returns:
        Día juliano del retorno.

    Raises:
        SolarReturnSearchError si no hay cruce en la ventana de búsqueda.
    """

    def f(jd):
        return signed_difference(sun_longitude_at(jd), target_longitude)

    low, high = _bracket(f, approx_jd)
    f_low = f(low)

    for _ in range(BISECTION_ITERATIONS):
        if high - low < CONVERGENCE_DAYS:
            break
        mid = (low + high) / 2.0
        f_mid = f(mid)
        if f_mid == 0.0:
            return mid
        if (f_low < 0.0) == (f_mid < 0.0):
            low, f_low = mid, f_mid
        else:
            high = mid

    return (low + high) / 2.0


def _bracket(f, center):
    """Ventana [low, high] con cambio de signo, expandida a pasos desde el centro."""
    previous_jd = center - MAX_BRACKET_DAYS
    previous = f(previous_jd)
    steps = int(2 * MAX_BRACKET_DAYS / BRACKET_STEP_DAYS)

    for i in range(1, steps + 1):
        current_jd = center - MAX_BRACKET_DAYS + i * BRACKET_STEP_DAYS
        current = f(current_jd)
        if current == 0.0:
            return current_jd, current_jd
        # Solo aceptamos cruces de signo "pequeños": un salto de +180 a -180 no
        # es un retorno, es la discontinuidad de la función angular.
        if (previous < 0.0) != (current < 0.0) and abs(current - previous) < 90.0:
            return previous_jd, current_jd
        previous_jd, previous = current_jd, current

    raise SolarReturnSearchError(
        "No se ha encontrado el retorno solar en la ventana de "
        f"±{MAX_BRACKET_DAYS} días alrededor del cumpleaños (JD {center})."
    )