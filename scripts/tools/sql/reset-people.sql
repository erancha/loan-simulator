-- Deletes every record of one person, or of everyone, so their next sign-in is a first visit:
-- their checks with the options, awaiting offers, recommendations, event logs and LangGraph
-- checkpoints under them, and the kept times of deleted checks, which the message limit counts.
-- -v person=<account id> names the person; -v person='*' means everyone. One transaction, so a
-- failure deletes nothing. sql-helper.sh --reset and --reset-all run this file.
BEGIN;
CREATE TEMP TABLE gone ON COMMIT DROP AS
  SELECT id FROM checks WHERE :'person' IN ('*', user_id);
DELETE FROM recommendations WHERE check_id IN (SELECT id FROM gone);
DELETE FROM awaiting_offers WHERE check_id IN (SELECT id FROM gone);
DELETE FROM options WHERE check_id IN (SELECT id FROM gone);
DELETE FROM check_events WHERE check_id IN (SELECT id FROM gone);
DELETE FROM checkpoint_writes WHERE thread_id IN (SELECT id FROM gone);
DELETE FROM checkpoint_blobs WHERE thread_id IN (SELECT id FROM gone);
DELETE FROM checkpoints WHERE thread_id IN (SELECT id FROM gone);
DELETE FROM checks WHERE id IN (SELECT id FROM gone);
DELETE FROM deleted_event_times WHERE :'person' IN ('*', user_id);
COMMIT;
