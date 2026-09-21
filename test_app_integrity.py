"""
Pruebas de integridad a nivel de servicio (Fase 0), con Swiss Ephemeris simulado.

En el entorno de desarrollo no hay pyswisseph ni ficheros de efemérides, así que
inyectamos un doble controlable de `swisseph`. Eso permite comprobar exactamente
lo que antes fallaba en silencio: motor degradado, cuerpo obligatorio ausente y
zona horaria irresoluble.

Ejecutar: python3 python-ephemeris/test_app_integrity.py
"""

import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FLG_SWIEPH = 2
FLG_MOSEPH = 4
FLG_SPEED = 256

# Comportamiento configurable del doble.
STATE = {
    "engine_flags": FLG_SWIEPH | FLG_SPEED,  # motor que "devuelve" Swiss
    "failing_bodies": set(),  # ids de cuerpo que lanzan excepción
    "speeds": {},  # id -> velocidad (negativa = retrógrado)
    "houses_raise": False,  # swe.houses falla
    "houses_cusps": None,  # cúspides forzadas (para provocar una longitud sin casa)
}

fake = types.ModuleType("swisseph")
fake.SUN, fake.MOON, fake.MERCURY, fake.VENUS, fake.MARS = 0, 1, 2, 3, 4
fake.JUPITER, fake.SATURN, fake.URANUS, fake.NEPTUNE, fake.PLUTO = 5, 6, 7, 8, 9
fake.TRUE_NODE, fake.MEAN_NODE, fake.CHIRON = 11, 10, 15
fake.FLG_SWIEPH, fake.FLG_SPEED, fake.FLG_MOSEPH = FLG_SWIEPH, FLG_SPEED, FLG_MOSEPH
fake.version = "fake-2.10"


def _set_ephe_path(path):
    return None


def _julday(y, m, d, h):
    return 2451545.0 + (y - 2000) * 365.25 + (m - 1) * 30.4 + d + h / 24.0


def _revjul(jd):
    return (2026, 1, 1, 12.0)


def _calc_ut(jd, planet_id, flags):
    if planet_id in STATE["failing_bodies"]:
        raise RuntimeError(f"SwissEph file not found for body {planet_id}")
    longitude = (planet_id * 27.5 + 10.0) % 360
    speed = STATE["speeds"].get(planet_id, 1.0)
    return ((longitude, 0.5, 1.0, speed, 0.0, 0.0), STATE["engine_flags"])


def _houses(jd, lat, lon, hsys):
    if STATE["houses_raise"]:
        raise RuntimeError("swe.houses ha fallado")
    cusps = STATE["houses_cusps"] or tuple((i * 30.0) % 360 for i in range(12))
    ascmc = (0.0, 270.0, 180.0, 90.0, 45.0)
    return cusps, ascmc


fake.set_ephe_path = _set_ephe_path
fake.julday = _julday
fake.revjul = _revjul
fake.calc_ut = _calc_ut
fake.houses = _houses
sys.modules["swisseph"] = fake

import app as service  # noqa: E402
from engine_integrity import EphemerisEngineError, TimezoneResolutionError  # noqa: E402

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
        print(f"FAIL  {name} (excepción inesperada: {type(e).__name__}: {e})")
        failures.append(name)
        return
    print(f"FAIL  {name} (no lanzó {exc_type.__name__})")
    failures.append(name)


def reset():
    STATE["engine_flags"] = FLG_SWIEPH | FLG_SPEED
    STATE["failing_bodies"] = set()
    STATE["speeds"] = {}
    STATE["houses_raise"] = False
    STATE["houses_cusps"] = None


print("\n[1] Zona horaria")
reset()
utc = service.convert_local_to_utc(1985, 7, 20, 14, 30, "Europe/Madrid")
check("verano en Madrid convierte a UTC (14:30 -> 12:30)", utc[3] == 12 and abs(utc[4] - 30) < 0.001)
utc_invierno = service.convert_local_to_utc(1985, 1, 20, 14, 30, "Europe/Madrid")
check("invierno en Madrid convierte a UTC (14:30 -> 13:30)", utc_invierno[3] == 13)
expect_raises(
    "zona horaria inexistente es error, no hora local tratada como UTC",
    TimezoneResolutionError,
    lambda: service.convert_local_to_utc(1985, 7, 20, 14, 30, "Europa/Madriz"),
)
expect_raises(
    "zona horaria vacía es error",
    TimezoneResolutionError,
    lambda: service.convert_local_to_utc(1985, 7, 20, 14, 30, ""),
)

