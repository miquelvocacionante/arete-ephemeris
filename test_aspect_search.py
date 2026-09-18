"""Pruebas de las funciones puras de búsqueda de perfecciones (sin efemérides)."""

import unittest
from datetime import datetime, timedelta

from aspect_search import (
    find_aspect_passes,
    dedupe_passes,
    find_crossings,
    signed_offset,
    normalize_aspect,
    normalize_transit_planet,
    sample_dates,
    target_angles,
    validate_window,
)


class NormalizationTests(unittest.TestCase):
    def test_planetas_en_espanol_y_con_acentos(self):
        self.assertEqual(normalize_transit_planet('Saturno'), 'saturn')
        self.assertEqual(normalize_transit_planet('Plutón'), 'pluto')
        self.assertEqual(normalize_transit_planet('jupiter'), 'jupiter')
        self.assertIsNone(normalize_transit_planet('Quirón'))
        self.assertIsNone(normalize_transit_planet(''))

    def test_aspectos(self):
        self.assertEqual(normalize_aspect('Conjunción'), 'conjunction')
        self.assertEqual(normalize_aspect('trigono'), 'trine')
        self.assertIsNone(normalize_aspect('quincuncio'))

    def test_angulos_objetivo(self):
        self.assertEqual(target_angles('conjunction'), [0.0])
        self.assertEqual(target_angles('opposition'), [180.0])
        self.assertEqual(target_angles('square'), [90.0, -90.0])


class WindowTests(unittest.TestCase):
    def test_ventana_valida(self):
        start, end, error = validate_window('2026-01-01', '2031-01-01')
        self.assertIsNone(error)
        self.assertEqual(start, datetime(2026, 1, 1))
        self.assertEqual(end, datetime(2031, 1, 1))

    def test_rangos_invalidos(self):
        self.assertIsNotNone(validate_window('2026-01-01', '2025-01-01')[2])
        self.assertIsNotNone(validate_window('2026-01-01', '2060-01-01')[2])
        self.assertIsNotNone(validate_window('ayer', '2027-01-01')[2])


class DedupeTests(unittest.TestCase):
    def test_ordena_numera_y_elimina_duplicados(self):
        hits = [
            {'exactDate': '2027-06-10'},
            {'exactDate': '2026-03-02'},
            {'exactDate': '2026-03-02'},
            {'exactDate': '2026-11-20'},
        ]
        result = dedupe_passes(hits)
        self.assertEqual([h['exactDate'] for h in result],
                         ['2026-03-02', '2026-11-20', '2027-06-10'])
        self.assertEqual([h['passNumber'] for h in result], [1, 2, 3])

    def test_conserva_las_tres_pasadas_por_retrogradacion(self):
        hits = [
            {'exactDate': '2027-02-14'},
            {'exactDate': '2027-07-30'},
            {'exactDate': '2027-12-05'},
        ]
        self.assertEqual(len(dedupe_passes(hits)), 3)


class SampleDatesTests(unittest.TestCase):
    def test_incluye_el_extremo_final(self):
        dates = sample_dates(datetime(2026, 1, 1), datetime(2026, 1, 10), 4)
        self.assertEqual(dates[0], datetime(2026, 1, 1))
        self.assertEqual(dates[-1], datetime(2026, 1, 10))


class CrossingTests(unittest.TestCase):
    def test_detecta_tres_pasadas_por_retrogradacion(self):
        # Longitud que avanza, retrograda y vuelve a avanzar sobre el punto natal.
        offsets = [-3, -2, -1, 1, 2, 1, -1, -2, -1, 1, 2, 3]
        dates = [datetime(2027, 1, 1) + timedelta(days=10 * i) for i in range(len(offsets))]
        by_date = dict(zip(dates, offsets))
        crossings = find_crossings(dates, lambda d: by_date[d])
        self.assertEqual(len(crossings), 3)

    def test_ignora_el_salto_de_envoltorio(self):
        dates = [datetime(2027, 1, 1), datetime(2027, 1, 11)]
        by_date = {dates[0]: 179.5, dates[1]: -179.5}
        self.assertEqual(find_crossings(dates, lambda d: by_date[d]), [])

    def test_offset_con_signo_cruza_cero_en_la_perfeccion(self):
        self.assertAlmostEqual(signed_offset(100.0, 100.0, 0.0), 0.0)
        self.assertAlmostEqual(signed_offset(280.0, 100.0, 180.0), 0.0)
        self.assertAlmostEqual(signed_offset(99.0, 100.0, 0.0), -1.0)


