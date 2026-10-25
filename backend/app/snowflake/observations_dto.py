"""Versioned observation vocabulary, independent of frozen simulation contracts."""

AGENT_METRICS = (
    "happiness",
    "safety",
    "trust",
    "resources",
    "stress",
    "health",
    "hunger",
    "fatigue",
    "social_need",
    "mental",
    "institutional_trust",
)
RELATIONSHIP_METRICS = {
    "relationship_trust": "trust",
    "relationship_affection": "affection",
    "relationship_conflict": "conflict",
    "relationship_respect": "respect",
    "relationship_familiarity": "familiarity",
}
COUNT_METRICS = (
    "population",
    "deaths",
    "cooperation_count",
    "conflict_count",
    "relationship_pairs",
    "opinion_count",
    "opinion_adoptions",
    "opinion_removals",
)
METRICS = {
    **{
        key: {
            "id": key,
            "label": key.replace("_", " ").capitalize(),
            "unit": "population_mean_0_100",
            "denominator": "Living active agents with a recorded value",
        }
        for key in AGENT_METRICS
    },
    **{
        key: {
            "id": key,
            "label": key.replace("_", " ").capitalize(),
            "unit": "directed_mean_0_100",
            "denominator": "Known directed ties between living active agents",
        }
        for key in RELATIONSHIP_METRICS
    },
    **{
        key: {
            "id": key,
            "label": key.replace("_", " ").capitalize(),
            "unit": "recorded_count",
            "denominator": "Recorded entities or distinct changes at this tick",
        }
        for key in COUNT_METRICS
    },
    "opinion_confidence": {
        "id": "opinion_confidence",
        "label": "Belief confidence",
        "unit": "recorded_confidence_0_100",
        "denominator": "Recorded numeric belief confidence on the source 0–100 scale",
    },
}


def empty_coverage():
    return {"state": "unavailable", "from_tick": None, "through_tick": None}
