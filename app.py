from flask import Flask, request, jsonify
from flask_cors import CORS
import swisseph as swe
from datetime import datetime
import os
import pytz

app = Flask(__name__)
CORS(app)

def _resolve_ephe_path() -> str:
    """
    Resolve ephemeris path in order of priority:
    1. Environment variable EPHE_PATH
    2. Docker default /app/ephe
    3. Local ephe directory
    """
    env_path = os.environ.get("EPHE_PATH")
    if env_path:
        return env_path

    docker_default = "/app/ephe"
    if os.path.isdir(docker_default):
        return docker_default

    return os.path.join(os.path.dirname(__file__), "ephe")

EPHE_PATH = _resolve_ephe_path()
swe.set_ephe_path(EPHE_PATH)

def _log_ephe_status():
    """Log ephemeris path and file status on startup"""
    try:
        files = []
        if os.path.isdir(EPHE_PATH):
            files = sorted([f for f in os.listdir(EPHE_PATH) if not f.startswith(".")])
        print(f"[ephe] Using EPHE_PATH={EPHE_PATH} | files={len(files)}")
        if files:
            print(f"[ephe] Sample files: {files[:10]}")
        else:
            print("[ephe] WARNING: No ephemeris files found. Outer bodies may work, but Chiron can be missing.")
    except Exception as e:
        print(f"[ephe] ERROR reading EPHE_PATH={EPHE_PATH}: {e}")

_log_ephe_status()

PLANETS = {
    'sun': swe.SUN,
    'moon': swe.MOON,
    'mercury': swe.MERCURY,
    'venus': swe.VENUS,
    'mars': swe.MARS,
    'jupiter': swe.JUPITER,
    'saturn': swe.SATURN,
    'uranus': swe.URANUS,
    'neptune': swe.NEPTUNE,
    'pluto': swe.PLUTO,
    'north_node': swe.TRUE_NODE,
    'south_node': None,  # Calculated as opposite of North Node
    'chiron': swe.CHIRON,
}

PLANET_NAMES = {
    'sun': 'Sol',
    'moon': 'Luna',
    'mercury': 'Mercurio',
    'venus': 'Venus',
    'mars': 'Marte',
    'jupiter': 'Júpiter',
    'saturn': 'Saturno',
    'uranus': 'Urano',
    'neptune': 'Neptuno',
    'pluto': 'Plutón',
    'north_node': 'Nodo Norte',
    'south_node': 'Nodo Sur',
    'chiron': 'Quirón',
}

SIGNS = [
    'Aries', 'Tauro', 'Géminis', 'Cáncer', 'Leo', 'Virgo',
    'Libra', 'Escorpio', 'Sagitario', 'Capricornio', 'Acuario', 'Piscis'
]

def get_sign(longitude):
    """Get zodiac sign and degree from ecliptic longitude"""
    normalized_lon = longitude % 360
    if normalized_lon < 0:
        normalized_lon += 360
    
    sign_index = int(normalized_lon / 30)
    degree = normalized_lon % 30
    
    return {
        'sign': SIGNS[sign_index],
        'degree': round(degree, 2)
    }

def format_dms(decimal_degrees):
    """Convert decimal degrees to degrees, minutes, seconds format"""
    d = int(decimal_degrees)
    m_float = (decimal_degrees - d) * 60
    m = int(m_float)
    s = int((m_float - m) * 60)
    return f"{d}°{m:02d}'{s:02d}\""

def convert_local_to_utc(year, month, day, hour, minute, timezone_str):
    """
    Convert local time to UTC.
    
    Args:
        year, month, day, hour, minute: Local time components
        timezone_str: IANA timezone string (e.g., 'Europe/Madrid')
    
    Returns:
        tuple: (year, month, day, hour, minute) in UTC
    """
    try:
        # Create a timezone-aware datetime in the local timezone
        local_tz = pytz.timezone(timezone_str)
        local_dt = local_tz.localize(datetime(year, month, day, hour, minute))
        
        # Convert to UTC
        utc_dt = local_dt.astimezone(pytz.UTC)
        
        print(f"[time] Local: {local_dt.strftime('%Y-%m-%d %H:%M %Z')} -> UTC: {utc_dt.strftime('%Y-%m-%d %H:%M %Z')}")
        
        return (
            utc_dt.year,
            utc_dt.month,
            utc_dt.day,
            utc_dt.hour,
            utc_dt.minute + utc_dt.second / 60.0
        )
    except Exception as e:
        print(f"[time] ERROR converting timezone: {e}. Using input time as UTC.")
        return (year, month, day, hour, minute)

def calculate_julian_day(year, month, day, hour, minute):
    """Calculate Julian Day from UTC time"""
    decimal_time = hour + minute / 60.0
    jd = swe.julday(year, month, day, decimal_time)
    return jd

