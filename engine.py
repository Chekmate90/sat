import math
from datetime import datetime, timezone, timedelta
from itertools import combinations

import requests
from sgp4.api import Satrec, jday
from sgp4 import omm


URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=last-30-days&FORMAT=json"

OBJECT_LIMIT = 120

SCAN_MINUTES = 60
COARSE_STEP = 5
FINE_STEP_SECONDS = 10

SCREENING_THRESHOLD = 150

VISUALIZATION_LIMIT = 10
ORBIT_DURATION_MINUTES = 90
ORBIT_SAMPLE_MINUTES = 5

def create_satellite(data):
    satellite = Satrec()
    omm.initialize(satellite, data)
    return satellite


def calculate_distance(a, b):
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    dz = b[2] - a[2]

    return math.sqrt(dx**2 + dy**2 + dz**2)


def calculate_risk(distance):
    if distance < 1:
        return "CRITICAL"
    elif distance < 5:
        return "HIGH"
    elif distance < 25:
        return "MEDIUM"
    elif distance < 100:
        return "LOW"
    else:
        return "SAFE"


def get_position(satellite, time):
    jd, fr = jday(
        time.year,
        time.month,
        time.day,
        time.hour,
        time.minute,
        time.second + time.microsecond / 1_000_000
    )

    error, position, _ = satellite.sgp4(jd, fr)

    if error != 0:
        return None

    return position

def gen_orbit_paths(satellites, start_time):
    orbit_paths = []
    
    for object_data, satellite in satellites[:VISUALIZATION_LIMIT]:
        points = []
        
        for minute in range(0,ORBIT_DURATION_MINUTES+1,ORBIT_SAMPLE_MINUTES):
            sample_time = start_time + timedelta(minutes=minute)
            position = get_position(satellite, sample_time)

            if position is None:
                continue
                
            points.append({
                "x": round(position[0], 2),
                "y": round(position[1], 2),
                "z": round(position[2], 2),
                "time": sample_time.isoformat()
            })
            
        if points:
            orbit_paths.append({
                "name": object_data["OBJECT_NAME"],
                "norad_id": object_data["NORAD_CAT_ID"],
                "points": points
            })
    
    return orbit_paths




def find_conjunctions():

    try:
        response = requests.get(URL, timeout=15)
        response.raise_for_status()
        objects = response.json()

    except requests.RequestException as e:
        print("CelesTrak request failed:", e)
        return None
        
    objects = objects[:OBJECT_LIMIT]
    satellites = []

    for obj in objects:
        satellites.append(
            (obj, create_satellite(obj))
        )

    now = datetime.now(timezone.utc)

    pairs = list(combinations(satellites, 2))

    print(f"Objects: {len(objects)}")
    print(f"Pairs: {len(pairs)}")
    print()

    conjunctions = []

    for pair_number, ((object_a, sat_a), (object_b, sat_b)) in enumerate(pairs, 1):

        if pair_number % 100 == 0:
            print(
                f"Checking pair "
                f"{pair_number}/{len(pairs)}"
            )

        coarse_distance = float("inf")
        coarse_time = None

        # COARSE SEARCH

        for minute in range(
            0,
            SCAN_MINUTES + 1,
            COARSE_STEP
        ):

            future = now + timedelta(minutes=minute)

            position_a = get_position(
                sat_a,
                future
            )

            position_b = get_position(
                sat_b,
                future
            )

            if position_a is None or position_b is None:
                continue

            distance = calculate_distance(
                position_a,
                position_b
            )

            if distance < coarse_distance:
                coarse_distance = distance
                coarse_time = future

        # Ignore distant pairs

        if coarse_distance > SCREENING_THRESHOLD:
            continue

        # FINE SEARCH

        search_start = (
            coarse_time
            - timedelta(minutes=COARSE_STEP)
        )

        search_end = (
            coarse_time
            + timedelta(minutes=COARSE_STEP)
        )

        closest_distance = float("inf")
        closest_time = None

        current_time = search_start

        while current_time <= search_end:

            position_a = get_position(
                sat_a,
                current_time
            )

            position_b = get_position(
                sat_b,
                current_time
            )

            if position_a is not None and position_b is not None:

                distance = calculate_distance(
                    position_a,
                    position_b
                )

                if distance < closest_distance:
                    closest_distance = distance
                    closest_time = current_time

            current_time += timedelta(
                seconds=FINE_STEP_SECONDS
            )

        if closest_distance < SCREENING_THRESHOLD:

            time_until = closest_time - now

            conjunctions.append({
                "id": len(conjunctions) + 1,
                "object_a": object_a["OBJECT_NAME"],
                "object_b": object_b["OBJECT_NAME"],
                "norad_a": object_a["NORAD_CAT_ID"],
                "norad_b": object_b["NORAD_CAT_ID"],
                "distance_km": round(
                    closest_distance,
                    2
                ),
                "time_until_seconds": int(
                    time_until.total_seconds()
                ),
                "risk": calculate_risk(
                    closest_distance
                )
            })

    return {
        "objects_tracked": len(objects),
        "conjunctions": conjunctions,
        "orbit_paths": gen_orbit_paths(
            satellites,
            now
        )
    }



if __name__ == "__main__":
    results = find_conjunctions()

    print()
    print("CONJUNCTIONS FOUND")
    print("-------------------")

    for event in results:
        print(event)

    print()
    print(f"Potential conjunctions: {len(results)}")