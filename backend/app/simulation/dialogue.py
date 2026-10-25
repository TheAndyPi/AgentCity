"""Local, reproducible speech grounded in disclosures and the speaker's own life.

Only the speaker's private state is read. Conversation topics record information
already spoken aloud; they never grant access to a listener's private profile.
"""

import hashlib


def choose(options, state, actor, interaction, previous):
    key = f"{state.simulation.config.seed}:{actor.summary.id}:{interaction.id}:{len(previous)}"
    offset = int.from_bytes(hashlib.sha256(key.encode()).digest()[:4]) % len(options)
    recent = {line.text for line in state.dialogue_index().by_speaker.get(actor.summary.id, [])[-100:]}
    return next(
        (
            options[(offset + i) % len(options)]
            for i in range(len(options))
            if options[(offset + i) % len(options)] not in recent
        ),
        options[offset],
    )


def phrase(value):
    return value[:250].strip().rstrip(".!?")


def personal_detail(actor):
    # The second skill is a leisure interest for generated profiles. Custom
    # characters can instead speak about their authored desires or main goal.
    if len(actor.profile.skills) > 1:
        return f"I've been making time for {phrase(actor.profile.skills[1])}."
    if actor.profile.desires:
        return f"Something I'd like is {phrase(actor.profile.desires[0])}."
    return f"I'm hoping to {phrase(actor.profile.primary_goal).lower()}."


def opening_topic(state, actor, target, reason=""):
    index = state.dialogue_index()
    past = [line.text for line in index.pair_lines(actor.summary.id, target.summary.id)[-100:]]
    events = [m for m in actor.memories[-512:] if m.text.startswith("World event:")]
    fresh = [
        m for m in events if not any(m.text.removeprefix("World event: ")[:160] in text for text in past)
    ]
    if fresh:
        return {"kind": "event", "detail": phrase(fresh[-1].text.removeprefix("World event: "))}
    if actor.needs.hunger >= 45 or min(actor.inventory.food, actor.inventory.water) < 1:
        return {
            "kind": "supplies",
            "detail": "food" if actor.inventory.food <= actor.inventory.water else "water",
        }
    if actor.needs.fatigue >= 50:
        return {"kind": "rest", "detail": "a chance to rest"}
    if "looks" in reason and "check" in reason:
        return {"kind": "check_in", "detail": target.summary.emotion}
    if "catch up" in reason:
        return {"kind": "catch_up", "detail": personal_detail(actor)}
    if "ask about their work" in reason:
        return {"kind": "work", "detail": target.summary.role}
    topics = [
        {"kind": "goal", "detail": phrase(actor.profile.primary_goal).lower()},
        {"kind": "interest", "detail": personal_detail(actor)},
        {"kind": "history", "detail": phrase(actor.profile.personal_history)},
    ]
    if events:
        topics.append({"kind": "event", "detail": phrase(events[-1].text.removeprefix("World event: "))})
    if actor.profile.secondary_goals:
        topics.append({"kind": "goal", "detail": phrase(actor.profile.secondary_goals[0]).lower()})
    # Rotate topics across meetings without consuming the world's physical RNG.
    meetings = index.meeting_count(actor.summary.id, target.summary.id)
    offset = int.from_bytes(hashlib.sha256(actor.summary.id.encode()).digest()[:2])
    return topics[(offset + meetings) % len(topics)]