def calculate_planet_position(julian_day, planet_id):
    """Calculate planet position using Swiss Ephemeris"""
    try:
        result = swe.calc_ut(julian_day, planet_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
        longitude = result[0][0]
        latitude = result[0][1]
        distance = result[0][2]
        speed = result[0][3]
        
        sign_info = get_sign(longitude)
        
        return {
            'longitude': round(longitude, 6),
            'latitude': round(latitude, 6),
            'distance': round(distance, 6),
            'speed': round(speed, 6),
            'degree_dms': format_dms(sign_info['degree']),
            **sign_info
        }
    except Exception as e:
        print(f"[calc] ERROR calculating planet {planet_id}: {e}")
        return None

def calculate_houses(julian_day, latitude, longitude):
    """Calculate houses using Placidus system"""
    try:
        # 'P' = Placidus, 'K' = Koch, 'E' = Equal, etc.
        houses, ascmc = swe.houses(julian_day, latitude, longitude, b'P')
        
        house_list = []
        house_names = [
            'Casa 1 (AC)', 'Casa 2', 'Casa 3', 'Casa 4 (FC)',
            'Casa 5', 'Casa 6', 'Casa 7 (DC)', 'Casa 8',
            'Casa 9', 'Casa 10 (MC)', 'Casa 11', 'Casa 12'
        ]
        
        for i in range(12):
            cusp = houses[i]
            sign_info = get_sign(cusp)
            house_list.append({
                'house': house_names[i],
                'house_number': i + 1,
                'cusp': round(cusp, 6),
                'degree_dms': format_dms(sign_info['degree']),
                **sign_info
            })
        
        # ascmc contains: [Ascendant, MC, ARMC, Vertex, Equatorial Ascendant, ...]
        ascendant = ascmc[0]
        mc = ascmc[1]
        vertex = ascmc[3]
        
        asc_sign = get_sign(ascendant)
        mc_sign = get_sign(mc)
        vertex_sign = get_sign(vertex)
        
        return {
            'houses': house_list,
            'ascendant': {
                'longitude': round(ascendant, 6),
                'degree_dms': format_dms(asc_sign['degree']),
                **asc_sign
            },
            'mc': {
                'longitude': round(mc, 6),
                'degree_dms': format_dms(mc_sign['degree']),
                **mc_sign
            },
            'vertex': {
                'longitude': round(vertex, 6),
                'degree_dms': format_dms(vertex_sign['degree']),
                **vertex_sign
            }
        }
    except Exception as e:
        print(f"[calc] ERROR calculating houses: {e}")
        return None

def get_house_for_planet(planet_longitude, houses):
    """Determine which house a planet is in based on its longitude"""
    cusps = [h['cusp'] for h in houses]
    
    for i in range(12):
        cusp_start = cusps[i]
        cusp_end = cusps[(i + 1) % 12]
        
        # Handle the case where the house spans 0° Aries
        if cusp_start > cusp_end:
            if planet_longitude >= cusp_start or planet_longitude < cusp_end:
                return i + 1
        else:
            if cusp_start <= planet_longitude < cusp_end:
                return i + 1
    
    return 1  # Default to house 1 if not found

def normalize_angle(angle):
    """Normalize angle to -180 to +180 range"""
    angle = angle % 360
    if angle > 180:
        angle -= 360
    return angle

def is_aspect_applying(planet1_lon, planet1_speed, planet2_lon, planet2_speed, aspect_angle):
    """
    Determine if an aspect is applying (A) or separating (S).
    An aspect is applying when planets are moving toward exactitude.
    
    Args:
        planet1_lon: Longitude of first planet (degrees)
        planet1_speed: Speed of first planet (degrees/day)
        planet2_lon: Longitude of second planet (degrees)
        planet2_speed: Speed of second planet (degrees/day)
        aspect_angle: Exact angle of the aspect (0, 60, 90, 120, 180)
    
    Returns:
        str: 'A' for applying, 'S' for separating
    """
    # Current angular difference (normalized to -180 to +180)
    current_diff = normalize_angle(planet1_lon - planet2_lon)
    
    # Relative speed (positive if planet1 is catching up)
    relative_speed = planet1_speed - planet2_speed
    
    # Calculate distance to exact aspect
    if aspect_angle == 0:  # Conjunction
        current_distance = abs(current_diff)
    elif aspect_angle == 180:  # Opposition
        current_distance = abs(abs(current_diff) - 180)
    else:  # Trine (120), Square (90), Sextile (60)
        # Find minimum distance to aspect (could be ± aspect_angle)
        dist_positive = abs(current_diff - aspect_angle)
        dist_negative = abs(current_diff + aspect_angle)
        current_distance = min(dist_positive, dist_negative)
    
    # Calculate future position (0.1 days = ~2.4 hours ahead)
    future_diff = normalize_angle(
        (planet1_lon + relative_speed * 0.1) - planet2_lon
    )
    
    # Calculate future distance to exact aspect
    if aspect_angle == 0:
        future_distance = abs(future_diff)
    elif aspect_angle == 180:
        future_distance = abs(abs(future_diff) - 180)
    else:
        dist_positive = abs(future_diff - aspect_angle)
        dist_negative = abs(future_diff + aspect_angle)
        future_distance = min(dist_positive, dist_negative)
    
    # Aspect is applying if future distance is smaller
    return 'A' if future_distance < current_distance else 'S'

def calculate_aspects(planets, ascendant_lon=None, mc_lon=None):
    """Calculate aspects between planets and to angles"""
    aspects = []
    planet_keys = list(planets.keys())
    
    # Traditional orbs
    aspect_orbs = {
        'conjunction': {'angle': 0, 'orb': 8, 'name': 'Conjunción'},
        'opposition': {'angle': 180, 'orb': 8, 'name': 'Oposición'},
        'trine': {'angle': 120, 'orb': 8, 'name': 'Trígono'},
        'square': {'angle': 90, 'orb': 8, 'name': 'Cuadratura'},
        'sextile': {'angle': 60, 'orb': 6, 'name': 'Sextil'},  # Increased from 4° to 6° (professional standard)
    }
    
    # Aspects between planets
    for i in range(len(planet_keys)):
        for j in range(i + 1, len(planet_keys)):
            planet1_key = planet_keys[i]
            planet2_key = planet_keys[j]
            
            if not planets[planet1_key] or not planets[planet2_key]:
                continue
            
            lon1 = planets[planet1_key]['longitude']
            lon2 = planets[planet2_key]['longitude']
            speed1 = planets[planet1_key].get('speed', 0)
            speed2 = planets[planet2_key].get('speed', 0)
            
            # Calculate angular separation
            diff = abs(lon1 - lon2)
            if diff > 180:
                diff = 360 - diff
            
            # Check each aspect type
            for aspect_type, aspect_data in aspect_orbs.items():
                orb = abs(diff - aspect_data['angle'])
                if orb <= aspect_data['orb']:
                    applying = is_aspect_applying(lon1, speed1, lon2, speed2, aspect_data['angle'])
                    # Field naming convention:
                    #   'aspect' = human-readable name ("Trígono", "Oposición") — consumed by AI/frontend
                    #   'category' = technical classification ("planet-planet", "planet-angle") — internal filtering only
                    aspects.append({
                        'planet1': PLANET_NAMES[planet1_key],
                        'planet2': PLANET_NAMES[planet2_key],
                        'aspect': aspect_data['name'],
                        'orb': round(orb, 2),
                        'angle': aspect_data['angle'],
                        'applying': applying,
                        'category': 'planet-planet'
                    })
    
    # Aspects to Ascendant
    if ascendant_lon is not None:
        for planet_key in planet_keys:
            if not planets[planet_key]:
                continue
            
            lon = planets[planet_key]['longitude']
            speed = planets[planet_key].get('speed', 0)
            
            diff = abs(lon - ascendant_lon)
            if diff > 180:
                diff = 360 - diff
            
            for aspect_type, aspect_data in aspect_orbs.items():
                orb = abs(diff - aspect_data['angle'])
                if orb <= aspect_data['orb']:
                    # Ascendant doesn't move, so only planet speed matters
                    applying = is_aspect_applying(lon, speed, ascendant_lon, 0, aspect_data['angle'])
                    aspects.append({
                        'planet1': PLANET_NAMES[planet_key],
                        'planet2': 'Ascendente',
                        'aspect': aspect_data['name'],
                        'orb': round(orb, 2),
                        'angle': aspect_data['angle'],
                        'applying': applying,
                        'category': 'planet-angle'
                    })
    
    # Aspects to MC
    if mc_lon is not None:
        for planet_key in planet_keys:
            if not planets[planet_key]:
                continue
            
            lon = planets[planet_key]['longitude']
            speed = planets[planet_key].get('speed', 0)
            
            diff = abs(lon - mc_lon)
            if diff > 180:
                diff = 360 - diff
            
            for aspect_type, aspect_data in aspect_orbs.items():
                orb = abs(diff - aspect_data['angle'])
                if orb <= aspect_data['orb']:
                    applying = is_aspect_applying(lon, speed, mc_lon, 0, aspect_data['angle'])
                    aspects.append({
                        'planet1': PLANET_NAMES[planet_key],
                        'planet2': 'Medio Cielo',
                        'aspect': aspect_data['name'],
                        'orb': round(orb, 2),
                        'angle': aspect_data['angle'],
                        'applying': applying,
                        'category': 'planet-angle'
                    })
    
    return aspects

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'swiss-ephemeris'})

