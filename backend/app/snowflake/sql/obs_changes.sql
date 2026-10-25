WITH p AS (SELECT PARSE_JSON(?) v),
facts AS (
 SELECT f.* FROM AGENTCITY_OBSERVATIONS_V1 f,p
 WHERE f.OWNER_ID=p.v:owner_id::VARCHAR AND f.SIMULATION_ID=p.v:simulation_id::VARCHAR
 AND f.REVISION<=p.v:through_revision::NUMBER
),
event_latest AS (
 SELECT * FROM facts WHERE KIND='event'
 QUALIFY ROW_NUMBER() OVER(PARTITION BY ENTITY_ID ORDER BY REVISION DESC,FACT_ID)=1
),
events AS (
 SELECT ENTITY_ID,PAYLOAD,REVISION,TICK FROM event_latest WHERE NOT COALESCE(PAYLOAD:deleted::BOOLEAN,FALSE)
)
SELECT TO_JSON(OBJECT_CONSTRUCT_KEEP_NULL('id',f.FACT_ID,'tick',f.TICK,'revision',f.REVISION,
'entity_kind',f.PAYLOAD:entity_kind,'entity_id',f.PAYLOAD:entity_id,'agent_id',f.PAYLOAD:agent_id,
'field',f.PAYLOAD:field,'before',f.PAYLOAD:before,'after',f.PAYLOAD:after,
'link',IFF(p.v:event_id IS NOT NULL AND NOT ARRAY_CONTAINS(p.v:event_id::VARIANT,f.PAYLOAD:event_ids),
'temporal',f.PAYLOAD:link),'event_ids',f.PAYLOAD:event_ids,
'evidence',OBJECT_CONSTRUCT('records',COALESCE(f.PAYLOAD:evidence,ARRAY_CONSTRUCT()),
'decision_ids',COALESCE(f.PAYLOAD:decision_ids,ARRAY_CONSTRUCT()),
'active_event_ids',COALESCE(f.PAYLOAD:active_event_ids,ARRAY_CONSTRUCT())))) FROM facts f,p
 WHERE f.KIND='change' AND f.TICK BETWEEN p.v:start_tick::NUMBER AND p.v:end_tick::NUMBER
 AND (p.v:agent_id IS NULL OR f.PAYLOAD:agent_id::VARCHAR=p.v:agent_id::VARCHAR)
 AND (p.v:event_id IS NULL OR ARRAY_CONTAINS(p.v:event_id::VARIANT,f.PAYLOAD:event_ids)
 OR ARRAY_CONTAINS(p.v:event_id::VARIANT,f.PAYLOAD:active_event_ids)
 OR EXISTS(SELECT 1 FROM events e WHERE e.ENTITY_ID=p.v:event_id::VARCHAR
 AND f.TICK BETWEEN e.PAYLOAD:start_tick::NUMBER AND COALESCE(e.PAYLOAD:end_tick::NUMBER+30,p.v:end_tick::NUMBER)))
 AND (p.v:entity_kind IS NULL OR f.PAYLOAD:entity_kind::VARCHAR=p.v:entity_kind::VARCHAR)
 QUALIFY ROW_NUMBER() OVER(ORDER BY f.REVISION,f.FACT_ID)>p.v:offset::NUMBER
 AND ROW_NUMBER() OVER(ORDER BY f.REVISION,f.FACT_ID)<=p.v:offset::NUMBER+p.v:limit::NUMBER
 ORDER BY f.REVISION,f.FACT_ID
