"""DS acceptance: real routes, committed engine, durability and compatibility."""

import math
from uuid import uuid4

import pytest
from conftest import command, create_city, write
from pydantic import ValidationError

from app.contracts import Vec2, WorldFrame
from app.disasters.geometry import envelope, exposure, footprint_exposure, intersects
from app.disasters.models import Parameters
from app.disasters.physics import advance, effective_services, initialize, reaction, structural_loss
from app.disasters.router import PreviewRequest, make_preview, parse_prompt
from app.simulation.navigation import polygon_contains, simple_polygon
from app.simulation.scenarios import activate, blocked_cells, queue_event


def parameters(kind="fire", **changes):
    intensity = {"fire": 80.0, "flood": 3.0, "storm": 60.0, "earthquake": 7.5, "tornado": 100.0}[kind]
    return Parameters(
        kind=kind,
        intensity=intensity,
        extent_m=24.0,
        origin=Vec2(x=64, y=64),
        track_end=Vec2(x=96, y=64) if kind == "tornado" else None,
        duration_ticks=4,
        seed=42,
        **changes,
    )


def world(client):
    sim = create_city(client)
    return client.app.state.service.owned("demo_owner", sim["id"]).model_copy(deep=True)


def runtime(state, params):
    from app.contracts import ScenarioPreview

    p = make_preview(state, PreviewRequest(intervention_id="test", parameters=params))
    event = queue_event(state, ScenarioPreview.model_validate(p["preview"]), "snapshot", False)
    state.events[event.id].physical = params
    activate(state)
    return state.events[event.id]


@pytest.mark.parametrize("kind", ["earthquake", "tornado", "flood", "fire", "storm"])
def test_ds03_clipped_geometry_and_independence(client, kind):
    state = world(client)
    p = parameters(kind)
    for origin in (Vec2(x=0, y=0), Vec2(x=128, y=128), Vec2(x=0, y=128)):
        q = p.model_copy(
            update=dict(origin=origin, track_end=Vec2(x=64, y=64) if kind == "tornado" else None)
        )
        poly = envelope(q, state.map)
        assert simple_polygon(poly)
        assert all(0 <= v.x <= 128 and 0 <= v.y <= 128 for v in poly)
    a = envelope(p, state.map)
    stronger = p.model_copy(
        update=dict(
            intensity={"earthquake": 9.0, "tornado": 130.0, "flood": 5.0, "fire": 100.0, "storm": 75.0}[kind]
        )
    )
    assert envelope(stronger, state.map) == a
    big = p.model_copy(update=dict(extent_m=48.0))
    small = make_preview(state, PreviewRequest(intervention_id="x", parameters=p))
    large = make_preview(state, PreviewRequest(intervention_id="x", parameters=big))
    assert len(large["preview"]["affected_building_ids"]) >= len(small["preview"]["affected_building_ids"])
    if kind != "tornado":
        point = Vec2(x=65, y=64)
        assert exposure(p, point, 0, a) == exposure(big, point, 0, envelope(big, state.map))
    assert exposure(stronger, p.origin, 0, a) >= exposure(p, p.origin, 0, a)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_ds03_invalid_size(value):
    with pytest.raises(ValidationError):
        parameters().model_copy(update={}).__class__.model_validate(
            {**parameters().model_dump(), "extent_m": value}
        )


def test_ds05_moving_tornado_and_attenuation(client):
    state = world(client)
    p = parameters("tornado")
    poly = envelope(p, state.map)
    assert exposure(p, p.origin, 0, poly) > 0
    assert exposure(p, p.track_end, 0, poly) == 0
    assert exposure(p, p.track_end, 3, poly) > 0
    quake = parameters("earthquake")
    poly = envelope(quake, state.map)
    assert exposure(quake, quake.origin, 0, poly) > exposure(quake, Vec2(x=80, y=64), 0, poly) > 0
    for kind in ("fire", "flood", "storm", "tornado"):
        zero = parameters(kind).model_copy(update=dict(intensity=0.0))
        assert exposure(zero, zero.origin, 0, envelope(zero, state.map)) == 0


def test_ds06_footprint_intersection_outside_entrance(client):
    state = world(client)
    b = state.map.buildings[0]
    center = Vec2(x=sum(v.x for v in b.footprint) / 4, y=sum(v.y for v in b.footprint) / 4)
    p = parameters().model_copy(update=dict(origin=center, extent_m=2.0))
    poly = envelope(p, state.map)
    assert not polygon_contains(b.entrance, poly)
    assert intersects(b.footprint, poly)
    assert footprint_exposure(p, b.footprint, 0, poly) > 0
    result = make_preview(state, PreviewRequest(intervention_id="x", parameters=p))
    assert b.id in result["preview"]["affected_building_ids"]