@app.route('/debug/ephe', methods=['GET'])
def debug_ephe():
    """Debug endpoint to check ephemeris files"""
    ephe_path = _resolve_ephe_path()
    files = []
    if os.path.isdir(ephe_path):
        files = sorted(os.listdir(ephe_path))
    
    # Test Chiron calculation
    chiron_test = None
    try:
        # Test with a known date (2000-01-01 12:00 UT)
        jd = swe.julday(2000, 1, 1, 12.0)
        result = swe.calc_ut(jd, swe.CHIRON, swe.FLG_SWIEPH | swe.FLG_SPEED)
        chiron_test = {
            'status': 'success',
            'longitude': round(result[0][0], 6),
            'sign': get_sign(result[0][0])['sign']
        }
    except Exception as e:
        chiron_test = {
            'status': 'error',
            'message': str(e)
        }
    
    return jsonify({
        'ephe_path': ephe_path,
        'files': files,
        'file_count': len(files),
        'chiron_test': chiron_test,
        'expected_files': ['seas_18.se1', 'sepl_18.se1']
    })

def calculate_progressed_moon(birth_jd, current_date_str):
    """
    Calculate Secondary Progression for the Moon.
    Secondary Progression: 1 day after birth = 1 year of life
    
    Args:
        birth_jd: Julian Day of birth
        current_date_str: Current date in YYYY-MM-DD format
    
    Returns:
        dict with progressed Moon position and info
    """
    try:
        # Parse current date
        current_year, current_month, current_day = map(int, current_date_str.split('-'))
        current_jd = swe.julday(current_year, current_month, current_day, 12.0)
        
        # Calculate years since birth
        days_since_birth = current_jd - birth_jd
        years_since_birth = days_since_birth / 365.25
        
        # Progressed date: birth + (years as days)
        # Each year of life = 1 day after birth
        progressed_jd = birth_jd + years_since_birth
        
        # Calculate Moon position at progressed date
        moon_position = calculate_planet_position(progressed_jd, swe.MOON)
        
        if not moon_position:
            return None
        
        # Calculate when Moon will change sign (approximate)
        moon_speed_per_year = 12.2  # Moon moves ~12.2 degrees per progressed year
        degrees_to_next_sign = 30 - (moon_position['longitude'] % 30)
        years_to_sign_change = degrees_to_next_sign / moon_speed_per_year
        
        # Previous sign
        prev_sign_index = (SIGNS.index(moon_position['sign']) - 1) % 12
        
        return {
            'name': 'Luna Progresada',
            'longitude': moon_position['longitude'],
            'sign': moon_position['sign'],
            'degree': moon_position['degree'],
            'degree_dms': moon_position['degree_dms'],
            'previousSign': SIGNS[prev_sign_index],
            'yearsToSignChange': round(years_to_sign_change, 1),
            'progressedJulianDay': round(progressed_jd, 6),
            'yearsSinceBirth': round(years_since_birth, 2)
        }
    except Exception as e:
        print(f"[calc] ERROR calculating progressed Moon: {e}")
        return None

