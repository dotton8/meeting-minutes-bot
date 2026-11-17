"""Offline tests for the minutes rules (no Azure calls needed)."""
from datetime import datetime

from pipeline.minutes import extract_minutes, resolve_date

MEETING = datetime(2026, 11, 16)  # a Monday


def _analysis(sentences, entities):
    """Build a fake Language result with correct offsets."""
    out, offset, text = [], 0, ""
    for s in sentences:
        out.append({"text": s, "offset": offset, "length": len(s), "sentiment": "neutral"})
        text += s + " "
        offset += len(s) + 1
    ents = []
    for ent_text, category in entities:
        ents.append({"text": ent_text, "category": category, "subcategory": None,
                     "offset": text.index(ent_text), "length": len(ent_text), "confidence": 0.9})
    return {"sentences": out, "entities": ents}


def test_resolve_dates():
    assert resolve_date("Friday", MEETING) == "2026-11-20"
    assert resolve_date("by Friday", MEETING) == "2026-11-20"
    assert resolve_date("next Tuesday", MEETING) == "2026-11-24"
    assert resolve_date("December 15th", MEETING) == "2026-12-15"


def test_example_meeting():
    analysis = _analysis(
        ["Okay, so we agreed to push the launch to December 15th.",
         "Jake, can you update the pitch deck by Friday?",
         "And Priya will send the budget numbers to finance next Tuesday.",
         "Let's meet again on the 10th."],
        [("December 15th", "DateTime"), ("Jake", "Person"), ("Friday", "DateTime"),
         ("Priya", "Person"), ("next Tuesday", "DateTime"), ("the 10th", "DateTime")],
    )
    m = extract_minutes(analysis, MEETING)
    assert m["counts"] == {"decisions": 1, "action_items": 2}
    jake, priya = m["action_items"]
    assert (jake["owner"], jake["due_date"]) == ("Jake", "2026-11-20")
    assert jake["task"] == "Update the pitch deck"
    assert (priya["owner"], priya["due_date"]) == ("Priya", "2026-11-24")
    assert priya["task"] == "Send the budget numbers to finance"


def test_completion_and_pronoun_owner():
    analysis = _analysis(
        ["Jake finished the pitch deck.", "I'll draft the agenda for Thursday."],
        [("Jake", "Person"), ("Thursday", "DateTime")],
    )
    m = extract_minutes(analysis, MEETING)
    assert m["completions"][0]["owner"] == "Jake"
    assert m["action_items"][0]["owner"] == "Me (speaker)"
    assert m["action_items"][0]["due_date"] == "2026-11-19"
