"""Agent response engine: individual choices under the current world systems.

The interpreter decides what changes in the world; nothing here is predicted by it.
Each citizen weighs options with their own traits, income, wallet, household,
memories, relationships, knowledge and the laws in force. Scores carry a small
reproducible personal variation, so two similar citizens can still differ.
"""

from app.contracts import Belief as CoreBelief
from app.contracts import EffectChange
from app.scenario_engine.systems import (
    MODE_SPEED,
    STRAIN_WALLET,
    TRIP_MIN_METERS,
    Belief,
    PolicyState,
    bump,
    in_region,
    unit,
)
from app.scenario_engine.world import (
    change,
    current_event,
    decide,
    housing_share,
    rent_multiplier,
    trace,
    walking_speed,
)
from app.simulation.agents import clamp, evidence, metric_delta, remember
from app.simulation.navigation import distance
from app.simulation.timing import legacy_ticks

BASELINE = PolicyState()
MODE_LABEL = {"walk": "on foot", "transit": "by public transit", "car": "by car"}
INCOME_SENSITIVITY = {"low": 1.25, "middle": 0.9, "high": 0.45}


def effective_service(state):
    level = state.systems.policy.transportation.transit_service_level
    return level * (0.5 if state.systems.treasury < -30 else 1)


def trip_length(citizen):
    points = [citizen.summary.position, *citizen.summary.path]
    return sum(distance(a, b) for a, b in zip(points, points[1:]))


def known_cost(state, agent, mode):
    """What the citizen believes a trip costs: the current price only once they know it."""
    transport = state.systems.policy.transportation
    actual = transport.transit_fare if mode == "transit" else transport.car_trip_cost if mode == "car" else 0
    if mode == "walk":
        return 0.0
    target = "transportation.transit_fare" if mode == "transit" else "transportation.car_trip_cost"
    changed = state.systems.counters.get(f"changed:{target}")
    if changed is None:
        return actual
    informed = (
        any(
            belief.topic in {"transport", "policy_change", "prices"} and belief.tick >= changed
            for belief in agent.beliefs.values()
        )
        or agent.last_paid.get(f"{mode}_tick", -1) >= changed
    )
    if informed:
        return actual
    return agent.last_paid.get(mode, getattr(BASELINE.transportation, target.split(".")[1]))


