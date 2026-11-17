"""Product logic: turn a Language analysis into meeting minutes.

Azure AI Language has no "action item" feature, so this module combines what it does return
(sentence boundaries + Person and DateTime entities) with simple, testable rules:

  * decision    -> sentence contains decision language ("we agreed", "decided", ...)
  * action item -> sentence contains commitment language ("can you", "will", "needs to", ...)
      owner     -> Person entity inside that sentence (or "Me"/"Team" for I/we)
      due date  -> DateTime entity inside that sentence, resolved relative to the meeting date
  * completion  -> sentence reports finished work ("finished", "sent", "done with", ...);
                   Track 1 uses these to close action items from earlier meetings.
"""
import re
from datetime import datetime, timedelta

import dateparser

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

DECISION_PATTERNS = [
    r"\bwe(?:'ve| have)? (?:agreed|decided)\b", r"\bdecided\b", r"\bagreed\b",
    r"\bwe(?:'re| are) going with\b", r"\blet'?s go with\b", r"\bfinal decision\b",
    r"\bwe(?:'ll| will) go with\b", r"\bapproved\b",
]
COMMITMENT_PATTERNS = [
    r"\bcan you\b", r"\bcould you\b", r"\bwould you\b", r"\bplease\b",
    r"\b(?:will|'ll)\b", r"\bneeds? to\b", r"\bhas to\b", r"\bhave to\b",
    r"\bis going to\b", r"\bare going to\b", r"\bi'?m going to\b",
    r"\bshould\b", r"\bin charge of\b", r"\bowns?\b", r"\btake care of\b", r"\bfollow up\b",
]
COMPLETION_PATTERNS = [
    r"\b(?:finished|completed|wrapped up|submitted|delivered)\b",
    r"\b(?:is|are|was) done\b", r"\bdone with\b", r"\balready (?:sent|did|updated|finished)\b",
    r"\b(?:sent|updated|shipped) (?:the|over|out)\b",
]
# Sentences that only look forward ("let's meet again on the 10th") are not tasks.
NOT_A_TASK = [r"^\s*let'?s meet\b", r"\bmeet again\b", r"\bnext meeting\b"]

FILLER_PREFIX = re.compile(
    r"^(?:okay|ok|so|and|also|alright|um|uh|then)[,\s]+", re.IGNORECASE)
COMMITMENT_PREFIX = re.compile(
    r"^(?:can you|could you|would you|will you|please|will|is going to|are going to|needs? to|"
    r"has to|have to|should|i'?ll|i will|i'?m going to|we'?ll|we will|we need to)\s+",
    re.IGNORECASE)
DUE_PHRASE = re.compile(r"\s*\b(?:by|before|on|until|no later than)\s*$", re.IGNORECASE)


def _matches(patterns, text):
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _entities_in(sentence, entities, category):
    start, end = sentence["offset"], sentence["offset"] + sentence["length"]
    return [e for e in entities
            if e["category"] == category and start <= e["offset"] < end]


def resolve_date(text: str, meeting_date: datetime):
    """Resolve 'Friday', 'next Tuesday', 'December 15th', 'the 10th' to an ISO date."""
    cleaned = re.sub(r"^(?:by|on|before|until)\s+", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)\b", r"\1", cleaned)
    # "next Tuesday" = the Tuesday of next week (Mon-Sun), which dateparser doesn't handle.
    next_week = re.match(r"^next\s+(" + "|".join(WEEKDAYS) + r")$", cleaned, re.IGNORECASE)
    if next_week:
        monday_next_week = meeting_date - timedelta(days=meeting_date.weekday()) + timedelta(days=7)
        target = monday_next_week + timedelta(days=WEEKDAYS.index(next_week.group(1).lower()))
        return target.date().isoformat()
    parsed = dateparser.parse(
        cleaned, settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": meeting_date})
    return parsed.date().isoformat() if parsed else None


def _owner_for(sentence, people):
    if people:
        return people[0]["text"]
    text = sentence["text"].lower()
    if re.search(r"\b(?:i'll|i will|i'm going to|i need to|i have to)\b", text):
        return "Me (speaker)"
    if re.search(r"\b(?:we'll|we will|we need to|we have to|we should)\b", text):
        return "Team"
    return "Unassigned"


def _task_text(sentence_text, owner, dates):
    task = sentence_text.strip().rstrip(".?!")
    task = FILLER_PREFIX.sub("", task)
    if owner and owner not in ("Me (speaker)", "Team", "Unassigned"):
        task = re.sub(rf"^{re.escape(owner)}\s*,?\s*", "", task)
        task = re.sub(rf"^{re.escape(owner)}\s+", "", task)
    task = COMMITMENT_PREFIX.sub("", task)
    for d in dates:
        task = task.replace(d["text"], "")
    task = DUE_PHRASE.sub("", task).strip(" ,")
    task = re.sub(r"\s{2,}", " ", task)
    return task[:1].upper() + task[1:] if task else sentence_text.strip()


def extract_minutes(analysis: dict, meeting_date: datetime | None = None) -> dict:
    meeting_date = meeting_date or datetime.now()
    entities = analysis.get("entities", [])
    decisions, action_items, completions = [], [], []

    for sentence in analysis.get("sentences", []):
        text = sentence["text"].strip()
        people = _entities_in(sentence, entities, "Person")
        dates = _entities_in(sentence, entities, "DateTime")

        if _matches(COMPLETION_PATTERNS, text):
            completions.append({"sentence": text,
                                "owner": people[0]["text"] if people else None})
            continue
        if _matches(DECISION_PATTERNS, text):
            decisions.append(FILLER_PREFIX.sub("", text).rstrip("."))
            continue
        if _matches(COMMITMENT_PATTERNS, text) and not _matches(NOT_A_TASK, text):
            owner = _owner_for(sentence, people)
            due_text = dates[0]["text"] if dates else None
            action_items.append({
                "task": _task_text(text, owner, dates),
                "owner": owner,
                "due_text": due_text,
                "due_date": resolve_date(due_text, meeting_date) if due_text else None,
                "source_sentence": text,
            })

    return {
        "meeting_date": meeting_date.date().isoformat(),
        "decisions": decisions,
        "action_items": action_items,
        "completions": completions,
        "counts": {"decisions": len(decisions), "action_items": len(action_items)},
    }
