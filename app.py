from flask import Flask, jsonify, render_template, request
import requests
from requests.auth import HTTPBasicAuth
from pathlib import Path
import csv
import os
from gtts import gTTS

app = Flask(__name__)

USERNAME = 'rttapi_callumf17'
PASSWORD = 'c75ca3dc58a73844831ed403b251a5e3cb17c4a2'

AUDIO_BASE = '/static/audio'
TTS_BASE = '/static/tts'

# Load station CSV for autocomplete
STATIONS = []
with open("data/uk-train-stations.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        STATIONS.append({
            "crs": row["3alpha"],
            "name": row["station_name"],
            "lat": float(row["latitude"]),
            "lon": float(row["longitude"])
        })

def convert_to_standard_time(military_time):
    if military_time == 'unknown time':
        return military_time
    if len(military_time) == 4:
        return military_time[:2] + ":" + military_time[2:]
    return military_time

def normalize_station_name(name):
    import re
    name = name.lower()
    name = re.sub(r"[^\w\s-]", "", name)
    name = name.replace(" ", "-")
    return f"destination-{name}.mp3"

def num_to_word(n):
    mapping = { 0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
        6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
        13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen",
        18: "eighteen", 19: "nineteen", 20: "twenty", 21: "twentyone", 22: "twentytwo",
        23: "twentythree", 24: "twentyfour", 25: "twentyfive", 26: "twentysix",
        27: "twentyseven", 28: "twentyeight", 29: "twentynine", 30: "thirty",
        31: "thirtyone", 32: "thirtytwo", 33: "thirtythree", 34: "thirtyfour",
        35: "thirtyfive", 36: "thirtysix", 37: "thirtyseven", 38: "thirtyeight",
        39: "thirtynine", 40: "forty", 41: "fortyone", 42: "fortytwo", 43: "fortythree",
        44: "fortyfour", 45: "fortyfive", 46: "fortysix", 47: "fortyseven",
        48: "fortyeight", 49: "fortynine", 50: "fifty", 51: "fiftyone", 52: "fiftytwo",
        53: "fiftythree", 54: "fiftyfour", 55: "fiftyfive", 56: "fiftysix",
        57: "fiftyseven", 58: "fiftyeight", 59: "fiftynine" }
    return mapping.get(n, str(n))

def get_or_generate_audio_path(text, filename_hint, lang='en', accent='co.uk'):
    sanitized = filename_hint.replace(" ", "_").lower()
    output_path = Path(f"static/tts/{sanitized}.mp3")
    if not output_path.exists():
        try:
            tts = gTTS(text=text, lang=lang, tld=accent)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            tts.save(str(output_path))
        except Exception as e:
            print(f"TTS generation failed: {e}")
            return None
    return f"/static/tts/{sanitized}.mp3"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/stations")
def stations():
    return jsonify(STATIONS)