def mode_scores(state, citizen, agent, meters, noise=True):
    transport = state.systems.policy.transportation
    service = effective_service(state)
    walk = walking_speed(citizen)
    sensitivity = INCOME_SENSITIVITY[agent.income] * (1.8 if agent.wallet < 5 else 1)
    time_value = 0.4 * (1 + citizen.needs.fatigue / 100 + (1 - citizen.profile.mobility / 100) * 0.5)
    trust = agent.institutional_trust / 100
    options = {"walk": (walk, 0.0)}
    if service > 0:
        options["transit"] = (
            walk * MODE_SPEED["transit"] * (0.6 + 0.4 * min(service, 2)),
            0.3 / max(service, 0.25),
        )
    if agent.owns_car:
        options["car"] = (walk * MODE_SPEED["car"], 0.1)
    scores = []
    for mode, (speed, wait) in options.items():
        expected = known_cost(state, agent, mode)
        ticks = meters / (speed * 10) + wait
        score = -expected * sensitivity - ticks * time_value
        why = []
        if mode == agent.habit:
            score += 0.2
            why.append("it is my usual way to travel")
        if mode == "transit":
            norm = agent.norms.get("use_public_transit", 0)
            score += norm * 0.8 + transport.transit_campaign * trust * 0.8
            score += agent.incentives.get("transit_rebate", 0) * sensitivity
            if norm:
                why.append("people I know ride transit")
            if transport.transit_campaign and trust > 0.5:
                why.append("the city asked us to ride transit")
        if mode == "car":
            score += 0.15 - transport.transit_campaign * trust * 0.3
        if noise:
            score += (unit(citizen.summary.id, mode, state.simulation.tick // 30) - 0.5) * 0.3
        actual = (
            transport.transit_fare if mode == "transit" else transport.car_trip_cost if mode == "car" else 0
        )
        label = f"Travel {MODE_LABEL[mode]} (about {ticks:.1f} ticks, expected cost {expected:.2f})"
        scores.append(
            dict(
                action=mode,
                label=label,
                score=score if actual <= agent.wallet else -1e6,
                why="; ".join(why) or f"it costs {expected:.2f} credits and takes {ticks:.1f} ticks",
                cost=actual,
                expected=expected,
            )
        )
    return scores


def habitual_mode(state, citizen, agent):
    scores = mode_scores(state, citizen, agent, 30, noise=False)
    for item in scores:
        item["score"] += (unit(citizen.summary.id, item["action"], "habit") - 0.5) * 0.8
    return max(scores, key=lambda s: (s["score"], s["action"]))["action"]


def choose_trip_mode(state, citizen, agent, decision):
    meters = trip_length(citizen)
    base = walking_speed(citizen)
    if meters < TRIP_MIN_METERS:
        citizen.summary.movement_speed_mps = base
        agent.trip_mode = None
        return
    scores = mode_scores(state, citizen, agent, meters)
    chosen = max(scores, key=lambda s: (s["score"], s["action"]))
    mode = chosen["action"]
    systems = state.systems
    event_id = current_event(state)
    changes = []
    if chosen["cost"]:
        before = agent.wallet
        agent.wallet = round(agent.wallet - chosen["cost"], 4)
        changes.append(change(citizen.summary.id, "wallet", before, agent.wallet))
        if mode == "transit":
            systems.treasury += chosen["cost"]
            bump(systems, "fare_revenue", chosen["cost"])
        rebate = agent.incentives.get("transit_rebate", 0) if mode == "transit" else 0
        if rebate:
            paid = min(rebate, chosen["cost"])
            agent.wallet += paid
            systems.treasury -= paid
    if abs(chosen["expected"] - chosen["cost"]) > 1e-9 and mode != "walk":
        memory = remember(
            state,
            citizen,
            f"The {mode} trip cost {chosen['cost']:.2f} credits; I expected {chosen['expected']:.2f}.",
            "observed",
            50,
            proof=evidence("Paid a changed travel price", event_ids=[event_id] if event_id else None),
        )
        trace(
            state,
            "decision",
            f"Discovered a new {mode} price while travelling",
            event_id=event_id,
            agent=citizen,
            observations=[f"Paid {chosen['cost']:.2f} instead of the expected {chosen['expected']:.2f}"],
            selected=mode,
            motivation="Learned the price by paying it",
            memory_ids=[memory.id],
            changes=changes,
            significance=1,
        )
    agent.last_paid[mode] = chosen["cost"]
    agent.last_paid[f"{mode}_tick"] = state.simulation.tick
    agent.trips[mode] = agent.trips.get(mode, 0) + 1
    bump(systems, f"trips_{mode}")
    service = effective_service(state)
    speed = MODE_SPEED[mode] * ((0.6 + 0.4 * min(service, 2)) if mode == "transit" else 1)
    citizen.summary.movement_speed_mps = round(base * speed, 4)
    agent.trip_mode = mode
    citizen.summary.thought_bubble = f"{decision.intent.motivation} ({MODE_LABEL[mode]})"[:2000]
    satisfaction = (
        70 - chosen["cost"] * 12 * INCOME_SENSITIVITY[agent.income] - meters / (base * speed * 10) * 2
    )
    agent.satisfaction = round(0.85 * agent.satisfaction + 0.15 * clamp(satisfaction), 3)
    streak = agent.streak
    streak["count"] = streak["count"] + 1 if streak["mode"] == mode else 1
    streak["mode"] = mode
    if mode != agent.habit:
        significance = 2 if streak["count"] >= 3 else 1
        title = (
            f"Switched my regular travel from {agent.habit} to {mode}"
            if streak["count"] >= 3
            else f"Travelled {MODE_LABEL[mode]} instead of my usual {agent.habit}"
        )
        memory_ids = []
        if streak["count"] == 1 or streak["count"] >= 3:
            memory_ids.append(
                remember(
                    state,
                    citizen,
                    f"I chose to travel {MODE_LABEL[mode]} because {chosen['why']}.",
                    "observed",
                    45,
                    proof=evidence("Travel mode choice", event_ids=[event_id] if event_id else None),
                ).id
            )
            trace(
                state,
                "decision",
                title,
                event_id=event_id,
                agent=citizen,
                observations=[
                    f"Trip of {meters:.0f} m to {decision.intent.target_id or 'a destination'}",
                    f"Wallet {agent.wallet:.2f} credits, income {agent.income}",
                    f"Transit fare {state.systems.policy.transportation.transit_fare:.2f}, "
                    f"car trip {state.systems.policy.transportation.car_trip_cost:.2f}",
                ],
                candidates=[
                    dict(action=s["action"], label=s["label"], score=round(s["score"], 3)) for s in scores
                ],
                selected=mode,
                motivation=chosen["why"],
                memory_ids=memory_ids,
                changes=[
                    *changes,
                    change(
                        citizen.summary.id, "movement_speed_mps", base, citizen.summary.movement_speed_mps
                    ),
                ],
                significance=significance,
            )
        if streak["count"] >= 3:
            bump(systems, "habit_changes")
            agent.habit = mode


def on_work(state, citizen, agent, decision):
    systems = state.systems
    building = decision.intent.target_id
    policy = systems.policy
    revenue = 0.85
    tax = revenue * policy.taxation.business_tax_rate
    wage = 0.5 * {"low": 0.8, "middle": 1.0, "high": 1.3}[agent.income] + agent.incentives.get(
        "work_bonus", 0
    )
    subsidy = policy.business.subsidy_per_shift if systems.treasury > -30 else 0
    reserve = systems.businesses.get(building, 0) + revenue - tax + subsidy
    paid = min(wage, max(0.0, reserve))
    if paid < wage:
        bump(systems, "wage_cuts")
    systems.businesses[building] = round(reserve - paid, 4)
    household_tax = paid * policy.taxation.household_tax_rate
    systems.treasury += tax + household_tax - subsidy
    bump(systems, "business_tax", tax)
    before = agent.wallet
    agent.wallet = round(agent.wallet + paid - household_tax, 4)
    agent.shifts += 1
    decision.effects.append(
        EffectChange(entity_id=citizen.summary.id, field="wallet", before=before, after=agent.wallet)
    )


def acceptance(state, citizen, agent, channel, credibility, topic):
    traits = citizen.profile.traits
    institutions = agent.institutional_trust / 100
    base = credibility / 100
    if channel == "official":
        return base * (0.25 + 0.75 * institutions)
    if channel == "media":
        return base * (0.4 + 0.6 * traits.trust / 100)
    if channel == "rumor":
        return base * (0.45 + 0.55 * (1 - institutions)) * (0.7 + 0.3 * traits.curiosity / 100)
    return base * (0.5 + 0.5 * traits.trust / 100)


def receive_information(state, citizen, op, event_id, repetition=0):
    from app.behavior.vitals import conscious

    if not conscious(citizen):
        return
    agent = state.systems.agents[citizen.summary.id]
    p = acceptance(state, citizen, agent, op.channel, op.credibility, op.topic)
    believed = unit(citizen.summary.id, op.id, event_id, repetition, "believe") < p
    source = {
        "official": "an official announcement",
        "media": "the news",
        "rumor": "a rumor",
        "word_of_mouth": "neighbors",
    }[op.channel]
    candidates = [
        dict(action="believe", label=f"Believe {source}", score=p, why=f"I find {source} credible"),
        dict(action="doubt", label=f"Doubt {source}", score=1 - p, why=f"I do not trust {source}"),
    ]
    if believed:
        candidates[0]["score"] = max(candidates[0]["score"], candidates[1]["score"] + 1e-6)
    else:
        candidates[1]["score"] = max(candidates[1]["score"], candidates[0]["score"] + 1e-6)
    action, record = decide(
        state,
        citizen,
        f"Heard {source}: {op.message[:120]}",
        candidates,
        event_id=event_id,
        op_id=op.id,
        observations=[
            f"Channel {op.channel}, stated credibility {op.credibility:.0f}",
            f"My trust in institutions {agent.institutional_trust:.0f}, trust in people {citizen.profile.traits.trust:.0f}",
        ],
        memory=("I heard from " + source + f": {op.message[:300]} I decided to {{choice}}."),
        significance=1,
        source="observed" if op.channel == "official" and believed else "heard",
    )
    if action == "believe":
        hold_belief(
            state,
            citizen,
            agent,
            op.topic,
            op.message,
            p * 100,
            op.channel,
            op.id,
            op.accurate,
            event_id,
            record.memory_ids[:1],
        )
        bump(state.systems, "beliefs_adopted")
    else:
        bump(state.systems, "beliefs_doubted")
    return action == "believe"


def hold_belief(
    state, citizen, agent, topic, message, confidence, channel, op_id, accurate, event_id, memory_ids
):
    key = f"{op_id}"
    agent.beliefs[key] = Belief(
        topic=topic,
        message=message[:500],
        confidence=round(confidence, 3),
        channel=channel,
        source_op=op_id,
        accurate=accurate,
        tick=state.simulation.tick,
    )
    citizen.beliefs.append(
        CoreBelief(
            text=(f"Heard ({channel}): {message}")[:2000],
            confidence=clamp(confidence),
            evidence=evidence(
                "Information I chose to believe; not verified fact"
                if channel != "official"
                else "Official information I chose to believe",
                event_ids=[event_id] if event_id else None,
                memory_ids=memory_ids,
            ),
        )
    )


def share_in_conversation(state, speaker, listener, decision):
    """Believers may pass information on; listeners judge it by their trust in the speaker."""
    systems = state.systems
    a, b = systems.agents.get(speaker.summary.id), systems.agents.get(listener.summary.id)
    if not a or not b:
        return
    for key, belief in list(a.beliefs.items()):
        if listener.summary.id in belief.shared_with or key in b.beliefs or belief.confidence < 35:
            continue
        p_share = (
            speaker.profile.traits.sociability
            / 100
            * belief.confidence
            / 100
            * (1.2 if belief.channel == "rumor" else 1)
        )
        if unit(speaker.summary.id, listener.summary.id, key, "share") >= p_share:
            continue
        belief.shared_with.append(listener.summary.id)
        bump(systems, "information_shares")
        tie = listener.relationships.get(speaker.summary.id)
        interpersonal = (tie.trust if tie else 40) / 100
        p_accept = interpersonal * belief.confidence / 100
        if belief.channel == "official" and belief.topic != "government":
            # Relayed official news is still official news to the listener.
            p_accept *= 0.4 + 0.6 * b.institutional_trust / 100
        accepted = unit(listener.summary.id, speaker.summary.id, key, "accept") < p_accept
        event_id = current_event(state)
        candidates = [
            dict(
                action="believe",
                label=f"Believe {speaker.summary.name}",
                score=p_accept,
                why=f"I trust {speaker.summary.name.split()[0]} ({interpersonal * 100:.0f})",
            ),
            dict(action="doubt", label="Keep my doubts", score=1 - p_accept, why="I am not convinced"),
        ]
        winner = 0 if accepted else 1
        candidates[winner]["score"] = max(candidates[winner]["score"], candidates[1 - winner]["score"] + 1e-6)
        _, record = decide(
            state,
            listener,
            f"{speaker.summary.name} told me: {belief.message[:120]}",
            candidates,
            event_id=event_id,
            op_id=belief.source_op,
            observations=[
                f"Heard in conversation from {speaker.summary.name} ({speaker.summary.id})",
                f"My trust in {speaker.summary.name.split()[0]}: {interpersonal * 100:.0f}",
            ],
            memory=f"{speaker.summary.name} told me: {belief.message[:300]} I decided to {{choice}}.",
            affected=[speaker.summary.id],
            significance=1,
        )
        if accepted:
            bump(systems, "information_accepted")
            hold_belief(
                state,
                listener,
                b,
                belief.topic,
                belief.message,
                belief.confidence * 0.8,
                belief.channel,
                belief.source_op,
                belief.accurate,
                event_id,
                record.memory_ids[:1],
            )
            if belief.topic == "government":
                skeptic = 3 * (1 - listener.profile.traits.trust / 100)
                before = b.institutional_trust
                b.institutional_trust = round(clamp(before - skeptic), 3)
                record.changes.append(
                    change(listener.summary.id, "institutional_trust", before, b.institutional_trust)
                )
        else:
            bump(systems, "information_rejected")


def credibility_shift(state, citizen, op, event_id):
    """A credibility condition moves each person's institutional trust by their susceptibility."""
    agent = state.systems.agents[citizen.summary.id]
    traits = citizen.profile.traits
    susceptibility = 0.35 + 0.65 * (1 - traits.trust / 100)
    if op.delta < 0 and agent.institutional_trust > 70:
        susceptibility *= 0.7
    official = sum(1 for b in agent.beliefs.values() if b.channel == "official" and b.accurate)
    if op.delta < 0 and official:
        susceptibility *= 0.75
    susceptibility *= 0.8 + 0.4 * unit(citizen.summary.id, op.id, "susceptibility")
    before = agent.institutional_trust
    after = round(clamp(before + op.delta * susceptibility), 3)
    agent.institutional_trust = after
    observations = [f"Condition: {op.reason}", f"My trust in people {traits.trust:.0f}"]
    if official:
        observations.append("Official information I relied on before turned out reliable")
    memory = remember(
        state,
        citizen,
        f"{op.reason} My trust in official sources went from {before:.0f} to {after:.0f}.",
        "heard",
        60,
        proof=evidence("Institutional credibility condition", event_ids=[event_id] if event_id else None),
    )
    trace(
        state,
        "decision",
        "Reassessed how much I trust official sources",
        event_id=event_id,
        op_id=op.id,
        agent=citizen,
        observations=observations,
        candidates=[
            dict(action="update_trust", label=f"Adjust trust by {after - before:+.1f}", score=susceptibility)
        ],
        selected="update_trust",
        motivation=f"Susceptibility {susceptibility:.2f} given my own trust and experience",
        memory_ids=[memory.id],
        changes=[change(citizen.summary.id, "institutional_trust", before, after)],
        significance=2 if abs(after - before) >= 10 else 1,
    )
    if op.delta < 0:
        hold_belief(
            state,
            citizen,
            agent,
            "government",
            op.reason,
            clamp(60 + abs(after - before) * 2),
            "word_of_mouth",
            op.id,
            True,
            event_id,
            [memory.id],
        )


NORM_ALIGNMENT = {
    "help_strangers": lambda c, a: (c.profile.traits.empathy + c.profile.traits.cooperation) / 200,
    "use_public_transit": lambda c, a: (
        0.6 * (c.profile.traits.cooperation + 100 - c.profile.traits.risk_tolerance) / 200
        + 0.4 * a.institutional_trust / 100
    ),
    "conserve_resources": lambda c, a: (
        0.6 * c.profile.traits.cooperation / 100 + 0.4 * a.institutional_trust / 100
    ),
    "civic_participation": lambda c, a: (c.profile.traits.sociability + c.profile.traits.curiosity) / 200,
}


def peer_share(state, citizen, predicate):
    ties = [
        aid
        for aid, tie in citizen.relationships.items()
        if tie.kind != "stranger" and aid in state.systems.agents
    ]
    if not ties:
        return 0.0
    return sum(predicate(state.systems.agents[aid]) for aid in ties) / len(ties)


def evaluate_norm(state, citizen, norm, strength, event_id=None, op_id=None, exposure="campaign"):
    from app.behavior.vitals import conscious

    if not conscious(citizen):
        return
    agent = state.systems.agents[citizen.summary.id]
    alignment = NORM_ALIGNMENT[norm](citizen, agent)
    peers = peer_share(state, citizen, lambda other: other.norms.get(norm, 0) > 0)
    score = (
        strength * alignment
        + 0.35 * peers
        + (unit(citizen.summary.id, norm, state.simulation.tick // 24) - 0.5) * 0.2
    )
    adopted = agent.norms.get(norm, 0) > 0
    adopt = score > 0.3
    if adopt == adopted:
        return
    candidates = [
        dict(
            action="adopt",
            label=f"Adopt '{norm.replace('_', ' ')}'",
            score=score,
            why=f"it fits my values ({alignment:.2f}) and {peers * 100:.0f}% of people I know do it",
        ),
        dict(action="ignore", label="Carry on as before", score=0.3, why="it does not fit how I live"),
    ]
    action, record = decide(
        state,
        citizen,
        f"Considered the social norm '{norm.replace('_', ' ')}' ({exposure})",
        candidates,
        event_id=event_id,
        op_id=op_id,
        observations=[f"Norm strength {strength:.2f}", f"Share of my ties who follow it {peers * 100:.0f}%"],
        memory=f"People are encouraging '{norm.replace('_', ' ')}'. I decided to {{choice}}.",
        significance=2,
    )
    before = agent.norms.get(norm, 0)
    agent.norms[norm] = round(min(1.0, score + 0.2), 3) if action == "adopt" else 0
    record.changes.append(change(citizen.summary.id, f"norms.{norm}", before, agent.norms[norm]))
    bump(state.systems, "norm_adoptions" if action == "adopt" else "norm_abandonments")


def help_threshold(state, citizen):
    if not state.systems.enabled:
        return 65
    agent = state.systems.agents.get(citizen.summary.id)
    if not agent:
        return 65
    reward = state.systems.policy.community_programs.cooperation_reward + agent.incentives.get(
        "help_reward", 0
    )
    return 65 - 30 * agent.norms.get("help_strangers", 0) - min(10, reward * 8)


def inventory_floor(state, citizen):
    if not state.systems.enabled:
        return 2
    agent = state.systems.agents.get(citizen.summary.id)
    if not agent or not any(b.topic == "prices" and b.confidence >= 40 for b in agent.beliefs.values()):
        return 2
    return 2 if stockpile_choice(state, citizen, agent) == "conserve" else 4


def stockpile_choice(state, citizen, agent):
    key = "stockpile"
    if key in agent.evacuation_choice:
        return "stockpile" if agent.evacuation_choice[key] else "conserve"
    programs = state.systems.policy.community_programs
    worry = max((b.confidence for b in agent.beliefs.values() if b.topic == "prices"), default=0) / 100
    risk_aversion = 1 - citizen.profile.traits.risk_tolerance / 100
    campaign = programs.conservation_campaign * agent.institutional_trust / 100
    conserve_norm = agent.norms.get("conserve_resources", 0)
    candidates = [
        dict(
            action="stockpile",
            label="Buy and gather extra food",
            score=worry * (0.4 + 0.6 * risk_aversion),
            why="I expect prices to rise",
        ),
        dict(
            action="conserve",
            label="Take only what I need",
            score=0.3 + campaign * 0.6 + conserve_norm * 0.5 + citizen.profile.traits.cooperation / 400,
            why="stockpiling hurts neighbors",
        ),
    ]
    action, _ = decide(
        state,
        citizen,
        "Decided whether to stockpile food",
        candidates,
        event_id=current_event(state),
        observations=[
            f"Belief that prices will rise (confidence {worry * 100:.0f})",
            f"Conservation campaign {programs.conservation_campaign:.2f}",
        ],
        memory="I heard prices may rise. I decided to {choice}.",
        significance=2,
    )
    agent.evacuation_choice[key] = action == "stockpile"
    if programs.conservation_campaign:
        bump(state.systems, "compliance_yes" if action == "conserve" else "compliance_no")
    return action


def complies_with_evacuation(state, citizen):
    """An evacuation order without observed danger is followed only by those who trust it."""
    agent = state.systems.agents.get(citizen.summary.id)
    if not agent:
        return True
    key = f"order:{state.systems.counters.get('changed:resource_distribution.evacuation_order', 0)}"
    if key in agent.evacuation_choice:
        return agent.evacuation_choice[key]
    traits = citizen.profile.traits
    p = 0.15 + 0.75 * agent.institutional_trust / 100 + 0.15 * (1 - traits.risk_tolerance / 100)
    comply = unit(citizen.summary.id, key, "comply") < p
    candidates = [
        dict(action="comply", label="Follow the evacuation order", score=p, why="I trust the authorities"),
        dict(action="ignore", label="Stay put; I see no danger", score=1 - p, why="I do not trust the order"),
    ]
    winner = 0 if comply else 1
    candidates[winner]["score"] = max(candidates[winner]["score"], candidates[1 - winner]["score"] + 1e-6)
    decide(
        state,
        citizen,
        "Decided whether to follow the evacuation order",
        candidates,
        event_id=current_event(state),
        observations=[
            "Official evacuation order in force",
            "No hazard where I am",
            f"My trust in institutions {agent.institutional_trust:.0f}",
        ],
        memory="An evacuation order was issued. I decided to {choice}.",
        significance=2,
    )
    agent.evacuation_choice[key] = comply
    bump(state.systems, "compliance_yes" if comply else "compliance_no")
    return comply


def preferred_destination(state, citizen):
    """Scenario-driven destinations that outrank the ordinary routine."""
    if not state.systems.enabled:
        return None
    agent = state.systems.agents.get(citizen.summary.id)
    if not agent:
        return None
    buildings = state.map.buildings
    if citizen.needs.health < 88:
        hospitals = [
            b for b in buildings if b.kind == "hospital" and b.functional and b.occupancy < b.capacity
        ]
        if hospitals and citizen.inside_building_id not in {b.id for b in hospitals}:
            hospital = min(hospitals, key=lambda b: (distance(citizen.summary.position, b.entrance), b.id))
            return hospital, "Go to the hospital for care"
    for org_id in agent.organizations:
        org = state.systems.organizations.get(org_id)
        if org and org.active and org.kind in {"tenant_union", "protest_group"} and rallying(state, org):
            centers = [
                b for b in buildings if b.kind == "community" and b.functional and b.occupancy < b.capacity
            ]
            if centers and citizen.inside_building_id not in {b.id for b in centers}:
                center = min(centers, key=lambda b: (distance(citizen.summary.position, b.entrance), b.id))
                return center, f"Join the {org.name} gathering"
    if agent.conditions:
        indoors = citizen.inside_building_id is not None
        home = next((b for b in buildings if b.id == agent.home_id and b.functional), None)
        if not indoors and home and citizen.profile.traits.risk_tolerance < 55:
            return home, "Stay indoors until conditions improve"
    if agent.regular_shop:
        shop = next((b for b in buildings if b.id == agent.regular_shop), None)
        if shop is not None and not shop.functional:
            agent.regular_shop = None
    return None


def staying_for_care(state, citizen):
    if not state.systems.enabled or citizen.needs.health >= 95:
        return False
    return any(
        b.id == citizen.inside_building_id and b.kind == "hospital" and b.functional
        for b in state.map.buildings
    )


def rallying(state, org):
    return (state.simulation.tick - org.created_tick) % legacy_ticks(state, org.rally_every) < legacy_ticks(
        state, 6
    )


def seek_alternative(state, citizen, building, event_id, op_id):
    agent = state.systems.agents[citizen.summary.id]
    others = sorted(
        (b for b in state.map.buildings if b.kind == building.kind and b.functional and b.id != building.id),
        key=lambda b: (distance(citizen.summary.position, b.entrance), b.id),
    )[:3]
    candidates = [
        dict(
            action=b.id,
            label=f"Use {b.name} instead",
            score=-distance(citizen.summary.position, b.entrance) / 40,
            why=f"it is the nearest open {building.kind}",
        )
        for b in others
    ]
    if building.kind == "shop":
        depots = sorted(
            (r for r in state.map.resources if r.kind == "food" and r.available_units > 0),
            key=lambda r: distance(citizen.summary.position, r.position),
        )[:1]
        candidates += [
            dict(
                action=r.id,
                label="Gather food from the depot instead",
                score=-distance(citizen.summary.position, r.position) / 40 - 0.5,
                why="the depot still has food",
            )
            for r in depots
        ]
    candidates.append(
        dict(action="go_without", label="Go without for now", score=-3, why="nothing else is reachable")
    )
    action, record = decide(
        state,
        citizen,
        f"{building.name} closed; looked for an alternative",
        candidates,
        event_id=event_id,
        op_id=op_id,
        observations=[
            f"{building.name} ({building.id}) is closed",
            f"I used it {agent.shop_visits.get(building.id, 0)} times",
        ],
        memory=f"{building.name} has closed. I decided to {{choice}}.",
        affected=[building.id],
        significance=2,
    )
    if building.kind == "shop":
        agent.regular_shop = action if action.startswith("building") else None
    bump(state.systems, "alternatives_sought")
    return action


def review(state, citizen):
    """Periodic personal review: housing pressure, organizations and norms."""
    systems = state.systems
    agent = systems.agents[citizen.summary.id]
    if state.simulation.tick < agent.next_review_tick:
        return
    agent.next_review_tick = state.simulation.tick + legacy_ticks(state, 12)
    review_housing(state, citizen, agent)
    for org in list(systems.organizations.values()):
        if org.active and citizen.summary.id not in org.members and eligible(state, citizen, agent, org):
            consider_joining(state, citizen, agent, org)
    for norm, strength in systems.norms.items():
        if strength > 0 or agent.norms.get(norm):
            evaluate_norm(state, citizen, norm, strength, current_event(state), exposure="peers")


def eligible(state, citizen, agent, org):
    if org.region != "citywide" and not in_region(citizen.summary.position, org.region):
        return False
    return {
        "all": True,
        "low_income": agent.income == "low" or agent.wallet < STRAIN_WALLET * 2,
        "renters": agent.renter,
        "region": True,
    }[org.eligibility]


def join_score(state, citizen, agent, org):
    traits = citizen.profile.traits
    civic = agent.norms.get("civic_participation", 0)
    strained = agent.wallet < STRAIN_WALLET * 2 or rent_multiplier(state) > 1.25
    peers = peer_share(state, citizen, lambda other: org.id in other.organizations)
    grievance = any(b.topic in {"government", "housing", "prices"} for b in agent.beliefs.values())
    base = {
        "mutual_aid": (traits.cooperation + traits.empathy) / 200
        + 0.3 * (citizen.summary.metrics.resources < 40),
        "tenant_union": 0.45 * (agent.renter and strained) + traits.sociability / 200,
        "protest_group": 0.45 * (1 - agent.institutional_trust / 100)
        + traits.risk_tolerance / 250
        + 0.25 * (strained or grievance),
        "community_program": 0.5 * (agent.income == "low") + agent.institutional_trust / 250,
        "assistance_office": 0.5 * strained + agent.institutional_trust / 250,
    }[org.kind]
    return (
        base
        + 0.3 * civic
        + 0.3 * peers
        + (unit(citizen.summary.id, org.id, state.simulation.tick // 24) - 0.5) * 0.2
    )


def consider_joining(state, citizen, agent, org, founding=False):
    from app.behavior.vitals import conscious

    if not conscious(citizen):
        return False
    score = join_score(state, citizen, agent, org) + (0.15 if founding else 0)
    if score <= 0.55 and not founding:
        return False
    candidates = [
        dict(
            action="join",
            label=f"Join {org.name}",
            score=score,
            why=org.mission or f"I support the {org.kind.replace('_', ' ')}",
        ),
        dict(action="stay_out", label="Stay out of it", score=0.55, why="it is not for me"),
    ]
    action, record = decide(
        state,
        citizen,
        f"Considered joining {org.name}",
        candidates,
        event_id=org.event_id,
        observations=[
            f"{org.name}: {org.mission[:120]}",
            f"{len(org.members)} members so far",
            f"Wallet {agent.wallet:.1f}, trust in institutions {agent.institutional_trust:.0f}",
        ],
        memory=f"{org.name} is organizing. I decided to {{choice}}.",
        affected=[org.id],
        significance=2,
    )
    if action == "join":
        org.members.append(citizen.summary.id)
        agent.organizations.append(org.id)
        record.changes.append(change(citizen.summary.id, "organizations", None, org.id))
        bump(state.systems, "organization_joins")
        if org.kind == "assistance_office" and agent.housing_status == "housed":
            agent.housing_status = "seeking_assistance"
            bump(state.systems, "assistance_requests")
    return action == "join"


def review_housing(state, citizen, agent):
    if not agent.renter or agent.housing_status in {"relocated", "sharing"}:
        return
    rent = rent_multiplier(state)
    strained = agent.wallet < STRAIN_WALLET * 2
    if not (strained and rent > 1.05) and not (rent > 1.6 and agent.income == "low"):
        return
    systems = state.systems
    traits = citizen.profile.traits
    cheaper = sorted(
        (
            b
            for b in state.map.buildings
            if b.kind == "home"
            and b.functional
            and systems.housing_available.get(b.id)
            and systems.home_rent.get(b.id, 1) < agent.rent_factor - 0.1
            and b.id != agent.home_id
        ),
        key=lambda b: (systems.home_rent.get(b.id, 1), b.id),
    )
    family = [
        state.citizens[aid]
        for aid, tie in citizen.relationships.items()
        if tie.kind == "family"
        and aid in state.citizens
        and aid in systems.agents
        and systems.agents[aid].home_id != agent.home_id
    ]
    assistance = systems.policy.housing.assistance_per_tick > 0 or any(
        o.active and o.kind == "assistance_office" for o in systems.organizations.values()
    )
    attachment = sum(1 for aid, t in citizen.relationships.items() if t.affection > 55) / 6
    candidates = [
        dict(
            action="stay",
            label="Stay and cut back",
            score=0.35 + 0.3 * min(1, attachment),
            why="my life and people are here",
        ),
    ]
    if cheaper:
        candidates.append(
            dict(
                action="relocate",
                label=f"Move to cheaper {cheaper[0].name}",
                score=0.3 + 0.4 * traits.risk_tolerance / 100 + 0.3 * strained - 0.2 * min(1, attachment),
                why="rent here is more than I can afford",
            )
        )
    if assistance and agent.housing_status == "housed":
        candidates.append(
            dict(
                action="assistance",
                label="Apply for housing assistance",
                score=0.25 + 0.5 * agent.institutional_trust / 100 + 0.2 * strained,
                why="I trust the city to help",
            )
        )
    if family:
        relative = max(family, key=lambda r: (citizen.relationships[r.summary.id].affection, r.summary.id))
        candidates.append(
            dict(
                action="share",
                label=f"Move in with {relative.summary.name}",
                score=0.2 + 0.5 * citizen.relationships[relative.summary.id].affection / 100,
                why="family can share the rent",
            )
        )
    for c in candidates:
        c["score"] += (unit(citizen.summary.id, c["action"], state.simulation.tick // 12) - 0.5) * 0.15
    action, record = decide(
        state,
        citizen,
        "Decided how to cope with rent",
        candidates,
        event_id=current_event(state),
        observations=[
            f"Rent multiplier {rent:.2f}, homes available {housing_share(state) * 100:.0f}%",
            f"Wallet {agent.wallet:.1f} credits, income {agent.income}",
        ],
        memory="Rent has become hard to manage. I decided to {choice}.",
        significance=2 if action_significant(candidates) else 1,
    )
    if action == "relocate":
        home = cheaper[0]
        before = agent.home_id
        systems.housing_available[home.id] = False
        if before:
            systems.housing_available[before] = True
        agent.home_id, agent.rent_factor = home.id, systems.home_rent.get(home.id, 1)
        citizen.home = home.entrance.model_copy()
        agent.housing_status = "relocated"
        record.changes.append(change(citizen.summary.id, "home", before, home.id))
        bump(systems, "relocations")
    elif action == "assistance":
        agent.housing_status = "seeking_assistance"
        bump(systems, "assistance_requests")
    elif action == "share":
        relative = max(family, key=lambda r: (citizen.relationships[r.summary.id].affection, r.summary.id))
        before = agent.home_id
        target = systems.agents[relative.summary.id]
        agent.home_id, agent.rent_factor = target.home_id, target.rent_factor
        citizen.home = relative.home.model_copy()
        agent.housing_status = "sharing"
        record.changes.append(change(citizen.summary.id, "home", before, target.home_id))
        bump(systems, "relocations")
    else:
        metric_delta(citizen, "stress", 0.5, evidence("Staying despite unaffordable rent"))


def action_significant(candidates):
    return len(candidates) > 1
