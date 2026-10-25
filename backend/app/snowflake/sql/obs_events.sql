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
),
selected AS (
 SELECT e.*,ROW_NUMBER() OVER(ORDER BY COALESCE(e.PAYLOAD:start_tick::NUMBER,e.PAYLOAD:queued_tick::NUMBER),e.ENTITY_ID) rn FROM events e,p
 WHERE COALESCE(e.PAYLOAD:end_tick::NUMBER,9007199254740991)>=p.v:start_tick::NUMBER
 AND COALESCE(e.PAYLOAD:start_tick::NUMBER,e.PAYLOAD:queued_tick::NUMBER,0)<=p.v:end_tick::NUMBER
 AND (p.v:event_id IS NULL OR e.ENTITY_ID=p.v:event_id::VARCHAR)
)
SELECT TO_JSON(OBJECT_CONSTRUCT_KEEP_NULL('event_id',e.PAYLOAD:event_id,'title',e.PAYLOAD:title,
'status',e.PAYLOAD:status,'start_tick',e.PAYLOAD:start_tick,'end_tick',e.PAYLOAD:end_tick)) FROM selected e,p
WHERE e.rn>p.v:offset::NUMBER AND e.rn<=p.v:offset::NUMBER+p.v:limit::NUMBER ORDER BY e.rn