@app.route("/api/data")
def get_departures():
    station_code = request.args.get('station', 'GLQ').upper()
    url = f'https://api.rtt.io/api/v1/json/search/{station_code}'

    try:
        resp = requests.get(url, auth=HTTPBasicAuth(USERNAME, PASSWORD))
        resp.raise_for_status()
        data = resp.json()
        services = data.get('services', [])
        station_name = data.get('location', {}).get('name', 'Unknown Station')

        if not services:
            return jsonify({"error": "No services found"}), 404

        display_departures = []

        for svc in services[:9]:
            loc = svc.get('locationDetail', {})
            scheduled = loc.get('gbttBookedDeparture', 'unknown time')
            realtime = loc.get('realtimeDeparture', None)
            platform = str(loc.get('platform', 'unknown'))
            is_cancelled = svc.get('isCancelled', False)

            # Determine status
            if is_cancelled:
                status = "Cancelled"
            else:
                if realtime and realtime != "N/A" and realtime != scheduled:
                    time_str = convert_to_standard_time(realtime)
                    status = f"Delayed to {time_str}"
                else:
                    time_str = convert_to_standard_time(scheduled)
                    status = "On time"

            destination = loc.get('destination', [{}])[0].get('description', 'Unknown destination')

            # Final destination and calling points
            service_uid = svc.get('serviceUid')
            run_date = svc.get('runDate').replace('-', '')
            calling_points = []
            try:
                url_details = f"https://api.rtt.io/api/v1/json/service/{service_uid}/{run_date[:4]}/{run_date[4:6]}/{run_date[6:8]}"
                resp_det = requests.get(url_details, auth=HTTPBasicAuth(USERNAME, PASSWORD))
                resp_det.raise_for_status()
                details = resp_det.json()
                if 'locations' in details:
                    locations = details['locations']
                    idx = next(i for i, locd in enumerate(locations) if locd.get('crs') == station_code)
                    calling_points = [locd.get('description') for locd in locations[idx + 1:-1]]
                    final_destination = locations[-1].get('description')
                else:
                    final_destination = destination
            except:
                final_destination = destination

            # ---------- Full preset announcement ----------
            audio_files = []
            if not is_cancelled:
                plat_file = f"{AUDIO_BASE}/scotrail_platforms/plat{platform}.mp3"
                if os.path.exists(f".{plat_file}"):
                    audio_files.append(plat_file)
                else:
                    tts = get_or_generate_audio_path(f"The next train at platform {platform} is the", f"plat_{platform}")
                    if tts:
                        audio_files.append(tts)

                # Correct hour / minute for speech
                try:
                    hour = int(scheduled[:2])
                    minute = int(scheduled[2:4])
                    hour_12 = hour % 12 or 12
                    audio_files.append(f"{AUDIO_BASE}/scotrail_numbers/number-{num_to_word(hour_12)}.mp3")
                    if minute != 0:
                        if minute < 10:
                            audio_files.append(f"{AUDIO_BASE}/scotrail_numbers/oh{minute}.mp3")
                        else:
                            audio_files.append(f"{AUDIO_BASE}/scotrail_numbers/number-{num_to_word(minute)}.mp3")
                except: pass

                audio_files.append(f"{AUDIO_BASE}/scotrail_misc/service_to.mp3")
                dest_file = f"{AUDIO_BASE}/scotrail_destinations/{normalize_station_name(destination)}"
                if os.path.exists(f".{dest_file}"):
                    audio_files.append(dest_file)
                else:
                    tts = get_or_generate_audio_path(destination, destination)
                    if tts:
                        audio_files.append(tts)

                if calling_points:
                    audio_files.append(f"{AUDIO_BASE}/scotrail_misc/calling_at.mp3")
                    for stop in calling_points:
                        stop_file = f"{AUDIO_BASE}/scotrail_destinations/{normalize_station_name(stop)}"
                        if os.path.exists(f".{stop_file}"):
                            audio_files.append(stop_file)
                        else:
                            tts = get_or_generate_audio_path(stop, stop)
                            if tts:
                                audio_files.append(tts)
                    audio_files.append(f"{AUDIO_BASE}/scotrail_fillers/and.mp3")

                final_file = f"{AUDIO_BASE}/scotrail_destinations/{normalize_station_name(final_destination)}"
                if os.path.exists(f".{final_file}"):
                    audio_files.append(final_file)
                else:
                    tts = get_or_generate_audio_path(final_destination, final_destination)
                    if tts:
                        audio_files.append(tts)

                audio_files.append(f"{AUDIO_BASE}/scotrail_misc/take_care.mp3")
            else:
                audio_files.append(f"{AUDIO_BASE}/scotrail_misc/has_been_cancelled.mp3")

            display_departures.append({
                "time": convert_to_standard_time(scheduled),
                "destination": destination,
                "platform": platform,
                "status": status,
                "final_destination": final_destination,
                "calling_points": calling_points,
                "platform_confirmed": loc.get('platformConfirmed', False),
                "scheduled": convert_to_standard_time(scheduled),
                "realtime": convert_to_standard_time(realtime) if realtime else "N/A",
                "announcement_audio": audio_files
            })

        return jsonify({
            "station_name": station_name,
            "departures": display_departures
        })

    except Exception as e:
        print(f"Error fetching data: {e}")
        return jsonify({"error": "Failed to fetch data"}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
