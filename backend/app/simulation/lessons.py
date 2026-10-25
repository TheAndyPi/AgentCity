"""Community lessons grounded in what citizens recorded during an event's interval."""

from collections import Counter

from app.contracts import Metrics
from app.simulation.agents import evidence, hazard_severity

METRIC_THRESHOLD = 1.0
MAX_NAMES = 3
MAX_EVIDENCE_IDS = 20
QUOTE_LENGTH = 160


def join(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def plural(count, word, many=None):
    return f"{count} {word if count == 1 else many or word + 's'}"


def names(state, ids):
    people = [state.citizens[aid].summary.name for aid in dict.fromkeys(ids) if aid in state.citizens]
    if len(people) > MAX_NAMES:
        people = people[:MAX_NAMES] + [plural(len(people) - MAX_NAMES, "other")]
    return join(people) if people else "Citizens"


def quote(text):
    text = " ".join(text.split())
    text = text if len(text) <= QUOTE_LENGTH else text[: QUOTE_LENGTH - 1].rstrip() + "…"
    return f'"{text}"'


def sentence(text):
    return text if text.rstrip('"')[-1:] in {".", "?", "!", "…"} else text + "."


def mentions_event(runtime, text):
    text = text.lower()
    return runtime.spec.title.lower() in text or runtime.spec.description[:80].lower() in text


def fact(theme, text, decisions=(), memory_ids=()):
    return dict(
        theme=theme,
        text=text,
        decision_ids=[d.id for d in decisions][:MAX_EVIDENCE_IDS],
        memory_ids=list(memory_ids)[:MAX_EVIDENCE_IDS],
    )


def spoken(state, decisions, action):
    keys = {(d.agent_id, d.tick) for d in decisions}
    return [line for line in state.dialogue if line.intent == action and (line.speaker_id, line.tick) in keys]


def gather_facts(state, runtime):
    """Called while the event is still active so hazard exposure is measurable."""
    start = runtime.summary.start_tick or 0
    end = state.simulation.tick
    cohort = set(runtime.cohort)
    buildings = {b.id: b for b in state.map.buildings}
    window = [d for d in state.decisions if start <= d.tick <= end and d.agent_id in cohort]

    def taken(action):
        return [d for d in window if d.intent.action == action and d.outcome != "rejected"]

    facts = []
    if cohort and any(e.type == "hazard" for e in runtime.spec.effects):
        total = len(cohort)
        evacuations = taken("evacuate")
        shelters = Counter(d.intent.target_id for d in evacuations if d.intent.target_id in buildings)
        text = (
            f"All {total} citizens in the affected area reached safety"
            if runtime.evacuated_count == total
            else f"{runtime.evacuated_count} of {total} citizens in the affected area reached safety"
        )
        if shelters:
            shelter, count = shelters.most_common(1)[0]
            text += f"; {count} of them headed for {buildings[shelter].name}"
        facts.append(fact("safety", text + ".", evacuations))
        stranded = [
            aid
            for aid in runtime.cohort
            if state.citizens[aid].summary.active
            and hazard_severity(state, state.citizens[aid].summary.position) > 0
        ]
        if stranded:
            facts.append(
                fact(
                    "safety",
                    f"{names(state, stranded)} {'was' if len(stranded) == 1 else 'were'} "
                    "still caught in the hazard when it ended.",
                )
            )

    warnings = taken("warn")
    if warnings:
        lines = spoken(state, warnings, "warn")
        text = (
            f"{names(state, [d.agent_id for d in warnings])} warned "
            f"{plural(len({d.intent.target_id for d in warnings}), 'neighbor')}"
        )
        facts.append(
            fact("warning", sentence(text + (f", saying {quote(lines[0].text)}" if lines else "")), warnings)
        )

    helping = taken("help")
    if helping:
        facts.append(
            fact(
                "mutual_aid",
                f"{names(state, [d.agent_id for d in helping])} gave supplies to "
                f"{names(state, [d.intent.target_id for d in helping])} "
                f"({plural(len(helping), 'act')} of help).",
                helping,
            )
        )
    trades = [d for d in taken("trade") if d.outcome_description.startswith("Both parties accepted")]
    if trades:
        facts.append(
            fact(
                "mutual_aid",
                f"{names(state, [d.agent_id for d in trades] + [d.intent.target_id for d in trades])} "
                f"completed {plural(len(trades), 'trade')} to cover what each other lacked.",
                trades,
            )
        )
    aid = [
        change
        for change in state.external_resource_changes
        if change.get("event_id") == runtime.summary.id and change.get("reason") == "external community aid"
    ]
    if aid:
        recipients = {change["agent_id"] for change in aid}
        facts.append(
            fact(
                "outside_aid",
                f"Community aid delivered {sum(c['units'] for c in aid):.2f} units of supplies "
                f"to {plural(len(recipients), 'citizen')}.",
            )
        )

    contested = [d for d in window if d.rejection_code == "RESOURCE_CONTESTED"]
    if contested:
        kinds = Counter(d.intent.parameters.resource_kind or "supplies" for d in contested)
        facts.append(
            fact(
                "scarcity",
                f"{names(state, [d.agent_id for d in contested])} reached for "
                f"{join(sorted(kinds))} that had already run out "
                f"({plural(len(contested), 'contested claim')}).",
                contested,
            )
        )

    talks = taken("talk")
    about = [line for line in spoken(state, talks, "talk") if mentions_event(runtime, line.text)]
    if about:
        keys = {(line.speaker_id, line.tick) for line in about}
        line = about[0]
        text = (
            f"Neighbors talked the event over in "
            f"{plural(len({line.interaction_id for line in about}), 'conversation')}; "
            f"{names(state, [line.speaker_id])} told {names(state, line.recipient_ids)}, {quote(line.text)}"
        )
        facts.append(fact("information", sentence(text), [d for d in talks if (d.agent_id, d.tick) in keys]))

    if any(e.type == "information" and e.reliability < 100 for e in runtime.spec.effects):
        heard = [
            memory.id
            for citizen in state.citizens.values()
            for memory in citizen.memories
            if memory.source == "heard" and runtime.summary.id in memory.evidence.event_ids
        ]
        if heard:
            facts.append(
                fact(
                    "rumor",
                    f"{plural(len(heard), 'citizen')} heard an unverified report about the event "
                    "before anyone could confirm it.",
                    memory_ids=heard,
                )
            )

    delta = {key: getattr(runtime.after, key) - getattr(runtime.before, key) for key in Metrics.model_fields}
    labels = dict(happiness="happiness", trust="trust between neighbors", safety="safety", stress="stress")
    changes = [
        f"{labels[key]} {'rose' if delta[key] > 0 else 'fell'} by {abs(delta[key]):.2f} points"
        for key in labels
        if abs(delta[key]) >= METRIC_THRESHOLD
    ]
    if changes:
        facts.append(fact("measure", f"Over the event, {join(changes)}."))
    return facts


TAKEAWAYS = dict(
    safety=("The community learned that knowing where shelter is ahead of time gets people out of danger."),
    safety_warned=(
        "The community learned that knowing where shelter is, and passing warnings along quickly, "
        "gets people out of danger."
    ),
    warning=("The community learned that speaking up early gives neighbors time to act."),
    safety_struggled=(
        "The community learned that safe routes and shelters have to be known before an emergency, "
        "because there is little time to find them once it starts."
    ),
    mutual_aid=(
        "The community learned that neighbors can rely on one another when supplies run short, "
        "and that sharing reaches people a single household could not."
    ),
    outside_aid=(
        "The community learned that aid arriving at one shared point can reach every household in the "
        "area, as long as people know where to collect it."
    ),
    scarcity=(
        "The community learned that shared stock runs out quickly under pressure, and that a fair way "
        "to divide it keeps neighbors from competing for the last of it."
    ),
    information=(
        "The community learned that talking an event through keeps people informed and connected, "
        "so news reaches those who did not see it firsthand."
    ),
    rumor=(
        "The community learned to check a report before acting on it, because word travels faster "
        "than anyone can confirm it."
    ),
    festival=(
        "The community learned that gathering for something joyful lifts people's spirits and gives "
        "neighbors a reason to come together."
    ),
)


def lesson_evidence(runtime, facts):
    return evidence(
        "Recorded citizen actions and measurements during the event interval",
        event_ids=[runtime.summary.id],
        decision_ids=list(dict.fromkeys(i for f in facts for i in f["decision_ids"]))[:MAX_EVIDENCE_IDS],
        memory_ids=list(dict.fromkeys(i for f in facts for i in f["memory_ids"]))[:MAX_EVIDENCE_IDS],
    ).model_dump()


def lesson(runtime, facts, takeaway):
    text = " ".join([*(f["text"] for f in facts), takeaway])
    return dict(text=text[:2000], evidence=lesson_evidence(runtime, facts))


def compose_lessons(runtime, facts):
    """Template lessons: what happened, then what the community took from it."""
    by_theme = {}
    for item in facts:
        by_theme.setdefault(item["theme"], []).append(item)
    lessons = []
    warnings = by_theme.get("warning", [])
    if "safety" in by_theme:
        struggled = runtime.evacuated_count * 2 < len(runtime.cohort)
        takeaway = "safety_struggled" if struggled else "safety_warned" if warnings else "safety"
        lessons.append(lesson(runtime, by_theme["safety"] + warnings, TAKEAWAYS[takeaway]))
    elif warnings:
        lessons.append(lesson(runtime, warnings, TAKEAWAYS["warning"]))
    aid = by_theme.get("mutual_aid", []) + by_theme.get("outside_aid", [])
    if aid:
        lessons.append(
            lesson(runtime, aid, TAKEAWAYS["mutual_aid" if "mutual_aid" in by_theme else "outside_aid"])
        )
    for theme in ("scarcity", "rumor", "information"):
        if theme in by_theme:
            lessons.append(lesson(runtime, by_theme[theme], TAKEAWAYS[theme]))
    festival = any(e.type == "community" and e.activity == "festival" for e in runtime.spec.effects)
    measures = by_theme.get("measure", [])
    if festival and measures:
        lessons.insert(0, lesson(runtime, measures, TAKEAWAYS["festival"]))
    elif lessons and measures:
        first = lessons[0]
        first["text"] = (first["text"] + " " + measures[0]["text"])[:2000]
    return lessons


def lesson_material(runtime):
    return dict(
        event=dict(
            title=runtime.spec.title,
            kind=runtime.spec.kind,
            description=runtime.spec.description[:2000],
            affected_citizens=len(runtime.cohort),
        ),
        facts=[dict(id=i, theme=f["theme"], text=f["text"]) for i, f in enumerate(runtime.lesson_facts)],
        draft_lessons=[lesson["text"] for lesson in runtime.lessons],
    )


def adopt_drafts(runtime, drafts):
    """Accept model-written lessons only when they cite recorded facts; otherwise keep templates."""
    facts = runtime.lesson_facts
    lessons = []
    for draft in drafts:
        cited = [facts[i] for i in dict.fromkeys(draft.fact_ids) if 0 <= i < len(facts)]
        text = " ".join(draft.text.split())
        if cited and text:
            lessons.append(dict(text=text[:2000], evidence=lesson_evidence(runtime, cited)))
    return lessons
