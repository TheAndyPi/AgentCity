"""Seeded identities and conservative upgrades for the original placeholder cast."""

import random

FIRST_NAMES = (
    "Maya",
    "Elias",
    "Nora",
    "Jules",
    "Priya",
    "Theo",
    "Amara",
    "Felix",
    "Lena",
    "Omar",
    "Iris",
    "Hugo",
    "Sofia",
    "Kai",
    "Zara",
    "Mateo",
    "Ada",
    "Noah",
    "Leila",
    "Arun",
    "Clara",
    "Miles",
    "Yuna",
    "Rafael",
    "Esme",
    "Jonah",
    "Imani",
    "Luca",
    "Mei",
    "Oscar",
    "Anika",
    "Silas",
)
LAST_NAMES = (
    "Reyes",
    "Chen",
    "Patel",
    "Brooks",
    "Okafor",
    "Rivera",
    "Kim",
    "Bennett",
    "Singh",
    "Morales",
    "Park",
    "Santos",
    "Walker",
    "Haddad",
    "Ito",
    "Clarke",
    "Nguyen",
    "Ali",
    "Costa",
    "Shah",
    "Mensah",
    "Reed",
    "Silva",
    "Tanaka",
    "Campbell",
    "Flores",
    "Laurent",
    "Ahmed",
    "Ellis",
    "Romero",
    "Das",
    "Walsh",
)
# Each occupation supplies a concrete ambition, worry and skill. Interests and
# history are selected independently so two people with the same job differ.
OCCUPATIONS = {
    "teacher": ("Start an after-school art club", "children losing a safe place to learn", "teaching"),
    "medic": (
        "Run a neighborhood first-aid class",
        "being unable to reach someone who needs care",
        "first aid",
    ),
    "builder": ("Restore a neglected house", "an unfinished repair becoming dangerous", "carpentry"),
    "shopkeeper": ("Open a stall selling local goods", "having to close my shop", "bookkeeping"),
    "engineer": (
        "Design a more reliable water system",
        "a preventable equipment failure",
        "repairing machines",
    ),
    "student": ("Finish my studies and earn a scholarship", "having to abandon my studies", "research"),
    "gardener": (
        "Grow a garden that neighbors can share",
        "losing a season of seedlings",
        "growing vegetables",
    ),
    "driver": ("Set up a dependable delivery route", "leaving someone stranded", "navigation"),
    "baker": ("Open a small neighborhood bakery", "wasting the savings for my bakery", "baking bread"),
    "librarian": (
        "Create a lending shelf on every street",
        "the library losing its regular visitors",
        "finding books",
    ),
    "musician": ("Organize a small outdoor concert", "losing the confidence to perform", "playing guitar"),
    "tailor": ("Teach a clothes-mending workshop", "being priced out of my workshop", "sewing"),
}
INTERESTS = (
    "sketching street scenes",
    "collecting old recipes",
    "birdwatching",
    "playing chess",
    "repairing bicycles",
    "learning a new language",
    "growing herbs",
    "photographing buildings",
    "writing short stories",
    "running before breakfast",
    "listening to jazz",
    "making pottery",
)
HISTORIES = (
    "Moved here after years in a much larger city",
    "Grew up nearby and returned after working elsewhere",
    "Arrived recently and is still finding a sense of belonging",
    "Stayed here after helping a relative through a difficult year",
    "Changed careers after a long period of uncertainty",
    "Has lived here for years but recently moved to a different street",
    "Came here to start again after a business closed",
    "Settled here after a friend described the neighborhood",
)
LEGACY_NAMES = ("Alex", "Morgan", "Sam", "Jordan", "Riley", "Casey", "Avery", "Taylor", "Cameron", "Drew")


def character_name(index, seed):
    # An odd stride permutes the 32 x 32 name space without collisions. It also
    # spreads first names across a cast instead of filling one surname at a time.
    rng = random.Random(f"names:{seed}")
    slot = (rng.randrange(1024) + index * rng.randrange(1, 1024, 2)) % 1024
    return f"{FIRST_NAMES[slot % 32]} {LAST_NAMES[slot // 32]}"


def character_details(role, traits, rng):
    ambition, worry, skill = OCCUPATIONS[role]
    interest = rng.choice(INTERESTS)
    history = rng.choice(HISTORIES)
    outlook = "Quick to explore unfamiliar ideas" if traits.curiosity >= 50 else "Prefers familiar routines"
    manner = "talkative and expressive" if traits.sociability >= 50 else "reserved and direct"
    priority = "mutual care" if traits.empathy >= 50 else "self-reliance"
    return dict(
        background=f"Works as a {role} and spends free time {interest}.",
        personality=f"{outlook}; {manner}.",
        values=[
            priority,
            rng.choice(["craftsmanship", "honesty", "creativity", "loyalty", "learning", "stability"]),
        ],
        primary_goal=ambition,
        secondary_goals=[f"Make more time for {interest}", "Keep my household safe and supplied"],
        desires=[
            f"More time for {interest}",
            rng.choice(["A close circle of friends", "A place of my own", "Work I can be proud of"]),
        ],
        fears=[worry],
        personal_history=f"I {history[0].lower() + history[1:]}. I hope to {ambition[0].lower() + ambition[1:]}.",
        skills=[skill, interest],
    )


def upgrade_placeholder_citizens(state):
    """Change only exact stock profiles, in a new revision, never stored history."""
    changed = False
    for index, citizen in enumerate(state.citizens.values()):
        profile = citizen.profile
        if citizen.profile_template_id or not (
            profile.name == f"{LEGACY_NAMES[index % 10]} {index + 1}"
            and profile.background == "A resident with local work and family responsibilities."
            and profile.primary_goal == "Keep my household safe and supplied"
            and profile.personal_history == "Has lived in this settlement and knows its public facilities."
            and profile.secondary_goals == ["Maintain friendships", "Finish my work"]
            and profile.desires == ["A stable home"]
            and profile.fears == ["Losing essential supplies"]
            and profile.role in OCCUPATIONS
            and profile.skills == [profile.role]
            and profile.personality
            == ("Community-minded" if profile.traits.cooperation >= 50 else "Independent and cautious")
            and profile.values
            == ["security", "community" if profile.traits.empathy >= 50 else "independence"]
        ):
            continue
        old_goals = [profile.primary_goal, *profile.secondary_goals]
        details = character_details(
            profile.role, profile.traits, random.Random(f"identity:{state.simulation.config.seed}:{index}")
        )
        citizen.profile = profile.model_copy(
            update=dict(name=character_name(index, state.simulation.config.seed), **details)
        )
        citizen.summary.name = citizen.profile.name
        if citizen.goals == old_goals:
            citizen.goals = [citizen.profile.primary_goal, *citizen.profile.secondary_goals]
        citizen.generation += 1
        changed = True
    return changed
