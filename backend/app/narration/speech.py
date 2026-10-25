"""Speech text comes only from records committed in the owner's simulation."""

from app.infrastructure.errors import DomainError, require


def _clean(*parts):
    return " ".join(" ".join(part.split()) for part in parts if part and part.strip())


def _name(state, agent_id):
    citizen = state.citizens.get(agent_id)
    return citizen.summary.name if citizen else ""


def _sentence(text):
    return text if not text or text[-1] in ".!?:;" else text + "."


def _bounded(text, limit):
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit // 2 else cut).rstrip() + "…"


def recorded_text(state, source_type, source_id, limit, *, live=False):
    """Return (speech, source) for an existing record, or raise NOT_FOUND."""
    text = ""
    if source_type == "event":
        runtime = state.events.get(source_id)
        if runtime:
            text = _clean(_sentence(runtime.summary.title), runtime.summary.summary)
    elif source_type == "decision":
        decision = next((d for d in state.decisions if d.id == source_id), None)
        if decision:
            text = _clean(
                _sentence(_name(state, decision.agent_id)),
                _sentence(decision.concise_rationale),
                decision.outcome_description,
            )
    elif source_type == "dialogue":
        line = next((d for d in state.dialogue if d.id == source_id), None)
        if line:
            speaker = _name(state, line.speaker_id)
            text = _clean(f"{speaker}:" if speaker and not live else "", line.text)
    else:
        raise DomainError("INVALID_REQUEST", "Unsupported narration source type", 400)
    require(text, "NOT_FOUND", "Narration source not found in this simulation", 404)
    require(
        not live or len(text) <= limit,
        "SERVICE_UNAVAILABLE",
        "Committed dialogue exceeds NARRATION_MAX_CHARACTERS; increase the configured limit",
        503,
    )
    return _bounded(text, limit)
