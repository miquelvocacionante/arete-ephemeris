"""
Validación REAL contra Swiss Ephemeris (sin dobles ni mocks).

Este script no sustituye a los tests con doble: los complementa. Comprueba que,
con la librería y los ficheros de efemérides reales, el motor efectivo es Swiss
y que los cálculos de Areté (posiciones, casas, retorno solar, progresiones y
geometría de aspectos cruzados) son correctos.

Falla de forma explícita —y con código de salida distinto de 0— si falta la
librería o los ficheros. Nunca "pasa" degradando a Moshier.

Uso (en el contenedor real del servicio):

    EPHE_PATH=/app/ephe python3 verify_swiss_real.py

Ficheros mínimos requeridos en EPHE_PATH:
    sepl_18.se1  (planetas)
    semo_18.se1  (Luna)
    seas_18.se1  (asteroides: Quirón)
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

REQUIRED_EPHE_FILES = ("sepl_18.se1", "semo_18.se1", "seas_18.se1")

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok  {name}" + (f" — {detail}" if detail else ""))
    else:
        print(f"FAIL  {name}" + (f" — {detail}" if detail else ""))
        failures.append(name)


def fatal(message):
    print(f"\nVALIDACIÓN REAL NO EJECUTADA: {message}")
    print("No se puede dar por validada la Fase 0 ni la Fase 2 sin este paso.")
    sys.exit(2)


# --- Requisito 1: librería real -------------------------------------------
try:
    import swisseph as swe
except ImportError:
    fatal("pyswisseph no está instalado (pip install pyswisseph==2.10.3.2).")

# --- Requisito 2: ficheros de efemérides reales ---------------------------
ephe_path = os.environ.get("EPHE_PATH") or (
    "/app/ephe" if os.path.isdir("/app/ephe") else os.path.join(HERE, "ephe")
)
if not os.path.isdir(ephe_path):
    fatal(f"EPHE_PATH no existe: {ephe_path}")

missing = [f for f in REQUIRED_EPHE_FILES if not os.path.isfile(os.path.join(ephe_path, f))]
if missing:
    fatal(
        f"Faltan ficheros de efemérides en {ephe_path}: {', '.join(missing)}. "
        "Sin ellos Swiss Ephemeris degrada a Moshier."
    )

os.environ["EPHE_PATH"] = ephe_path

import app as service  # noqa: E402
from cross_aspects import calculate_cross_aspects  # noqa: E402
from engine_integrity import ARETE_ASTRO_POLICY, REQUIRED_BODIES  # noqa: E402

print(f"\n[0] Entorno real")
print(f"  pyswisseph = {swe.version}")
print(f"  EPHE_PATH  = {ephe_path}")
print(f"  ficheros   = {sorted(os.listdir(ephe_path))}")
check("la política declarada es la de Areté", ARETE_ASTRO_POLICY["ephemeris"] == "swiss")

# --- Caso de referencia: 20 julio 1985, 14:30, Madrid ---------------------
Y, M, D, HH, MM = 1985, 7, 20, 14, 30
LAT, LON, TZ = 40.4168, -3.7038, "Europe/Madrid"

print("\n[1] Zona horaria real (pytz, no asumir UTC)")
uy, um, ud, uh, umin = service.convert_local_to_utc(Y, M, D, HH, MM, TZ)
check("verano en Madrid: 14:30 local -> 12:30 UTC", (uh, round(umin)) == (12, 30), f"{uh}:{umin}")
jd = service.calculate_julian_day(uy, um, ud, uh, umin)

print("\n[2] calc_ut real: Sol, Luna, Quirón y Nodo Verdadero")
positions = {}
for key in ("sun", "moon", "chiron", "north_node"):
    pos = service.calculate_planet_position(jd, service.PLANETS[key], body_key=key)
    positions[key] = pos
    prov = pos["provenance"]
    check(
        f"{key}: motor efectivo Swiss",
        prov["engine"] == "swiss",
        f"lon={pos['longitude']:.4f} {pos['sign']} {pos['degree_dms']} retflags={prov['retflags']}",
    )
check("Nodo Verdadero (no medio) según política", ARETE_ASTRO_POLICY["node"] == "true_node")

print("\n[3] Todos los cuerpos obligatorios con motor real")
all_planets = {}
for key, pid in service.PLANETS.items():
    if key == "south_node":
        continue
    p = service.calculate_planet_position(jd, pid, body_key=key)
    if p:
        all_planets[key] = {"name": service.PLANET_NAMES[key], **p}
nn = all_planets["north_node"]["longitude"]
all_planets["south_node"] = {"name": "Nodo Sur", "longitude": (nn + 180) % 360}
for body in REQUIRED_BODIES:
    check(f"cuerpo obligatorio presente: {body}", body in all_planets)
check(
    "Nodo Sur exactamente opuesto al Norte",
    abs(((all_planets["south_node"]["longitude"] - nn) % 360) - 180) < 1e-9,
)

print("\n[4] Casas Placidus reales en latitud normal")
houses = service.calculate_houses(jd, LAT, LON)
check("12 cúspides", len(houses["houses"]) == 12)
check("Placidus declarado fiable", houses["houseSystem"]["reliable"] is True)
check(
    "Ascendente y MC presentes",
    houses["ascendant"]["longitude"] is not None and houses["mc"]["longitude"] is not None,
    f"ASC {houses['ascendant']['sign']} {houses['ascendant']['degree_dms']} / "
    f"MC {houses['mc']['sign']} {houses['mc']['degree_dms']}",
)
for key, p in all_planets.items():
    h = service.get_house_for_planet(p["longitude"], houses["houses"])
    check(f"{key} cae en una casa real", 1 <= h <= 12)

print("\n[5] Latitud polar: Placidus bloqueado, nunca etiquetado en falso")
try:
    service.calculate_houses(jd, 69.65, 18.96)
    check("latitud 69.65° bloqueada", False, "no lanzó error")
except Exception as e:  # HouseSystemUnavailableError
    check("latitud 69.65° bloqueada", type(e).__name__ == "HouseSystemUnavailableError", str(e)[:70])

print("\n[6] Retorno solar real")
natal_points = service.build_natal_points(all_planets, houses)
sr = service.calculate_solar_return(jd, all_planets["sun"]["longitude"], 2026, LAT, LON, natal_points)
check("la revolución solar se calcula", sr is not None)
if sr:
    sr_sun = sr["planets"]["sun"]["longitude"]
    delta = abs(((sr_sun - all_planets["sun"]["longitude"] + 180) % 360) - 180)
    check("el Sol vuelve a su posición natal (<1\")", delta < 1 / 3600, f"delta={delta*3600:.3f}\"")
    sr_date = sr["exactMoment"]["date"]
    check("la revolución cae en el año pedido", sr_date.startswith("2026"), sr_date)
    check(
        "la revolución cae cerca del cumpleaños",
        sr_date[5:7] == "07",
        f"{sr_date} {sr['exactMoment']['time']} UT",
    )
    check("incluye Nodo Sur derivado", "south_node" in sr["planets"])
    check("trae aspectos internos calculados", isinstance(sr.get("aspects"), list))
    check("trae aspectos contra la carta natal", isinstance(sr.get("natalAspects"), list))

print("\n[7] Progresiones secundarias reales")
prog = service.calculate_secondary_progressions(jd, "2026-09-15", natal_points)
check("las progresiones se calculan", prog is not None)
if prog:
    for body in ("sun", "moon", "mercury", "venus", "mars"):
        check(f"progresado presente: {body}", body in prog["points"])
    check("Ascendente progresado no soportado", prog["progressedAscendant"]["supported"] is False)
    check(
        "cambio de signo determinista o ausente",
        prog["yearsToSignChange"] is None or isinstance(prog["yearsToSignChange"], float),
        str(prog["yearsToSignChange"]),
    )
    moon = prog["points"]["moon"]
    print(f"      Luna progresada: {moon['sign']} {moon['degree_dms']} (lon {moon['longitude']:.4f})")
    for a in prog["aspects"]:
        check(
            f"aspecto progresado con geometría real ({a['sourcePoint']} {a['aspect']} {a['targetPoint']})",
            abs(a["separationExact"] - a["angle"]) <= a["maxOrb"] + 1e-9,
        )

print("\n[8] Caso Marta Alí sobre el motor real: 151°34' vs 91°22'")
marta = calculate_cross_aspects(
    {"moon": {"name": "Luna Progresada", "longitude": 151 + 34 / 60}},
    {"chiron": {"name": "Quirón", "longitude": 91 + 22 / 60}},
    service.PROGRESSION_ORBS,
    source_suffix="",
)
check("se detecta exactamente un aspecto", len(marta) == 1, str(marta))
if marta:
    a = marta[0]
    check("es un sextil, nunca una conjunción", a["aspectKey"] == "sextile", a["aspect"])
    check("orbe 0°12'", abs(a["orbExact"] - 0.2) < 1e-6, f"{a['orbExact']:.4f}°")
    check("separación 60°12'", abs(a["separationExact"] - 60.2) < 1e-6, f"{a['separationExact']:.4f}°")

print("\n[9] Diagnóstico de salud con motor real")
client = service.app.test_client()
resp = client.get("/health/engine")
check("/health/engine responde 200", resp.status_code == 200, str(resp.status_code))
body = resp.get_json()
check("Quirón calculable con motor Swiss", body["bodies"]["chiron"]["engine"] == "swiss")
check("/health informa healthy", client.get("/health").get_json()["status"] == "healthy")

print()
if failures:
    print(f"VALIDACIÓN REAL FALLIDA: {len(failures)} comprobación(es)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("VALIDACIÓN REAL SUPERADA: motor Swiss efectivo en todos los cálculos.")