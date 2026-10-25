-- Run after 001_setup.sql. Comparison payloads may now contain a complete
-- versioned disaster_projection. Missing keys remain NULL, never inferred zero.
CREATE OR REPLACE VIEW AGENTCITY_DISASTERS_V2 AS
SELECT OWNER_ID, SIMULATION_ID, REVISION, EXPORT_SHA256,
       PAYLOAD:disaster_projection:schema_version::VARCHAR AS PROJECTION_VERSION,
       PAYLOAD:disaster_projection:conditions AS CONDITIONS,
       PAYLOAD:disaster_projection:damage AS DAMAGE_TRANSITIONS,
       PAYLOAD:disaster_projection:terrain AS TERRAIN,
       PAYLOAD:disaster_projection:repairs AS REPAIRS,
       PAYLOAD:disaster_projection:events AS EVENTS,
       PAYLOAD:disaster_projection:totals AS TOTALS,
       PAYLOAD:disaster_projection:service_changes AS SERVICE_CHANGES,
       INGESTED_AT
FROM AGENTCITY_COMPARISON_EXPORTS_V1;
