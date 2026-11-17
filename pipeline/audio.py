"""Audio format handling: validate uploads and convert everything to 16 kHz mono 16-bit WAV."""
import os
import shutil
import subprocess
import uuid

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".webm", ".ogg", ".m4a", ".mp4", ".aac"}


class UnsupportedAudioError(Exception):
    """Raised when an upload is not audio we can decode. The API maps this to HTTP 415."""


def check_extension(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedAudioError(
            f"Unsupported file type '{ext or 'none'}'. Upload one of: "
            + ", ".join(sorted(ALLOWED_EXTENSIONS))
        )
    return ext


def to_wav_16k_mono(src_path: str, tmp_dir: str) -> str:
    """Convert any supported input to the format the Speech SDK handles best.

    Always converting (even .wav) normalizes sample rate and channel count, and means
    browser WebM/Opus recordings and MP3s work on App Service, which has no GStreamer.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed on this machine (see startup.sh).")
    out_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}.wav")
    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", src_path,
         "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", out_path],
        capture_output=True, text=True,
    )
    # A WAV header alone is 44 bytes; anything that small means no audio was decoded.
    if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) <= 44:
        raise UnsupportedAudioError(
            "Could not decode the uploaded audio. " + (proc.stderr.strip()[-300:] or "")
        )
    return out_path
