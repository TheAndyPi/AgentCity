"""Local, claimed physical rescue and conserved hospital treatment."""

from app.behavior.models import Hospital
from app.behavior.rules import RULES
from app.behavior.vitals import conscious, detach, emit, evaluate, impact, living, rest
from app.contracts import Inventory
from app.simulation.agents import evidence, hazard_severity, metric_delta
from app.simulation.building_visits import same_room, trip_route
from app.simulation.navigation import distance


def eligible(state, helper):
    return (
        conscious(helper)
        and not helper.trapped_building_id
        and helper.needs.health > RULES["helper_health"]
        and 100 - helper.needs.fatigue > RULES["helper_energy"]
        and 100 - helper.needs.hunger > RULES["helper_fullness"]
        and helper.condition.mental > RULES["helper_mental"]
        and helper.profile.mobility >= RULES["helper_mobility"]
        and hazard_severity(state, helper.summary.position) == 0
        and not state.policies.evacuation_order
    )


def fund_hospitals(state):
    for b in state.map.buildings:
        if b.kind != "hospital" or b.id in state.behavior.hospitals:
            continue
        stock = Inventory(food=0, water=0, supplies=0)
        for kind in ("food", "water", "supplies"):
            remaining = RULES["hospital_stock"]
            for source in state.map.resources:
                if source.kind != kind:
                    continue
                units = min(source.available_units, remaining)
                source.available_units -= units
                setattr(stock, kind, getattr(stock, kind) + units)
                remaining -= units
                if units:
                    state.external_resource_changes.append(
                        dict(
                            event_id=None,
                            tick=state.simulation.tick,
                            resource_id=source.id,
                            hospital_id=b.id,
                            resource=kind,
                            units=units,
                            reason="Conserved depot-to-hospital funding",
                        )
                    )
        state.behavior.hospitals[b.id] = Hospital(inventory=stock)


def available_hospital(state, helper):
    from app.simulation.scenarios import blocked_cells

    candidates = [
        b
        for b in state.map.buildings
        if b.kind == "hospital"
        and b.functional
        and b.id in helper.known_locations
        and b.id in state.behavior.hospitals
        and hazard_severity(state, b.entrance) == 0
    ]
    for b in sorted(candidates, key=lambda b: distance(helper.summary.position, b.entrance)):
        h = state.behavior.hospitals[b.id]
        occupants = {
            c.summary.id
            for c in state.citizens.values()
            if living(c) and c.inside_building_id == b.id and c is not helper
        }
        reserved = set(h.reservations)
        if len(occupants | set(h.patients) | reserved) >= b.capacity:
            continue
        route = trip_route(state, helper, b.entrance, b, blocked_cells(state))
        if route is not None:
            return b, route
    return None


def rescue_choice(state, helper, context):
    from app.behavior.classes import affinity
    from app.behavior.game_master import act
    from app.simulation.game_master import make_intent
    from app.simulation.navigation import meeting_point

    if not eligible(state, helper):
        return None, False
    if helper.condition.patient_id:
        patient = state.citizens.get(helper.condition.patient_id)
        if patient is None or not living(patient):
            detach(state, helper)
            return None, False
        if helper.summary.path:
            return None, True
        if patient.condition.care == "claimed":
            synchronize_transport(state, helper)
            return None, True
        hospital = next((b for b in state.map.buildings if b.id == patient.condition.hospital_id), None)
        if hospital and hospital.functional and helper.inside_building_id == hospital.id:
            act(state, helper, "admit", patient.summary.id, context)
            return None, True
        detach(state, helper)
        return make_intent(
            "rest", motivation="Rescue route interrupted; patient is safe at my actual position"
        ), True
    if max(helper.profile.traits.empathy, helper.profile.traits.cooperation) < RULES["helper_empathy"]:
        return None, False
    if helper.profile.traits.cooperation >= RULES["helper_cooperation"] and helper.inventory.supplies >= 1:
        for group in state.interactions.values():
            target_id = group.proposal.get("target_id")
            if (
                group.kind != "aid_group"
                or group.status not in {"invited", "accepted"}
                or group.expires_tick < state.simulation.tick
                or helper.summary.id not in group.participant_ids
                or helper.summary.id in group.accepted_ids
                or target_id not in context["nearby_ids"]
            ):
                continue
            patient = state.citizens[target_id]
            if (
                patient.condition.care in {"claimed", "carried", "escorted"}
                and patient.needs.health < RULES["release_health"]
                and same_room(helper, patient)
                and distance(helper.summary.position, patient.summary.position) <= RULES["range"]
            ):
                return make_intent(
                    "help",
                    target=target_id,
                    motivation="Accept a public rescue-team invitation: provide first aid while the carrier handles transport",
                ), True
    victims = [
        state.citizens[aid]
        for aid in context["nearby_ids"]
        if living(state.citizens[aid])
        and (
            not conscious(state.citizens[aid]) or state.citizens[aid].needs.health <= RULES["injured_health"]
        )
        and state.citizens[aid].condition.care == "none"
        and affinity(helper, state.citizens[aid]) >= -1
    ]
    if not victims:
        return None, False
    victim = min(
        victims, key=lambda c: (c.needs.health, distance(helper.summary.position, c.summary.position))
    )
    if distance(helper.summary.position, victim.summary.position) <= RULES["range"] and same_room(
        helper, victim
    ):
        result = act(state, helper, "rescue", victim.summary.id, context)
        if not result.accepted and helper.inventory.supplies >= 1:
            return make_intent(
                "help", target=victim.summary.id, motivation="Hospital unavailable; offer local first aid"
            ), True
        return None, result.accepted
    if helper.summary.path:
        return None, True
    return make_intent(
        "move",
        target=victim.summary.id,
        destination=meeting_point(state.map, helper.summary.position, victim.summary.position),
        motivation="Approach a publicly observed injured or unconscious neighbor",
    ), True


