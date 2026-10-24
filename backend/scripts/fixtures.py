import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi.testclient import TestClient

from app.infrastructure.config import AppConfig
from app.main import create_app
from app.simulation.game_master import apply_intent, make_intent
from app.simulation.state import now
from scripts.client import Driver


def generate(directory):
    directory.mkdir(parents=True, exist_ok=True)

    def save(name, model, data, revision=0, valid=True):
        (directory / (name + ".json")).write_text(
            json.dumps(
                dict(model=model, valid=valid, revision=revision, data=data),
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    with TemporaryDirectory() as temp:
        with TestClient(
            create_app(AppConfig(data_dir=Path(temp), base_tps=2)),
            base_url="http://127.0.0.1",
            client=("127.0.0.1", 50000),
        ) as client:
            driver = Driver(client)
            created = driver.write(
                "/simulations", dict(config=dict(name="Fixture city", seed=24, population=10))
            )
            save("initializing_job", "Simulation", created["data"])
            import time

            sid = created["data"]["id"]
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                simulation = driver.get(f"/simulations/{sid}")
                if simulation["status"] != "initializing":
                    break
                time.sleep(0.01)
            assert simulation["status"] == "paused", simulation
            ready = driver.get(f"/simulations/{sid}/state")
            save("ready_paused_city", "WorldFrame", ready, simulation["revision"])
            save("all_empty_lists", "Page[Memory]", dict(items=[], next_cursor=None), simulation["revision"])
            state = client.app.state.service.heads[sid].model_copy(deep=True)
            a, b = list(state.citizens.values())[:2]
            a.summary.position.x = 1
            a.summary.position.y = 3
            b.summary.position.x = 110
            b.summary.position.y = 101
            rejected = apply_intent(state, a, make_intent("help", target=b.summary.id))
            save("rejected_remote_help", "Decision", rejected.model_dump(), state.simulation.revision)
            save(
                "directed_edge_a_b",
                "Relationship",
                a.relationships[b.summary.id].model_dump(),
                state.simulation.revision,
            )
            other = next(iter(b.relationships.values())).model_copy(deep=True)
            other.to_agent_id = a.summary.id
            other.trust = 17
            save("directed_edge_b_a", "Relationship", other.model_dump(), state.simulation.revision)
            driver.command(sid, "play")
            running = driver.get(f"/simulations/{sid}/state")
            save("running_city", "WorldFrame", running, running["ref"]["revision"])
            driver.command(sid, "pause")
            hold, p = driver.preview(sid, "A flood severity 65 for 2 ticks")
            save("custom_preview", "ScenarioPreview", p, p["based_on"]["revision"])
            key = str(uuid4())
            queued = driver.commit(sid, hold, p, key)["data"]
            again = driver.commit(sid, hold, p, key)["data"]
            assert queued == again
            save("paused_queued_event", "ScenarioResult", queued, queued["simulation"]["revision"])
            command = driver.command(sid, "save", reason="manual", label="Idempotency fixture")["data"]
            save("idempotent_command_original", "CommandResult", command, command["simulation"]["revision"])
            save("idempotent_command_duplicate", "CommandResult", command, command["simulation"]["revision"])
            driver.command(sid, "step", count=1)
            active = driver.get(f"/simulations/{sid}/state")
            save("active_flood", "WorldFrame", active, active["ref"]["revision"])
            aid = active["agents"][0]["id"]
            inspector = driver.get(f"/simulations/{sid}/agents/{aid}")
            decision = inspector["decisions"]["items"][0]
            save("rules_fallback", "Decision", decision, inspector["ref"]["revision"])
            driver.command(sid, "step", count=10)
            report = driver.get(f"/simulations/{sid}/events/{queued['event']['id']}")
            save("resolved_event_report", "EventReport", report, report["ref"]["revision"])
            outcome = driver.get(f"/simulations/{sid}")
            save("pending_outcome", "Simulation", outcome, outcome["revision"])
            branch = driver.write(
                f"/simulations/{sid}/branches",
                dict(
                    name="Restored fixture",
                    source=dict(kind="snapshot", snapshot_id=queued["snapshot"]["id"]),
                ),
            )["data"]
            save("restored_branch", "BranchResult", branch, branch["simulation"]["revision"])
            historical = driver.get(f"/simulations/{sid}/agents/{aid}", revision=ready["ref"]["revision"])
            save("historical_agent_no_future", "AgentDetail", historical, historical["ref"]["revision"])
            archived = driver.command(sid, "archive")["data"]["simulation"]
            save("archived_simulation", "Simulation", archived, archived["revision"])
            for suffix in ("snapshot", "reconnection"):
                save(
                    "transport_" + suffix,
                    "ServerMessage",
                    dict(
                        schema_version="1.0.0", simulation_id=sid, sent_at=now(), type="snapshot", data=active
                    ),
                    active["ref"]["revision"],
                )
            initial = driver.city(scenario_description="A flood for 5 ticks", population=10)
            save(
                "initial_scenario_preview", "ScenarioPreview", initial["initial_preview"], initial["revision"]
            )
            bad = driver.write(
                "/simulations", dict(config=dict(name="Invalid", seed=2, population=9)), expected=422
            )
            save("validation_error", "Failure", bad)
            stale = {
                "schema_version": "1.0.0",
                "request_id": str(uuid4()),
                "error": {
                    "code": "PREVIEW_STALE",
                    "message": "World changed after preview",
                    "retryable": False,
                    "details": [],
                },
            }
            save("stale_preview_error", "Failure", stale, archived["revision"])
            invalid = copy.deepcopy(ready)
            invalid["agents"][0]["position"]["x"] = "NaN"
            save("invalid_coordinate", "WorldFrame", invalid, ready["ref"]["revision"], False)
            invalid = copy.deepcopy(ready)
            invalid["agents"][0]["metrics"]["trust"] = 101
            save("invalid_pct", "WorldFrame", invalid, ready["ref"]["revision"], False)
            save(
                "invalid_extra_field",
                "CreateSimulation",
                dict(config=dict(name="Bad", seed=1), extra=True),
                valid=False,
            )
            save(
                "invalid_population",
                "CreateSimulation",
                dict(config=dict(name="Bad", seed=1, population=101)),
                valid=False,
            )
            save(
                "invalid_missing_nullable",
                "Intent",
                dict(
                    action="rest",
                    parameters=dict(resource_kind=None, amount=None, message=None),
                    motivation="Rest",
                    emotion="calm",
                ),
                valid=False,
            )
            save(
                "invalid_request_uuid",
                "CommandRequest",
                dict(request_id="not-uuid", expected_control_version=0, command=dict(type="play")),
                valid=False,
            )
            # Store a concise independent trace beside backend handoff artifacts.
            output = Path(__file__).resolve().parents[1] / "artifacts"
            output.mkdir(exist_ok=True)
            (output / "request-response-trace.json").write_text(
                json.dumps(driver.trace, indent=2) + "\n", encoding="utf-8"
            )
            prompts = {
                "persona": historical["profile"],
                "decision": make_intent("rest").model_dump(),
                "interaction": dict(
                    message="Can I help?",
                    intent="offer support",
                    emotion="concerned",
                    physical_action=None,
                    end_conversation=False,
                ),
                "game_master": dict(
                    action_outcomes=[],
                    position_changes=[],
                    world_changes=[],
                    interaction_results=[],
                    relationship_events=[],
                    observable_events=[],
                ),
                "reflection": dict(
                    new_memories=[],
                    belief_changes=[],
                    relationship_changes=[],
                    goal_changes=[],
                    social_desires=[],
                    emotional_state="calm",
                ),
                "world_events": dict(events=[report["spec"]]),
                "planning": dict(
                    primary_objective="Rest",
                    planned_actions=[dict(intent=make_intent("rest").model_dump(), priority=50)],
                    social_objectives=[],
                    expected_outcome="Recover some energy",
                    reconsider_if=["A nearby threat appears"],
                ),
                "perception": dict(
                    observations=[],
                    recognized_people=[],
                    social_opportunities=[],
                    potential_threats=[],
                    interpretations=[],
                    uncertainties=[],
                    emotional_reaction="calm",
                ),
                "social": dict(
                    relationship_type="acquaintance",
                    trust=50,
                    affection=35,
                    respect=50,
                    familiarity=30,
                    conflict=10,
                    desired_relationship="Mutual support",
                    social_intentions=[],
                    private_feelings="Cautious curiosity",
                ),
            }
            prompt_path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "prompts.json"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(json.dumps(prompts, indent=2) + "\n", encoding="utf-8")
