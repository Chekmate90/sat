import json
import math
from datetime import datetime, timezone, timedelta
from itertools import combinations

import requests
from sgp4.api import Satrec, jday
from sgp4 import omm

# --- CONFIGURATION & CONSTANTS ---
URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=last-30-days&FORMAT=json"

# Because of our O(n) filters, we can significantly increase the object limit!
OBJECT_LIMIT = 200

SCAN_MINUTES = 1440 # Scan 24 hours into the future for the MVP
COARSE_STEP = 5
FINE_STEP_SECONDS = 10

SCREENING_THRESHOLD = 120 # km distance to flag as a conjunction

# Multi-Tiered Filter Thresholds
RADIAL_BUFFER_KM = 20
MOID_THRESHOLD_KM = 150 
EARTH_RADIUS_KM = 6371.0
CELL_SIZE = 150 # Spatial hashing 3D grid size (km)

ORBIT_DURATION_MINUTES = 90
ORBIT_SAMPLE_MINUTES = 5


# --- SATELLITE & MATH UTILITIES ---

def create_satellite(data):
    satellite = Satrec()
    omm.initialize(satellite, data)
    return satellite

def calculate_distance(a, b):
    return math.sqrt((b[0] - a[0])**2 + (b[1] - a[1])**2 + (b[2] - a[2])**2)

def calculate_risk(distance):
    if distance < 1: return "CRITICAL"
    elif distance < 5: return "HIGH"
    elif distance < 25: return "MEDIUM"
    elif distance < 100: return "LOW"
    else: return "SAFE"

def get_position(satellite, time):
    jd, fr = jday(
        time.year, time.month, time.day,
        time.hour, time.minute, time.second + time.microsecond / 1_000_000
    )
    error, position, _ = satellite.sgp4(jd, fr)
    return position if error == 0 else None

def gen_orbit_paths(satellites, start_time):
    orbit_paths = []
    for object_data, satellite in satellites:
        points = []
        for minute in range(0, ORBIT_DURATION_MINUTES+1, ORBIT_SAMPLE_MINUTES):
            sample_time = start_time + timedelta(minutes=minute)
            position = get_position(satellite, sample_time)
            if position:
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


# --- STAGE 1 & 2: THE GEOMETRY FILTERS ---

def get_apogee_perigee(satellite):
    """Calculates Apogee and Perigee in km from SGP4 Keplerian elements."""
    mean_motion_rad_sec = satellite.no_kozai / 60.0
    mu = 398600.4418 # Earth's gravitational constant (km^3/s^2)
    
    try:
        a = (mu / (mean_motion_rad_sec**2)) ** (1.0/3.0) # Semi-major axis
    except ZeroDivisionError:
        return 0, 0 
        
    perigee_alt = (a * (1 - satellite.ecco)) - EARTH_RADIUS_KM
    apogee_alt = (a * (1 + satellite.ecco)) - EARTH_RADIUS_KM
    return apogee_alt, perigee_alt

def radial_filter_passes(sat_a, sat_b):
    """Discards pairs whose altitudes never overlap."""
    apogee_a, perigee_a = get_apogee_perigee(sat_a)
    apogee_b, perigee_b = get_apogee_perigee(sat_b)
    
    if (perigee_a - RADIAL_BUFFER_KM) > apogee_b: return False
    if (perigee_b - RADIAL_BUFFER_KM) > apogee_a: return False
    return True

def calculate_moid(sat_a, sat_b, now):
    """Fast numerical approximation of MOID by sampling orbits for one full period."""
    period_a = (2 * math.pi) / sat_a.no_kozai if sat_a.no_kozai > 0 else 100
    period_b = (2 * math.pi) / sat_b.no_kozai if sat_b.no_kozai > 0 else 100
    
    points_a, points_b = [], []
    
    # Sample 20 points along the physical orbit track
    for i in range(20):
        pos_a = get_position(sat_a, now + timedelta(minutes=(i/20.0)*period_a))
        if pos_a: points_a.append(pos_a)
            
        pos_b = get_position(sat_b, now + timedelta(minutes=(i/20.0)*period_b))
        if pos_b: points_b.append(pos_b)

    min_dist = float('inf')
    for pa in points_a:
        for pb in points_b:
            d = calculate_distance(pa, pb)
            if d < min_dist: min_dist = d
                
    return min_dist


# --- MAIN ENGINE LOOP ---