def synchronize_transport(state, helper):
    patient = state.citizens.get(helper.condition.patient_id)
    if not patient:
        return
    if not eligible(state, helper) or not living(patient):
        detach(state, helper)
        return
    hospital = next((b for b in state.map.buildings if b.id == patient.condition.hospital_id), None)
    if not hospital or not hospital.functional or hazard_severity(state, hospital.entrance):
        detach(state, helper)
        emit(
            state,
            "rescue_cancelled",
            helper,
            patient,
            "Hospital closed/unsafe; released claim at actual location",
        )
        return
    if patient.condition.care == "claimed":
        if helper.summary.path or distance(helper.summary.position, patient.summary.position) > 0.1:
            return
        from app.simulation.scenarios import blocked_cells

        route = trip_route(state, helper, hospital.entrance, hospital, blocked_cells(state))
        if route is None:
            detach(state, helper)
            return
        patient.condition.care = "carried" if not conscious(patient) else "escorted"
        helper.summary.path = route
        helper.entering_building_id = hospital.id
        helper.leaving_building_id = helper.inside_building_id
    # Carried patients share the exact legal carrier path. Escorted patients move
    # with a speed-limited helper and have explicitly consented before transport.
    patient.summary.position = helper.summary.position.model_copy()
    patient.inside_building_id = helper.inside_building_id


def treatment(state):
    for bid, hospital in state.behavior.hospitals.items():
        building = next(b for b in state.map.buildings if b.id == bid)
        for aid in list(hospital.patients):
            patient = state.citizens[aid]
            evaluate(state, patient, "Before hospital care")
            if not living(patient):
                continue
            if not building.functional or hazard_severity(state, patient.summary.position):
                detach(state, patient)
                emit(
                    state, "care_cancelled", patient, description="Hospital closed or hazardous; released bed"
                )
                continue
            dt = state.simulation.config.tick_seconds / 10
            unit = RULES["treatment_units"] * dt
            # Bed rest requires a functioning bed; nutrition and treatment require stock.
            rest(state, patient, RULES["bed_energy"] * dt, "care")
            if hospital.inventory.supplies >= unit:
                hospital.inventory.supplies -= unit
                state.counters["resources_consumed"] += unit
                impact(state, patient, "health", RULES["treatment_health"] * dt, "Hospital supplies", "care")
                if state.systems.enabled:
                    from app.scenario_engine.systems import bump

                    bump(state.systems, "hospital_care")
                impact(state, patient, "mental", RULES["treatment_mental"] * dt, "Hospital treatment", "care")
                metric_delta(
                    patient, "stress", RULES["treatment_stress"] * dt, evidence("Hospital treatment")
                )
            for kind in ("food", "water"):
                if hospital.inventory.__getattribute__(kind) >= unit and patient.needs.hunger >= 20:
                    setattr(hospital.inventory, kind, getattr(hospital.inventory, kind) - unit)
                    state.counters["resources_consumed"] += unit
                    impact(state, patient, "fullness", 12 * unit, f"Hospital {kind} consumed", "care")
            evaluate(state, patient, "Hospital recovery")
            if (
                conscious(patient)
                and patient.needs.health >= RULES["release_health"]
                and 100 - patient.needs.fatigue >= RULES["wake_energy"]
            ):
                detach(state, patient)
                emit(
                    state,
                    "hospital_release",
                    patient,
                    description="Recovered consciousness and sufficient health; bed released",
                )
