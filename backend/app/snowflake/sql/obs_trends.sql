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
ticks AS (
 SELECT r.TICK,MAX(r.REVISION) REVISION FROM AGENTCITY_OBSERVATION_REVISIONS_V1 r,p
 WHERE r.OWNER_ID=p.v:owner_id::VARCHAR AND r.SIMULATION_ID=p.v:simulation_id::VARCHAR
 AND r.REVISION<=p.v:through_revision::NUMBER
 AND r.TICK BETWEEN p.v:start_tick::NUMBER AND p.v:end_tick::NUMBER
 AND (p.v:event_id IS NULL OR EXISTS(
  SELECT 1 FROM events e WHERE e.ENTITY_ID=p.v:event_id::VARCHAR
  AND r.TICK BETWEEN COALESCE(e.PAYLOAD:start_tick::NUMBER,e.PAYLOAD:queued_tick::NUMBER)
  AND COALESCE(e.PAYLOAD:end_tick::NUMBER+30,p.v:end_tick::NUMBER)
 ))
 GROUP BY r.TICK
),
versions AS (
 SELECT f.*,LEAD(REVISION,1,9007199254740992) OVER(PARTITION BY KIND,ENTITY_ID ORDER BY REVISION) next_revision
 FROM facts f WHERE KIND IN('agent','relationship','opinion')
),
agent_latest AS (
 SELECT t.TICK,t.REVISION,f.ENTITY_ID,f.PAYLOAD FROM ticks t JOIN versions f
 ON f.REVISION<=t.REVISION AND f.next_revision>t.REVISION AND f.KIND='agent'
),
living AS (
 SELECT * FROM agent_latest
 WHERE NOT COALESCE(PAYLOAD:deleted::BOOLEAN,FALSE) AND COALESCE(PAYLOAD:active::BOOLEAN,FALSE)
 AND PAYLOAD:life::VARCHAR!='dead'
),
relationship_latest AS (
 SELECT t.TICK,t.REVISION,f.ENTITY_ID,f.PAYLOAD FROM ticks t JOIN versions f
 ON f.REVISION<=t.REVISION AND f.next_revision>t.REVISION AND f.KIND='relationship'
),
relationships AS (
 SELECT r.* FROM relationship_latest r JOIN living a ON a.TICK=r.TICK AND a.ENTITY_ID=r.PAYLOAD:from_agent_id::VARCHAR
 JOIN living b ON b.TICK=r.TICK AND b.ENTITY_ID=r.PAYLOAD:to_agent_id::VARCHAR,p
 WHERE NOT COALESCE(r.PAYLOAD:deleted::BOOLEAN,FALSE)
 AND (p.v:agent_id IS NULL OR r.PAYLOAD:from_agent_id::VARCHAR=p.v:agent_id::VARCHAR)
),
opinion_latest AS (
 SELECT t.TICK,t.REVISION,f.ENTITY_ID,f.PAYLOAD FROM ticks t JOIN versions f
 ON f.REVISION<=t.REVISION AND f.next_revision>t.REVISION AND f.KIND='opinion'
),
opinions AS (
 SELECT o.* FROM opinion_latest o JOIN living a ON a.TICK=o.TICK AND a.ENTITY_ID=o.PAYLOAD:agent_id::VARCHAR,p
 WHERE NOT COALESCE(o.PAYLOAD:deleted::BOOLEAN,FALSE)
 AND (p.v:agent_id IS NULL OR o.PAYLOAD:agent_id::VARCHAR=p.v:agent_id::VARCHAR)
),
agent_stats AS (
 SELECT t.TICK,COUNT_IF(a.PAYLOAD:life::VARCHAR='dead' AND NOT COALESCE(a.PAYLOAD:deleted::BOOLEAN,FALSE)) deaths,
 COUNT_IF(a.PAYLOAD:life::VARCHAR!='dead' AND COALESCE(a.PAYLOAD:active::BOOLEAN,FALSE)
 AND NOT COALESCE(a.PAYLOAD:deleted::BOOLEAN,FALSE)) population,
 AVG(IFF(a.PAYLOAD:life::VARCHAR!='dead' AND COALESCE(a.PAYLOAD:active::BOOLEAN,FALSE)
 AND NOT COALESCE(a.PAYLOAD:deleted::BOOLEAN,FALSE),TRY_TO_DOUBLE(GET(a.PAYLOAD,p.v:metric::VARCHAR)::VARCHAR),NULL)) agent_mean,
 COUNT(IFF(a.PAYLOAD:life::VARCHAR!='dead' AND COALESCE(a.PAYLOAD:active::BOOLEAN,FALSE)
 AND NOT COALESCE(a.PAYLOAD:deleted::BOOLEAN,FALSE),TRY_TO_DOUBLE(GET(a.PAYLOAD,p.v:metric::VARCHAR)::VARCHAR),NULL)) recorded_n
 FROM ticks t LEFT JOIN agent_latest a ON a.TICK=t.TICK,p
 WHERE p.v:agent_id IS NULL OR a.ENTITY_ID=p.v:agent_id::VARCHAR
 GROUP BY t.TICK
),
relationship_stats AS (
 SELECT t.TICK,COUNT(r.ENTITY_ID) n,COUNT(DISTINCT r.PAYLOAD:pair_id::VARCHAR) pairs,
 AVG(TRY_TO_DOUBLE(GET(r.PAYLOAD,REPLACE(p.v:metric::VARCHAR,'relationship_',''))::VARCHAR)) score
 FROM ticks t LEFT JOIN relationships r ON t.TICK=r.TICK,p GROUP BY t.TICK
),
opinion_stats AS (
 SELECT t.TICK,COUNT(o.ENTITY_ID) n,COUNT(o.PAYLOAD:confidence::FLOAT) confidence_n,
 AVG(o.PAYLOAD:confidence::FLOAT) confidence
 FROM ticks t LEFT JOIN opinions o ON t.TICK=o.TICK GROUP BY t.TICK
),
flows AS (
 SELECT t.TICK,COUNT_IF(f.PAYLOAD:entity_kind::VARCHAR='opinion' AND f.PAYLOAD:field::VARCHAR='__entity__'
 AND IS_NULL_VALUE(f.PAYLOAD:before) AND NOT IS_NULL_VALUE(f.PAYLOAD:after)) adoptions,
 COUNT_IF(f.PAYLOAD:entity_kind::VARCHAR='opinion' AND f.PAYLOAD:field::VARCHAR='__entity__'
 AND NOT IS_NULL_VALUE(f.PAYLOAD:before) AND IS_NULL_VALUE(f.PAYLOAD:after)) removals
 FROM ticks t LEFT JOIN facts f ON f.KIND='change' AND f.TICK=t.TICK AND f.REVISION<=t.REVISION,p
 WHERE p.v:agent_id IS NULL OR f.PAYLOAD:agent_id::VARCHAR=p.v:agent_id::VARCHAR
 GROUP BY t.TICK
),
city_points AS (SELECT * FROM facts WHERE KIND='city'),
points AS (
 SELECT t.TICK,t.REVISION,
 CASE
 WHEN p.v:metric::VARCHAR='population' THEN COALESCE(a.population,0)
 WHEN p.v:metric::VARCHAR='deaths' THEN COALESCE(a.deaths,0)
 WHEN p.v:metric::VARCHAR IN('cooperation_count','conflict_count') THEN TRY_TO_DOUBLE(GET(c.PAYLOAD,p.v:metric::VARCHAR)::VARCHAR)
 WHEN p.v:metric::VARCHAR='relationship_pairs' THEN r.pairs
 WHEN p.v:metric::VARCHAR LIKE 'relationship_%' THEN r.score
 WHEN p.v:metric::VARCHAR='opinion_count' THEN o.n
 WHEN p.v:metric::VARCHAR='opinion_confidence' THEN o.confidence
 WHEN p.v:metric::VARCHAR='opinion_adoptions' THEN COALESCE(f.adoptions,0)
 WHEN p.v:metric::VARCHAR='opinion_removals' THEN COALESCE(f.removals,0)
 ELSE a.agent_mean END value,
 CASE WHEN p.v:metric::VARCHAR='relationship_pairs' THEN r.pairs
 WHEN p.v:metric::VARCHAR LIKE 'relationship_%' THEN r.n
 WHEN p.v:metric::VARCHAR='opinion_confidence' THEN o.confidence_n
 WHEN p.v:metric::VARCHAR LIKE 'opinion_%' THEN o.n
 WHEN p.v:metric::VARCHAR IN('population','deaths','cooperation_count','conflict_count') THEN COALESCE(a.population,0)
 ELSE COALESCE(a.recorded_n,0) END denominator
 FROM ticks t JOIN city_points c ON c.REVISION=t.REVISION
 LEFT JOIN agent_stats a ON t.TICK=a.TICK LEFT JOIN relationship_stats r ON t.TICK=r.TICK
 LEFT JOIN opinion_stats o ON t.TICK=o.TICK LEFT JOIN flows f ON t.TICK=f.TICK,p
),
buckets AS (
 SELECT *,FLOOR((TICK-MIN(TICK) OVER())/GREATEST(1,CEIL((MAX(TICK) OVER()-MIN(TICK) OVER()+1)/500))) bucket
 FROM points
),
series AS (
 SELECT OBJECT_CONSTRUCT_KEEP_NULL('tick',MAX(TICK),'revision',MAX(REVISION),
 'mean',AVG(value),'min',MIN(value),'max',MAX(value),'sample_count',COUNT(*),
 'denominator',MAX(denominator)) value,MAX(TICK) tick FROM buckets GROUP BY bucket
),
pair_labels AS (
 SELECT r.PAYLOAD:pair_id::VARCHAR pair_id,
 LISTAGG(DISTINCT r.PAYLOAD:kind::VARCHAR,' / ') WITHIN GROUP(ORDER BY r.PAYLOAD:kind::VARCHAR) label
 FROM relationships r WHERE r.TICK=(SELECT MAX(TICK) FROM ticks) GROUP BY r.PAYLOAD:pair_id::VARCHAR
),
distribution AS (
 SELECT label,COUNT(*) n FROM pair_labels,p WHERE p.v:metric::VARCHAR LIKE 'relationship_%' GROUP BY label
 UNION ALL
 SELECT o.PAYLOAD:category::VARCHAR label,COUNT(*) n FROM opinions o,p
 WHERE o.TICK=(SELECT MAX(TICK) FROM ticks) AND p.v:metric::VARCHAR LIKE 'opinion_%' GROUP BY label
)
SELECT TO_JSON(OBJECT_CONSTRUCT(
 'items',(SELECT COALESCE(ARRAY_AGG(value) WITHIN GROUP(ORDER BY tick),ARRAY_CONSTRUCT()) FROM series),
 'events',(SELECT COALESCE(ARRAY_AGG(OBJECT_CONSTRUCT_KEEP_NULL('event_id',e.PAYLOAD:event_id,'title',e.PAYLOAD:title,
'status',e.PAYLOAD:status,'start_tick',e.PAYLOAD:start_tick,'end_tick',e.PAYLOAD:end_tick)) WITHIN GROUP(ORDER BY e.ENTITY_ID),ARRAY_CONSTRUCT()) FROM events e,p
 WHERE COALESCE(e.PAYLOAD:start_tick::NUMBER,e.PAYLOAD:queued_tick::NUMBER)<=p.v:end_tick::NUMBER
 AND COALESCE(e.PAYLOAD:end_tick::NUMBER,9007199254740991)>=p.v:start_tick::NUMBER),
 'distribution',(SELECT COALESCE(ARRAY_AGG(OBJECT_CONSTRUCT('label',label,'count',n)) WITHIN GROUP(ORDER BY label),ARRAY_CONSTRUCT()) FROM distribution)
))
