"""Part B: Speech-to-Text with continuous recognition (Azure AI Speech, F0)."""
import json
import os
import threading

import azure.cognitiveservices.speech as speechsdk

from .audio import UnsupportedAudioError

TICKS_PER_SECOND = 10_000_000  # the SDK reports offsets/durations in 100-ns ticks


def _speech_config() -> speechsdk.SpeechConfig:
    cfg = speechsdk.SpeechConfig(
        subscription=os.environ["AZURE_SPEECH_KEY"],
        region=os.environ.get("AZURE_SPEECH_REGION", "eastus"),
    )
    cfg.speech_recognition_language = os.environ.get("SPEECH_LANGUAGE", "en-US")
    cfg.output_format = speechsdk.OutputFormat.Detailed  # gives NBest confidence
    cfg.request_word_level_timestamps()
    return cfg


def transcribe_wav(wav_path: str, timeout_s: int = 300) -> dict:
    """Transcribe a 16 kHz mono WAV with continuous recognition.

    recognize_once() stops at the first pause (~30 s max), so a meeting clip would be cut off.
    Continuous recognition keeps going until the file ends (session_stopped).
    """
    cfg = _speech_config()
    audio_cfg = speechsdk.audio.AudioConfig(filename=wav_path)
    recognizer = speechsdk.SpeechRecognizer(speech_config=cfg, audio_config=audio_cfg)

    segments, errors = [], []
    done = threading.Event()

    def on_recognized(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and evt.result.text:
            segments.append(json.loads(evt.result.json))

    def on_canceled(evt):
        details = evt.cancellation_details
        if details.reason == speechsdk.CancellationReason.Error:
            errors.append((details.error_code, details.error_details))
        done.set()

    recognizer.recognized.connect(on_recognized)
    recognizer.canceled.connect(on_canceled)
    recognizer.session_stopped.connect(lambda _evt: done.set())

    recognizer.start_continuous_recognition_async().get()
    finished = done.wait(timeout=timeout_s)
    recognizer.stop_continuous_recognition_async().get()

    if errors:
        code, msg = errors[0]
        if "header" in (msg or "").lower() or "format" in (msg or "").lower():
            raise UnsupportedAudioError(f"Speech service rejected the audio format: {msg}")
        raise RuntimeError(f"Speech recognition failed ({code}): {msg}")
    if not finished:
        raise TimeoutError("Speech recognition timed out.")

    return _build_response(segments, cfg.speech_recognition_language)


def _build_response(segments: list, language: str) -> dict:
    texts, words, confidences = [], [], []
    duration_ticks = 0
    for seg in segments:
        best = (seg.get("NBest") or [{}])[0]
        texts.append(best.get("Display") or seg.get("DisplayText", ""))
        if "Confidence" in best:
            confidences.append(best["Confidence"])
        duration_ticks = max(duration_ticks, seg.get("Offset", 0) + seg.get("Duration", 0))
        for w in best.get("Words", []):
            words.append({
                "word": w.get("Word"),
                "offset": round(w.get("Offset", 0) / TICKS_PER_SECOND, 2),
                "duration": round(w.get("Duration", 0) / TICKS_PER_SECOND, 2),
                # Per-word confidence is not always returned; fall back to the segment's.
                "confidence": round(w.get("Confidence", best.get("Confidence", 0.0)), 3),
            })
    return {
        "transcript": " ".join(t for t in texts if t).strip(),
        "language": language,
        "duration_seconds": round(duration_ticks / TICKS_PER_SECOND, 2),
        "confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
        "words": words,
    }
