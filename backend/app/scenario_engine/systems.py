"""Persistent world systems that scenario operations mutate and agents interact with.

This state is internal checkpoint data (like `State`), not a frozen wire DTO.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import Field

from app.contracts import Model
from app.scenario_engine.registry import POLICY_TARGETS, REGIONS

# Economy rules, in credits. Baseline income roughly balances baseline costs.
WAGE_PER_SHIFT = 0.7
REVENUE_PER_SHIFT = 0.85
FOOD_PRICE = 1.0
RENT_PER_TICK = 0.012
TRANSIT_OPERATING_COST = 0.08
HOSPITAL_UPKEEP = 0.15
STRAIN_WALLET = 3.0
SHOP_STOCK_MAX = 30.0
SHOP_PRODUCTION = 0.25
TRIP_MIN_METERS = 16
MODE_SPEED = {"walk": 1.0, "transit": 1.9, "car": 2.4}
TRACE_LIMIT = 4000
SERIES_LIMIT = 400


class Taxation(Model):
    business_tax_rate: float = 0.10
    household_tax_rate: float = 0.05


class Transportation(Model):
    transit_fare: float = 0.3
    car_trip_cost: float = 0.8
    transit_service_level: float = 1.0
    transit_campaign: float = 0.0


class Housing(Model):
    rent_level: float = 1.0
    rent_cap: float | None = None
    assistance_per_tick: float = 0.0


class PublicServices(Model):
    hospital_funding: float = 1.0


class BusinessRegulation(Model):
    price_level: float = 1.0
    subsidy_per_shift: float = 0.0


class ResourceDistribution(Model):
    ration_units_per_agent: float | None = None
    aid_multiplier: float = 1.0
    evacuation_order: float = 0.0


class CommunityPrograms(Model):
    cooperation_reward: float = 0.0
    conservation_campaign: float = 0.0


class PolicyState(Model):
    taxation: Taxation = Field(default_factory=Taxation)
    transportation: Transportation = Field(default_factory=Transportation)
    housing: Housing = Field(default_factory=Housing)
    public_services: PublicServices = Field(default_factory=PublicServices)
    business: BusinessRegulation = Field(default_factory=BusinessRegulation)
    resource_distribution: ResourceDistribution = Field(default_factory=ResourceDistribution)
    community_programs: CommunityPrograms = Field(default_factory=CommunityPrograms)

    def get(self, target):
        domain, field = registered(target)
        return getattr(getattr(self, domain), field)

    def set(self, target, value):
        domain, field = registered(target)
        setattr(getattr(self, domain), field, value)


def registered(target):
    if target not in POLICY_TARGETS:
        raise KeyError(f"Unregistered policy target {target}")
    domain, field = target.split(".")
    return domain, field


class Belief(Model):
    topic: str
    message: str
    confidence: float
    channel: str
    source_op: str
    accurate: bool
    tick: int
    shared_with: list[str] = Field(default_factory=list)


class AgentSystems(Model):
    wallet: float
    income: Literal["low", "middle", "high"]
    owns_car: bool
    habit: Literal["walk", "transit", "car"]
    institutional_trust: float
    rent_factor: float
    home_id: str | None = None
    renter: bool = True
    norms: dict[str, float] = Field(default_factory=dict)
    organizations: list[str] = Field(default_factory=list)
    incentives: dict[str, float] = Field(default_factory=dict)
    beliefs: dict[str, Belief] = Field(default_factory=dict)
    trips: dict[str, int] = Field(default_factory=lambda: {"walk": 0, "transit": 0, "car": 0})
    streak: dict[str, Any] = Field(default_factory=lambda: {"mode": None, "count": 0})
    trip_mode: str | None = None
    regular_shop: str | None = None
    shop_visits: dict[str, int] = Field(default_factory=dict)
    housing_status: Literal["housed", "seeking_assistance", "relocated", "sharing"] = "housed"
    next_review_tick: int = 0
    satisfaction: float = 60
    last_paid: dict[str, float] = Field(default_factory=dict)
    shifts: int = 0
    last_purchase_tick: int = -100
    evacuation_choice: dict[str, bool] = Field(default_factory=dict)
    conditions: dict[str, int] = Field(default_factory=dict)


class Organization(Model):
    id: str
    kind: str
    name: str
    mission: str
    eligibility: str
    region: str
    budget_per_tick: float
    rally_every: int
    created_tick: int
    event_id: str | None
    active: bool = True
    members: list[str] = Field(default_factory=list)
    pool: float = 0
    paid: float = 0


class Scheduled(Model):
    tick: int
    event_id: str
    op: dict[str, Any]
    action: Literal["apply", "revert"]
    repetition: int = 0
    permanent: bool = False
    undo: dict[str, Any] = Field(default_factory=dict)


class Trace(Model):
    id: str
    tick: int
    kind: Literal["operation", "decision"]
    event_id: str | None
    op_id: str | None
    agent_id: str | None
    title: str
    observations: list[str] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    selected: str | None = None
    motivation: str = ""
    memory_ids: list[str] = Field(default_factory=list)
    changes: list[dict[str, Any]] = Field(default_factory=list)
    affected_ids: list[str] = Field(default_factory=list)
    significance: float = 0


class PlanRecord(Model):
    event_id: str
    plan: dict[str, Any]
    status: Literal["queued", "active", "resolved"] = "queued"
    activated_tick: int | None = None
    resolved_tick: int | None = None
    baseline: dict[str, Any] = Field(default_factory=dict)
    counters: dict[str, float] = Field(default_factory=dict)
    series: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    policy_before: dict[str, Any] = Field(default_factory=dict)
    policy_after: dict[str, Any] = Field(default_factory=dict)
    cohort: list[str] = Field(default_factory=list)


class WorldSystems(Model):
    enabled: bool = False
    enabled_tick: int | None = None
    policy: PolicyState = Field(default_factory=PolicyState)
    treasury: float = 60
    businesses: dict[str, float] = Field(default_factory=dict)
    shop_stock: dict[str, float] = Field(default_factory=dict)
    housing_available: dict[str, bool] = Field(default_factory=dict)
    home_rent: dict[str, float] = Field(default_factory=dict)
    base_capacity: dict[str, int] = Field(default_factory=dict)
    closed_by: dict[str, str] = Field(default_factory=dict)
    service_controls: dict[str, dict[str, dict[str, Any]]] = Field(default_factory=dict)
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    agents: dict[str, AgentSystems] = Field(default_factory=dict)
    organizations: dict[str, Organization] = Field(default_factory=dict)
    norms: dict[str, float] = Field(default_factory=dict)
    schedule: list[Scheduled] = Field(default_factory=list)
    traces: list[Trace] = Field(default_factory=list)
    plans: dict[str, PlanRecord] = Field(default_factory=dict)
    initial_plan: dict[str, Any] | None = None
    initial_preview_id: str | None = None
    counters: dict[str, float] = Field(default_factory=dict)
    sequence: int = 0

    def next_id(self, prefix):
        self.sequence += 1
        return f"{prefix}_{self.sequence:07d}"


def unit(*parts):
    """A reproducible number in [0, 1) for a named choice, independent of the world RNG."""
    digest = hashlib.sha256(":".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:4]) / 2**32


def in_region(point, region):
    x0, y0, x1, y1 = REGIONS[region]
    return x0 <= point.x <= x1 and y0 <= point.y <= y1


def bump(systems, name, amount=1):
    systems.counters[name] = systems.counters.get(name, 0) + amount