def rule_speech(state, actor, target, intent, interaction, previous):
    name = target.summary.name.split()[0]
    if intent.action == "talk" and not previous:
        for memory in reversed(actor.memories[-512:]):
            if (
                memory.source not in {"observed", "heard"}
                or not memory.text.startswith(("I witnessed ", "I heard about "))
                or "death" not in memory.text.lower()
            ):
                continue
            for aid in memory.subject_ids:
                deceased = state.citizens.get(aid)
                if deceased and not deceased.summary.active:
                    report = (
                        f"{name}, I learned that {deceased.summary.name} has died. I could use some support."
                    )
                    if not state.dialogue_index().has_said(actor.summary.id, target.summary.id, report):
                        return report
    if intent.action == "warn":
        events = [m for m in actor.memories[-512:] if m.text.startswith("World event:")]
        detail = f"{phrase(events[-1].text.removeprefix('World event: '))}. " if events else ""
        return choose(
            [
                f"{name}, please be careful. {detail}Let's look for a safe route.",
                f"Watch out, {name}. {detail}We should get somewhere safe.",
            ],
            state,
            actor,
            interaction,
            previous,
        )

    # A provider's message stays verbatim, and later rule replies can respond to
    # its actual words rather than continuing an unrelated scripted exchange.
    topic = interaction.proposal.get("dialogue_topic")
    if previous and (topic is None or interaction.proposal.get("last_rule_line") != previous[-1].id):
        detail = phrase(previous[-1].text)
        interaction.proposal["dialogue_topic"] = {"kind": "external", "detail": detail}
        question = previous[-1].text.lower()
        if "?" in question:
            resource = next((kind for kind in ("food", "water", "supplies") if kind in question), None)
            if resource:
                options = [
                    f"I've got {getattr(actor.inventory, resource):g} units of {resource} myself, {name}."
                ]
            elif any(word in question for word in ("tired", "energy", "rest")):
                options = [
                    "I'm worn out myself."
                    if actor.needs.fatigue >= 50
                    else "I've still got some energy left."
                ]
            elif any(word in question for word in ("brought you", "from", "settled", "live here")):
                options = [f"{phrase(actor.profile.personal_history)}."]
            elif any(word in question for word in ("plan", "goal", "working on")):
                options = [f"I'd like to {phrase(actor.profile.primary_goal).lower()}. What about you?"]
            elif any(word in question for word in ("free time", "quiet moment", "hobb", "enjoy")):
                options = [personal_detail(actor)]
            else:
                options = [
                    f"I'm not sure how to answer “{detail}” yet, {name}. What do you think?",
                    f"“{detail}” — I need to think about that. What made you ask?",
                ]
        else:
            options = [
                f"You said, “{detail}.” What led you to that, {name}?",
                f"“{detail}” — I want to understand. What matters most to you about it?",
            ]
        return choose(options, state, actor, interaction, previous)
    if not previous:
        topic = opening_topic(state, actor, target, interaction.proposal.get("approach_reason", ""))
        interaction.proposal["dialogue_topic"] = topic
    kind, detail = topic["kind"], topic["detail"]
    empathetic = actor.profile.traits.empathy >= 50
    relationship = actor.relationships.get(target.summary.id)
    familiar = relationship and relationship.familiarity >= 30
    greeting = f"{name}, good to see you." if familiar else f"Hi {name}."
    goal = phrase(actor.profile.primary_goal).lower()
    turn = len(previous)
    supplies = getattr(actor.inventory, detail) if kind == "supplies" else 0
    if turn == 0:
        options = {
            "check_in": [f"{greeting} You look {detail}. How are you doing?"],
            "catch_up": [f"{greeting} I wanted to catch up. How has your day been?"],
            "work": [f"{greeting} What's it like working as a {detail}? What are you working on lately?"],
            "event": [
                f"{greeting} {detail}. What do you make of it?",
                f"I can't stop thinking about this: {detail}. Have you heard anything, {name}?",
            ],
            "supplies": [
                f"{greeting} I'm running low on {detail}. How are you managing?",
                f"I'm trying to stretch my {detail}, {name}. Have you had any luck finding more?",
            ],
            "rest": [
                f"{greeting} I'm worn out and need a breather. How has your day been?",
                f"I need to slow down for a bit, {name}. What's been keeping you busy?",
            ],
            "goal": [
                f"{greeting} I'd like to {detail}. Where would you start?",
                f"I've been trying to {detail}, {name}. Do you ever take on something that feels too big?",
            ],
            "interest": [
                f"{greeting} {detail} What do you do when you get a quiet moment?",
                f"{detail} It gives me something to look forward to. What about you, {name}?",
            ],
            "history": [
                f"{greeting} {detail}. What brought you to this neighborhood?",
                f"I've been thinking about how I ended up here, {name}. {detail}. How about you?",
            ],
        }[kind]
    elif turn == 1:
        # React to what the opener actually disclosed, then offer the responder's
        # own condition or history. No claim to know the other person's mind.
        options = {
            "check_in": [
                f"{'I am worn out and could use a rest' if actor.needs.fatigue >= 50 else 'I am doing all right, thank you for asking'}. {personal_detail(actor)} How about you?"
            ],
            "catch_up": [
                f"I've been trying to {goal}. {'I could use a break' if actor.needs.fatigue >= 45 else 'I feel like I am making some progress'}. How has yours been?"
            ],
            "work": [
                f"As a {actor.profile.role}, I spend a lot of time helping where I can. Right now I'd like to {goal}. What drew you to ask?"
            ],
            "event": [
                f"{detail}? That's a lot to take in. I want to know more before deciding what to do.",
                f"{detail} — if that's what's happening, I'll need to rethink my plans to {goal}.",
            ],
            "supplies": [
                f"I've got {supplies:g} units of {detail} left myself. I'm trying to make them last.",
                f"{detail.capitalize()} is something I need to keep an eye on too. I don't want either of us caught short.",
            ],
            "rest": [
                f"My own energy's {'running low too' if actor.needs.fatigue >= 50 else 'holding up so far'}. What wore you out?",
                f"Take a moment, {name}. I've been focused on trying to {goal}.",
            ],
            "goal": [
                f"To {detail}? I'd start small. In my own work as a {actor.profile.role}, that helps me get moving.",
                f"I can see why you'd want to {detail}. I'm hoping to {goal}, so I know that feeling.",
            ],
            "interest": [
                f"{personal_detail(actor)} It's {'nice to find that we both need a little time for ourselves' if empathetic else 'how I clear my head'}.",
                f"In a quiet moment? {personal_detail(actor)} What got you interested?",
            ],
            "history": [
                f"{phrase(actor.profile.personal_history)}. I'm still working out what comes next.",
                f"For me, it was this: {phrase(actor.profile.personal_history)}. Do you feel settled here?",
            ],
        }[kind]
    elif turn == 2:
        last = previous[-1].text.lower()
        options = {
            "check_in": [
                f"{'I have been tired too' if actor.needs.fatigue >= 50 else 'I am doing well today'}. {personal_detail(actor)} I'm glad we stopped to talk."
            ],
            "catch_up": [
                f"{'It has been a busy day for me too' if actor.needs.fatigue >= 45 else 'Mine has been fairly quiet'}. {personal_detail(actor)}"
            ],
            "work": [
                f"I'm thinking about my own plan to {goal}, and wanted to hear your experience rather than guess."
            ],
            "external": [
                f"What you said gives me something to think about. I'm hoping to {goal}, and I wonder how that fits.",
                f"I don't have it all worked out either, {name}. {personal_detail(actor)}",
            ],
            "event": [
                f"I don't want to jump to conclusions either. {personal_detail(actor)} Days like this make that harder.",
                f"I'll keep an eye on what I can actually see. I'm still hoping to {goal}.",
            ],
            "supplies": [
                f"It helps to know where you stand. I'd rather talk about {detail} now than wait until it's gone.",
                f"I'll check what I have before making plans. I still want to {goal}.",
            ],
            "rest": [
                f"A little space to think would help. {personal_detail(actor)}",
                f"You're right to ask. I'm trying to {goal}, and I need to pace myself.",
            ],
            "goal": [
                f"{'Starting small sounds manageable' if 'start small' in last else 'It helps to hear what you are working toward'}. I keep coming back to wanting to {detail}.",
                f"Hearing your side helps. {personal_detail(actor)} That's another thing I don't want to lose time for.",
            ],
            "interest": [
                f"It grew out of my own experience. {phrase(actor.profile.personal_history)}. I kept coming back to it.",
                f"{personal_detail(actor)} It gives me a little space to slow down when work takes over.",
            ],
            "history": [
                f"I {'feel more at home when I get to know people like this' if empathetic else 'need time before a place feels like home'}. {personal_detail(actor)}",
                f"There are things I miss, but I'd like to {goal} here. That's a reason to stay.",
            ],
        }[kind]
    else:
        subject = {
            "check_in": "how we are doing",
            "catch_up": "our day",
            "work": "our work and plans",
            "external": "what you said",
            "event": "what's happening",
            "supplies": f"the {detail} situation",
            "rest": "taking a breather",
            "goal": f"your hope to {detail}",
            "interest": "making time for ourselves",
            "history": "how we ended up here",
        }[kind]
        options = [
            f"I'm glad we talked about {subject}, {name}. I'll let you get back to your day.",
            f"You've given me something to think about — {subject}. Take care, {name}.",
            f"Let's pick this up another time, {name}. I need to get back to my own plans.",
        ]
    if (
        turn == 1
        and kind == "goal"
        and relationship
        and (relationship.trust < 35 or relationship.conflict >= 40)
    ):
        options = [
            f"I'm not sure about your plan to {detail}, {name}. What would it mean for everyone else?",
            f"Before I get behind your idea to {detail}, I'd want to hear a practical first step.",
        ]
    elif turn == 1 and kind == "event" and actor.profile.traits.risk_tolerance < 35:
        options = [f"{detail}? I'd rather be cautious until I know more. How did you find out?"]
    return choose(options, state, actor, interaction, previous)
