from flask import Flask, request, send_file, jsonify
from pydub import AudioSegment
from pydub.silence import detect_nonsilent
import os
import re
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

AUDIO_DIR = "./audio"
GAP_DURATION_MS = 100  # 100ms silent gap between words
MAPPING_FILE = os.path.join(AUDIO_DIR, "mapping.tsv")


def load_mapping():
    mapping = {}
    if os.path.isfile(MAPPING_FILE):
        with open(MAPPING_FILE, "r") as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 2:
                    mapping[parts[0].lower()] = parts[1]
    return mapping


def trim_silence(audio, silence_threshold=-40, min_silence_length=50):
    non_silent_ranges = detect_nonsilent(audio, min_silence_length, silence_threshold)
    if not non_silent_ranges:
        return AudioSegment.silent(duration=0)
    start_trim, end_trim = non_silent_ranges[0][0], non_silent_ranges[-1][1]
    return audio[start_trim:end_trim]


def parse_prompt(prompt_text):
    lines = prompt_text.strip().splitlines()
    tokens = []
    for line in lines:
        if line.strip() == "":
            tokens.append("DELAY_1S")
        else:
            line_tokens = re.findall(r'[A-Za-z]+|\d', line)
            tokens.extend(line_tokens)
    return tokens


def compile_wav_files(tokens, mapping, output_path):
    reference_audio = None
    for token in tokens:
        if token != "DELAY_1S":
            audio_file = mapping.get(token.lower())
            if audio_file:
                reference_audio = AudioSegment.from_wav(os.path.join(AUDIO_DIR, audio_file))
                break

    if reference_audio is None:
        raise Exception("No valid audio files to compile.")

    common_frame_rate = reference_audio.frame_rate
    common_sample_width = reference_audio.sample_width
    common_channels = reference_audio.channels

    final_audio = AudioSegment.empty()
    silence_gap = AudioSegment.silent(duration=GAP_DURATION_MS)

    for token in tokens:
        if token == "DELAY_1S":
            final_audio += AudioSegment.silent(duration=500)
        else:
            file_name = mapping.get(token.lower())
            if file_name:
                audio_path = os.path.join(AUDIO_DIR, file_name)
                seg = AudioSegment.from_wav(audio_path)
                seg = trim_silence(seg)
                seg = seg.set_frame_rate(common_frame_rate)
                seg = seg.set_sample_width(common_sample_width)
                seg = seg.set_channels(common_channels)
                final_audio += seg + silence_gap
            else:
                audio_path = os.path.join(AUDIO_DIR, f"{token.lower()}.wav")
                if os.path.isfile(audio_path):
                    seg = AudioSegment.from_wav(audio_path)
                    seg = trim_silence(seg)
                    seg = seg.set_frame_rate(common_frame_rate)
                    seg = seg.set_sample_width(common_sample_width)
                    seg = seg.set_channels(common_channels)
                    final_audio += seg + silence_gap
                else:
                    raise Exception(f"Audio file for token '{token}' not found in mapping or directory.")

    final_audio.export(output_path, format="wav")


@app.route("/generate-audio", methods=["POST"])
def generate_audio():
    data = request.get_json()
    
    wind_dir = data["wind"][0:3]
    wind_speed = data["wind"][3:5]
    gusting = ""
    visibility = data["visibility"]
    if visibility == "9999":
        visibility = "KMORMORE"
    if data["wind"][5] == "G":
        gusting = data["wind"][6:8]
    temp = data["temperatureDewPoint"].split("/")[0].replace("M", "MINUS ")
    dew_point = data["temperatureDewPoint"].split("/")[1].replace("M", "MINUS ")
    departure_runway = data["departureRunway"].replace("L", " LEFT").replace("R", " RIGHT")
    arrival_runway = ""
    if data["arrivalRunway"]:
        arrival_runway = data["arrivalRunway"].replace("L", " LEFT").replace("R", " RIGHT")


    prompt_text = f"""THISIS {data["airport"]} INFO {data["letter"]} AUTOMATIC TIME {data["time"]}Z.
"""
    if (departure_runway != arrival_runway) and arrival_runway:
        prompt_text += f"DEP RWY {departure_runway} ARR RWY {arrival_runway}."
    else:
        prompt_text += f"RWYINUSE {departure_runway}."
    prompt_text += f"""SURFACEWINDS {wind_dir} DEGREES AT {wind_speed} KNOTS"""
    if gusting:
        prompt_text += f" GUSTING {gusting} KNOTS"
    prompt_text += f""" VISIBILITY {visibility} {data["cloudLayer"]} TEMPERATURE {temp} DEGREES DEWPOINT {dew_point} DEGREES QNH {data["qnh"]} HECTOPASCALS.
TRANSITIONLEVEL FL{data["transitionLevel"]}.
ACKNOWLEDGE {data["letter"]} ADVISEACFTTYPE ONFIRSTCONTACT WITH ${data["airport"]}."""

    try:
        tokens = parse_prompt(prompt_text)
        mapping = load_mapping()
        output_file_path = "output.wav"
        compile_wav_files(tokens, mapping, output_file_path)
        return send_file(output_file_path, mimetype="audio/wav", as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # app.run(host="0.0.0.0", port=5000, debug=True)
    app.run(host="0.0.0.0", port=5000, ssl_context=("/etc/letsencrypt/live/itwithlyam.co.uk/fullchain.pem", "/etc/letsencrypt/live/itwithlyam.co.uk/privkey.pem"))
    