from flask import Flask, request, jsonify
from flask_cors import CORS
import swisseph as swe
from datetime import datetime
import os

app = Flask(__name__)
CORS(app)

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
    'lilith': swe.MEAN_APOG,
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
    'lilith': 'Lilith',
}

SIGNS = [
    'Aries', 'Tauro', 'Géminis', 'Cáncer', 'Leo', 'Virgo',
    'Libra', 'Escorpio', 'Sagitario', 'Capricornio', 'Acuario', 'Piscis'
]

def get_sign(longitude):
    normalized_lon = longitude % 360
    if normalized_lon < 0:
        normalized_lon += 360
    sign_index = int(normalized_lon / 30)
    degree = normalized_lon % 30
    return {'sign': SIGNS[sign_index], 'degree': round(degree, 2)}

def calculate_julian_day(year, month, day, hour, minute):
    decimal_time = hour + minute / 60.0
    jd = swe.julday(year, month, day, decimal_time)
    return jd

def calculate_planet_position(julian_day, planet_id):
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
            **sign_info
        }
    except Exception as e:
        print(f"Error calculating planet {planet_id}: {e}")
        return None

def calculate_houses(julian_day, latitude, longitude):
    try:
        houses, ascmc = swe.houses(julian_day, latitude, longitude, b'P')
        house_list = []
        house_names = [
            'Casa 1 (Ascendente)', 'Casa 2', 'Casa 3', 'Casa 4 (IC)',
            'Casa 5', 'Casa 6', 'Casa 7 (Descendente)', 'Casa 8',
            'Casa 9', 'Casa 10 (MC)', 'Casa 11', 'Casa 12'
        ]
        for i in range(12):
            cusp = houses[i]
            sign_info = get_sign(cusp)
            house_list.append({
                'house': house_names[i],
                'cusp': round(cusp, 6),
                **sign_info
            })
        ascendant = ascmc[0]
        mc = ascmc[1]
        return {
            'houses': house_list,
            'ascendant': {'longitude': round(ascendant, 6), **get_sign(ascendant)},
            'mc': {'longitude': round(mc, 6), **get_sign(mc)}
        }
    except Exception as e:
        print(f"Error calculating houses: {e}")
        return None

def calculate_aspects(planets):
    aspects = []
    planet_keys = list(planets.keys())
    aspect_orbs = {
        'conjunction': {'angle': 0, 'orb': 8, 'name': 'Conjunción'},
        'opposition': {'angle': 180, 'orb': 8, 'name': 'Oposición'},
        'trine': {'angle': 120, 'orb': 8, 'name': 'Trígono'},
        'square': {'angle': 90, 'orb': 8, 'name': 'Cuadratura'},
        'sextile': {'angle': 60, 'orb': 6, 'name': 'Sextil'},
    }
    for i in range(len(planet_keys)):
        for j in range(i + 1, len(planet_keys)):
            planet1_key = planet_keys[i]
            planet2_key = planet_keys[j]
            if not planets[planet1_key] or not planets[planet2_key]:
                continue
            lon1 = planets[planet1_key]['longitude']
            lon2 = planets[planet2_key]['longitude']
            diff = abs(lon1 - lon2)
            if diff > 180:
                diff = 360 - diff
            for aspect_type, aspect_data in aspect_orbs.items():
                orb = abs(diff - aspect_data['angle'])
                if orb <= aspect_data['orb']:
                    aspects.append({
                        'planet1': PLANET_NAMES[planet1_key],
                        'planet2': PLANET_NAMES[planet2_key],
                        'aspect': aspect_data['name'],
                        'orb': round(orb, 2),
                        'angle': aspect_data['angle']
                    })
    return aspects

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'service': 'swiss-ephemeris'})

@app.route('/calculate', methods=['POST'])
def calculate_natal_chart():
    try:
        data = request.get_json()
        birth_date = data.get('birthDate')
        birth_time = data.get('birthTime')
        latitude = float(data.get('latitude'))
        longitude = float(data.get('longitude'))
        timezone = data.get('timezone', 'UTC')
        year, month, day = map(int, birth_date.split('-'))
        hour, minute = map(int, birth_time.split(':'))
        julian_day = calculate_julian_day(year, month, day, hour, minute)
        planets = {}
        for planet_key, planet_id in PLANETS.items():
            position = calculate_planet_position(julian_day, planet_id)
            if position:
                planets[planet_key] = {'name': PLANET_NAMES[planet_key], **position}
        houses_data = calculate_houses(julian_day, latitude, longitude)
        if not houses_data:
            return jsonify({'error': 'Failed to calculate houses'}), 500
        aspects = calculate_aspects(planets)
        chart_data = {
            'birthInfo': {
                'date': birth_date,
                'time': birth_time,
                'latitude': latitude,
                'longitude': longitude,
                'timezone': timezone,
                'julianDay': round(julian_day, 6)
            },
            'planets': planets,
            'houses': houses_data['houses'],
            'ascendant': houses_data['ascendant'],
            'mc': houses_data['mc'],
            'aspects': aspects,
            'calculatedAt': datetime.utcnow().isoformat() + 'Z',
            'precision': 'high',
            'ephemeris': 'Swiss Ephemeris'
        }
        return jsonify({'success': True, 'chartData': chart_data})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