def find_conjunctions(object_limit=OBJECT_LIMIT, scan_minutes=SCAN_MINUTES):
    try:
        print("Downloading TLEs from CelesTrak...")
        response = requests.get(URL, timeout=15)
        response.raise_for_status()
        objects = response.json()[:object_limit]
    except requests.RequestException as e:
        print("CelesTrak request failed:", e)
        print("Loading sample data...")
        try:
            with open("sample_data_feb142026.json", "r") as f:
                objects = json.load(f)[:object_limit]
        except Exception as e2:
             print("Failed to load sample data:", e2)
             return None
        
    satellites = [(obj, create_satellite(obj)) for obj in objects]
    now = datetime.now(timezone.utc)
    all_pairs = list(combinations(satellites, 2))

    print(f"\n--- FUNNEL OPTIMIZATION STATS ---")
    print(f"Total Objects Tracked: {len(objects)}")
    print(f"Initial nC2 Pairs: {len(all_pairs)}")

    # 1. APPLY PRE-PROPAGATION FILTERS (The Funnel)
    filtered_pairs = []
    valid_pair_ids = set()
    active_satellites = {}
    
    radial_passed = 0
    
    for (obj_a, sat_a), (obj_b, sat_b) in all_pairs:
        # Filter 1: Radial (Altitude)
        if not radial_filter_passes(sat_a, sat_b): continue
        radial_passed += 1
        
        # Filter 2: MOID (Path Intersection)
        if calculate_moid(sat_a, sat_b, now) > MOID_THRESHOLD_KM: continue
        
        filtered_pairs.append(((obj_a, sat_a), (obj_b, sat_b)))
        
        id_a, id_b = obj_a["NORAD_CAT_ID"], obj_b["NORAD_CAT_ID"]
        valid_pair_ids.add(tuple(sorted([id_a, id_b])))
        active_satellites[id_a] = (obj_a, sat_a)
        active_satellites[id_b] = (obj_b, sat_b)

    print(f"Pairs surviving Radial Filter: {radial_passed}")
    print(f"Pairs surviving MOID Filter: {len(filtered_pairs)}")
    print(f"Total Eliminated before Time Loop: {len(all_pairs) - len(filtered_pairs)}")
    print("---------------------------------\n")

    # 2. THE TIME LOOP & SPATIAL HASHING
    coarse_results = {}
    
    print(f"Initiating Spatial Hashing Loop for next {scan_minutes} minutes...")
    
    for minute in range(0, scan_minutes + 1, COARSE_STEP):
        future = now + timedelta(minutes=minute)
        grid = {}
        positions = {}
        
        # Hash active satellites into the 3D grid
        for norad_id, (obj, sat) in active_satellites.items():
            pos = get_position(sat, future)
            if pos:
                positions[norad_id] = pos
                cell = (int(pos[0] // CELL_SIZE), int(pos[1] // CELL_SIZE), int(pos[2] // CELL_SIZE))
                if cell not in grid: grid[cell] = []
                grid[cell].append(norad_id)
        
        # Check for collisions in same and adjacent cells
        checked_this_step = set()
        for (cx, cy, cz), sats_in_cell in grid.items():
            
            # Generate 27 grid checks (Center + 26 neighbors)
            neighbors = [(cx+dx, cy+dy, cz+dz) for dx in [-1,0,1] for dy in [-1,0,1] for dz in [-1,0,1]]
            
            for neighbor in neighbors:
                if neighbor in grid:
                    for id_a in sats_in_cell:
                        for id_b in grid[neighbor]:
                            if id_a == id_b: continue
                            
                            pair_key = tuple(sorted([id_a, id_b]))
                            if pair_key in checked_this_step: continue
                            checked_this_step.add(pair_key)
                            
                            # Execute Math ONLY if they passed geometry filters and share a cell
                            if pair_key in valid_pair_ids:
                                dist = calculate_distance(positions[id_a], positions[id_b])
                                if dist <= SCREENING_THRESHOLD:
                                    if pair_key not in coarse_results or dist < coarse_results[pair_key]["distance"]:
                                        coarse_results[pair_key] = {
                                            "sat_a": active_satellites[id_a],
                                            "sat_b": active_satellites[id_b],
                                            "time": future,
                                            "distance": dist
                                        }

    # 3. THE FINE SEARCH
    conjunctions = []
    
    for pair_key, data in coarse_results.items():
        obj_a, sat_a = data["sat_a"]
        obj_b, sat_b = data["sat_b"]
        
        search_start = data["time"] - timedelta(minutes=COARSE_STEP)
        search_end = data["time"] + timedelta(minutes=COARSE_STEP)
        
        closest_dist = float("inf")
        closest_time = None
        current = search_start
        
        while current <= search_end:
            pos_a = get_position(sat_a, current)
            pos_b = get_position(sat_b, current)
            
            if pos_a and pos_b:
                d = calculate_distance(pos_a, pos_b)
                if d < closest_dist:
                    closest_dist = d
                    closest_time = current
            current += timedelta(seconds=FINE_STEP_SECONDS)
            
        if closest_dist <= SCREENING_THRESHOLD:
            conjunctions.append({
                "id": len(conjunctions) + 1,
                "object_a": obj_a["OBJECT_NAME"],
                "object_b": obj_b["OBJECT_NAME"],
                "norad_a": obj_a["NORAD_CAT_ID"],
                "norad_b": obj_b["NORAD_CAT_ID"],
                "distance_km": round(closest_dist, 2),
                "time_until_seconds": int((closest_time - now).total_seconds()),
                "risk": calculate_risk(closest_dist)
            })

    conjunction_satellites = []
    for pair_key, data in coarse_results.items():
        conjunction_satellites.extend([data["sat_a"], data["sat_b"]])

    return {
        "objects_tracked": len(objects),
        "conjunctions": conjunctions,
        "orbit_paths": gen_orbit_paths(conjunction_satellites, now)
    }

if __name__ == "__main__":
    results = find_conjunctions()
    
    print("\nCONJUNCTIONS FOUND")
    print("-------------------")
    for event in results["conjunctions"]:
        print(event)
    print(f"\nTotal potential conjunctions: {len(results['conjunctions'])}")
