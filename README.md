# Meeting Minutes Bot

CS 345 Azure AI Speech semester project. Record or upload a meeting clip and get the transcript, the decisions made, action items with an owner and due date, and a spoken summary.

## Architecture

```
Audio (browser mic or file)
  → ffmpeg: 16 kHz mono WAV
  → Azure AI Speech (F0): continuous recognition            POST /transcribe
  → Azure AI Language (F0): key phrases, NER, sentiment      POST /analyze
  → Minutes rules: decisions, action items (owner + due date)
  → Azure Neural TTS (F0): spoken summary                    POST /process (full pipeline)
  → Application Insights telemetry                           (Part G)
```

| File | Role |
|---|---|
| `app.py` | Flask app and endpoints |
| `pipeline/audio.py` | Upload validation and ffmpeg conversion (HTTP 415 on bad audio) |
| `pipeline/speech.py` | Continuous speech-to-text with word timings and confidence |
| `pipeline/language.py` | Azure AI Language calls |
| `pipeline/minutes.py` | Decision, action-item and completion detection |
| `pipeline/tts.py` | Summary text and Neural TTS (MP3, base64) |
| `static/index.html` | Recorder and upload page |
| `telemetry.py` | Application Insights setup, custom metrics, pipeline events, session log (Part G) |

## Setup (local)

Requires Python 3.11+, ffmpeg and the Azure CLI.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
az login
bash scripts/provision.sh        # Part A: creates resources, writes .env
python app.py                    # http://localhost:5000
```

## API

```bash
curl -F "audio=@meeting1.wav" http://localhost:5000/transcribe
curl -H "Content-Type: application/json" -d '{"text":"Jake, can you update the deck by Friday?"}' http://localhost:5000/analyze
curl -F "audio=@meeting1.wav" -F "meeting_date=2026-11-16" http://localhost:5000/process
```

`GET /telemetry-summary` returns session averages (confidence, per-stage latency, action items per meeting).

Errors return JSON `{"error": ..., "status": ...}`: 400 missing input, 413 file over 25 MB, 415 unsupported or undecodable audio, 422 no speech recognized, 502 Azure service failure.

## Telemetry (Part G)

Every `/process` call emits a `pipeline.process` span with three child spans (`stage.speech_to_text`, `stage.language_analysis`, `stage.text_to_speech`), the standard custom metrics (`stt_confidence`, `stage_*_ms`, ...), and the domain metric **`action_items_per_meeting`**.

## Deploy (Part F)

Resources live in **West US 2** (Azure for Students region policy). App settings hold the keys; `.env` is never deployed. `startup.sh` installs ffmpeg on every cold start.

## Tests

```bash
python -m pytest -q
```

The tests stub out Azure, so they run without keys. ffmpeg conversion and the minutes rules are tested for real.

## Part I extensions

- **Track 1: Action items that carry across meetings.** Action items are stored in Azure Cosmos DB and stay open until resolved. Later meetings close them when someone reports them done, and the app flags overdue items.
- **Track 2: CI/CD.** A GitHub Actions workflow runs the tests and deploys to App Service on every push to `main`, using OpenID Connect (no stored credentials).

## Cleanup

```bash
az group delete --name cs345-speech-rg --yes --no-wait
```
