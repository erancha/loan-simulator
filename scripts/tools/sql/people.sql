-- One row per person the agent holds records of, most recently active first: the Google account
-- ID the records are keyed by, the number of checks and the time of the latest record. The agent
-- keeps no email address, so a person is found by when they were active.
-- sql-helper.sh --people runs this file.
SELECT user_id AS account_id,
       count(*) FILTER (WHERE kind = 'check') AS checks,
       max(at) AS last_activity
FROM (
  SELECT user_id, 'check' AS kind, created_at AS at FROM checks
  UNION ALL
  SELECT user_id, 'event', created_at FROM check_events
) records
GROUP BY user_id
ORDER BY last_activity DESC;
