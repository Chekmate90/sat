import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from itertools import combinations

import numpy as np
import requests
from sgp4.api import Satrec, SatrecArray, jday
from sgp4 import omm

# --- CONFIGURATION & CONSTANTS ---
URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=last-30-days&FORMAT=json"

# Because of our O(n) filters, we can significantly increase the object limit!
OBJECT_LIMIT = 500

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

# Fine-search candidates are independent and SGP4 performs their propagation in
# native code, so a bounded thread pool can refine them concurrently.
MAX_WORKERS = min(32, (os.cpu_count() or 1) + 4)


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

def _julian_date_arrays(start_time, offsets_seconds):
    jd_start, fr_start = jday(
        start_time.year, start_time.month, start_time.day,
        start_time.hour, start_time.minute,
        start_time.second + start_time.microsecond / 1_000_000,
    )
    fractions = fr_start + np.asarray(offsets_seconds, dtype=float) / 86400.0
    day_offsets = np.floor(fractions)
    return jd_start + day_offsets, fractions - day_offsets


def gen_orbit_paths(satellites, start_time):
    unique_satellites = {}
    for object_data, satellite in satellites:
        unique_satellites.setdefault(
            object_data["NORAD_CAT_ID"],
            (object_data, satellite),
        )

    satellite_data = list(unique_satellites.values())
    if not satellite_data:
        return []

    offsets_minutes = np.arange(
        0,
        ORBIT_DURATION_MINUTES + 1,
        ORBIT_SAMPLE_MINUTES,
        dtype=float,
    )
    jd, fr = _julian_date_arrays(start_time, offsets_minutes * 60.0)
    satellite_array = SatrecArray([satellite for _, satellite in satellite_data])
    errors, positions, _ = satellite_array.sgp4(jd, fr)

    orbit_paths = []
    for satellite_index, (object_data, _) in enumerate(satellite_data):
        points = []
        for time_index, minute in enumerate(offsets_minutes):
            if errors[satellite_index, time_index] != 0:
                continue

            sample_time = start_time + timedelta(minutes=float(minute))
            position = positions[satellite_index, time_index]
            points.append({
                "x": round(float(position[0]), 2),
                "y": round(float(position[1]), 2),
                "z": round(float(position[2]), 2),
                "time": sample_time.isoformat(),
            })

        if points:
            orbit_paths.append({
                "name": object_data["OBJECT_NAME"],
                "norad_id": object_data["NORAD_CAT_ID"],
                "points": points,
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

    return _radial_bounds_overlap(
        apogee_a, perigee_a, apogee_b, perigee_b
    )


def _radial_bounds_overlap(apogee_a, perigee_a, apogee_b, perigee_b):
    if (perigee_a - RADIAL_BUFFER_KM) > apogee_b:
        return False
    if (perigee_b - RADIAL_BUFFER_KM) > apogee_a:
        return False
    return True


def _sample_moid_track(satellite, now):
    period_minutes = (
        (2 * math.pi) / satellite.no_kozai
        if satellite.no_kozai > 0
        else 100
    )
    offsets_seconds = np.arange(20, dtype=float) * period_minutes * 3.0
    jd, fr = _julian_date_arrays(now, offsets_seconds)
    errors, positions, _ = satellite.sgp4_array(jd, fr)
    return positions[errors == 0]


def _calculate_moid_from_tracks(points_a, points_b):
    if len(points_a) == 0 or len(points_b) == 0:
        return float("inf")

    deltas = points_a[:, np.newaxis, :] - points_b[np.newaxis, :, :]
    distances_squared = np.einsum("ijk,ijk->ij", deltas, deltas)
    return float(np.sqrt(np.min(distances_squared)))

def calculate_moid(sat_a, sat_b, now):
    """Fast numerical approximation of MOID by sampling orbits for one full period."""
    return _calculate_moid_from_tracks(
        _sample_moid_track(sat_a, now),
        _sample_moid_track(sat_b, now),
    )


def _precompute_orbital_data(satellite_data, now):
    _, satellite = satellite_data
    apogee, perigee = get_apogee_perigee(satellite)
    return id(satellite), {
        "apogee": apogee,
        "perigee": perigee,
        "moid_track": _sample_moid_track(satellite, now),
    }


def _filter_pairs(pairs, orbital_data):
    filtered_pairs = []
    radial_passed = 0

    for (obj_a, sat_a), (obj_b, sat_b) in pairs:
        data_a = orbital_data[id(sat_a)]
        data_b = orbital_data[id(sat_b)]

        if not _radial_bounds_overlap(
            data_a["apogee"],
            data_a["perigee"],
            data_b["apogee"],
            data_b["perigee"],
        ):
            continue
        radial_passed += 1

        moid = _calculate_moid_from_tracks(
            data_a["moid_track"],
            data_b["moid_track"],
        )
        if moid <= MOID_THRESHOLD_KM:
            filtered_pairs.append(((obj_a, sat_a), (obj_b, sat_b)))

    return radial_passed, filtered_pairs


def _scan_coarse_step(
    active_entries,
    active_satellites,
    valid_pair_ids,
    future,
    propagation_errors,
    propagated_positions,
):
    grid = {}
    positions = {}

    for index, (norad_id, _, _) in enumerate(active_entries):
        if propagation_errors[index] != 0:
            continue

        position = propagated_positions[index]
        positions[norad_id] = position
        cell = tuple(int(coordinate // CELL_SIZE) for coordinate in position)
        grid.setdefault(cell, []).append(norad_id)

    results = {}
    checked_pairs = set()
    for (cx, cy, cz), satellites_in_cell in grid.items():
        neighbors = (
            (cx + dx, cy + dy, cz + dz)
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for dz in (-1, 0, 1)
        )

        for neighbor in neighbors:
            for id_a in satellites_in_cell:
                for id_b in grid.get(neighbor, ()):
                    if id_a == id_b:
                        continue

                    pair_key = tuple(sorted((id_a, id_b)))
                    if pair_key in checked_pairs:
                        continue
                    checked_pairs.add(pair_key)

                    if pair_key not in valid_pair_ids:
                        continue

                    distance = calculate_distance(positions[id_a], positions[id_b])
                    if distance <= SCREENING_THRESHOLD:
                        results[pair_key] = {
                            "sat_a": active_satellites[id_a],
                            "sat_b": active_satellites[id_b],
                            "time": future,
                            "distance": distance,
                        }

    return results


def _refine_conjunction(data, now):
    obj_a, sat_a = data["sat_a"]
    obj_b, sat_b = data["sat_b"]

    search_start = data["time"] - timedelta(minutes=COARSE_STEP)
    duration_seconds = COARSE_STEP * 2 * 60
    offsets_seconds = np.arange(
        0,
        duration_seconds + FINE_STEP_SECONDS,
        FINE_STEP_SECONDS,
        dtype=float,
    )
    jd, fr = _julian_date_arrays(search_start, offsets_seconds)
    errors_a, positions_a, _ = sat_a.sgp4_array(jd, fr)
    errors_b, positions_b, _ = sat_b.sgp4_array(jd, fr)

    valid = (errors_a == 0) & (errors_b == 0)
    if not np.any(valid):
        return None

    valid_indices = np.flatnonzero(valid)
    deltas = positions_a[valid] - positions_b[valid]
    distances_squared = np.einsum("ij,ij->i", deltas, deltas)
    closest_valid_index = int(np.argmin(distances_squared))
    closest_dist = float(np.sqrt(distances_squared[closest_valid_index]))

    if closest_dist > SCREENING_THRESHOLD:
        return None

    closest_index = int(valid_indices[closest_valid_index])
    closest_time = search_start + timedelta(
        seconds=float(offsets_seconds[closest_index])
    )

    return {
        "object_a": obj_a["OBJECT_NAME"],
        "object_b": obj_b["OBJECT_NAME"],
        "norad_a": obj_a["NORAD_CAT_ID"],
        "norad_b": obj_b["NORAD_CAT_ID"],
        "distance_km": round(closest_dist, 2),
        "time_until_seconds": int((closest_time - now).total_seconds()),
        "risk": calculate_risk(closest_dist),
    }


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
    orbital_data = dict(
        _precompute_orbital_data(satellite_data, now)
        for satellite_data in satellites
    )
    radial_passed, filtered_pairs = _filter_pairs(all_pairs, orbital_data)

    valid_pair_ids = set()
    active_satellites = {}
    for (obj_a, sat_a), (obj_b, sat_b) in filtered_pairs:
        id_a, id_b = obj_a["NORAD_CAT_ID"], obj_b["NORAD_CAT_ID"]
        valid_pair_ids.add(tuple(sorted((id_a, id_b))))
        active_satellites[id_a] = (obj_a, sat_a)
        active_satellites[id_b] = (obj_b, sat_b)

    print(f"Pairs surviving Radial Filter: {radial_passed}")
    print(f"Pairs surviving MOID Filter: {len(filtered_pairs)}")
    print(f"Total Eliminated before Time Loop: {len(all_pairs) - len(filtered_pairs)}")
    print("---------------------------------\n")

    # 2. THE TIME LOOP & SPATIAL HASHING
    coarse_results = {}
    print(f"Initiating Spatial Hashing Loop for next {scan_minutes} minutes...")
    minute_values = np.arange(
        0,
        scan_minutes + 1,
        COARSE_STEP,
        dtype=float,
    )
    active_entries = [
        (norad_id, object_data, satellite)
        for norad_id, (object_data, satellite) in active_satellites.items()
    ]

    if active_entries:
        jd, fr = _julian_date_arrays(now, minute_values * 60.0)
        satellite_array = SatrecArray([
            satellite for _, _, satellite in active_entries
        ])
        errors, positions, _ = satellite_array.sgp4(jd, fr)
        step_results = (
            _scan_coarse_step(
                active_entries,
                active_satellites,
                valid_pair_ids,
                now + timedelta(minutes=float(minute_values[time_index])),
                errors[:, time_index],
                positions[:, time_index, :],
            )
            for time_index in range(len(minute_values))
        )
    else:
        step_results = ()

    for results_at_step in step_results:
        for pair_key, candidate in results_at_step.items():
            existing = coarse_results.get(pair_key)
            if existing is None or candidate["distance"] < existing["distance"]:
                coarse_results[pair_key] = candidate

    # 3. THE FINE SEARCH
    if coarse_results:
        fine_search_workers = min(MAX_WORKERS, len(coarse_results))
        print(f"Fine-search worker threads: {fine_search_workers}")
        with ThreadPoolExecutor(
            max_workers=fine_search_workers,
            thread_name_prefix="orbit-refine",
        ) as executor:
            refined = list(executor.map(
                lambda data: _refine_conjunction(data, now),
                coarse_results.values(),
            ))
    else:
        refined = []

    conjunctions = []
    for event in refined:
        if event is not None:
            event["id"] = len(conjunctions) + 1
            conjunctions.append(event)

    conjunction_satellites = []
    for data in coarse_results.values():
        conjunction_satellites.extend([data["sat_a"], data["sat_b"]])

    orbit_paths = gen_orbit_paths(conjunction_satellites, now)

    return {
        "objects_tracked": len(objects),
        "conjunctions": conjunctions,
        "orbit_paths": orbit_paths,
    }

if __name__ == "__main__":
    results = find_conjunctions()
    
    print("\nCONJUNCTIONS FOUND")
    print("-------------------")
    for event in results["conjunctions"]:
        print(event)
    print(f"\nTotal potential conjunctions: {len(results['conjunctions'])}")
