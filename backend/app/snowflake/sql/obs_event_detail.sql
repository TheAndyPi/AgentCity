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
target AS (SELECT e.* FROM events e,p WHERE e.ENTITY_ID=p.v:event_id::VARCHAR),
resolved AS (
 SELECT MIN(f.REVISION) revision FROM facts f,target e
 WHERE f.KIND='event' AND f.ENTITY_ID=e.ENTITY_ID AND f.PAYLOAD:end_tick::NUMBER IS NOT NULL
),
phases AS (
 SELECT 'baseline' phase,e.PAYLOAD:start_tick::NUMBER tick,
 COALESCE(e.PAYLOAD:baseline_available::BOOLEAN,FALSE) available,e.PAYLOAD:cohort cohort,
 NULL::NUMBER revision FROM target e
 UNION ALL
 SELECT 'resolution',e.PAYLOAD:end_tick::NUMBER,e.PAYLOAD:end_tick::NUMBER IS NOT NULL,e.PAYLOAD:cohort,r.revision
 FROM target e,resolved r
 UNION ALL
 SELECT 'followup',IFF(e.PAYLOAD:end_tick::NUMBER IS NULL,NULL,
 LEAST(e.PAYLOAD:end_tick::NUMBER+30,(SELECT MAX(TICK) FROM facts))),
 e.PAYLOAD:end_tick::NUMBER IS NOT NULL,e.PAYLOAD:cohort,
 (SELECT MAX(f.REVISION) FROM facts f WHERE f.TICK<=e.PAYLOAD:end_tick::NUMBER+30)
 FROM target e
),
baseline_agents AS (
 SELECT 'baseline' phase,a.value payload FROM target e,LATERAL FLATTEN(input=>e.PAYLOAD:baseline:agents) a
),
later_agents AS (
 SELECT ph.phase,f.PAYLOAD payload FROM phases ph JOIN facts f ON f.REVISION<=ph.revision AND f.KIND='agent'
 WHERE ph.phase!='baseline'
 QUALIFY ROW_NUMBER() OVER(PARTITION BY ph.phase,f.ENTITY_ID ORDER BY f.REVISION DESC,f.FACT_ID)=1
),
agents AS (SELECT * FROM baseline_agents UNION ALL SELECT * FROM later_agents),
samples AS (
 SELECT a.phase,a.payload,ARRAY_CONTAINS(a.payload:agent_id,ph.cohort) in_cohort,
 COALESCE(a.payload:active::BOOLEAN,FALSE) AND a.payload:life::VARCHAR!='dead'
 AND NOT COALESCE(a.payload:deleted::BOOLEAN,FALSE) living
 FROM agents a JOIN phases ph ON ph.phase=a.phase
),
snapshots AS (
 SELECT ph.phase,OBJECT_CONSTRUCT_KEEP_NULL('tick',ph.tick,'city',OBJECT_CONSTRUCT_KEEP_NULL('happiness',AVG(IFF(s.living,TRY_TO_DOUBLE(s.payload:happiness::VARCHAR),NULL)),
'safety',AVG(IFF(s.living,TRY_TO_DOUBLE(s.payload:safety::VARCHAR),NULL)),
'trust',AVG(IFF(s.living,TRY_TO_DOUBLE(s.payload:trust::VARCHAR),NULL)),
'resources',AVG(IFF(s.living,TRY_TO_DOUBLE(s.payload:resources::VARCHAR),NULL)),
'stress',AVG(IFF(s.living,TRY_TO_DOUBLE(s.payload:stress::VARCHAR),NULL)),
'health',AVG(IFF(s.living,TRY_TO_DOUBLE(s.payload:health::VARCHAR),NULL)),
'hunger',AVG(IFF(s.living,TRY_TO_DOUBLE(s.payload:hunger::VARCHAR),NULL)),
'fatigue',AVG(IFF(s.living,TRY_TO_DOUBLE(s.payload:fatigue::VARCHAR),NULL)),
'social_need',AVG(IFF(s.living,TRY_TO_DOUBLE(s.payload:social_need::VARCHAR),NULL)),
'mental',AVG(IFF(s.living,TRY_TO_DOUBLE(s.payload:mental::VARCHAR),NULL)),
'institutional_trust',AVG(IFF(s.living,TRY_TO_DOUBLE(s.payload:institutional_trust::VARCHAR),NULL)),
'population',IFF(MAX(IFF(ph.available,1,0))=1,COALESCE(COUNT_IF(s.living),0),NULL),
'deaths',IFF(MAX(IFF(ph.available,1,0))=1,COALESCE(COUNT_IF(s.payload:life::VARCHAR='dead'),0),NULL)
),'cohort',OBJECT_CONSTRUCT_KEEP_NULL('happiness',AVG(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:happiness::VARCHAR),NULL)),
'safety',AVG(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:safety::VARCHAR),NULL)),
'trust',AVG(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:trust::VARCHAR),NULL)),
'resources',AVG(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:resources::VARCHAR),NULL)),
'stress',AVG(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:stress::VARCHAR),NULL)),
'health',AVG(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:health::VARCHAR),NULL)),
'hunger',AVG(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:hunger::VARCHAR),NULL)),
'fatigue',AVG(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:fatigue::VARCHAR),NULL)),
'social_need',AVG(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:social_need::VARCHAR),NULL)),
'mental',AVG(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:mental::VARCHAR),NULL)),
'institutional_trust',AVG(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:institutional_trust::VARCHAR),NULL)),
'population',IFF(MAX(IFF(ph.available,1,0))=1,COALESCE(COUNT_IF(s.in_cohort AND s.living),0),NULL),
'deaths',IFF(MAX(IFF(ph.available,1,0))=1,COALESCE(COUNT_IF(s.in_cohort AND s.payload:life::VARCHAR='dead'),0),NULL)
,'initial_population',ARRAY_SIZE(ANY_VALUE(ph.cohort))),
'denominators',OBJECT_CONSTRUCT('city',OBJECT_CONSTRUCT('happiness',COUNT(IFF(s.living,TRY_TO_DOUBLE(s.payload:happiness::VARCHAR),NULL)),
'safety',COUNT(IFF(s.living,TRY_TO_DOUBLE(s.payload:safety::VARCHAR),NULL)),
'trust',COUNT(IFF(s.living,TRY_TO_DOUBLE(s.payload:trust::VARCHAR),NULL)),
'resources',COUNT(IFF(s.living,TRY_TO_DOUBLE(s.payload:resources::VARCHAR),NULL)),
'stress',COUNT(IFF(s.living,TRY_TO_DOUBLE(s.payload:stress::VARCHAR),NULL)),
'health',COUNT(IFF(s.living,TRY_TO_DOUBLE(s.payload:health::VARCHAR),NULL)),
'hunger',COUNT(IFF(s.living,TRY_TO_DOUBLE(s.payload:hunger::VARCHAR),NULL)),
'fatigue',COUNT(IFF(s.living,TRY_TO_DOUBLE(s.payload:fatigue::VARCHAR),NULL)),
'social_need',COUNT(IFF(s.living,TRY_TO_DOUBLE(s.payload:social_need::VARCHAR),NULL)),
'mental',COUNT(IFF(s.living,TRY_TO_DOUBLE(s.payload:mental::VARCHAR),NULL)),
'institutional_trust',COUNT(IFF(s.living,TRY_TO_DOUBLE(s.payload:institutional_trust::VARCHAR),NULL)),'population',COALESCE(COUNT_IF(s.living),0),'deaths',COUNT(IFF(NOT COALESCE(s.payload:deleted::BOOLEAN,FALSE),s.payload:agent_id,NULL))),'cohort',OBJECT_CONSTRUCT('happiness',COUNT(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:happiness::VARCHAR),NULL)),
'safety',COUNT(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:safety::VARCHAR),NULL)),
'trust',COUNT(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:trust::VARCHAR),NULL)),
'resources',COUNT(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:resources::VARCHAR),NULL)),
'stress',COUNT(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:stress::VARCHAR),NULL)),
'health',COUNT(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:health::VARCHAR),NULL)),
'hunger',COUNT(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:hunger::VARCHAR),NULL)),
'fatigue',COUNT(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:fatigue::VARCHAR),NULL)),
'social_need',COUNT(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:social_need::VARCHAR),NULL)),
'mental',COUNT(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:mental::VARCHAR),NULL)),
'institutional_trust',COUNT(IFF(s.in_cohort AND s.living,TRY_TO_DOUBLE(s.payload:institutional_trust::VARCHAR),NULL)),'population',COALESCE(COUNT_IF(s.in_cohort AND s.living),0),'deaths',COUNT(IFF(s.in_cohort AND NOT COALESCE(s.payload:deleted::BOOLEAN,FALSE),s.payload:agent_id,NULL))))) value,
 ph.revision FROM phases ph LEFT JOIN samples s ON s.phase=ph.phase
 GROUP BY ph.phase,ph.tick,ph.revision
),
event_changes AS (
 SELECT f.* FROM facts f,target e
 WHERE f.KIND='change' AND (ARRAY_CONTAINS(e.PAYLOAD:event_id,f.PAYLOAD:event_ids)
 OR ARRAY_CONTAINS(e.PAYLOAD:event_id,f.PAYLOAD:active_event_ids)
 OR f.TICK BETWEEN e.PAYLOAD:start_tick::NUMBER AND COALESCE(e.PAYLOAD:end_tick::NUMBER+30,9007199254740991))
),
direct_changes AS (
 SELECT * FROM event_changes f
 QUALIFY ROW_NUMBER() OVER(ORDER BY f.REVISION,f.FACT_ID)<=100
),
numeric_facts AS (
 SELECT k.value::VARCHAR metric,
 GET(r.value:city,k.value::VARCHAR)::FLOAT-GET(b.value:city,k.value::VARCHAR)::FLOAT delta,r.revision
 FROM snapshots b JOIN snapshots r ON b.phase='baseline' AND r.phase='resolution',
 LATERAL FLATTEN(input=>PARSE_JSON('["health","trust","mental","happiness","stress","population","deaths"]')) k
)
SELECT TO_JSON(OBJECT_CONSTRUCT_KEEP_NULL(
 'event',(SELECT OBJECT_CONSTRUCT_KEEP_NULL('event_id',e.PAYLOAD:event_id,'title',e.PAYLOAD:title,
'status',e.PAYLOAD:status,'start_tick',e.PAYLOAD:start_tick,'end_tick',e.PAYLOAD:end_tick) FROM target e),
 'baseline',(SELECT value FROM snapshots WHERE phase='baseline'),
 'resolution',(SELECT value FROM snapshots WHERE phase='resolution'),
 'followup',(SELECT value FROM snapshots WHERE phase='followup'),
 'followup_complete',COALESCE((SELECT MAX(f.TICK)>=e.PAYLOAD:end_tick::NUMBER+30 FROM facts f,target e GROUP BY e.PAYLOAD:end_tick),FALSE),
 'overlaps',(SELECT COALESCE(ARRAY_AGG(OBJECT_CONSTRUCT_KEEP_NULL('event_id',e.PAYLOAD:event_id,'title',e.PAYLOAD:title,
'status',e.PAYLOAD:status,'start_tick',e.PAYLOAD:start_tick,'end_tick',e.PAYLOAD:end_tick)) WITHIN GROUP(ORDER BY e.ENTITY_ID),ARRAY_CONSTRUCT()) FROM events e,target t
 WHERE e.ENTITY_ID!=t.ENTITY_ID AND COALESCE(e.PAYLOAD:start_tick::NUMBER,e.PAYLOAD:queued_tick::NUMBER)<=COALESCE(t.PAYLOAD:end_tick::NUMBER,9007199254740991)
 AND COALESCE(e.PAYLOAD:end_tick::NUMBER,9007199254740991)>=t.PAYLOAD:start_tick::NUMBER),
 'changes',(SELECT COALESCE(ARRAY_AGG(OBJECT_CONSTRUCT_KEEP_NULL('id',f.FACT_ID,'tick',f.TICK,'revision',f.REVISION,
'entity_kind',f.PAYLOAD:entity_kind,'entity_id',f.PAYLOAD:entity_id,'agent_id',f.PAYLOAD:agent_id,
'field',f.PAYLOAD:field,'before',f.PAYLOAD:before,'after',f.PAYLOAD:after,
'link',IFF(ARRAY_CONTAINS((SELECT PAYLOAD:event_id FROM target),f.PAYLOAD:event_ids),'explicit','temporal'),
'event_ids',f.PAYLOAD:event_ids,
'evidence',OBJECT_CONSTRUCT('records',COALESCE(f.PAYLOAD:evidence,ARRAY_CONSTRUCT()),
'decision_ids',COALESCE(f.PAYLOAD:decision_ids,ARRAY_CONSTRUCT()),
'active_event_ids',COALESCE(f.PAYLOAD:active_event_ids,ARRAY_CONSTRUCT())))) WITHIN GROUP(ORDER BY f.REVISION,f.FACT_ID),ARRAY_CONSTRUCT()) FROM direct_changes f),
 'citations',ARRAY_CONSTRUCT(),
 'change_counts',(SELECT OBJECT_CONSTRUCT('explicit',COALESCE(COUNT_IF(ARRAY_CONTAINS(e.PAYLOAD:event_id,f.PAYLOAD:event_ids)),0),
 'temporal',COALESCE(COUNT_IF(NOT ARRAY_CONTAINS(e.PAYLOAD:event_id,f.PAYLOAD:event_ids)),0)) FROM event_changes f,target e),
 'numeric_observations',(SELECT COALESCE(ARRAY_AGG(OBJECT_CONSTRUCT_KEEP_NULL(
 'metric',metric,'delta',delta,'revision',revision)),ARRAY_CONSTRUCT()) FROM numeric_facts)
))
