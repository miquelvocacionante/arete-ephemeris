"""
Tests de progresiones secundarias con una efeméride lunar sintética.

La Luna progresada avanza ~12,2° por año, pero ese valor medio no puede
presentarse como el próximo cambio de signo real: aquí se comprueba que el
cambio se busca con el motor.
"""

import unittest

from progressions import (
    PROGRESSED_ASCENDANT_SUPPORTED,
    find_next_sign_change,
    next_sign_boundary,
    years_to_sign_change,
)

START_JD = 2451545.0


def make_moon(start_longitude, speed_per_day):
    def longitude_at(jd):
        return (start_longitude + (jd - START_JD) * speed_per_day) % 360.0

    return longitude_at


class SignBoundaryTest(unittest.TestCase):
    def test_boundary_of_each_sign(self):
        self.assertEqual(next_sign_boundary(0.0), 30.0)
        self.assertEqual(next_sign_boundary(151.5667), 180.0)
        self.assertEqual(next_sign_boundary(345.0), 0.0)


class NextSignChangeTest(unittest.TestCase):
    def test_finds_exact_crossing(self):
        # 10° de Virgo (160°), a 12°/año: faltan 20° -> ~1,667 años.
        moon = make_moon(160.0, 12.0)
        years = years_to_sign_change(moon, START_JD)
        self.assertAlmostEqual(years, 20.0 / 12.0, places=2)

    def test_crossing_into_aries(self):
        moon = make_moon(355.0, 12.0)
        years = years_to_sign_change(moon, START_JD)
        self.assertAlmostEqual(years, 5.0 / 12.0, places=2)

    def test_returns_none_when_out_of_window(self):
        # Movimiento casi nulo: el cambio no ocurre dentro de la ventana.
        self.assertIsNone(years_to_sign_change(make_moon(10.0, 0.0001), START_JD))

    def test_exact_cusp_looks_for_the_following_boundary(self):
        # Justo en 0° de Tauro (30°), el próximo cambio es 60°: 30° a 12°/año.
        change_jd = find_next_sign_change(make_moon(30.0, 12.0), START_JD)
        self.assertAlmostEqual(change_jd - START_JD, 2.5, places=3)


class ProgressedAscendantTest(unittest.TestCase):
    def test_not_supported(self):
        # No hay convención única validada: no se calcula.
        self.assertFalse(PROGRESSED_ASCENDANT_SUPPORTED)


if __name__ == '__main__':
    unittest.main(verbosity=2)