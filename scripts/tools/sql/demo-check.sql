-- One check's stored events in seq order, as the recording demo.html replays: {"events": [...]}
-- with each event's seq, type and data, the frames the page's event stream carries. The owner's
-- account ID stays out. No row when the check has no events. sql-helper.sh --demo-check runs it.
SELECT json_build_object(
         'events',
         json_agg(json_build_object('seq', seq, 'type', type, 'data', data) ORDER BY seq))
FROM check_events
WHERE check_id = :'check'
HAVING count(*) > 0;
