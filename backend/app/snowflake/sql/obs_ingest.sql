MERGE INTO AGENTCITY_OBSERVATION_FACTS_V1 t
USING (
 SELECT p.v:owner_id::VARCHAR owner_id,p.v:simulation_id::VARCHAR simulation_id,
 p.v:revision::NUMBER revision,p.v:tick::NUMBER tick,
 f.value:id::VARCHAR fact_id,r.body:kind::VARCHAR kind,
 r.body:entity_id::VARCHAR entity_id,r.body:payload payload,SHA2(f.value:record_json::VARCHAR,256) fact_sha256
 FROM (SELECT PARSE_JSON(?) v) p,LATERAL FLATTEN(input=>p.v:facts) f,
 LATERAL (SELECT PARSE_JSON(f.value:record_json::VARCHAR) body) r
) s
ON t.OWNER_ID=s.owner_id AND t.SIMULATION_ID=s.simulation_id
 AND t.REVISION=s.revision AND t.FACT_ID=s.fact_id
WHEN NOT MATCHED THEN INSERT
 (OWNER_ID,SIMULATION_ID,REVISION,TICK,FACT_ID,KIND,ENTITY_ID,PAYLOAD,FACT_SHA256)
 VALUES(s.owner_id,s.simulation_id,s.revision,s.tick,s.fact_id,s.kind,s.entity_id,s.payload,s.fact_sha256)
