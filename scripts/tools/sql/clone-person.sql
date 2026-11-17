-- Copies every check of one person to another, so the second account sees the first one's checks
-- as its own: the checks with their options, awaiting offers, recommendations, event logs and
-- LangGraph checkpoints. -v from=<account id> -v to=<account id>. The copies get new check,
-- option and awaiting-offer ids, written in place of the old ones wherever a record names them,
-- checkpoint blobs included (an id is a 36-character uuid, so its bytes are swapped one for one).
-- The kept times of deleted checks stay with their owner. It stops, copying nothing, when the
-- source has no checks or the target has any record, so a reset of the target is a deliberate
-- separate step. One transaction, so a failure copies nothing. sql-helper.sh --clone runs this.
BEGIN;
SELECT set_config('clone.from', :'from', true), set_config('clone.to', :'to', true);

DO $$
BEGIN
  IF current_setting('clone.from') = current_setting('clone.to') THEN
    RAISE EXCEPTION 'the source and the target are the same account';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM checks WHERE user_id = current_setting('clone.from')) THEN
    RAISE EXCEPTION 'account % has no checks to copy', current_setting('clone.from');
  END IF;
  IF EXISTS (SELECT 1 FROM checks WHERE user_id = current_setting('clone.to'))
     OR EXISTS (SELECT 1 FROM check_events WHERE user_id = current_setting('clone.to'))
     OR EXISTS (SELECT 1 FROM deleted_event_times WHERE user_id = current_setting('clone.to'))
  THEN
    RAISE EXCEPTION 'account % has records; reset it first (--reset) or choose another target',
      current_setting('clone.to');
  END IF;
END $$;

CREATE TEMP TABLE source_checks ON COMMIT DROP AS
  SELECT id FROM checks WHERE user_id = current_setting('clone.from');

-- Key: an id of the source's records; value: the id its copy takes.
CREATE TEMP TABLE id_map ON COMMIT DROP AS
  SELECT id AS old_id, gen_random_uuid()::text AS new_id FROM source_checks
  UNION ALL
  SELECT id, gen_random_uuid()::text FROM options
    WHERE check_id IN (SELECT id FROM source_checks)
  UNION ALL
  SELECT id, gen_random_uuid()::text FROM awaiting_offers
    WHERE check_id IN (SELECT id FROM source_checks);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM id_map WHERE length(old_id) <> 36) THEN
    RAISE EXCEPTION 'an id is not a 36-character uuid, so checkpoint blobs cannot be rewritten';
  END IF;
END $$;

CREATE FUNCTION pg_temp.remap(value text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE
  pair record;
BEGIN
  FOR pair IN SELECT old_id, new_id FROM id_map LOOP
    value := replace(value, pair.old_id, pair.new_id);
  END LOOP;
  RETURN value;
END $$;

CREATE FUNCTION pg_temp.remap_blob(value bytea) RETURNS bytea LANGUAGE plpgsql AS $$
DECLARE
  pair record;
  hex text := encode(value, 'hex');
BEGIN
  FOR pair IN SELECT old_id, new_id FROM id_map LOOP
    hex := replace(hex, encode(convert_to(pair.old_id, 'UTF8'), 'hex'),
                   encode(convert_to(pair.new_id, 'UTF8'), 'hex'));
  END LOOP;
  RETURN decode(hex, 'hex');
END $$;

CREATE FUNCTION pg_temp.new_id(old text) RETURNS text LANGUAGE sql AS $$
  SELECT new_id FROM id_map WHERE old_id = old
$$;

INSERT INTO checks (id, user_id, created_at, archived_at, loan, term_months, payment_ceiling,
                    ceiling_source, finances)
SELECT pg_temp.new_id(id), current_setting('clone.to'), created_at, archived_at, loan,
       term_months, payment_ceiling, ceiling_source, finances
FROM checks WHERE id IN (SELECT id FROM source_checks);

INSERT INTO options (id, check_id, loan, source, lender, offer_date, figures, created_at,
                     max_term_months)
SELECT pg_temp.new_id(id), pg_temp.new_id(check_id), loan, source, lender, offer_date,
       figures, created_at, max_term_months
FROM options WHERE check_id IN (SELECT id FROM source_checks);

INSERT INTO awaiting_offers (check_id, id, lender, data, created_at)
SELECT pg_temp.new_id(check_id), pg_temp.new_id(id), lender,
       pg_temp.remap(data::text)::jsonb, created_at
FROM awaiting_offers WHERE check_id IN (SELECT id FROM source_checks);

INSERT INTO recommendations (check_id, data, created_at)
SELECT pg_temp.new_id(check_id), pg_temp.remap(data::text)::jsonb, created_at
FROM recommendations WHERE check_id IN (SELECT id FROM source_checks);

INSERT INTO check_events (check_id, seq, type, data, user_id, created_at, copied)
SELECT pg_temp.new_id(check_id), seq, type, pg_temp.remap(data::text)::jsonb,
       current_setting('clone.to'), created_at, copied
FROM check_events WHERE check_id IN (SELECT id FROM source_checks);

INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type,
                         checkpoint, metadata)
SELECT pg_temp.new_id(thread_id), checkpoint_ns, checkpoint_id, parent_checkpoint_id, type,
       pg_temp.remap(checkpoint::text)::jsonb, pg_temp.remap(metadata::text)::jsonb
FROM checkpoints WHERE thread_id IN (SELECT id FROM source_checks);

INSERT INTO checkpoint_blobs (thread_id, checkpoint_ns, channel, version, type, blob)
SELECT pg_temp.new_id(thread_id), checkpoint_ns, channel, version, type,
       pg_temp.remap_blob(blob)
FROM checkpoint_blobs WHERE thread_id IN (SELECT id FROM source_checks);

INSERT INTO checkpoint_writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel,
                               type, blob, task_path)
SELECT pg_temp.new_id(thread_id), checkpoint_ns, checkpoint_id, task_id, idx, channel, type,
       pg_temp.remap_blob(blob), task_path
FROM checkpoint_writes WHERE thread_id IN (SELECT id FROM source_checks);

SELECT count(*) AS checks_copied FROM source_checks;
COMMIT;
