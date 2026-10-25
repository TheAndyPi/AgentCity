"""Disaster merge boundaries with canonical survival, care and physical ticks."""

import pytest
from test_disasters import parameters, runtime, world

from app.behavior.care import fund_hospitals, treatment
from app.disasters.models import TerrainDamage
from app.disasters.physics import advance, effective_services, initialize, reaction, reconcile_occupants, view
from app.simulation.engine import tick
from app.simulation.game_master import advance_movement, apply_intent, make_intent
from app.simulation.navigation import cell_at


def test_fatal_disaster_injury_precedes_hospital_healing_and_has_one_cause(client):
    state = world(client)
    citizen = next(iter(state.citizens.values()))
    state.citizens = {citizen.summary.id: citizen}
    fund_hospitals(state)
    building = next(b for b in state.map.buildings if b.kind == "hospital")
    hospital = state.behavior.hospitals[building.id]
    citizen.inside_building_id = building.id
    citizen.summary.position = building.entrance.model_copy()
    citizen.condition.care = "hospital"
    citizen.condition.hospital_id = building.id
    hospital.patients = [citizen.summary.id]
    citizen.needs.health = 1
    params = parameters().model_copy(update=dict(intensity=100.0, extent_m=100.0, origin=building.entrance))
    runtime(state, params)
    stock = hospital.inventory.model_dump()
    advance(state)
    treatment(state)
    advance(state)
    assert citizen.needs.health == 0 and citizen.condition.life == "dead"
    assert not citizen.summary.active and not hospital.patients
    assert hospital.inventory.model_dump() == stock
    assert len([e for e in state.behavior.events if e.kind == "death"]) == 1
    injuries = [r for r in state.damage_records if r.entity_id == citizen.summary.id]
    assert len(injuries) == 1 and injuries[0].before == 1 and injuries[0].after == 0
    impacts = [i for i in citizen.condition.impacts if i.phase == "disaster"]
    assert len(impacts) == 1 and impacts[0].delta == -1


def test_unconscious_with_positive_raw_energy_does_not_react_or_egress(client):
    state = world(client)
    citizen = next(iter(state.citizens.values()))
    citizen.condition.life = "unconscious"
    citizen.needs.fatigue = 99
    r = runtime(state, parameters())
    reaction(state, r, citizen, 1, acute=True)
    assert not state.reactions
    assert not view(state)["vocal_states"][citizen.summary.id]["conscious"]
    building = state.map.buildings[0]
    initialize(state)
    state.conditions[building.id].integrity = 0
    citizen.inside_building_id = building.id
    citizen.summary.path = []
    reconcile_occupants(state)
    assert citizen.trapped_building_id == building.id and not citizen.summary.path
    before = citizen.summary.position.model_copy()
    advance_movement(state, citizen)
    assert citizen.summary.position == before


def test_trapped_actor_cannot_use_an_override_to_resume_ordinary_activity(client):
    state = world(client)
    citizen = next(iter(state.citizens.values()))
    citizen.trapped_building_id = state.map.buildings[0].id
    before = citizen.needs.model_dump()
    decision = apply_intent(state, citizen, make_intent("rest"))
    assert decision.outcome == "rejected" and decision.rejection_code == "INCAPACITATED"
    assert citizen.needs.model_dump() == before
    from app.behavior.care import eligible
    from app.behavior.game_master import act

    other = next(c for c in state.citizens.values() if c is not citizen)
    decision = act(state, citizen, "comfort", other.summary.id)
    assert not decision.accepted
    assert not eligible(state, citizen)


def test_disaster_closure_releases_inbound_care_claim_at_actual_location(client):
    state = world(client)
    patient, helper = list(state.citizens.values())[:2]
    fund_hospitals(state)
    initialize(state)
    building = next(b for b in state.map.buildings if b.kind == "hospital")
    hospital = state.behavior.hospitals[building.id]
    patient.condition.care = "claimed"
    patient.condition.helper_id = helper.summary.id
    patient.condition.hospital_id = building.id
    helper.condition.patient_id = patient.summary.id
    hospital.reservations[patient.summary.id] = helper.summary.id
    before = patient.summary.position.model_copy()
    state.conditions[building.id].integrity = 0
    effective_services(state)
    assert not building.functional and building.capacity == 0
    assert not hospital.reservations and helper.condition.patient_id is None
    assert patient.condition.care == "none" and patient.condition.helper_id is None
    assert patient.summary.position == before


@pytest.mark.parametrize("care", ["hospital", "carried", "escorted"])
def test_unsafe_occupied_hospital_detaches_beds_and_transport_without_teleport(client, care):
    state = world(client)
    patient, helper = list(state.citizens.values())[:2]
    fund_hospitals(state)
    building = next(b for b in state.map.buildings if b.kind == "hospital")
    initialize(state)
    state.conditions[building.id].integrity = 0
    hospital = state.behavior.hospitals[building.id]
    patient.inside_building_id = helper.inside_building_id = building.id
    patient.summary.position = helper.summary.position = building.entrance.model_copy()
    patient.condition.life = "unconscious"
    patient.needs.fatigue = 100
    patient.condition.care = care
    patient.condition.hospital_id = building.id
    if care == "hospital":
        hospital.patients = [patient.summary.id]
    else:
        patient.condition.helper_id = helper.summary.id
        helper.condition.patient_id = patient.summary.id
        hospital.reservations[patient.summary.id] = helper.summary.id
    cell = cell_at(state.map, building.entrance)
    state.terrain_damage[f"{cell.col}:{cell.row}"] = TerrainDamage(
        col=cell.col, row=cell.row, stage="rubble", blocked=True, cause_ids=[f"building:{building.id}"]
    )
    before = patient.summary.position.model_copy(), hospital.inventory.model_dump()
    reconcile_occupants(state)
    reconcile_occupants(state)
    assert patient.condition.care == "none" and patient.condition.helper_id is None
    assert helper.condition.patient_id is None
    assert not hospital.patients and not hospital.reservations
    assert patient.trapped_building_id == building.id and not patient.summary.path
    assert (patient.summary.position, hospital.inventory.model_dump()) == before


def test_typed_hazard_injury_is_applied_once_by_the_merged_physical_tick(client):
    state = world(client)
    for citizen in state.citizens.values():
        citizen.condition.life = "unconscious"
        citizen.needs.fatigue = 100
        citizen.needs.health = 100
        citizen.inside_building_id = None
    params = parameters("flood").model_copy(update=dict(intensity=5.0, extent_m=181.0))
    event = runtime(state, params)
    tick(state)
    for citizen in state.citizens.values():
        assert citizen.needs.health == pytest.approx(98)
        assert len([i for i in citizen.condition.impacts if i.phase == "disaster"]) == 1
    before = len(state.damage_records)
    advance(state)
    assert len(state.damage_records) == before
    assert event.last_physical_tick == state.simulation.tick