print("\n[2] Validación de motor en calc_ut")
reset()
pos = service.calculate_planet_position(2451545.0, fake.SUN, body_key="sun")
check("posición con Swiss aceptada", pos is not None and pos["provenance"]["engine"] == "swiss")
check("trazabilidad de flags solicitados", pos["provenance"]["requested_flags"] == FLG_SWIEPH | FLG_SPEED)

STATE["engine_flags"] = FLG_MOSEPH | FLG_SPEED
expect_raises(
    "motor degradado a Moshier no se acepta en silencio",
    EphemerisEngineError,
    lambda: service.calculate_planet_position(2451545.0, fake.CHIRON, body_key="chiron"),
)

print("\n[3] Retrogradación")
reset()
STATE["speeds"][fake.MERCURY] = -0.4
retro = service.calculate_planet_position(2451545.0, fake.MERCURY, body_key="mercury")
directo = service.calculate_planet_position(2451545.0, fake.VENUS, body_key="venus")
check("velocidad negativa marca retrógrado", retro["retrograde"] is True)
check("velocidad positiva no marca retrógrado", directo["retrograde"] is False)

print("\n[4] Cuerpo obligatorio ausente en /calculate")
reset()
STATE["failing_bodies"] = {fake.CHIRON}
client = service.app.test_client()
payload = {
    "birthDate": "1985-07-20",
    "birthTime": "14:30",
    "latitude": 40.4168,
    "longitude": -3.7038,
    "timezone": "Europe/Madrid",
    "includeProgressions": False,
    "includeSolarReturn": False,
}

print("\n[4a] Contrato de hora de nacimiento")
reset()
resp = client.post("/calculate", json={**payload, "birthTime": "14:30:00"})
check("HH:MM:SS de Postgres se acepta", resp.status_code == 200)
resp = client.post("/calculate", json={**payload, "birthTime": "14:30:45.500000"})
check("segundos fraccionarios se aceptan sin romper el endpoint", resp.status_code == 200)
resp = client.post("/calculate", json={**payload, "birthTime": "14:99:00"})
check("hora imposible devuelve 400", resp.status_code == 400)
check("hora imposible tiene código explícito", resp.get_json().get("code") == "invalid_birth_time")
resp = client.post("/calculate", json=payload)
body = resp.get_json()
check("Quirón ausente devuelve error de servicio", resp.status_code == 503)
check("código explícito", body.get("code") == "required_body_missing")
check("el mensaje nombra Quirón", "chiron" in body.get("error", ""))

print("\n[5] Zona horaria inválida en /calculate")
reset()
resp = client.post("/calculate", json={**payload, "timezone": "Europa/Madriz"})
check("devuelve 400", resp.status_code == 400)
check("código explícito", resp.get_json().get("code") == "timezone_unresolved")

print("\n[6] Motor degradado en /calculate")
reset()
STATE["engine_flags"] = FLG_MOSEPH | FLG_SPEED
resp = client.post("/calculate", json=payload)
check("devuelve 503", resp.status_code == 503)
check("código explícito", resp.get_json().get("code") == "ephemeris_engine_mismatch")

print("\n[7] Carta correcta: trazabilidad y casas")
reset()
resp = client.post("/calculate", json=payload)
data = resp.get_json()
check("carta calculada", resp.status_code == 200 and data.get("success") is True)
prov = data["chartData"]["provenance"]
check("política versionada", prov["policy"]["node"] == "true_node")
check("motor por cuerpo registrado", prov["bodies"]["chiron"]["engine"] == "swiss")
check("sistema de casas declarado fiable en Madrid", prov["houseSystem"]["reliable"] is True)

