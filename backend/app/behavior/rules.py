"""Versioned gameplay data. Time-based rates are per ten simulated seconds."""

VERSION = "2.0.0"
RULES = {
    "mental_default": 70,
    "distribution_weights": [0.4, 0.8, 1.8],
    "hoarding_units": 2,
    "uncertain_warning_trust": 40,
    "support_trust": 60,
    "distress_mental": 40,
    "distress_stress": 65,
    "quiet_sociability": 40,
    "cautious_risk": 40,
    "curiosity_threshold": 70,
    "mental_trigger": 10,
    "stress_trigger": 80,
    "mental_exit": 25,
    "stress_exit": 60,
    "exit_ticks": 3,
    "episode_ticks": 60,
    "cooldown_ticks": 12,
    "wake_energy": 20,
    "passive_energy": 1.5,
    "bed_energy": 4,
    "rest_mental": 0.5,
    "comfort_mental": 3,
    "comfort_stress": -3,
    "comfort_social": 6,
    "grief_mental": -8,
    "attack_damage": 12,
    "attack_cooldown": 3,
    "attack_mental": -2,
    "fire_cap": 3,
    "fire_radius": 3,
    "fire_severity": 60,
    "fire_ticks": 12,
    "fire_damage": 2,
    "suppress_units": 1,
    "helper_health": 60,
    "helper_energy": 25,
    "helper_fullness": 25,
    "helper_mental": 25,
    "helper_mobility": 20,
    "helper_empathy": 65,
    "helper_cooperation": 65,
    "injured_health": 45,
    "release_health": 75,
    "treatment_units": 0.25,
    "treatment_health": 3,
    "treatment_mental": 1,
    "treatment_stress": -2,
    "hospital_stock": 6,
    "poor_boundary": 10,
    "rich_boundary": 24,
    "band_hysteresis": 2,
    "class_cadence": 12,
    "class_penalty": 3,
    "class_support": 3,
    "neutral_trust": 50,
    "range": 3,
    "mental_coefficients": {
        "happiness": [0.12, -0.30],
        "safety": [0.10, -0.35],
        "trust": [0.08, -0.20],
        "resources": [0.06, -0.30],
        "stress": [0, -0.55],
    },
    "social_coefficients": {
        "happiness": 0.15,
        "safety": 0.10,
        "trust": 0.15,
        "resources": 0.10,
        "stress": 0.20,
    },
    "energy_coefficients": {
        "happiness": 0.12,
        "safety": 0.20,
        "trust": 0.10,
        "resources": 0.18,
        "stress": 0.30,
    },
    "mental_cap": [-1.50, 0.30],
    "social_cap": 0.50,
    "energy_cap": 0.60,
    "social_good": {"happiness": 0.20, "safety": 0.20, "trust": 0.25, "resources": 0.10},
    "social_strain": -0.25,
    "social_distrust": -0.20,
    "social_range": [0.50, 1.60],
    "rest_good": {"happiness": 0.10, "safety": 0.20, "trust": 0.05, "resources": 0.05},
    "rest_bad": {"safety": -0.20, "resources": -0.15},
    "rest_strain": -0.25,
    "rest_range": [0.50, 1.40],
    "mode_weights": {"withdrawal": 1, "panic": 1, "support": 1, "aggression": 0.05, "fire": 0.02},
    "mode_trait_weight": 4,
    "mode_need_weight": 0.5,
    "mode_grief_weight": 1,
    "mode_stress_weight": 0.5,
    "violent_grievance": 30,
    "share_units": 1,
}


def bounded(x, low=0, high=100):
    return max(low, min(high, x))


def bad(x):
    return bounded((40 - x) / 40, 0, 1)


def good(x):
    return bounded((x - 60) / 40, 0, 1)


def strain(x):
    return bounded((x - 40) / 60, 0, 1)


def coupling(metrics, seconds, rules=RULES):
    """Pure frozen-input simultaneous outputs, with capped component attribution."""
    m = metrics.model_dump() if hasattr(metrics, "model_dump") else dict(metrics)
    mental = {
        k: a * good(m[k]) + b * (strain(m[k]) if k == "stress" else bad(m[k]))
        for k, (a, b) in rules["mental_coefficients"].items()
    }
    outputs = {"mental": mental}
    for meter in ("social", "energy"):
        outputs[meter] = {
            k: -v * (strain(m[k]) if k == "stress" else bad(m[k]))
            for k, v in rules[meter + "_coefficients"].items()
        }
    for meter, components in outputs.items():
        total = sum(components.values())
        cap = rules["mental_cap"] if meter == "mental" else [-rules[meter + "_cap"], 0]
        final = bounded(total, *cap)
        scale = (final / total if total else 1) * seconds / 10
        outputs[meter] = {k: v * scale for k, v in components.items() if v}
    return outputs


def social_multiplier(citizen, partner, rules=RULES):
    m = citizen.summary.metrics.model_dump()
    tie = citizen.relationships.get(partner.summary.id)
    m["trust"] = tie.trust if tie else rules["neutral_trust"]
    return bounded(
        1
        + sum(v * good(m[k]) for k, v in rules["social_good"].items())
        + rules["social_strain"] * strain(m["stress"])
        + rules["social_distrust"] * bad(m["trust"]),
        *rules["social_range"],
    )


def rest_multiplier(citizen, rules=RULES):
    m = citizen.summary.metrics.model_dump()
    # Adequate supplies alone cannot confer the nutrition-dependent bonus.
    fed = citizen.needs.hunger < 45 and citizen.inventory.food > 0 and citizen.inventory.water > 0
    positive = sum(v * good(m[k]) for k, v in rules["rest_good"].items() if k != "resources" or fed)
    return bounded(
        1
        + positive
        + sum(v * bad(m[k]) for k, v in rules["rest_bad"].items())
        + rules["rest_strain"] * strain(m["stress"]),
        *rules["rest_range"],
    )
