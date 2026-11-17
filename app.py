"""Meeting Minutes Bot - Flask backend.

Endpoints
  POST /transcribe   audio file  -> transcript JSON                      (Part B)
  POST /analyze      {"text"}    -> key phrases, entities, sentiment, minutes (Part C)
  POST /process      audio file  -> full pipeline incl. spoken summary   (Parts B-D)
  GET  /health                   -> liveness check
"""
import os
import shutil
import tempfile
import time
import uuid
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

load_dotenv()

from pipeline.audio import UnsupportedAudioError, check_extension, to_wav_16k_mono  # noqa: E402
from pipeline.language import analyze_text  # noqa: E402
from pipeline.minutes import extract_minutes  # noqa: E402
from pipeline.speech import transcribe_wav  # noqa: E402
from pipeline.tts import DEFAULT_VOICE, build_summary, synthesize  # noqa: E402

app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB upload limit (B2)
TEMP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_audio")


def error(status: int, message: str):
    return jsonify({"error": message, "status": status}), status


@app.errorhandler(RequestEntityTooLarge)
def too_large(_e):
    return error(413, "File too large. Maximum upload size is 25 MB.")


def _transcribe_upload():
    """Save the upload to a temp dir, convert to WAV, transcribe, always clean up."""
    if "audio" not in request.files or not request.files["audio"].filename:
        raise ValueError("No audio file uploaded. Send multipart/form-data with field 'audio'.")
    upload = request.files["audio"]
    ext = check_extension(upload.filename)

    os.makedirs(TEMP_ROOT, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(dir=TEMP_ROOT)
    try:
        src = os.path.join(tmp_dir, f"{uuid.uuid4().hex}{ext}")
        upload.save(src)
        wav = to_wav_16k_mono(src, tmp_dir)
        return transcribe_wav(wav)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)  # delete temp files (B2)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/transcribe")
def transcribe():
    try:
        return jsonify(_transcribe_upload())
    except ValueError as e:
        return error(400, str(e))
    except UnsupportedAudioError as e:
        return error(415, str(e))
    except Exception as e:  # noqa: BLE001
        return error(502, f"Transcription failed: {e}")


@app.post("/analyze")
def analyze():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return error(400, "JSON body must include a non-empty 'text' field.")
    try:
        analysis = analyze_text(text)
        analysis["minutes"] = extract_minutes(analysis, _meeting_date(body.get("meeting_date")))
        return jsonify(analysis)
    except Exception as e:  # noqa: BLE001
        return error(502, f"Language analysis failed: {e}")


@app.post("/process")
def process():
    timings = {}
    t0 = time.perf_counter()
    try:
        transcription = _transcribe_upload()
    except ValueError as e:
        return error(400, str(e))
    except UnsupportedAudioError as e:
        return error(415, str(e))
    except Exception as e:  # noqa: BLE001
        return error(502, f"Transcription failed: {e}")
    timings["speech_to_text_ms"] = round((time.perf_counter() - t0) * 1000)

    if not transcription["transcript"]:
        return error(422, "No speech was recognized in the recording.")

    try:
        t1 = time.perf_counter()
        analysis = analyze_text(transcription["transcript"])
        minutes = extract_minutes(analysis, _meeting_date(request.form.get("meeting_date")))
        timings["language_analysis_ms"] = round((time.perf_counter() - t1) * 1000)
    except Exception as e:  # noqa: BLE001
        return error(502, f"Language analysis failed: {e}")

    summary = build_summary(analysis, minutes)
    audio_b64, tts_error = None, None
    try:
        t2 = time.perf_counter()
        audio_b64 = synthesize(summary, request.form.get("voice", DEFAULT_VOICE))
        timings["text_to_speech_ms"] = round((time.perf_counter() - t2) * 1000)
    except Exception as e:  # noqa: BLE001 - minutes are still useful without audio
        tts_error = str(e)

    timings["total_ms"] = round((time.perf_counter() - t0) * 1000)
    return jsonify({
        "meeting_id": uuid.uuid4().hex,
        "transcription": transcription,
        "analysis": {k: analysis[k] for k in ("key_phrases", "entities", "sentiment")},
        "minutes": minutes,
        "summary": {"text": summary, "audio_base64": audio_b64,
                    "audio_format": "audio/mpeg", "error": tts_error},
        "metrics": {**timings, "action_items_count": minutes["counts"]["action_items"]},
    })


def _meeting_date(value):
    """Optional ISO date so due dates like 'Friday' resolve against the real meeting day."""
    if value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
