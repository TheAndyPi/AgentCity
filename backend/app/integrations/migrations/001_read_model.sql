-- Schema is provisioned by the operator. No extensions, database ownership or
-- public-schema changes are required. All identities are simulation scoped.
CREATE TABLE tiger_simulations (
    simulation_id text PRIMARY KEY,
    provenance jsonb NOT NULL,
    ingested_at timestamptz NOT NULL
);
CREATE TABLE tiger_records (
    simulation_id text NOT NULL REFERENCES tiger_simulations(simulation_id),
    kind text NOT NULL CHECK (kind IN ('metric', 'decision', 'event', 'movement')),
    entity_key text NOT NULL,
    revision bigint NOT NULL CHECK (revision >= 0),
    tick bigint NOT NULL CHECK (tick >= 0),
    sim_time_seconds double precision NOT NULL CHECK (sim_time_seconds >= 0),
    payload jsonb NOT NULL,
    ingested_at timestamptz NOT NULL,
    PRIMARY KEY (simulation_id, kind, entity_key)
);
CREATE INDEX tiger_records_revision ON tiger_records(simulation_id, revision, kind);
CREATE INDEX tiger_records_tick ON tiger_records(simulation_id, kind, tick);
CREATE TABLE tiger_progress (
    simulation_id text PRIMARY KEY REFERENCES tiger_simulations(simulation_id),
    revision bigint NOT NULL CHECK (revision >= 0),
    ingested_at timestamptz NOT NULL
);