def calculate_solar_return(birth_jd, birth_sun_longitude, current_year, sr_latitude, sr_longitude):
    """
    Calculate Solar Return chart for a given year.
    Solar Return is when the Sun returns to its exact natal position.
    
    Args:
        birth_jd: Julian Day of birth (for reference)
        birth_sun_longitude: Natal Sun longitude in degrees
        current_year: Year for which to calculate SR
        sr_latitude: Latitude where the birthday is spent
        sr_longitude: Longitude where the birthday is spent
    
    Returns:
        dict with Solar Return chart data
    """
    try:
        # Start searching from January 1 of the target year
        search_jd = swe.julday(current_year, 1, 1, 12.0)
        
        # Find when Sun returns to natal position (within 1 degree tolerance to start)
        # Binary search for exact moment
        low_jd = search_jd
        high_jd = search_jd + 366  # Search within one year
        
        target_longitude = birth_sun_longitude
        
        # Iterative refinement
        for _ in range(50):  # Max iterations
            mid_jd = (low_jd + high_jd) / 2
            sun_pos = swe.calc_ut(mid_jd, swe.SUN, swe.FLG_SWIEPH)[0][0]
            
            # Normalize difference
            diff = sun_pos - target_longitude
            if diff > 180:
                diff -= 360
            elif diff < -180:
                diff += 360
            
            if abs(diff) < 0.0001:  # Very precise
                break
            
            if diff > 0:
                high_jd = mid_jd
            else:
                low_jd = mid_jd
        
        sr_jd = mid_jd
        
        # Calculate houses for SR location
        sr_houses = calculate_houses(sr_jd, sr_latitude, sr_longitude)
        if not sr_houses:
            return None
        
        # Calculate all planets at SR moment
        sr_planets = {}
        for planet_key, planet_id in PLANETS.items():
            position = calculate_planet_position(sr_jd, planet_id)
            if position:
                house_num = get_house_for_planet(position['longitude'], sr_houses['houses'])
                sr_planets[planet_key] = {
                    'name': PLANET_NAMES[planet_key],
                    'house': house_num,
                    **position
                }
        
        # Calculate aspects in SR
        sr_aspects = calculate_aspects(
            sr_planets,
            ascendant_lon=sr_houses['ascendant']['longitude'],
            mc_lon=sr_houses['mc']['longitude']
        )
        
        # Convert SR Julian Day back to calendar date using swe.revjul
        sr_date = swe.revjul(sr_jd)
        sr_date_str = f"{int(sr_date[0])}-{int(sr_date[1]):02d}-{int(sr_date[2]):02d}"
        # Use revjul's decimal hour (index 3) — NOT (sr_jd % 1) * 24 which is wrong
        sr_time_decimal = sr_date[3]
        sr_hour = int(sr_time_decimal)
        sr_minute = int((sr_time_decimal - sr_hour) * 60)
        sr_time_str = f"{sr_hour:02d}:{sr_minute:02d}"
        
        print(f"[SR] Exact moment: {sr_date_str} {sr_time_str} UT (JD={sr_jd:.6f})")
        print(f"[SR] Location: lat={sr_latitude}, lon={sr_longitude}")
        print(f"[SR] Houses: AC={sr_houses['ascendant']['sign']} {sr_houses['ascendant']['degree_dms']}, MC={sr_houses['mc']['sign']} {sr_houses['mc']['degree_dms']}")
        
        return {
            'year': current_year,
            'exactMoment': {
                'julianDay': round(sr_jd, 6),
                'date': sr_date_str,
                'time': sr_time_str
            },
            'planets': sr_planets,
            'houses': sr_houses['houses'],
            'ascendant': sr_houses['ascendant'],
            'mc': sr_houses['mc'],
            'location': {
                'latitude': sr_latitude,
                'longitude': sr_longitude
            }
        }
    except Exception as e:
        print(f"[calc] ERROR calculating Solar Return: {e}")
        import traceback
        traceback.print_exc()
        return None


# ============ TRANSIT CALCULATION ============

