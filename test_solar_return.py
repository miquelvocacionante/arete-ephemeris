"""
Tests del retorno solar con una efeméride solar sintética (sin Swiss real).

El Sol avanza ~0,9856°/día. La efeméride sintética usa esa velocidad media
partiendo de una longitud conocida, lo que basta para comprobar que el
algoritmo elige el retorno del año pedido y no el de diciembre anterior.
"""

import unittest

from solar_return import (
    SolarReturnSearchError,
    approximate_return_jd,
    find_solar_return_jd,
    signed_difference,
)

TROPICAL_YEAR_DAYS = 365.2422
SUN_SPEED = 360.0 / TROPICAL_YEAR_DAYS


def julday(year, month, day, hour=0.0):
    """Día juliano civil (Fliegel-Van Flandern), suficiente para los tests."""
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    jdn = day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    return jdn + (hour - 12.0) / 24.0


def make_sun(reference_jd, reference_longitude):
    def sun_longitude_at(jd):
        return (reference_longitude + (jd - reference_jd) * SUN_SPEED) % 360.0

    return sun_longitude_at


class SignedDifferenceTest(unittest.TestCase):
    def test_wrap_around_zero(self):
        self.assertAlmostEqual(signed_difference(359.0, 1.0), -2.0)
        self.assertAlmostEqual(signed_difference(1.0, 359.0), 2.0)


class ApproximateReturnTest(unittest.TestCase):
    def test_feb_29_in_non_leap_year_anchors_to_28(self):
        jd = approximate_return_jd(julday, 2, 29, 2027, 12.0)
        self.assertAlmostEqual(jd, julday(2027, 2, 28, 12.0))

    def test_feb_29_in_leap_year_kept(self):
        jd = approximate_return_jd(julday, 2, 29, 2028, 12.0)
        self.assertAlmostEqual(jd, julday(2028, 2, 29, 12.0))


class FindSolarReturnTest(unittest.TestCase):
    def _assert_return(self, birth_year, month, day, target_year, birth_hour=6.0):
        birth_jd = julday(birth_year, month, day, birth_hour)
        natal_longitude = 123.456
        sun = make_sun(birth_jd, natal_longitude)

        approx = approximate_return_jd(julday, month, day, target_year, 12.0)
        sr_jd = find_solar_return_jd(sun, approx, natal_longitude)

        self.assertAlmostEqual(signed_difference(sun(sr_jd), natal_longitude), 0.0, places=4)
        # El retorno debe caer cerca del cumpleaños del año pedido, nunca a
        # meses de distancia.
        self.assertLess(abs(sr_jd - approx), 3.0)
        return sr_jd

    def test_january_first_birthday(self):
        self._assert_return(1980, 1, 1, 2026)

    def test_january_second_birthday(self):
        self._assert_return(1980, 1, 2, 2026)

    def test_december_thirty_first_birthday(self):
        self._assert_return(1980, 12, 31, 2026)

    def test_february_29_birthday_in_non_leap_year(self):
        self._assert_return(1980, 2, 29, 2027)

    def test_regular_september_birthday(self):
        self._assert_return(1985, 9, 15, 2026)

    def test_natal_longitude_crossing_zero_aries(self):
        birth_jd = julday(1980, 3, 20, 10.0)
        natal_longitude = 359.9
        sun = make_sun(birth_jd, natal_longitude)
        approx = approximate_return_jd(julday, 3, 20, 2026, 12.0)
        sr_jd = find_solar_return_jd(sun, approx, natal_longitude)
        self.assertAlmostEqual(signed_difference(sun(sr_jd), natal_longitude), 0.0, places=4)

    def test_no_crossing_raises(self):
        # Sol inmóvil lejos del objetivo: no hay retorno que encontrar.
        with self.assertRaises(SolarReturnSearchError):
            find_solar_return_jd(lambda jd: 10.0, julday(2026, 5, 1, 12.0), 200.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)