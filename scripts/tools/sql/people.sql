-- One row per person the agent holds records of, most recently active first: the Google account
-- ID the records are keyed by, whether a profile exists, the number of checks and the time of the
-- latest record. The agent keeps no email address, so a person is found by when they were active.
-- sql-helper.sh --people runs this file.
SELECT user_id AS account_id,
       bool_or(kind = 'profile') AS has_profile,
       count(*) FILTER (WHERE kind = 'check') AS checks,
       max(at) AS last_activity
FROM (
  SELECT user_id, 'profile' AS kind, updated_at AS at FROM profiles
  UNION ALL
  SELECT user_id, 'check', created_at FROM checks
  UNION ALL
  SELECT user_id, 'event', created_at FROM check_events
) records
GROUP BY user_id
ORDER BY last_activity DESC;
