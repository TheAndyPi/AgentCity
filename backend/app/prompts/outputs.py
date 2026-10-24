from typing import Annotated, Literal

from pydantic import Field

from app.contracts import (
    ID,
    EventSpec,
    Evidence,
    Intent,
    Model,
    Name,
    Pct,
    Profile,
    RelationshipKind,
    ScenePart,
    Text,
    Vec2,
)


class SceneDesign(Model):
    label: Name
    parts: Annotated[list[ScenePart], Field(max_length=8)]


class MemoryProposal(Model):
    text: Text
    importance: Pct
    source: Literal["observed", "heard", "reflection", "injected"]
    evidence: Evidence


class BeliefProposal(Model):
    text: Text
    confidence: Pct
    evidence: Evidence


class RelationshipDelta(Model):
    person_id: ID
    trust_delta: Annotated[float, Field(ge=-20, le=20)]
    affection_delta: Annotated[float, Field(ge=-20, le=20)]
    respect_delta: Annotated[float, Field(ge=-20, le=20)]
    familiarity_delta: Annotated[float, Field(ge=-20, le=20)]
    conflict_delta: Annotated[float, Field(ge=-20, le=20)]
    reason: Text
    evidence: Evidence


class InteractionOutput(Model):
    message: Text
    intent: Text
    emotion: Text
    physical_action: Intent | None
    end_conversation: bool


class ReflectionOutput(Model):
    new_memories: list[MemoryProposal]
    belief_changes: list[BeliefProposal]
    relationship_changes: list[RelationshipDelta]
    goal_changes: list[Text]
    social_desires: list[Text]
    emotional_state: Text


class PlannedAction(Model):
    intent: Intent
    priority: Annotated[float, Field(ge=0, le=100)]


class PlanningOutput(Model):
    primary_objective: Text
    planned_actions: Annotated[list[PlannedAction], Field(max_length=5)]
    social_objectives: list[Text]
    expected_outcome: Text
    reconsider_if: list[Text]


class PerceptionOutput(Model):
    observations: list[Text]
    recognized_people: list[ID]
    social_opportunities: list[Text]
    potential_threats: list[Text]
    interpretations: list[Text]
    uncertainties: list[Text]
    emotional_reaction: Text


class SocialOutput(Model):
    relationship_type: RelationshipKind
    trust: Pct
    affection: Pct
    respect: Pct
    familiarity: Pct
    conflict: Pct
    desired_relationship: Text
    social_intentions: list[Text]
    private_feelings: Text


class ActionOutcome(Model):
    agent_id: ID
    accepted: bool
    description: Text


class PositionProposal(Model):
    agent_id: ID
    position: Vec2
    evidence: Evidence


class WorldProposal(Model):
    effect: EventSpec
    evidence: Evidence


class ObservableProposal(Model):
    text: Text
    position: Vec2
    observer_ids: list[ID]


class NarrativeOutput(Model):
    action_outcomes: list[ActionOutcome]
    position_changes: list[PositionProposal]
    world_changes: list[WorldProposal]
    interaction_results: list[InteractionOutput]
    relationship_events: list[RelationshipDelta]
    observable_events: list[ObservableProposal]


class WorldEventsOutput(Model):
    events: list[EventSpec]


OUTPUTS = {
    "persona": Profile,
    "decision": Intent,
    "interaction": InteractionOutput,
    "game_master": NarrativeOutput,
    "reflection": ReflectionOutput,
    "world_events": WorldEventsOutput,
    "planning": PlanningOutput,
    "perception": PerceptionOutput,
    "social": SocialOutput,
}
