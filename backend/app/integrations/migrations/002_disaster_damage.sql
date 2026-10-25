-- Additive v2 projection. Never edit the checksum-pinned v1 migration.
ALTER TABLE tiger_records DROP CONSTRAINT tiger_records_kind_check;
ALTER TABLE tiger_records ADD CONSTRAINT tiger_records_kind_check CHECK
  (kind IN ('metric','decision','event','movement','disaster_event','damage','condition','terrain','repair','reaction','service'));
CREATE VIEW tiger_disaster_damage_v2 AS
SELECT simulation_id, entity_key AS damage_id, revision, tick,
       payload->>'event_id' AS event_id, payload->>'entity_id' AS entity_id,
       payload->>'units' AS units, (payload->>'before')::double precision AS before_value,
       (payload->>'after')::double precision AS after_value, payload
FROM tiger_records WHERE kind='damage';
