MERGE INTO AGENTCITY_COMPARISON_EXPORTS_V1 t
USING (SELECT ?::VARCHAR owner_id, ?::VARCHAR simulation_id,
              ?::NUMBER revision, ?::VARCHAR export_sha256,
              PARSE_JSON(?) payload) s
ON t.OWNER_ID=s.owner_id AND t.SIMULATION_ID=s.simulation_id AND t.REVISION=s.revision
WHEN NOT MATCHED THEN INSERT (OWNER_ID, SIMULATION_ID, REVISION, EXPORT_SHA256, PAYLOAD)
VALUES (s.owner_id, s.simulation_id, s.revision, s.export_sha256, s.payload)
