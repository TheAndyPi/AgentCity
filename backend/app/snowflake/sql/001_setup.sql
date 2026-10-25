-- Execute once in an explicitly selected dedicated database/schema as its owner.
-- Standard-table PRIMARY KEY constraints are informational: the application
-- serializes MERGE operations with its single-worker integration gate.
CREATE TABLE IF NOT EXISTS AGENTCITY_COMPARISON_EXPORTS_V1 (
    OWNER_ID VARCHAR NOT NULL,
    SIMULATION_ID VARCHAR NOT NULL,
    REVISION NUMBER(38,0) NOT NULL,
    EXPORT_SHA256 VARCHAR NOT NULL,
    PAYLOAD VARIANT NOT NULL,
    INGESTED_AT TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (OWNER_ID, SIMULATION_ID, REVISION)
);