# Orbs for transit aspects (tighter than natal)
TRANSIT_ORBS = {
    'sun':       {'conjunction': 1, 'opposition': 1, 'trine': 1, 'square': 1, 'sextile': 1},
    'moon':      {'conjunction': 1, 'opposition': 1, 'trine': 1, 'square': 1, 'sextile': 1},
    'mercury':   {'conjunction': 2, 'opposition': 2, 'trine': 2, 'square': 2, 'sextile': 1},
    'venus':     {'conjunction': 2, 'opposition': 2, 'trine': 2, 'square': 2, 'sextile': 1},
    'mars':      {'conjunction': 2, 'opposition': 2, 'trine': 2, 'square': 2, 'sextile': 1},
    'jupiter':   {'conjunction': 4, 'opposition': 4, 'trine': 4, 'square': 4, 'sextile': 2},
    'saturn':    {'conjunction': 4, 'opposition': 4, 'trine': 4, 'square': 4, 'sextile': 2},
    'uranus':    {'conjunction': 4, 'opposition': 4, 'trine': 4, 'square': 4, 'sextile': 2},
    'neptune':   {'conjunction': 4, 'opposition': 4, 'trine': 4, 'square': 4, 'sextile': 2},
    'pluto':     {'conjunction': 4, 'opposition': 4, 'trine': 4, 'square': 4, 'sextile': 2},
    'north_node':{'conjunction': 2, 'opposition': 2, 'trine': 2, 'square': 2, 'sextile': 1},
    'chiron':    {'conjunction': 3, 'opposition': 3, 'trine': 3, 'square': 3, 'sextile': 2},
}

TRANSIT_ASPECT_DEFS = [
    {'key': 'conjunction', 'angle': 0,   'name': 'Conjunción'},
    {'key': 'opposition',  'angle': 180, 'name': 'Oposición'},
    {'key': 'trine',       'angle': 120, 'name': 'Trígono'},
    {'key': 'square',      'angle': 90,  'name': 'Cuadratura'},
    {'key': 'sextile',     'angle': 60,  'name': 'Sextil'},
]

