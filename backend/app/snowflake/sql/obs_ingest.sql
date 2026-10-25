MERGE INTO AGENTCITY_OBSERVATION_FACTS_V1 t
USING (
 SELECT p.v:owner_id::VARCHAR owner_id,p.v:simulation_id::VARCHAR simulation_id,
 p.v:revision::NUMBER revision,p.v:tick::NUMBER tick,
 f.value:id::VARCHAR fact_id,f.value:kind::VARCHAR kind,
 f.value:entity_id::VARCHAR entity_id,f.value:payload payload,f.value:sha256::VARCHAR fact_sha256
 FROM (SELECT PARSE_JSON(?) v) p,LATERAL FLATTEN(input=>p.v:facts) f
) s
ON t.OWNER_ID=s.owner_id AND t.SIMULATION_ID=s.simulation_id
 AND t.REVISION=s.revision AND t.FACT_ID=s.fact_id
WHEN NOT MATCHED THEN INSERT
 (OWNER_ID,SIMULATION_ID,REVISION,TICK,FACT_ID,KIND,ENTITY_ID,PAYLOAD,FACT_SHA256)
 VALUES(s.owner_id,s.simulation_id,s.revision,s.tick,s.fact_id,s.kind,s.entity_id,s.payload,s.fact_sha256)
