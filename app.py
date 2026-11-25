"""Meeting Minutes Bot - Flask backend.

Endpoints
  POST /process            audio file  -> full pipeline incl. spoken summary   (Parts B-D)
  POST /transcribe         audio file  -> transcript JSON                      (Part B)
  POST /analyze            {"text"}    -> key phrases, entities, sentiment, minutes (Part C)
  GET  /telemetry-summary              -> session averages per stage           (Part G8)
  GET  /health                         -> liveness check
"""
# --- Telemetry MUST be initialized before Flask or any Azure SDK is imported (Part G2) ---
from dotenv import load_dotenv

load_dotenv()

from telemetry import init_telemetry  # noqa: E402

init_telemetry()

import os  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402
from werkzeug.exceptions import RequestEntityTooLarge  # noqa: E402

import telemetry  # noqa: E402
from pipeline.audio import UnsupportedAudioError, check_extension, to_wav_16k_mono  # noqa: E402
from pipeline.language import analyze_text  # noqa: E402
from pipeline.minutes import extract_minutes  # noqa: E402
from pipeline.speech import transcribe_wav  # noqa: E402
from pipeline.tts import DEFAULT_VOICE, build_summary, synthesize  # noqa: E402

app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB upload limit (B2)
TEMP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_audio")
tracer = telemetry.tracer


def error(status: int, message: str):
    return jsonify({"error": message, "status": status}), status


@app.errorhandler(RequestEntityTooLarge)
def too_large(_e):
    return error(413, "File too large. Maximum upload size is 25 MB.")


def _audio_format() -> str:
    upload = request.files.get("audio")
    name = (upload.filename if upload else "") or ""
    return name.rsplit(".", 1)[-1].lower() if "." in name else "unknown"


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


@app.get("/telemetry-summary")
def telemetry_summary():
    return jsonify(telemetry.telemetry_summary())


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
    audio_format = _audio_format()
    with tracer.start_as_current_span("pipeline.process") as root:
        root.set_attribute("audio.format", audio_format)
        t_total = time.perf_counter()

        # Stage 1 - Speech-to-Text
        with tracer.start_as_current_span("stage.speech_to_text") as span:
            t0 = time.perf_counter()
            try:
                transcription = _transcribe_upload()
            except ValueError as e:
                return _fail(root, "speech_to_text", audio_format, 400, str(e))
            except UnsupportedAudioError as e:
                return _fail(root, "speech_to_text", audio_format, 415, str(e))
            except Exception as e:  # noqa: BLE001
                return _fail(root, "speech_to_text", audio_format, 502,
                             f"Transcription failed: {e}")
            stt_ms = (time.perf_counter() - t0) * 1000
            span.set_attribute("stt.confidence", transcription["confidence"])
            span.set_attribute("stt.word_count", len(transcription["transcript"].split()))
            span.set_attribute("duration_ms", stt_ms)

        if not transcription["transcript"]:
            return _fail(root, "speech_to_text", audio_format, 422,
                         "No speech was recognized in the recording.")

        # Stage 2 - Language analysis + minutes rules
        with tracer.start_as_current_span("stage.language_analysis") as span:
            t0 = time.perf_counter()
            try:
                analysis = analyze_text(transcription["transcript"])
                minutes = extract_minutes(analysis, _meeting_date(request.form.get("meeting_date")))
            except Exception as e:  # noqa: BLE001
                return _fail(root, "language_analysis", audio_format, 502,
                             f"Language analysis failed: {e}")
            language_ms = (time.perf_counter() - t0) * 1000
            span.set_attribute("entity_count", len(analysis["entities"]))
            span.set_attribute("sentiment", analysis["sentiment"]["label"])
            span.set_attribute("action_items", minutes["counts"]["action_items"])
            span.set_attribute("duration_ms", language_ms)

        # Stage 3 - Text-to-Speech
        with tracer.start_as_current_span("stage.text_to_speech") as span:
            t0 = time.perf_counter()
            summary = build_summary(analysis, minutes)
            audio_b64, tts_error = None, None
            try:
                audio_b64 = synthesize(summary, request.form.get("voice", DEFAULT_VOICE))
            except Exception as e:  # noqa: BLE001 - minutes are still useful without audio
                tts_error = str(e)
                span.record_exception(e)
            tts_ms = (time.perf_counter() - t0) * 1000
            span.set_attribute("char_count", len(summary))
            span.set_attribute("duration_ms", tts_ms)

        timings = {"stt_ms": stt_ms, "language_ms": language_ms, "tts_ms": tts_ms}
        telemetry.emit_pipeline_metrics(transcription, analysis, minutes, len(summary),
                                        timings, audio_format)
        telemetry.emit_pipeline_event(root, transcription, analysis, minutes, audio_format)
        telemetry.log_pipeline_call(transcription, analysis, minutes, timings)

        total_ms = (time.perf_counter() - t_total) * 1000
        return jsonify({
            "meeting_id": uuid.uuid4().hex,
            "transcription": transcription,
            "analysis": {k: analysis[k] for k in ("key_phrases", "entities", "sentiment")},
            "minutes": minutes,
            "summary": {"text": summary, "audio_base64": audio_b64,
                        "audio_format": "audio/mpeg", "error": tts_error},
            "metrics": {
                "speech_to_text_ms": round(stt_ms),
                "language_analysis_ms": round(language_ms),
                "text_to_speech_ms": round(tts_ms),
                "total_ms": round(total_ms),
                "action_items_count": minutes["counts"]["action_items"],
            },
        })


def _fail(root_span, stage, audio_format, status, message):
    telemetry.emit_pipeline_event(root_span, audio_format=audio_format, success=False,
                                  error_stage=stage, error_msg=message)
    return error(status, message)


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
    app.run(host="127.0.0.1", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
