"""Part G: Application Insights setup, custom metrics, pipeline events and the session log.

init_telemetry() must run before Flask and the Azure SDKs are imported (see app.py),
otherwise their automatic instrumentation never attaches.
"""
import os
import statistics

_initialized = False


def init_telemetry() -> bool:
    """Connect OpenTelemetry to Application Insights. Returns False (no-op) when the
    connection string is missing, e.g. in the offline test suite."""
    global _initialized
    if _initialized:
        return True
    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        print("APPLICATIONINSIGHTS_CONNECTION_STRING not set: telemetry disabled.")
        return False
    from azure.monitor.opentelemetry import configure_azure_monitor
    configure_azure_monitor(connection_string=connection_string)
    _initialized = True
    print("Application Insights initialized.")
    return True


# --- Instruments (created once, at import time) -------------------------------------
from opentelemetry import metrics, trace  # noqa: E402

tracer = trace.get_tracer("meeting-minutes-bot")
meter = metrics.get_meter("meeting-minutes-bot")

stt_confidence_gauge = meter.create_gauge("stt_confidence")
stt_duration_gauge = meter.create_gauge("stt_duration_seconds")
stt_word_count_gauge = meter.create_gauge("stt_word_count")
entity_count_gauge = meter.create_gauge("language_entity_count")
keyphrase_count_gauge = meter.create_gauge("language_keyphrase_count")
sentiment_gauge = meter.create_gauge("language_sentiment")
tts_char_count_gauge = meter.create_gauge("tts_char_count")
stage_stt_hist = meter.create_histogram("stage_stt_ms")
stage_language_hist = meter.create_histogram("stage_language_ms")
stage_tts_hist = meter.create_histogram("stage_tts_ms")
# Domain metric for this product (see the product brief)
action_items_gauge = meter.create_gauge("action_items_per_meeting")

SENTIMENT_SCORE = {"positive": 1.0, "neutral": 0.0, "negative": -1.0, "mixed": 0.0}


def emit_pipeline_metrics(stt, analysis, minutes, tts_chars, timings, audio_format):
    attrs = {"audio_format": audio_format, "language": stt["language"]}
    stt_confidence_gauge.set(stt["confidence"], attrs)
    stt_duration_gauge.set(stt["duration_seconds"], attrs)
    stt_word_count_gauge.set(len(stt["transcript"].split()), attrs)
    entity_count_gauge.set(len(analysis["entities"]), attrs)
    keyphrase_count_gauge.set(len(analysis["key_phrases"]), attrs)
    sentiment_gauge.set(SENTIMENT_SCORE.get(analysis["sentiment"]["label"], 0.0), attrs)
    tts_char_count_gauge.set(tts_chars, attrs)
    stage_stt_hist.record(timings["stt_ms"], attrs)
    stage_language_hist.record(timings["language_ms"], attrs)
    stage_tts_hist.record(timings["tts_ms"], attrs)
    action_items_gauge.set(minutes["counts"]["action_items"], attrs)


def emit_pipeline_event(span, stt=None, analysis=None, minutes=None, audio_format=None,
                        success=True, error_stage=None, error_msg=None):
    """G4: record the outcome as attributes on the request's pipeline span."""
    if success:
        span.set_attribute("event.name", "pipeline_completed")
        span.set_attribute("stt.confidence", stt["confidence"])
        span.set_attribute("stt.language", stt["language"])
        span.set_attribute("entities.count", len(analysis["entities"]))
        span.set_attribute("sentiment", analysis["sentiment"]["label"])
        span.set_attribute("minutes.action_items", minutes["counts"]["action_items"])
        span.set_attribute("minutes.decisions", minutes["counts"]["decisions"])
    else:
        span.set_attribute("event.name", "pipeline_error")
        span.set_attribute("error.stage", error_stage or "unknown")
        span.set_attribute("error.message", (error_msg or "")[:500])
        span.record_exception(Exception(error_msg))
    if audio_format:
        span.set_attribute("audio.format", audio_format)


# --- G8: in-memory session log for GET /telemetry-summary ----------------------------
session_log = []


def log_pipeline_call(stt, analysis, minutes, timings):
    session_log.append({
        "confidence": stt["confidence"],
        "language": stt["language"],
        "entity_count": len(analysis["entities"]),
        "sentiment": analysis["sentiment"]["label"],
        "action_items": minutes["counts"]["action_items"],
        "stt_ms": round(timings["stt_ms"], 1),
        "language_ms": round(timings["language_ms"], 1),
        "tts_ms": round(timings["tts_ms"], 1),
    })


def telemetry_summary() -> dict:
    if not session_log:
        return {"message": "No calls yet"}
    confidences = [e["confidence"] for e in session_log]
    stt_sorted = sorted(e["stt_ms"] for e in session_log)
    p95_index = max(0, int(round(0.95 * len(stt_sorted))) - 1)
    return {
        "total_calls": len(session_log),
        "avg_confidence": round(statistics.mean(confidences), 3),
        "min_confidence": round(min(confidences), 3),
        "avg_action_items_per_meeting": round(
            statistics.mean(e["action_items"] for e in session_log), 2),
        "avg_stage_ms": {
            stage: round(statistics.mean(e[stage] for e in session_log), 1)
            for stage in ("stt_ms", "language_ms", "tts_ms")
        },
        "p95_stt_ms": stt_sorted[p95_index],
        "sentiment_breakdown": {
            s: sum(1 for e in session_log if e["sentiment"] == s)
            for s in ("positive", "neutral", "negative", "mixed")
        },
        "calls": session_log[-10:],
    }