class TestMotorPuroDeBusqueda(unittest.TestCase):
    """Pruebas del algoritmo sin Swiss Ephemeris: la posición se inyecta."""

    START = datetime(2027, 1, 1)

    def _run(self, longitude_of, natal, aspect, days=120, step=1.0):
        def state_at(moment):
            t = (moment - self.START).total_seconds() / 86400.0
            lon = longitude_of(t)
            nxt = longitude_of(t + 0.01)
            speed = (((nxt - lon + 180.0) % 360.0) - 180.0) / 0.01
            return lon % 360.0, speed
        return find_aspect_passes(
            state_at, natal, aspect, self.START,
            self.START + timedelta(days=days), step,
        )

    def test_trayectoria_monotona_una_raiz(self):
        passes = self._run(lambda t: 90.0 + t, natal=100.0, aspect='conjunction')
        self.assertEqual(len(passes), 1)
        self.assertIn(passes[0]['exactDate'], ('2027-01-10', '2027-01-11'))
        self.assertFalse(passes[0]['retrograde'])
        self.assertEqual(passes[0]['passNumber'], 1)

    def test_tres_pasadas_por_retrogradacion(self):
        # Directa hasta 105, retrógrada hasta 95 y de nuevo directa: cruza 100 tres veces.
        def longitude_of(t):
            if t <= 30:
                return 90.0 + 0.5 * t          # 90 -> 105
            if t <= 70:
                return 105.0 - 0.25 * (t - 30)  # 105 -> 95
            return 95.0 + 0.5 * (t - 70)        # 95 -> 125

        passes = self._run(longitude_of, natal=100.0, aspect='conjunction')
        self.assertEqual(len(passes), 3)
        dates = [p['exactDate'] for p in passes]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual([p['passNumber'] for p in passes], [1, 2, 3])
        self.assertEqual([p['retrograde'] for p in passes], [False, True, False])

    def test_envoltorio_no_genera_raiz_falsa(self):
        # Movimiento rápido y continuo: solo hay perfecciones reales, sin falsos
        # cruces al pasar el offset de +180 a -180.
        passes = self._run(lambda t: 10.0 * t, natal=0.0, aspect='conjunction', days=100, step=1.0)
        self.assertEqual(len(passes), 2)  # solo 360 y 720 grados dentro de la ventana
        for p in passes:
            self.assertLess(p['orb'], 0.01)

    def test_cuadratura_detecta_ambas_configuraciones_sin_duplicar(self):
        passes = self._run(lambda t: 3.0 * t, natal=0.0, aspect='square', days=120, step=1.0)
        # Una vuelta completa: +90 y -90 (270) se perfeccionan una vez cada una.
        self.assertEqual(len(passes), 2)
        self.assertEqual(len({p['exactDate'] for p in passes}), 2)
        self.assertEqual([p['passNumber'] for p in passes], [1, 2])

    def test_refinado_converge_dentro_de_la_tolerancia(self):
        # Raíz analítica: 90 + t = 100 -> t = 10 días exactos desde el inicio.
        passes = self._run(lambda t: 90.0 + t, natal=100.0, aspect='conjunction')
        # Tolerancia documentada: 60 s -> orbe muy por debajo de 0,001 grados.
        self.assertLess(passes[0]['orb'], 0.001)


if __name__ == '__main__':
    unittest.main()