def test_ds07_exact_loss_once_resolution_and_compounding(client):
    state = world(client)
    r = runtime(state, parameters())
    b = state.map.buildings[0]
    initialize(state)
    state.conditions[b.id].integrity = 80
    assert structural_loss(state, r, b, 5.0, 1.0)
    assert state.conditions[b.id].integrity == 75
    assert state.damage_records[-1].before == 80 and state.damage_records[-1].after == 75
    effective_services(state)
    assert b.capacity == math.floor(state.conditions[b.id].design_capacity * 0.75)
    before = len(state.damage_records)
    r.last_physical_tick = state.simulation.tick
    advance(state)
    assert len(state.damage_records) == before
    r.summary.status = "resolved"
    effective_services(state)
    assert state.conditions[b.id].integrity == 75
    assert structural_loss(state, r, b, 5.0, 1.0)
    assert state.conditions[b.id].integrity == 70


def test_ds08_service_threshold_and_overlapping_closures(client):
    state = world(client)
    b = state.map.buildings[0]
    initialize(state)
    c = state.conditions[b.id]
    for integrity, stage, opened in [
        (100, "intact", True),
        (50, "damaged", True),
        (49.99, "unsafe", False),
        (0, "destroyed", False),
    ]:
        c.integrity = integrity
        effective_services(state)
        assert c.stage == stage and b.functional == opened
        assert b.capacity == (math.floor(c.design_capacity * integrity / 100) if opened else 0)
    from app.simulation.scenarios import compile_preview

    p = compile_preview(state, "custom", "A power outage citywide for 4 ticks")
    c.integrity = 75
    first = queue_event(state, p, "snapshot", False)
    second = queue_event(state, p, "snapshot", False)
    activate(state)
    effective_services(state)
    assert not b.functional
    state.events[first.id].summary.status = "resolved"
    effective_services(state)
    assert not b.functional
    state.events[second.id].summary.status = "resolved"
    effective_services(state)
    assert b.functional and c.integrity == 75


def open_editor(client, sid):
    sim = client.get(f"/api/v1/simulations/{sid}").json()["data"]
    return write(
        client, f"/simulations/{sid}/interventions", dict(expected_control_version=sim["control_version"])
    ).json()["data"]


def test_ds02_routes_preview_commit_stale_durability_and_branch(client):
    sim = create_city(client)
    sid = sim["id"]
    hold = open_editor(client, sid)
    base = f"/integrations/disasters/v2/simulations/{sid}"
    core = client.app.state.service
    before = core.owned("demo_owner", sid).model_dump()
    body = dict(intervention_id=hold["id"], parameters=parameters("earthquake").model_dump())
    a = write(client, base + "/previews", body)
    assert a.status_code == 201, a.text
    assert core.owned("demo_owner", sid).model_dump() == before
    b = write(client, base + "/previews", body).json()["data"]
    stale = write(
        client,
        base + "/commits",
        dict(
            intervention_id=hold["id"],
            preview_id=a.json()["data"]["preview"]["id"],
            expected_control_version=hold["control_version"],
        ),
    )
    assert stale.status_code == 409
    key = str(uuid4())
    commit = dict(
        intervention_id=hold["id"],
        preview_id=b["preview"]["id"],
        expected_control_version=hold["control_version"],
    )
    committed = write(client, base + "/commits", commit, key=key)
    assert committed.status_code == 201, committed.text
    assert write(client, base + "/commits", commit, key=key).json() == committed.json()
    queued_rev = committed.json()["data"]["simulation"]["revision"]
    assert command(client, sid, "step", count=1).status_code == 200
    current = client.get("/api/v1" + base + "/state").json()["data"]
    assert current["damage"] and any(c["integrity"] < 100 for c in current["conditions"].values())
    assert not client.get("/api/v1" + base + f"/state?revision={queued_rev}").json()["data"]["damage"]
    revision = current["ref"]["revision"]
    persisted = core.repo.read(sid, revision)
    assert len(persisted.damage_records) == len(current["damage"])
    branch = write(
        client,
        f"/simulations/{sid}/branches",
        dict(name="Damaged branch", source=dict(kind="revision", revision=revision)),
    )
    assert branch.status_code == 201, branch.text
    other = branch.json()["data"]["simulation"]["id"]
    inherited = client.get(f"/api/v1/integrations/disasters/v2/simulations/{other}/state").json()["data"]
    assert inherited["conditions"] == current["conditions"]
    WorldFrame.model_validate(client.get(f"/api/v1/simulations/{sid}/state").json()["data"])


