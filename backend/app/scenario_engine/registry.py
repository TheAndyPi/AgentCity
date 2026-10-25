"""Explicit registry of world systems, mutable targets and parameterized operations.

Nothing outside this registry can be mutated by a plan. Policy targets are a fixed
table of `domain.field` names with ranges; there is no generic property-path setter.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from app.contracts import ID, Model, Text

Region = Literal[
    "citywide", "north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest"
]
REGIONS: dict[str, tuple[float, float, float, float]] = {
    "citywide": (0, 0, 128, 128),
    "north": (0, 64, 128, 128),
    "south": (0, 0, 128, 64),
    "east": (64, 0, 128, 128),
    "west": (0, 0, 64, 128),
    "northeast": (64, 64, 128, 128),
    "northwest": (0, 64, 64, 128),
    "southeast": (64, 0, 128, 64),
    "southwest": (0, 0, 64, 64),
}

System = Literal[
    "economy",
    "taxation",
    "transportation",
    "housing",
    "public_services",
    "healthcare",
    "business",
    "resources",
    "information",
    "public_trust",
    "social_norms",
    "social_network",
    "organizations",
    "population_traits",
    "environment",
    "infrastructure",
    "safety",
]

MetricId = Literal[
    "happiness",
    "stress",
    "safety",
    "trust",
    "institutional_trust",
    "resources",
    "cooperation",
    "social_conflict",
    "policy_compliance",
    "service_access",
    "transit_usage",
    "car_usage",
    "walking_trips",
    "business_resources",
    "city_treasury",
    "household_wallets",
    "financial_strain",
    "rent_burden",
    "relocations",
    "assistance_requests",
    "information_shares",
    "belief_adoption",
    "norm_adoption",
    "organization_membership",
    "relationship_change",
    "hospital_care",
    "food_access",
]

METRICS: dict[str, str] = {
    "happiness": "Mean citizen happiness (0-100)",
    "stress": "Mean citizen stress (0-100)",
    "safety": "Mean citizen safety (0-100)",
    "trust": "Mean interpersonal trust (0-100)",
    "institutional_trust": "Mean trust in official institutions (0-100)",
    "resources": "Mean household resource score (0-100)",
    "cooperation": "Cooperative actions (help, trade, aid transfers) since activation",
    "social_conflict": "Contested claims and recorded disagreements since activation",
    "policy_compliance": "Share of decisions about official directives that complied",
    "service_access": "Share of attempts to enter services that succeeded",
    "transit_usage": "Share of recorded trips taken by public transit",
    "car_usage": "Share of recorded trips taken by car",
    "walking_trips": "Share of recorded trips taken on foot",
    "business_resources": "Total business reserves in credits",
    "city_treasury": "City treasury balance in credits",
    "household_wallets": "Mean household wallet in credits",
    "financial_strain": "Citizens with wallets below the strain threshold",
    "rent_burden": "Mean rent paid per tick in credits",
    "relocations": "Citizens who moved to another home since activation",
    "assistance_requests": "Citizens who requested assistance since activation",
    "information_shares": "Times a citizen passed information to someone else",
    "belief_adoption": "Citizens currently holding a belief introduced by this scenario",
    "norm_adoption": "Citizens who adopted a scenario social norm",
    "organization_membership": "Members of scenario organizations",
    "relationship_change": "Directed relationship updates since activation",
    "hospital_care": "Citizen-ticks of hospital care delivered since activation",
    "food_access": "Food units bought at shops or gathered since activation",
}

PolicyTarget = Literal[
    "taxation.business_tax_rate",
    "taxation.household_tax_rate",
    "transportation.transit_fare",
    "transportation.car_trip_cost",
    "transportation.transit_service_level",
    "transportation.transit_campaign",
    "housing.rent_level",
    "housing.rent_cap",
    "housing.assistance_per_tick",
    "public_services.hospital_funding",
    "business.price_level",
    "business.subsidy_per_shift",
    "resource_distribution.ration_units_per_agent",
    "resource_distribution.aid_multiplier",
    "resource_distribution.evacuation_order",
    "community_programs.cooperation_reward",
    "community_programs.conservation_campaign",
]

# (minimum, maximum, unit, nullable, description, systems)
POLICY_TARGETS: dict[str, tuple[float, float, str, bool, str, tuple[str, ...]]] = {
    "taxation.business_tax_rate": (
        0, 0.6, "share", False,
        "Share of each business's revenue paid to the city treasury.", ("taxation", "business", "economy"),
    ),
    "taxation.household_tax_rate": (
        0, 0.4, "share", False, "Share of each wage paid to the city treasury.", ("taxation", "economy"),
    ),
    "transportation.transit_fare": (
        0, 10, "credits per trip", False,
        "Fare a rider pays per public transit trip. Fare revenue goes to the treasury.",
        ("transportation", "economy"),
    ),
    "transportation.car_trip_cost": (
        0, 20, "credits per trip", False, "Fuel, parking and toll cost of one car trip.",
        ("transportation", "economy"),
    ),
    "transportation.transit_service_level": (
        0, 2, "multiplier", False,
        "Transit frequency and speed. 0 suspends service; 1 is normal; above 1 is faster service "
        "that costs the treasury more to operate.",
        ("transportation", "infrastructure"),
    ),
    "transportation.transit_campaign": (
        0, 1, "intensity", False,
        "Official encouragement to ride transit instead of driving. Citizens weigh it by how much "
        "they trust institutions.",
        ("transportation", "public_trust"),
    ),
    "housing.rent_level": (
        0.2, 3, "multiplier", False, "Market rent level relative to today's rents.", ("housing", "economy"),
    ),
    "housing.rent_cap": (
        0.2, 3, "multiplier", True,
        "Rent control: the highest rent multiplier landlords may charge. Clear it to remove control.",
        ("housing",),
    ),
    "housing.assistance_per_tick": (
        0, 1, "credits per tick", False,
        "Housing assistance the treasury pays to low-income renters who request it.",
        ("housing", "public_services", "economy"),
    ),
    "public_services.hospital_funding": (
        0.25, 3, "multiplier", False,
        "Hospital funding. It sets care quality (healing per tick) and capacity, and costs the "
        "treasury upkeep above the normal level.",
        ("public_services", "healthcare"),
    ),
    "business.price_level": (
        0.25, 3, "multiplier", False, "Shop prices relative to today's prices, including food.",
        ("business", "economy", "resources"),
    ),
    "business.subsidy_per_shift": (
        0, 2, "credits per shift", False, "Treasury subsidy paid to a business per work shift.",
        ("business", "economy"),
    ),
    "resource_distribution.ration_units_per_agent": (
        0.25, 10, "units per tick", True,
        "Most units one citizen may gather from a depot per tick. Clear it to remove rationing.",
        ("resources",),
    ),
    "resource_distribution.aid_multiplier": (
        0, 3, "multiplier", False, "Strength of help and community aid deliveries.", ("resources",),
    ),
    "resource_distribution.evacuation_order": (
        0, 1, "boolean (0 or 1)", False,
        "Official evacuation order. Citizens decide whether to comply based on institutional trust "
        "and what they observe.",
        ("safety", "public_trust"),
    ),
    "community_programs.cooperation_reward": (
        0, 2, "credits per action", False,
        "Treasury reward paid to a citizen for each accepted help or trade.",
        ("social_norms", "economy"),
    ),
    "community_programs.conservation_campaign": (
        0, 1, "intensity", False,
        "Official campaign asking citizens not to stockpile. Citizens weigh it by institutional trust.",
        ("resources", "public_trust"),
    ),
}

BuildingKind = Literal["home", "work", "shop", "shelter", "hospital", "community"]
ResourceKind = Literal["food", "water", "supplies"]
Trait = Literal["curiosity", "empathy", "sociability", "trust", "cooperation", "risk_tolerance"]
Norm = Literal["help_strangers", "use_public_transit", "conserve_resources", "civic_participation"]
NORMS: dict[str, str] = {
    "help_strangers": "Helping people you do not know, including in shortages.",
    "use_public_transit": "Choosing public transit over driving.",
    "conserve_resources": "Taking only what you need instead of stockpiling.",
    "civic_participation": "Joining organizations and public meetings.",
}
Topic = Literal[
    "policy_change", "prices", "safety", "services", "housing", "transport", "community", "government", "other"
]
Channel = Literal["official", "media", "rumor", "word_of_mouth"]
AudienceKind = Literal[
    "all_citizens", "region", "low_income", "middle_income", "high_income", "renters", "workers",
    "transit_riders", "car_users", "organization_members", "share",
]
OrganizationKind = Literal["mutual_aid", "tenant_union", "protest_group", "community_program", "assistance_office"]
ORGANIZATIONS: dict[str, str] = {
    "mutual_aid": "Members with surplus contribute supplies to a pool; members in need draw from it.",
    "tenant_union": "Renters organize, meet at the community center and demand housing help.",
    "protest_group": "Residents rally at the community center on a schedule to press a cause.",
    "community_program": "A funded program that pays a stipend to eligible members who join.",
    "assistance_office": "An office that pays treasury-funded assistance to eligible citizens who apply.",
}
Eligibility = Literal["all", "low_income", "renters", "region"]
Incentive = Literal["transit_rebate", "help_reward", "conservation_bonus", "work_bonus"]
INCENTIVES: dict[str, str] = {
    "transit_rebate": "Credits returned to the citizen per transit trip.",
    "help_reward": "Credits paid to the citizen per accepted help or trade.",
    "conservation_bonus": "Credits per tick while the citizen keeps a modest inventory (no stockpiling).",
    "work_bonus": "Extra credits per work shift.",
}
Condition = Literal["heat", "cold", "illness", "pollution", "noise"]
Hazard = Literal["flood", "fire", "storm"]

Fraction = Annotated[float, Field(ge=0, le=1)]
Offset = Annotated[int, Field(ge=0, le=500)]
Duration = Annotated[int, Field(ge=1, le=1000)]
Repeat = Annotated[int, Field(ge=2, le=100)]
RepeatCount = Annotated[int, Field(ge=1, le=20)]
ShortText = Annotated[str, Field(max_length=300)]
Label = Annotated[str, Field(min_length=1, max_length=80)]


class Audience(Model):
    kind: AudienceKind = "all_citizens"
    share: Fraction = 1
    region: Region | None = None
    organization_id: ID | None = None


class Timing(Model):
    start_tick: Offset = 0
    duration_ticks: Duration | None = None
    repeat_every: Repeat | None = None
    repeat_count: RepeatCount | None = None


class Base(Model):
    id: Annotated[str, Field(min_length=1, max_length=40)] = "op"
    timing: Timing = Field(default_factory=Timing)
    rationale: ShortText = ""


class ModifyPolicy(Base):
    type: Literal["modify_policy"]
    target: PolicyTarget
    operation: Literal["set", "increase", "decrease", "multiply", "clear"]
    value: float | None = None


class SetServiceAvailability(Base):
    type: Literal["set_service_availability"]
    building_id: ID | None = None
    building_kind: BuildingKind | None = None
    region: Region = "citywide"
    open: bool
    capacity_multiplier: Annotated[float, Field(ge=0, le=3)] = 1


class ModifyResourceStock(Base):
    type: Literal["modify_resource_stock"]
    resource: ResourceKind
    region: Region = "citywide"
    multiplier: Annotated[float, Field(ge=0, le=3)]


class ModifyHousingSupply(Base):
    type: Literal["modify_housing_supply"]
    available_share: Annotated[float, Field(ge=0.3, le=1)]
    region: Region = "citywide"


class BroadcastInformation(Base):
    type: Literal["broadcast_information"]
    audience: Audience = Field(default_factory=Audience)
    channel: Channel
    topic: Topic
    message: Annotated[str, Field(min_length=1, max_length=500)]
    credibility: Annotated[float, Field(ge=0, le=100)] = 80
    accurate: bool = True


class AdjustInstitutionalCredibility(Base):
    type: Literal["adjust_institutional_credibility"]
    audience: Audience = Field(default_factory=Audience)
    delta: Annotated[float, Field(ge=-50, le=50)]
    reason: Annotated[str, Field(min_length=1, max_length=300)]


class IntroduceSocialNorm(Base):
    type: Literal["introduce_social_norm"]
    norm: Norm
    strength: Fraction
    audience: Audience = Field(default_factory=Audience)


class CreateOrganization(Base):
    type: Literal["create_organization"]
    kind: OrganizationKind
    name: Label
    mission: ShortText = ""
    eligibility: Eligibility = "all"
    region: Region = "citywide"
    budget_per_tick: Annotated[float, Field(ge=0, le=5)] = 0
    rally_every: Annotated[int, Field(ge=6, le=200)] = 24
    founding_share: Annotated[float, Field(ge=0, le=0.5)] = 0.1


class RemoveOrganization(Base):
    type: Literal["remove_organization"]
    organization_id: ID


class SetIncentive(Base):
    type: Literal["set_incentive"]
    incentive: Incentive
    amount: Annotated[float, Field(ge=0, le=3)]
    audience: Audience = Field(default_factory=Audience)


class AdjustPopulationTraits(Base):
    type: Literal["adjust_population_traits"]
    trait: Trait
    delta: Annotated[float, Field(ge=-40, le=40)]
    audience: Audience = Field(default_factory=Audience)
    selection: Literal["random", "lowest", "highest"] = "random"


class ModifySocialNetwork(Base):
    type: Literal["modify_social_network"]
    action: Literal["connect_strangers", "weaken_ties"]
    audience: Audience = Field(default_factory=Audience)
    ties_per_agent: Annotated[int, Field(ge=1, le=3)] = 1


class PhysicalHazard(Base):
    type: Literal["physical_hazard"]
    hazard: Hazard
    region: Region
    severity: Annotated[float, Field(ge=1, le=100)]


class CommunityGathering(Base):
    type: Literal["community_gathering"]
    activity: Literal["festival", "aid"]
    region: Region


class EnvironmentalCondition(Base):
    type: Literal["environmental_condition"]
    condition: Condition
    region: Region = "citywide"
    intensity: Annotated[float, Field(ge=1, le=100)]


Operation = Annotated[
    ModifyPolicy
    | SetServiceAvailability
    | ModifyResourceStock
    | ModifyHousingSupply
    | BroadcastInformation
    | AdjustInstitutionalCredibility
    | IntroduceSocialNorm
    | CreateOrganization
    | RemoveOrganization
    | SetIncentive
    | AdjustPopulationTraits
    | ModifySocialNetwork
    | PhysicalHazard
    | CommunityGathering
    | EnvironmentalCondition,
    Field(discriminator="type"),
]

OPERATION_MODELS = {
    model.model_fields["type"].annotation.__args__[0]: model
    for model in (
        ModifyPolicy,
        SetServiceAvailability,
        ModifyResourceStock,
        ModifyHousingSupply,
        BroadcastInformation,
        AdjustInstitutionalCredibility,
        IntroduceSocialNorm,
        CreateOrganization,
        RemoveOrganization,
        SetIncentive,
        AdjustPopulationTraits,
        ModifySocialNetwork,
        PhysicalHazard,
        CommunityGathering,
        EnvironmentalCondition,
    )
}
OperationType = Literal[tuple(OPERATION_MODELS)]

# Description, the systems an operation touches, and whether it is a physical
# event that shares the event's single map region.
OPERATIONS: dict[str, tuple[str, tuple[str, ...], bool]] = {
    "modify_policy": (
        "Set, increase, decrease, multiply or clear one registered policy target.", (), False,
    ),
    "set_service_availability": (
        "Open or close a building (by building_id) or every building of a kind in a region, and "
        "scale its capacity. Closed businesses stop producing and selling.",
        ("public_services", "infrastructure", "business"),
        False,
    ),
    "modify_resource_stock": (
        "Multiply the stock of food, water or supplies at the depots in a region.", ("resources",), False,
    ),
    "modify_housing_supply": (
        "Set the share of homes in a region that accept tenants. Scarcer housing pushes market rent up.",
        ("housing", "economy"),
        False,
    ),
    "broadcast_information": (
        "Tell an audience something through a channel. Each citizen decides whether to believe it, "
        "and believers may pass it on in conversation.",
        ("information",),
        False,
    ),
    "adjust_institutional_credibility": (
        "Introduce a condition that changes how credible official sources seem (for example a scandal "
        "or a transparency program). Each affected citizen's trust shifts by their own susceptibility.",
        ("public_trust", "information"),
        False,
    ),
    "introduce_social_norm": (
        "Promote a social norm. Citizens adopt it or not based on their traits and on whether people "
        "they know have adopted it.",
        ("social_norms",),
        False,
    ),
    "create_organization": (
        "Create an organization. Eligible citizens decide whether to join; members act on its mission.",
        ("organizations",),
        False,
    ),
    "remove_organization": ("Dissolve an existing organization by organization_id.", ("organizations",), False),
    "set_incentive": (
        "Give an audience a per-action or per-tick credit incentive.", ("economy", "social_norms"), False,
    ),
    "adjust_population_traits": (
        "Directly edit a personality trait for part of the population. This changes who citizens are, "
        "not their environment; use it only when the request is about changing people themselves.",
        ("population_traits",),
        False,
    ),
    "modify_social_network": (
        "Create acquaintance ties between strangers, or weaken existing ties.", ("social_network",), False,
    ),
    "physical_hazard": (
        "A flood, fire or storm in a region at a severity. Citizens decide how to stay safe.",
        ("safety", "environment"),
        True,
    ),
    "community_gathering": (
        "A festival or community aid distribution in a region.", ("social_norms", "resources"), True,
    ),
    "environmental_condition": (
        "Heat, cold, illness, pollution or noise in a region. It affects health and stress per tick; "
        "being indoors or in hospital mitigates it.",
        ("environment", "healthcare"),
        False,
    ),
}

Category = Literal["policy", "behavioral", "economic", "environmental", "social", "infrastructure", "mixed"]


class ScenarioPlan(Model):
    title: Label
    category: Category
    description: Annotated[str, Field(min_length=1, max_length=1000)]
    public_description: Annotated[str, Field(min_length=1, max_length=500)]
    duration: Literal["temporary", "permanent"]
    measurement_ticks: Annotated[int, Field(ge=4, le=500)] = 36
    affected_systems: Annotated[list[System], Field(max_length=17)]
    operations: Annotated[list[Operation], Field(min_length=1, max_length=24)]
    agent_knowledge: Annotated[str, Field(max_length=500)] = ""
    metrics: Annotated[list[MetricId], Field(max_length=27)]
    assumptions: Annotated[list[ShortText], Field(max_length=8)] = Field(default_factory=list)
    unsupported: Annotated[list[ShortText], Field(max_length=8)] = Field(default_factory=list)
    source: Literal["gemini", "manual"] = "manual"
    prompt: Text = ""


def capabilities():
    """The registry description given to the interpreter and the editor UI."""
    return dict(
        operations=[
            dict(
                type=name,
                description=description,
                systems=list(systems),
                physical=physical,
                parameters=OPERATION_MODELS[name].model_json_schema(),
            )
            for name, (description, systems, physical) in OPERATIONS.items()
        ],
        policy_targets=[
            dict(
                target=target,
                minimum=low,
                maximum=high,
                unit=unit,
                nullable=nullable,
                description=description,
                systems=list(systems),
            )
            for target, (low, high, unit, nullable, description, systems) in POLICY_TARGETS.items()
        ],
        regions=list(REGIONS),
        norms=NORMS,
        organizations=ORGANIZATIONS,
        incentives=INCENTIVES,
        metrics=METRICS,
        systems=list(System.__args__),
    )
