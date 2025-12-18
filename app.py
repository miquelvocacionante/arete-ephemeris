from flask import Flask, request, jsonify
from flask_cors import CORS
import swisseph as swe
from datetime import datetime
import os
import pytz

app = Flask(__name__)
CORS(app)

# Set Swiss Ephemeris path (adjust if needed)
swe.set_ephe_path(os.path.join(os.path.dirname(__file__), 'ephe'))

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
    """Get zodiac sign from longitude"""
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
        
        print(f"Local time: {local_dt.strftime('%Y-%m-%d %H:%M %Z')} -> UTC: {utc_dt.strftime('%Y-%m-%d %H:%M %Z')}")
        
        return (
            utc_dt.year,
            utc_dt.month,
            utc_dt.day,
            utc_dt.hour,
            utc_dt.minute + utc_dt.second / 60.0
        )
    except Exception as e:
        print(f"Error converting timezone: {e}. Using input time as UTC.")
        return (year, month, day, hour, minute)

def calculate_julian_day(year, month, day, hour, minute):
    """Calculate Julian Day from UTC time"""
    decimal_time = hour + minute / 60.0
    jd = swe.julday(year, month, day, decimal_time)
    return jd

def calculate_planet_position(julian_day, planet_id):
    """Calculate planet position"""
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
        print(f"Error calculating planet {planet_id}: {e}")
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
        print(f"Error calculating houses: {e}")
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

def is_aspect_applying(planet1_lon, planet1_speed, planet2_lon, planet2_speed, aspect_angle):
    """
    Determine if an aspect is applying (A) or separating (S).
    An aspect is applying when the faster planet is moving toward the exact aspect.
    """
    # Calculate the current angular distance
    diff = planet1_lon - planet2_lon
    if diff < 0:
        diff += 360
    if diff > 180:
        diff = 360 - diff
    
    # Calculate relative speed (positive means planet1 is moving faster toward planet2)
    relative_speed = planet1_speed - planet2_speed
    
    # Calculate distance to exact aspect
    distance_to_exact = abs(diff - aspect_angle)
    
    # Future position after a small time increment
    future_diff = (planet1_lon + planet1_speed * 0.1) - (planet2_lon + planet2_speed * 0.1)
    if future_diff < 0:
        future_diff += 360
    if future_diff > 180:
        future_diff = 360 - future_diff
    
    future_distance = abs(future_diff - aspect_angle)
    
    # If future distance is smaller, the aspect is applying
    return 'A' if future_distance < distance_to_exact else 'S'

def calculate_aspects(planets, ascendant_lon=None, mc_lon=None):
    """Calculate aspects between planets and to angles"""
    aspects = []
    planet_keys = list(planets.keys())
    
    aspect_orbs = {
        'conjunction': {'angle': 0, 'orb': 8, 'name': 'Conjunción'},
        'opposition': {'angle': 180, 'orb': 8, 'name': 'Oposición'},
        'trine': {'angle': 120, 'orb': 8, 'name': 'Trígono'},
        'square': {'angle': 90, 'orb': 8, 'name': 'Cuadratura'},
        'sextile': {'angle': 60, 'orb': 6, 'name': 'Sextil'},
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
            
            diff = abs(lon1 - lon2)
            if diff > 180:
                diff = 360 - diff
            
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

@app.route('/calculate', methods=['POST'])
def calculate_natal_chart():
    """Calculate natal chart"""
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
        
        print(f"Input LOCAL time: {year}-{month}-{day} {hour}:{minute} ({timezone}) at lat={latitude}, lon={longitude}")
        
        # Convert local time to UTC for ephemeris calculations
        utc_year, utc_month, utc_day, utc_hour, utc_minute = convert_local_to_utc(
            year, month, day, hour, minute, timezone
        )
        
        print(f"Converted to UTC: {utc_year}-{utc_month}-{utc_day} {utc_hour}:{utc_minute:.2f}")
        
        # Calculate Julian Day using UTC time
        julian_day = calculate_julian_day(utc_year, utc_month, utc_day, utc_hour, utc_minute)
        print(f"Julian Day (UT): {julian_day}")
        
        # Calculate houses first (needed for planet house placement)
        houses_data = calculate_houses(julian_day, latitude, longitude)
        if not houses_data:
            return jsonify({'error': 'Failed to calculate houses'}), 500
        
        print("Houses calculated")
        
        # Calculate planets with house placement
        planets = {}
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
        
        print(f"Calculated {len(planets)} planets")
        
        # Calculate aspects (including to angles)
        aspects = calculate_aspects(
            planets, 
            ascendant_lon=houses_data['ascendant']['longitude'],
            mc_lon=houses_data['mc']['longitude']
        )
        print(f"Calculated {len(aspects)} aspects")
        
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
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
