MERGE INTO AGENTCITY_OBSERVATION_REVISIONS_V1 t
USING (
 SELECT p.v:owner_id::VARCHAR owner_id,p.v:simulation_id::VARCHAR simulation_id,
 p.v:revision::NUMBER revision,p.v:tick::NUMBER tick,p.v:source_sha256::VARCHAR source_sha256,
 p.v:facts_sha256::VARCHAR facts_sha256,p.v:fact_count::NUMBER fact_count,p.v:provenance provenance
 FROM (SELECT PARSE_JSON(?) v) p
) s
ON t.OWNER_ID=s.owner_id AND t.SIMULATION_ID=s.simulation_id AND t.REVISION=s.revision
WHEN NOT MATCHED THEN INSERT
 (OWNER_ID,SIMULATION_ID,REVISION,TICK,SOURCE_SHA256,FACTS_SHA256,FACT_COUNT,PROVENANCE)
 VALUES(s.owner_id,s.simulation_id,s.revision,s.tick,s.source_sha256,s.facts_sha256,s.fact_count,s.provenance)