print("\n[8] Latitud extrema: Placidus bloqueado, no etiquetado en falso")
reset()
resp = client.post("/calculate", json={**payload, "latitude": 69.65, "timezone": "Europe/Oslo"})
check("devuelve 422", resp.status_code == 422)
check("código explícito", resp.get_json().get("code") == "house_system_unavailable")
check("el mensaje nombra Placidus", "Placidus" in resp.get_json().get("error", ""))

print("\n[9] Diagnóstico del motor")
reset()
resp = client.get("/health/engine")
check("motor sano devuelve 200", resp.status_code == 200)
check("informa de Quirón", resp.get_json()["bodies"]["chiron"]["engine"] == "swiss")
STATE["engine_flags"] = FLG_MOSEPH
resp = client.get("/health/engine")
check("motor degradado devuelve 503", resp.status_code == 503)
check("endpoint antiguo sigue respondiendo", client.get("/debug/ephe").status_code == 200)

print("\n[10] /health deja de mentir")
reset()
check("motor sano: healthy", client.get("/health").get_json()["status"] == "healthy")
STATE["engine_flags"] = FLG_MOSEPH
degraded = client.get("/health").get_json()
check("motor degradado: degraded", degraded["status"] == "degraded")
check("liveness sigue en 200", client.get("/health").status_code == 200)

print("\n[11] Motor degradado fuera de la carta natal")
reset()
STATE["engine_flags"] = FLG_MOSEPH | FLG_SPEED
resp = client.post("/transits", json={"natalPlanets": {"sun": {"longitude": 10.0}}})
check("tránsitos: 503", resp.status_code == 503)
check("tránsitos: código explícito", resp.get_json().get("code") == "ephemeris_engine_mismatch")
resp = client.get("/current-positions")
check("posiciones actuales: 503", resp.status_code == 503)
resp = client.post("/yearly-transits", json={"natalPlanets": {"sun": {"longitude": 10.0}}, "year": 2026})
check("tránsitos anuales: 503", resp.status_code == 503)
resp = client.post("/search-transit-aspect", json={
    "transitPlanet": "saturno", "aspect": "conjuncion", "natalLongitude": 10.0,
    "startDate": "2026-01-01", "endDate": "2026-03-01",
})
check("búsqueda de perfección: 503", resp.status_code == 503)

print("\n[12] Cuerpo obligatorio ausente fuera de la carta natal")
reset()
STATE["failing_bodies"] = {fake.CHIRON}
resp = client.post("/transits", json={"natalPlanets": {"sun": {"longitude": 10.0}}})
check("tránsitos no continúan sin Quirón", resp.status_code == 503)
check("código explícito", resp.get_json().get("code") == "required_body_missing")

print("\n[13] Precisión DMS: no se redondea antes de convertir")
reset()
# 10.008333° = 10°00'30\"; con degree redondeado a 2 decimales salía 10°00'28\",
# y truncando los segundos salía 10°00'29\".
sign_info = service.get_sign(10.008333)
check("grado exacto conservado", abs(sign_info["degree_exact"] - 10.008333) < 1e-6)
check("DMS con segundos correctos", service.dms_of(sign_info) == "10°00'30\"")
# Acarreo en los bordes: los segundos se redondean, no se truncan.
check("acarreo de segundos a minuto", service.format_dms(10 + 59.6 / 3600) == "10°01'00\"")
check("acarreo de minuto a grado", service.format_dms(10 + 59 / 60 + 59.6 / 3600) == "11°00'00\"")
check("cero exacto", service.format_dms(0.0) == "0°00'00\"")

print("\n[14] Fase 2: aspectos deterministas en progresiones y revolución solar")
reset()
resp = client.post("/calculate", json={
    **payload, "includeProgressions": True, "includeSolarReturn": True, "solarReturnYear": 2026,
})
chart = resp.get_json()["chartData"]
check("carta con progresiones y RS", resp.status_code == 200)
check("la Luna progresada trae lista de aspectos", isinstance(chart["progressedMoon"]["aspects"], list))
check("la RS trae sus aspectos internos", isinstance(chart["solarReturn"]["aspects"], list))
check("la RS trae aspectos contra la carta natal", isinstance(chart["solarReturn"]["natalAspects"], list))
check("política de orbes versionada en la carta", chart["provenance"]["orbPolicy"]["version"] == "v1")
for aspect in chart["progressedMoon"]["aspects"]:
    check(
        f"aspecto progresado con geometría real ({aspect['aspect']})",
        abs(aspect["separation"] - aspect["angle"]) <= aspect["maxOrb"] + 1e-6,
    )