def test_ds_reactions_local_life_state_and_cooldown(client):
    state = world(client)
    r = runtime(state, parameters())
    a = next(iter(state.citizens.values()))
    a.profile.traits.risk_tolerance = 10
    a.needs.fatigue = 0
    reaction(state, r, a, 0.8)
    assert len(state.reactions) == 1
    reaction(state, r, a, 0.9, True)
    assert len(state.reactions) == 1
    state.simulation.sim_time_seconds += 30
    reaction(state, r, a, 0.9)
    assert len(state.reactions) == 2
    state.simulation.sim_time_seconds += 30
    a.needs.health = 0
    reaction(state, r, a, 1, True)
    assert len(state.reactions) == 2


def test_ds_parse_typed_natural_language(client):
    state = world(client)
    assert parse_prompt("An earthquake magnitude 6.2 for 20 ticks", state.map, 42).intensity == 6.2
    p = parse_prompt("tornado, 60 m/s, 20-meter width", state.map, 42)
    assert p.extent_m == 20 and p.intensity == 60 and p.track_end
    assert parse_prompt("Policy change", state.map, 42) is None


def test_ds_rubble_and_repair_route(client):
    state = world(client)
    sid = state.simulation.id
    initialize(state)
    b = next(
        b
        for b in state.map.buildings
        if not any(b.id in {c.inside_building_id, c.entering_building_id} for c in state.citizens.values())
    )
    state.conditions[b.id].integrity = 40
    from app.disasters.models import TerrainDamage

    cell = next(c for c in state.map.cells if c.walkable)
    state.terrain_damage[f"{cell.col}:{cell.row}"] = TerrainDamage(
        col=cell.col, row=cell.row, stage="rubble", blocked=True, cause_ids=[f"building:{b.id}"]
    )
    assert (cell.col, cell.row) in blocked_cells(state)
    core = client.app.state.service
    state.simulation.revision += 1
    core.repo.commit([state])
    core.heads[sid] = state
    base = f"/integrations/disasters/v2/simulations/{sid}"
    before = sum(r.available_units for r in state.map.resources if r.kind == "supplies")
    result = write(
        client,
        base + "/repairs",
        dict(building_id=b.id, expected_control_version=state.simulation.control_version),
    )
    assert result.status_code == 201, result.text
    assert command(client, sid, "step", count=10).status_code == 200
    after = core.owned("demo_owner", sid)
    assert after.conditions[b.id].integrity == 65
    assert sum(r.available_units for r in after.map.resources if r.kind == "supplies") <= before - 10
    assert after.repairs[-1].status == "completed"


def test_ds06_actual_indoor_protection_late_entrant_and_outside_bounds(client):
    state = world(client)
    b = state.map.buildings[0]
    center = Vec2(x=sum(p.x for p in b.footprint) / 4, y=sum(p.y for p in b.footprint) / 4)
    p = parameters("fire").model_copy(update=dict(origin=center, extent_m=12.0))
    r = runtime(state, p)
    indoor, outdoor, entrant = list(state.citizens.values())[:3]
    for citizen in (indoor, outdoor, entrant):
        citizen.needs.health = 100
        citizen.summary.active = True
    indoor.inside_building_id = b.id
    indoor.summary.position = center
    outdoor.inside_building_id = None
    outdoor.summary.position = b.entrance.model_copy()
    entrant.inside_building_id = None
    entrant.summary.position = Vec2(x=1, y=1)
    advance(state)
    indoor_loss = 100 - indoor.needs.health
    outdoor_loss = 100 - outdoor.needs.health
    assert indoor_loss == pytest.approx(outdoor_loss * 0.4, abs=1e-6)
    assert entrant.needs.health == 100
    entrant.summary.position = center
    state.simulation.tick += 1
    state.simulation.sim_time_seconds += 10
    advance(state)
    assert entrant.needs.health < 100 and entrant.summary.id in r.cohort


def test_ds_cancel_queued_and_active_never_rewind_damage(client):
    sim = create_city(client)
    sid = sim["id"]
    base = f"/integrations/disasters/v2/simulations/{sid}"
    for start in (False, True):
        hold = open_editor(client, sid)
        p = write(
            client,
            base + "/previews",
            dict(intervention_id=hold["id"], parameters=parameters("fire").model_dump()),
        ).json()["data"]
        result = write(
            client,
            base + "/commits",
            dict(
                intervention_id=hold["id"],
                preview_id=p["preview"]["id"],
                expected_control_version=hold["control_version"],
            ),
        ).json()["data"]
        if start:
            assert command(client, sid, "step", count=1).status_code == 200
        before = client.get("/api/v1" + base + "/state").json()["data"]
        sim = client.get(f"/api/v1/simulations/{sid}").json()["data"]
        result = write(
            client,
            base + f"/events/{result['event']['id']}/cancel",
            dict(expected_control_version=sim["control_version"]),
        )
        assert result.status_code == 200, result.text
        after = result.json()["data"]
        assert after["events"][-1]["phase"] == "cancel"
        assert after["damage"] == before["damage"] and after["conditions"] == before["conditions"]
        assert bool(after["damage"]) == start


