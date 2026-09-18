"""
Pruebas matemáticas de los aspectos entre cartas (Fase 2).

Puras: no requieren swisseph ni ficheros de efemérides.
Ejecutar: python3 python-ephemeris/test_cross_aspects.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cross_aspects import (  # noqa: E402
    PROGRESSION_ORBS,
    TRANSIT_ORBS,
    angular_separation,
    calculate_cross_aspects,
    classify_aspect,
)

failures = []


def check(label, condition):
    if condition:
        print(f"  ok  {label}")
    else:
        failures.append(label)
        print(f"FAIL  {label}")


print("\n== Separación angular ==")
check("mismo punto", angular_separation(10, 10) == 0)
check("cruce 359/0", abs(angular_separation(359.0, 1.0) - 2.0) < 1e-9)
check("cruce 0/359 simétrico", abs(angular_separation(1.0, 359.0) - 2.0) < 1e-9)
check("máximo 180", abs(angular_separation(0.0, 180.0) - 180.0) < 1e-9)
check("nunca supera 180", angular_separation(0.0, 200.0) == 160.0)
check("normaliza fuera de rango", abs(angular_separation(720.0 + 10.0, 10.0)) < 1e-9)
check("negativos normalizados", abs(angular_separation(-1.0, 1.0) - 2.0) < 1e-9)

print("\n== Caso Marta Alí: Luna progresada 151°34' vs Quirón natal 91°22' ==")
LUNA_PROGRESADA = 151 + 34 / 60.0   # Virgo 1°34'
QUIRON_NATAL = 91 + 22 / 60.0       # Cáncer 1°22'
separacion = angular_separation(LUNA_PROGRESADA, QUIRON_NATAL)
check("separación 60°12'", abs(separacion - (60 + 12 / 60.0)) < 1e-9)

marta = classify_aspect(LUNA_PROGRESADA, QUIRON_NATAL, PROGRESSION_ORBS)
check("existe aspecto", marta is not None)
check("es sextil, NUNCA conjunción", marta["aspectKey"] == "sextile")
check("orbe 0°12' (0.2°)", abs(marta["orb"] - 0.2) < 0.01)

print("\n== Tipos de aspecto ==")
check("oposición exacta", classify_aspect(10.0, 190.0, PROGRESSION_ORBS)["aspectKey"] == "opposition")
check("cuadratura exacta", classify_aspect(10.0, 100.0, PROGRESSION_ORBS)["aspectKey"] == "square")
check("trígono exacto", classify_aspect(10.0, 130.0, PROGRESSION_ORBS)["aspectKey"] == "trine")
check("sextil exacto", classify_aspect(10.0, 70.0, PROGRESSION_ORBS)["aspectKey"] == "sextile")

conj_cruzando_signo = classify_aspect(359.5, 0.3, PROGRESSION_ORBS)
check("conjunción cruzando 0° Aries", conj_cruzando_signo["aspectKey"] == "conjunction")
check("orbe de ese cruce 0.8°", abs(conj_cruzando_signo["orb"] - 0.8) < 1e-6)

conj_cruzando_signo_2 = classify_aspect(29.7, 30.4, PROGRESSION_ORBS)
check("conjunción entre signos contiguos", conj_cruzando_signo_2["aspectKey"] == "conjunction")

print("\n== Límites de orbe ==")
check("dentro del orbe (1.0°)", classify_aspect(10.0, 71.0, PROGRESSION_ORBS) is not None)
check("fuera del orbe (1.01°)", classify_aspect(10.0, 71.01, PROGRESSION_ORBS) is None)
check("mismo grado dentro del signo pero 60° de separación: no es conjunción",
      classify_aspect(151.5667, 91.3667, PROGRESSION_ORBS)["aspectKey"] != "conjunction")
check("posiciones sin relación no dan aspecto",
      classify_aspect(10.0, 55.0, PROGRESSION_ORBS) is None)

print("\n== Aspecto más ceñido cuando hay empate posible ==")
ceñido = classify_aspect(0.0, 89.6, {"square": 1.0, "conjunction": 1.0})
check("elige la cuadratura", ceñido["aspectKey"] == "square")

print("\n== calculate_cross_aspects ==")
progresadas = {"moon": {"name": "Luna Progresada", "longitude": LUNA_PROGRESADA}}
natal = {
    "chiron": {"name": "Quirón", "longitude": QUIRON_NATAL},
    "sun": {"name": "Sol", "longitude": 200.0},
}
cruzados = calculate_cross_aspects(progresadas, natal, PROGRESSION_ORBS, source_suffix="progresada")
check("un único aspecto detectado", len(cruzados) == 1)
check("etiqueta de origen", cruzados[0]["sourcePoint"] == "Luna Progresada progresada")
check("etiqueta de destino", cruzados[0]["targetPoint"] == "Quirón natal")
check("sextil en el resultado", cruzados[0]["aspect"] == "Sextil")
check("longitudes absolutas presentes", cruzados[0]["sourceLongitude"] > 0 and cruzados[0]["targetLongitude"] > 0)

print("\n== Orbes por cuerpo (RS -> natal reutiliza tránsitos) ==")
rs = {"saturn": {"name": "Saturno", "longitude": 100.0}, "moon": {"name": "Luna", "longitude": 100.0}}
objetivo = {"venus": {"name": "Venus", "longitude": 103.0}}
por_cuerpo = calculate_cross_aspects(rs, objetivo, TRANSIT_ORBS, source_suffix="RS")
claves = {a["sourceKey"] for a in por_cuerpo}
check("Saturno (orbe 4°) sí aspecta a 3°", "saturn" in claves)
check("Luna (orbe 1°) no aspecta a 3°", "moon" not in claves)

print("\n== Precisión: datos exactos, redondeo solo para presentación ==")
exacto = calculate_cross_aspects(
    {"moon": {"name": "Luna Progresada", "longitude": 151.5666666666}},
    {"chiron": {"name": "Quirón", "longitude": 91.3666666666}},
    PROGRESSION_ORBS,
)[0]
check("orbe exacto sin redondear", abs(exacto["orbExact"] - 0.2) < 1e-9)
check("orbe de presentación redondeado", exacto["orb"] == 0.2)
check("separación exacta conservada", abs(exacto["separationExact"] - 60.2) < 1e-9)
check("longitud de origen sin redondeo previo",
      abs(exacto["sourceLongitude"] - 151.5666666666) < 1e-12)
check("no se afirma aplicativo ni separativo", exacto["motion"] == "unknown")

print("\n== Entradas degeneradas ==")
check("sin puntos no hay aspectos", calculate_cross_aspects({}, natal, PROGRESSION_ORBS) == [])
check("longitud nula se ignora",
      calculate_cross_aspects({"x": {"longitude": None}}, natal, PROGRESSION_ORBS) == [])
check("longitud no numérica se ignora",
      calculate_cross_aspects({"x": {"longitude": "abc"}}, natal, PROGRESSION_ORBS) == [])

print()
if failures:
    print(f"{len(failures)} pruebas fallidas:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("Todas las pruebas de aspectos entre cartas pasan.")