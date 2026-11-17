"""Part C: Azure AI Language analysis (key phrases, entities, sentiment with sentences)."""
import os

from azure.ai.textanalytics import TextAnalyticsClient
from azure.core.credentials import AzureKeyCredential

MAX_CHARS = 5120  # per-document limit for synchronous Language calls

_client = None


def _get_client() -> TextAnalyticsClient:
    global _client
    if _client is None:
        _client = TextAnalyticsClient(
            endpoint=os.environ["AZURE_LANGUAGE_ENDPOINT"],
            credential=AzureKeyCredential(os.environ["AZURE_LANGUAGE_KEY"]),
        )
    return _client


def analyze_text(text: str) -> dict:
    """Run key phrase extraction, NER and sentiment on one transcript."""
    if not text or not text.strip():
        raise ValueError("Text is empty.")
    doc = [text[:MAX_CHARS]]
    client = _get_client()

    kp = client.extract_key_phrases(doc)[0]
    ner = client.recognize_entities(doc)[0]
    sent = client.analyze_sentiment(doc)[0]
    for result in (kp, ner, sent):
        if result.is_error:
            raise RuntimeError(f"Language API error: {result.error.code} {result.error.message}")

    return {
        "key_phrases": list(kp.key_phrases),
        "entities": [
            {
                "text": e.text,
                "category": e.category,
                "subcategory": e.subcategory,
                "offset": e.offset,
                "length": e.length,
                "confidence": round(e.confidence_score, 3),
            }
            for e in ner.entities
        ],
        "sentiment": {
            "label": sent.sentiment,
            "scores": {
                "positive": round(sent.confidence_scores.positive, 3),
                "neutral": round(sent.confidence_scores.neutral, 3),
                "negative": round(sent.confidence_scores.negative, 3),
            },
        },
        # Sentence boundaries come back with sentiment; minutes.py uses them.
        "sentences": [
            {"text": s.text, "offset": s.offset, "length": s.length, "sentiment": s.sentiment}
            for s in sent.sentences
        ],
        "truncated": len(text) > MAX_CHARS,
    }