def test_ds_injury_rates_scale_with_simulation_seconds_not_reads(client):
    import copy

    a = world(client)
    p = parameters("fire")
    r = runtime(a, p)
    a.simulation.config = a.simulation.config.model_copy(update=dict(tick_seconds=10))
    b = copy.deepcopy(a)
    b.simulation.config = b.simulation.config.model_copy(update=dict(tick_seconds=5))
    advance(a)
    advance(b)
    b.simulation.tick += 1
    advance(b)
    assert {bid: c.integrity for bid, c in a.conditions.items()} == {
        bid: c.integrity for bid, c in b.conditions.items()
    }
    # Source state is unchanged by projection, reads, or another invocation at this tick.
    before = a.model_dump()
    from app.disasters.physics import view

    view(a)
    view(a)
    advance(a)
    assert a.model_dump() == before
    assert r.last_physical_tick == a.simulation.tick


def test_ds_v1_hazard_activation_migrates_at_live_boundary(client):
    from app.simulation.scenarios import compile_preview

    state = world(client)
    preview = compile_preview(state, "custom", "A fire severity 100 citywide for 2 ticks")
    e = queue_event(state, preview, "snapshot", False)
    assert not state.events[e.id].physical
    activate(state)
    assert state.events[e.id].physical.kind == "fire"
    advance(state)
    assert any(c.integrity < 100 for c in state.conditions.values())
    assert state.events[e.id].spec.affected_polygon == preview.spec.affected_polygon


def test_ds02_late_control_generation_cannot_replace_new_preview(client):
    sid = create_city(client)["id"]
    hold = open_editor(client, sid)
    path = f"/integrations/disasters/v2/simulations/{sid}/previews"
    body = dict(intervention_id=hold["id"], parameters=parameters().model_dump(), editor_generation=4)
    latest = write(client, path, body)
    assert latest.status_code == 201, latest.text
    late = write(client, path, {**body, "editor_generation": 2})
    assert late.status_code == 409 and late.json()["error"]["code"] == "PREVIEW_STALE"
    result = write(
        client,
        path.replace("/previews", "/commits"),
        dict(
            intervention_id=hold["id"],
            preview_id=latest.json()["data"]["preview"]["id"],
            expected_control_version=hold["control_version"],
        ),
    )
    assert result.status_code == 201, result.text


def test_ds_typed_fixtures_are_executable(client):
    import json
    from pathlib import Path

    state = world(client)
    fixture = json.loads(
        (Path(__file__).parents[2] / "contracts/disasters-v2/fixtures/typed-controls.json").read_text()
    )
    for case in fixture["cases"]:
        p = Parameters.model_validate(case["parameters"])
        poly = envelope(p, state.map)
        assert [v.model_dump() for v in poly] == case["footprint"]
        assert exposure(p, p.origin, 0, poly) == pytest.approx(case["origin_exposure_at_start"])


def test_ds_clear_debris_frees_trapped_occupant_without_repairing_occupied_structure(client):
    from app.disasters.models import Repair, TerrainDamage
    from app.disasters.physics import finish_repairs, reconcile_occupants
    from app.simulation.navigation import cell_at

    state = world(client)
    initialize(state)
    b = state.map.buildings[0]
    c = next(iter(state.citizens.values()))
    c.inside_building_id = b.id
    c.entering_building_id = None
    c.leaving_building_id = None
    c.summary.position = Vec2(x=sum(p.x for p in b.footprint) / 4, y=sum(p.y for p in b.footprint) / 4)
    c.needs.health = 80
    c.needs.fatigue = 0
    state.conditions[b.id].integrity = 30
    cell = cell_at(state.map, b.entrance)
    state.terrain_damage[f"{cell.col}:{cell.row}"] = TerrainDamage(
        col=cell.col, row=cell.row, stage="rubble", blocked=True, cause_ids=[f"building:{b.id}"]
    )
    reconcile_occupants(state)
    assert c.trapped_building_id == b.id and not c.summary.path
    state.repairs.append(
        Repair(
            action="clear",
            id="clear-test",
            building_id=b.id,
            start_tick=0,
            finish_tick=1,
            before=30,
            supplies=2.0,
            resource_id="operator-fixture",
        )
    )
    state.simulation.tick = 1
    finish_repairs(state)
    reconcile_occupants(state)
    assert state.conditions[b.id].integrity == 30
    assert (
        c.trapped_building_id is None and c.leaving_building_id == b.id and c.summary.path[-1] == b.entrance
    )


def test_ds_extension_openapi_matches_documented(client):
    import json
    from pathlib import Path

    documented = json.loads((Path(__file__).parents[2] / "contracts/disasters-v2/openapi.json").read_text())
    assert client.app.state.disasters.openapi() == documented