print("\n[15] Casas: nunca inventadas, nunca degradadas")
reset()
from engine_integrity import HouseCalculationError, HousePlacementError  # noqa: E402

# Antes se devolvía Casa 1 cuando ninguna cúspide contenía la longitud.
expect_raises(
    "longitud sin casa lanza error",
    HousePlacementError,
    lambda: service.get_house_for_planet(10.0, [{"cusp": 0.0}]),
)

# Cúspides degeneradas (todas iguales): ninguna contiene la longitud.
STATE["houses_cusps"] = tuple(0.0 for _ in range(12))
resp = client.post("/calculate", json=payload)
check("carta natal no entrega casa inventada", resp.status_code == 500)
check("código explícito de casa", resp.get_json().get("code") == "house_placement_failed")

reset()
STATE["houses_cusps"] = tuple(0.0 for _ in range(12))
resp = client.post("/calculate", json={**payload, "includeSolarReturn": True, "solarReturnYear": 2026})
check("revolución solar tampoco inventa casa", resp.status_code == 500)

reset()
STATE["houses_raise"] = True
resp = client.post("/calculate", json=payload)
check("fallo real de casas no se degrada a 'sin datos'", resp.status_code == 503)
check("código explícito de fallo de casas", resp.get_json().get("code") == "house_calculation_failed")

print("\n[16] Revolución solar: Nodo Sur derivado, sin calc_ut(None)")
reset()
resp = client.post("/calculate", json={**payload, "includeSolarReturn": True, "solarReturnYear": 2026})
sr = resp.get_json()["chartData"]["solarReturn"]
check("la RS incluye Nodo Sur", "south_node" in sr["planets"])
north = sr["planets"]["north_node"]["longitude"]
south = sr["planets"]["south_node"]["longitude"]
check("Nodo Sur exactamente opuesto al Norte", abs(((south - north) % 360) - 180) < 1e-6)

print("\n[17] Tránsitos: sin cúspides natales reales no hay casa natal")
reset()
natal_planets = {"sun": {"longitude": 100.0}, "moon": {"longitude": 200.0}}
resp = client.post("/transits", json={"natalPlanets": natal_planets, "targetDate": "2026-05-01"})
transits = resp.get_json()["transitPlanets"]
check("se omite natalHouse sin cúspides", all("natalHouse" not in p for p in transits.values()))

resp = client.post("/transits", json={
    "natalPlanets": natal_planets,
    "targetDate": "2026-05-01",
    "natalHouses": [{"cusp": (i * 30.0) % 360} for i in range(12)],
})
transits = resp.get_json()["transitPlanets"]
check("con cúspides reales sí hay natalHouse", all("natalHouse" in p for p in transits.values()))
check(
    "casa natal coherente con las cúspides",
    all(1 <= p["natalHouse"] <= 12 for p in transits.values()),
)

print("\n[18] Progresiones secundarias")
reset()
chart = client.post("/calculate", json={**payload, "includeProgressions": True}).get_json()["chartData"]
prog = chart["secondaryProgressions"]
check("incluye Sol, Luna, Mercurio, Venus y Marte",
      all(k in prog["points"] for k in ("sun", "moon", "mercury", "venus", "mars")))
check("una única fecha progresada", isinstance(prog["progressedJulianDay"], float))
check("Ascendente progresado no soportado", prog["progressedAscendant"]["supported"] is False)
check("la Luna progresada se deriva de las progresiones",
      chart["progressedMoon"]["longitude"] == prog["points"]["moon"]["longitude"])
check("el cambio de signo se calcula o se omite, nunca se estima",
      prog["yearsToSignChange"] is None or isinstance(prog["yearsToSignChange"], float))

print()
if failures:
    print(f"{len(failures)} prueba(s) fallidas")
    sys.exit(1)
print("Todas las pruebas de servicio han pasado")