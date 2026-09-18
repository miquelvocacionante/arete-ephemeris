"""
Pruebas puras de integridad del motor (Fase 0).

No requieren swisseph ni ficheros de efemérides: validan la lógica de decisión
sobre los retflags, los cuerpos obligatorios, la zona horaria y Placidus.

Ejecutar: python3 python-ephemeris/test_engine_integrity.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine_integrity import (  # noqa: E402
    ARETE_ASTRO_POLICY,
    BodyCalculationError,
    EphemerisEngineError,
    FLG_JPLEPH,
    FLG_MOSEPH,
    FLG_SPEED,
    FLG_SWIEPH,
    REQUIRED_BODIES,
    assert_required_bodies,
    placidus_status,
    resolve_effective_engine,
    validate_engine,
)

REQUESTED = FLG_SWIEPH | FLG_SPEED
failures = []


def check(name, condition):
    if condition:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}")
        failures.append(name)


def expect_raises(name, exc_type, fn):
    try:
        fn()
    except exc_type:
        print(f"  ok  {name}")
        return
    except Exception as e:  # noqa: BLE001
        print(f"FAIL  {name} (excepción inesperada: {type(e).__name__})")
        failures.append(name)
        return
    print(f"FAIL  {name} (no lanzó {exc_type.__name__})")
    failures.append(name)


print("\n[1] Motor efectivo a partir de retflags")
check("swiss", resolve_effective_engine(FLG_SWIEPH | FLG_SPEED) == "swiss")
check("moshier", resolve_effective_engine(FLG_MOSEPH | FLG_SPEED) == "moshier")
check("jpl", resolve_effective_engine(FLG_JPLEPH | FLG_SPEED) == "jpl")
check("error de swiss (-1)", resolve_effective_engine(-1) == "error")
check("ausente", resolve_effective_engine(None) == "unknown")

print("\n[2] Validación de motor solicitado frente a motor efectivo")
prov = validate_engine("sun", REQUESTED, FLG_SWIEPH | FLG_SPEED)
check("swiss aceptado", prov["engine"] == "swiss")
check("trazabilidad de flags", prov["requested_flags"] == REQUESTED and prov["retflags"] == REQUESTED)
expect_raises(
    "fallback silencioso a Moshier rechazado",
    EphemerisEngineError,
    lambda: validate_engine("sun", REQUESTED, FLG_MOSEPH | FLG_SPEED),
)
expect_raises(
    "Quirón con motor degradado rechazado",
    EphemerisEngineError,
    lambda: validate_engine("chiron", REQUESTED, FLG_MOSEPH),
)
expect_raises(
    "retflags de error rechazados",
    EphemerisEngineError,
    lambda: validate_engine("chiron", REQUESTED, -1),
)

print("\n[3] Cuerpos obligatorios")
check("Quirón es obligatorio", "chiron" in REQUIRED_BODIES)
check("juego completo aceptado", assert_required_bodies(list(REQUIRED_BODIES)))
expect_raises(
    "carta sin Quirón rechazada",
    BodyCalculationError,
    lambda: assert_required_bodies([b for b in REQUIRED_BODIES if b != "chiron"]),
)
expect_raises(
    "carta sin Luna rechazada",
    BodyCalculationError,
    lambda: assert_required_bodies([b for b in REQUIRED_BODIES if b != "moon"]),
)

print("\n[4] Placidus y latitudes extremas")
check("Madrid fiable", placidus_status(40.4)["reliable"] is True)
check("Tromso no fiable", placidus_status(69.6)["reliable"] is False)
check("polo sur no fiable", placidus_status(-70.0)["reliable"] is False)
check("aviso presente", placidus_status(69.6)["warning"] is not None)
check("latitud inválida no fiable", placidus_status(None)["reliable"] is False)

print("\n[5] Convenciones versionadas")
check("nodo verdadero", ARETE_ASTRO_POLICY["node"] == "true_node")
check("tropical", ARETE_ASTRO_POLICY["zodiac"] == "tropical")
check("geocéntrico", ARETE_ASTRO_POLICY["frame"] == "geocentric")
check("placidus", ARETE_ASTRO_POLICY["house_system"] == "placidus")
check("flags requeridos", ARETE_ASTRO_POLICY["required_flags"] == REQUESTED)

print("\n[6] Zona horaria: nunca asumir UTC")
sys.modules.setdefault("swisseph", None)
from engine_integrity import TimezoneResolutionError  # noqa: E402

check("existe error específico", issubclass(TimezoneResolutionError, ValueError))

print()
if failures:
    print(f"{len(failures)} prueba(s) fallidas")
    sys.exit(1)
print("Todas las pruebas de integridad del motor han pasado")