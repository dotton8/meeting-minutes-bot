"""Part D: spoken summary with Azure Neural TTS."""
import base64
import os

import azure.cognitiveservices.speech as speechsdk

DEFAULT_VOICE = "en-US-JennyNeural"


def build_summary(analysis: dict, minutes: dict) -> str:
    """Summary must cover key phrases, sentiment and entity types (D1), plus the minutes."""
    phrases = analysis.get("key_phrases", [])[:3]
    parts = []
    if phrases:
        parts.append(f"This meeting covered {len(analysis['key_phrases'])} key topics, "
                     f"including {', '.join(phrases)}.")
    parts.append(f"The overall tone was {analysis['sentiment']['label']}.")

    counts = {}
    for e in analysis.get("entities", []):
        counts[e["category"]] = counts.get(e["category"], 0) + 1
    if counts:
        described = [f"{n} {cat.lower()}{'' if n == 1 else 's'}"
                     for cat, n in sorted(counts.items(), key=lambda kv: -kv[1])[:4]]
        parts.append("I detected " + ", ".join(described) + ".")

    d, a = minutes["counts"]["decisions"], minutes["counts"]["action_items"]
    parts.append(f"I found {d} decision{'' if d == 1 else 's'} and "
                 f"{a} action item{'' if a == 1 else 's'}.")
    for item in minutes["action_items"][:3]:
        due = f", due {item['due_text']}" if item.get("due_text") else ""
        parts.append(f"{item['owner']}: {item['task']}{due}.")
    return " ".join(parts)


def synthesize(text: str, voice: str = DEFAULT_VOICE) -> str:
    """Return base64 MP3 audio playable in an HTML5 <audio> element."""
    cfg = speechsdk.SpeechConfig(subscription=os.environ["AZURE_SPEECH_KEY"],
                                 region=os.environ.get("AZURE_SPEECH_REGION", "eastus"))
    cfg.speech_synthesis_voice_name = voice
    cfg.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
    result = synthesizer.speak_text_async(text).get()
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        details = result.cancellation_details
        raise RuntimeError(f"TTS failed: {details.reason} {details.error_details}")
    return base64.b64encode(result.audio_data).decode("ascii")