def calculate_transits(natal_planets_data, target_date_str=None, latitude=None, longitude=None):
    """
    Calculate current transiting planets and their aspects to natal chart.
    
    Args:
        natal_planets_data: dict of natal planets with longitude values
        target_date_str: date string YYYY-MM-DD (default: today UTC)
        latitude: for natal house placement of transiting planets
        longitude: for natal house placement of transiting planets
    
    Returns:
        dict with transitPlanets, transitAspects, date
    """
    try:
        if target_date_str:
            year, month, day = map(int, target_date_str.split('-'))
        else:
            now = datetime.utcnow()
            year, month, day = now.year, now.month, now.day
        
        # Use noon UT for transit date
        transit_jd = swe.julday(year, month, day, 12.0)
        
        # Calculate current transit positions
        transit_planets = {}
        for planet_key, planet_id in PLANETS.items():
            if planet_key == 'south_node':
                continue
            position = calculate_planet_position(transit_jd, planet_id)
            if position:
                transit_planets[planet_key] = {
                    'name': PLANET_NAMES[planet_key],
                    **position
                }
        
        # Add south node
        if 'north_node' in transit_planets:
            nn_lon = transit_planets['north_node']['longitude']
            sn_lon = (nn_lon + 180) % 360
            sn_sign = get_sign(sn_lon)
            transit_planets['south_node'] = {
                'name': PLANET_NAMES['south_node'],
                'longitude': round(sn_lon, 6),
                'speed': transit_planets['north_node']['speed'],
                'degree_dms': format_dms(sn_sign['degree']),
                **sn_sign
            }
        
        # Add natal house placement to transiting planets (which house are they crossing?)
        natal_houses = None
        if latitude is not None and longitude is not None:
            # Calculate natal houses using natal birth location
            # (same JD doesn't matter for natal house structure — we'd need natal JD, 
            #  but for "which house does this transit fall in", we use natal house cusps
            #  which are determined by natal JD; here we use transit JD as approximation
            #  since the natal house structure changes slowly)
            natal_houses = calculate_houses(transit_jd, latitude, longitude)
        
        if natal_houses:
            for pk in transit_planets:
                lon = transit_planets[pk]['longitude']
                house_num = get_house_for_planet(lon, natal_houses['houses'])
                transit_planets[pk]['natalHouse'] = house_num
        
        # Build transit aspects against natal planets
        transit_aspects = []
        
        for t_key, t_planet in transit_planets.items():
            t_lon = t_planet['longitude']
            t_speed = t_planet.get('speed', 0)
            t_orbs = TRANSIT_ORBS.get(t_key, {'conjunction': 2, 'opposition': 2, 'trine': 2, 'square': 2, 'sextile': 1})
            
            for n_key, n_planet in natal_planets_data.items():
                # natal_planets_data may contain longitude as a float or as a dict
                if isinstance(n_planet, dict):
                    n_lon = n_planet.get('longitude')
                else:
                    n_lon = n_planet
                
                if n_lon is None:
                    continue
                
                n_lon = float(n_lon)
                n_name = PLANET_NAMES.get(n_key, n_key)
                
                diff = abs(t_lon - n_lon)
                if diff > 180:
                    diff = 360 - diff
                
                for asp in TRANSIT_ASPECT_DEFS:
                    orb_allowed = t_orbs.get(asp['key'], 2)
                    orb = abs(diff - asp['angle'])
                    if orb <= orb_allowed:
                        applying = is_aspect_applying(t_lon, t_speed, n_lon, 0, asp['angle'])
                        transit_aspects.append({
                            'transitPlanet': t_planet['name'],
                            'transitPlanetKey': t_key,
                            'natalPlanet': n_name,
                            'natalPlanetKey': n_key,
                            'aspect': asp['name'],
                            'orb': round(orb, 2),
                            'angle': asp['angle'],
                            'applying': applying,
                            'natalHouse': transit_planets[t_key].get('natalHouse'),
                        })
        
        # Sort by orb (tightest first)
        transit_aspects.sort(key=lambda x: x['orb'])
        
        date_str = f"{year}-{month:02d}-{day:02d}"
        print(f"[transits] Calculated {len(transit_aspects)} transit aspects for {date_str}")
        
        return {
            'transitPlanets': transit_planets,
            'transitAspects': transit_aspects,
            'date': date_str,
        }
    except Exception as e:
        print(f"[transits] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


@app.route('/transits', methods=['POST'])
def get_transits():
    """Calculate current transit aspects against a natal chart"""
    try:
        data = request.get_json()
        
        natal_planets = data.get('natalPlanets', {})
        target_date = data.get('targetDate', None)
        latitude = data.get('latitude', None)
        longitude = data.get('longitude', None)
        
        if not natal_planets:
            return jsonify({'error': 'natalPlanets is required'}), 400
        
        if latitude is not None:
            latitude = float(latitude)
        if longitude is not None:
            longitude = float(longitude)
        
        result = calculate_transits(natal_planets, target_date, latitude, longitude)
        
        if not result:
            return jsonify({'error': 'Failed to calculate transits'}), 500
        
        return jsonify({'success': True, **result})
        
    except Exception as e:
        print(f"[transits] ERROR in endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def calculate_current_positions(target_date_str=None):
    """
    Calculate planetary positions for a given date (default: today UTC),
    without requiring a natal chart. Used by the daily global snapshot cron.
    """
    try:
        if target_date_str:
            year, month, day = map(int, target_date_str.split('-'))
        else:
            now = datetime.utcnow()
            year, month, day = now.year, now.month, now.day

        jd = swe.julday(year, month, day, 12.0)

        planets = {}
        for planet_key, planet_id in PLANETS.items():
            if planet_key == 'south_node':
                continue
            position = calculate_planet_position(jd, planet_id)
            if position:
                planets[planet_key] = {
                    'name': PLANET_NAMES[planet_key],
                    **position,
                }

        if 'north_node' in planets:
            nn_lon = planets['north_node']['longitude']
            sn_lon = (nn_lon + 180) % 360
            sn_sign = get_sign(sn_lon)
            planets['south_node'] = {
                'name': PLANET_NAMES['south_node'],
                'longitude': round(sn_lon, 6),
                'speed': planets['north_node']['speed'],
                'degree_dms': format_dms(sn_sign['degree']),
                **sn_sign,
            }

        date_str = f"{year}-{month:02d}-{day:02d}"
        print(f"[current-positions] Calculated {len(planets)} planets for {date_str}")
        return {'planets': planets, 'date': date_str}
    except Exception as e:
        print(f"[current-positions] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


@app.route('/current-positions', methods=['POST', 'GET'])
def get_current_positions():
    """Return today's (or targetDate's) planetary positions, no natal required."""
    try:
        target_date = None
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            target_date = data.get('targetDate')
        else:
            target_date = request.args.get('targetDate')

        result = calculate_current_positions(target_date)
        if not result:
            return jsonify({'error': 'Failed to calculate current positions'}), 500
        return jsonify({'success': True, **result})
    except Exception as e:
        print(f"[current-positions] ERROR in endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500



def calculate_yearly_transits(natal_planets_data, year, latitude=None, longitude=None):
    SLOW_PLANET_KEYS = ['jupiter', 'saturn', 'uranus', 'neptune', 'pluto']
    SLOW_PLANET_IDS = {'jupiter': swe.JUPITER, 'saturn': swe.SATURN, 'uranus': swe.URANUS, 'neptune': swe.NEPTUNE, 'pluto': swe.PLUTO}
    try:
        from datetime import timedelta
        monthly_positions = []
        for month in range(1, 13):
            jd = swe.julday(year, month, 1, 12.0)
            planets = {}
            for pk in SLOW_PLANET_KEYS:
                pos = calculate_planet_position(jd, SLOW_PLANET_IDS[pk])
                if pos:
                    planets[pk] = {'name': PLANET_NAMES[pk], **pos}
            monthly_positions.append({'month': month, 'date': f"{year}-{month:02d}-01", 'planets': planets})
        transit_aspects = []
        seen_aspects = set()
        sample_dates = []
        for day_offset in range(0, 366, 10):
            base = datetime(year, 1, 1) + timedelta(days=day_offset)
            if base.year > year:
                break
            sample_dates.append(base)
        for pk in SLOW_PLANET_KEYS:
            pid = SLOW_PLANET_IDS[pk]
            t_orbs = TRANSIT_ORBS.get(pk, {'conjunction': 4, 'opposition': 4, 'trine': 4, 'square': 4, 'sextile': 2})
            for sample_date in sample_dates:
                jd = swe.julday(sample_date.year, sample_date.month, sample_date.day, 12.0)
                t_pos = calculate_planet_position(jd, pid)
                if not t_pos:
                    continue
                t_lon = t_pos['longitude']
                for n_key, n_planet in natal_planets_data.items():
                    n_lon = n_planet.get('longitude') if isinstance(n_planet, dict) else n_planet
                    if n_lon is None:
                        continue
                    n_lon = float(n_lon)
                    diff = abs(t_lon - n_lon)
                    if diff > 180:
                        diff = 360 - diff
                    for asp in TRANSIT_ASPECT_DEFS:
                        orb_allowed = t_orbs.get(asp['key'], 2)
                        orb = abs(diff - asp['angle'])
                        if orb <= orb_allowed * 0.75:
                            aspect_key = f"{pk}-{asp['key']}-{n_key}"
                            if aspect_key in seen_aspects:
                                continue
                            seen_aspects.add(aspect_key)
                            exact_date_str = _refine_aspect_date(pid, n_lon, asp['angle'], sample_date, year)
                            transit_aspects.append({
                                'transitPlanet': PLANET_NAMES[pk], 'transitPlanetKey': pk,
                                'natalPlanet': PLANET_NAMES.get(n_key, n_key), 'natalPlanetKey': n_key,
                                'aspect': asp['name'], 'orb': round(orb, 2), 'angle': asp['angle'],
                                'exactDate': exact_date_str or sample_date.strftime('%Y-%m-%d'),
                            })
        transit_aspects.sort(key=lambda x: x.get('exactDate', ''))
        sign_changes = []
        for pk in SLOW_PLANET_KEYS:
            pid = SLOW_PLANET_IDS[pk]
            prev_sign = None
            prev_jd = None
            for month in range(1, 14):
                if month <= 12:
                    jd = swe.julday(year, month, 1, 12.0)
                else:
                    jd = swe.julday(year + 1, 1, 1, 12.0)
                pos = calculate_planet_position(jd, pid)
                if not pos:
                    continue
                if prev_sign and pos['sign'] != prev_sign and prev_jd is not None:
                    exact_iso = _refine_sign_change_date(pid, prev_jd, jd)
                    sign_changes.append({
                        'planet': PLANET_NAMES[pk],
                        'planetKey': pk,
                        'fromSign': prev_sign,
                        'toSign': pos['sign'],
                        'exactDate': exact_iso,
                        'approximateDate': exact_iso or f"{year}-{min(month,12):02d}-01",
                    })
                prev_sign = pos['sign']
                prev_jd = jd
        print(f"[yearly-transits] Year {year}: {len(transit_aspects)} aspects, {len(sign_changes)} sign changes")
        return {'year': year, 'monthlyPositions': monthly_positions, 'transitAspects': transit_aspects, 'signChanges': sign_changes, 'totalAspects': len(transit_aspects)}
    except Exception as e:
        print(f"[yearly-transits] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


def _refine_aspect_date(planet_id, natal_lon, aspect_angle, approx_date, year):
    try:
        from datetime import timedelta
        low_date = max(approx_date - timedelta(days=15), datetime(year, 1, 1))
        high_date = min(approx_date + timedelta(days=15), datetime(year, 12, 31))
        low_jd = swe.julday(low_date.year, low_date.month, low_date.day, 12.0)
        high_jd = swe.julday(high_date.year, high_date.month, high_date.day, 12.0)
        mid_jd = low_jd
        for _ in range(30):
            mid_jd = (low_jd + high_jd) / 2
            t_lon = swe.calc_ut(mid_jd, planet_id, swe.FLG_SWIEPH | swe.FLG_SPEED)[0][0]
            diff = t_lon - natal_lon
            if diff > 180: diff -= 360
            elif diff < -180: diff += 360
            if aspect_angle == 0: distance = abs(diff)
            elif aspect_angle == 180: distance = abs(abs(diff) - 180)
            else: distance = min(abs(diff - aspect_angle), abs(diff + aspect_angle))
            if distance < 0.01:
                break
            t_lon_plus = swe.calc_ut(mid_jd + 0.5, planet_id, swe.FLG_SWIEPH | swe.FLG_SPEED)[0][0]
            diff_plus = t_lon_plus - natal_lon
            if diff_plus > 180: diff_plus -= 360
            elif diff_plus < -180: diff_plus += 360
            if aspect_angle == 0: dist_plus = abs(diff_plus)
            elif aspect_angle == 180: dist_plus = abs(abs(diff_plus) - 180)
            else: dist_plus = min(abs(diff_plus - aspect_angle), abs(diff_plus + aspect_angle))
            if dist_plus < distance: low_jd = mid_jd
            else: high_jd = mid_jd
        result = swe.revjul(mid_jd)
        return f"{int(result[0])}-{int(result[1]):02d}-{int(result[2]):02d}"
    except Exception:
        return None


def _refine_sign_change_date(planet_id, low_jd, high_jd):
    """Binary-search the exact JD where the planet crosses into a new sign (30-deg boundary)."""
    try:
        low = low_jd
        high = high_jd
        start_sign = int(swe.calc_ut(low, planet_id, swe.FLG_SWIEPH)[0][0] // 30)
        for _ in range(40):
            mid = (low + high) / 2
            mid_sign = int(swe.calc_ut(mid, planet_id, swe.FLG_SWIEPH)[0][0] // 30)
            if mid_sign == start_sign:
                low = mid
            else:
                high = mid
            if (high - low) < (1.0 / 1440.0):  # ~1 minute
                break
        result = swe.revjul(high)
        return f"{int(result[0])}-{int(result[1]):02d}-{int(result[2]):02d}"
    except Exception:
        return None


@app.route('/yearly-transits', methods=['POST'])
def get_yearly_transits():
    try:
        data = request.get_json()
        natal_planets = data.get('natalPlanets', {})
        year = data.get('year', datetime.utcnow().year)
        if not natal_planets:
            return jsonify({'error': 'natalPlanets is required'}), 400
        result = calculate_yearly_transits(natal_planets, int(year), data.get('latitude'), data.get('longitude'))
        if not result:
            return jsonify({'error': 'Failed to calculate yearly transits'}), 500
        return jsonify({'success': True, **result})
    except Exception as e:
        print(f"[yearly-transits] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/calculate', methods=['POST'])
def calculate_natal_chart():
    """Calculate natal chart from birth data"""
    try:
        data = request.get_json()
        
        # Parse input
        birth_date = data.get('birthDate')  # YYYY-MM-DD
        birth_time = data.get('birthTime')  # HH:MM (LOCAL TIME)
        latitude = float(data.get('latitude'))
        longitude = float(data.get('longitude'))
        timezone = data.get('timezone', 'UTC')
        
        # Optional: Solar Return location (if different from birth)
        sr_latitude = data.get('solarReturnLatitude', latitude)
        sr_longitude = data.get('solarReturnLongitude', longitude)
        sr_year = data.get('solarReturnYear', datetime.utcnow().year)
        include_progressions = data.get('includeProgressions', True)
        include_solar_return = data.get('includeSolarReturn', True)
        
        # Parse date and time (LOCAL)
        year, month, day = map(int, birth_date.split('-'))
        hour, minute = map(int, birth_time.split(':'))
        
        print(f"[calc] Input LOCAL time: {year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d} ({timezone})")
        print(f"[calc] Coordinates: lat={latitude}, lon={longitude}")
        
        # Convert local time to UTC for ephemeris calculations
        utc_year, utc_month, utc_day, utc_hour, utc_minute = convert_local_to_utc(
            year, month, day, hour, minute, timezone
        )
        
        print(f"[calc] Converted to UTC: {utc_year}-{utc_month:02d}-{utc_day:02d} {int(utc_hour):02d}:{utc_minute:05.2f}")
        
        # Calculate Julian Day using UTC time
        julian_day = calculate_julian_day(utc_year, utc_month, utc_day, utc_hour, utc_minute)
        print(f"[calc] Julian Day: {julian_day:.6f}")
        
        # Calculate houses first (needed for planet house placement)
        houses_data = calculate_houses(julian_day, latitude, longitude)
        if not houses_data:
            return jsonify({'error': 'Failed to calculate houses'}), 500
        
        print(f"[calc] Houses calculated successfully")
        
        # Calculate planets with house placement
        planets = {}
        failed_planets = []
        north_node_position = None  # Store for calculating South Node
        
        for planet_key, planet_id in PLANETS.items():
            # Skip south_node for now, calculate after north_node
            if planet_key == 'south_node':
                continue
                
            position = calculate_planet_position(julian_day, planet_id)
            if position:
                # Add house placement
                house_num = get_house_for_planet(position['longitude'], houses_data['houses'])
                planets[planet_key] = {
                    'name': PLANET_NAMES[planet_key],
                    'house': house_num,
                    **position
                }
                # Store north node position for south node calculation
                if planet_key == 'north_node':
                    north_node_position = position
            else:
                failed_planets.append(planet_key)
                print(f"[calc] WARNING: Failed to calculate {planet_key}")
        
        # Calculate South Node as opposite of North Node (180° apart)
        if north_node_position:
            south_lon = (north_node_position['longitude'] + 180) % 360
            south_sign_info = get_sign(south_lon)
            south_house = get_house_for_planet(south_lon, houses_data['houses'])
            planets['south_node'] = {
                'name': PLANET_NAMES['south_node'],
                'house': south_house,
                'longitude': round(south_lon, 6),
                'latitude': round(-north_node_position['latitude'], 6),  # Opposite latitude
                'distance': north_node_position['distance'],
                'speed': north_node_position['speed'],  # Same speed as north node
                'degree_dms': format_dms(south_sign_info['degree']),
                **south_sign_info
            }
        
        print(f"[calc] Calculated {len(planets)}/{len(PLANETS)} planets successfully")
        if failed_planets:
            print(f"[calc] FAILED planets: {failed_planets}")
        
        # Calculate aspects (including to angles)
        aspects = calculate_aspects(
            planets, 
            ascendant_lon=houses_data['ascendant']['longitude'],
            mc_lon=houses_data['mc']['longitude']
        )
        print(f"[calc] Calculated {len(aspects)} aspects")
        
        # Prepare base response
        chart_data = {
            'birthInfo': {
                'date': birth_date,
                'time': birth_time,
                'latitude': latitude,
                'longitude': longitude,
                'timezone': timezone,
                'julianDay': round(julian_day, 6),
                'utcTime': f"{utc_year}-{utc_month:02d}-{utc_day:02d} {int(utc_hour):02d}:{int(utc_minute):02d} UT"
            },
            'planets': planets,
            'houses': houses_data['houses'],
            'ascendant': houses_data['ascendant'],
            'mc': houses_data['mc'],
            'vertex': houses_data['vertex'],
            'aspects': aspects,
            'calculatedAt': datetime.utcnow().isoformat() + 'Z',
            'precision': 'high',
            'ephemeris': 'Swiss Ephemeris'
        }
        
        # Calculate Progressed Moon (Secondary Progression)
        if include_progressions:
            current_date = datetime.utcnow().strftime('%Y-%m-%d')
            progressed_moon = calculate_progressed_moon(julian_day, current_date)
            if progressed_moon:
                chart_data['progressedMoon'] = progressed_moon
                print(f"[calc] Progressed Moon: {progressed_moon['sign']} {progressed_moon['degree_dms']}")
        
        # Calculate Solar Return for specified year
        if include_solar_return and planets.get('sun'):
            natal_sun_longitude = planets['sun']['longitude']
            solar_return = calculate_solar_return(
                julian_day, 
                natal_sun_longitude, 
                int(sr_year),
                float(sr_latitude),
                float(sr_longitude)
            )
            if solar_return:
                chart_data['solarReturn'] = solar_return
                print(f"[calc] Solar Return {sr_year}: ASC {solar_return['ascendant']['sign']}")
        
        return jsonify({'success': True, 'chartData': chart_data})
        
    except Exception as e:
        print(f"[calc] ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"[server] Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
