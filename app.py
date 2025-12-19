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
        'sextile': {'angle': 60, 'orb': 4, 'name': 'Sextil'},
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
                    aspects.append({
                        'planet1': PLANET_NAMES[planet1_key],
                        'planet2': PLANET_NAMES[planet2_key],
                        'aspect': aspect_data['name'],
                        'orb': round(orb, 2),
                        'angle': aspect_data['angle'],
                        'applying': applying,
                        'type': 'planet-planet'
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
                        'type': 'planet-angle'
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
                        'type': 'planet-angle'
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
        for planet_key, planet_id in PLANETS.items():
            position = calculate_planet_position(julian_day, planet_id)
            if position:
                # Add house placement
                house_num = get_house_for_planet(position['longitude'], houses_data['houses'])
                planets[planet_key] = {
                    'name': PLANET_NAMES[planet_key],
                    'house': house_num,
                    **position
                }
            else:
                failed_planets.append(planet_key)
                print(f"[calc] WARNING: Failed to calculate {planet_key}")
        
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
        
        # Prepare response
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
