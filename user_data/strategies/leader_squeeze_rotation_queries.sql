-- PostgreSQL: one append-only table, leader_rotation_events.
-- Each SELECT is independent. Adjust time limits / pair / rotation_token as needed.

-- 1. Recent rotation decisions and lifecycle events (display time in Beijing).
SELECT id, occurred_at AT TIME ZONE 'Asia/Shanghai' AS beijing_time,
       event_type, channel, weak_pair, target_pair,
       weak_score, target_raw_score, target_entry_score, score_gap,
       reason, rotation_token
FROM leader_rotation_events
ORDER BY occurred_at DESC, id DESC
LIMIT 100;

-- 2. Replay one confirmed rotation. Replace the token literal with a real token.
SELECT occurred_at, event_type, reason, snapshot -> 'decision' AS decision,
       snapshot -> 'rotation' AS rotation,
       snapshot -> 'holdings' AS holdings,
       snapshot -> 'positions' AS exchange_positions
FROM leader_rotation_events
WHERE rotation_token = 'REPLACE_WITH_ROTATION_TOKEN'
ORDER BY occurred_at, id;

-- 3. Failed gates, including no-rotation decisions, in the last 24 hours.
SELECT e.occurred_at, c ->> 'channel' AS channel,
       c ->> 'weak' AS weak_pair, c ->> 'target' AS target_pair,
       c ->> 'stage' AS stage, c AS actual_check
FROM leader_rotation_events AS e
CROSS JOIN LATERAL jsonb_array_elements(
    COALESCE(e.snapshot #> '{decision,checks}', '[]'::jsonb)
) AS c
WHERE e.event_type = 'evaluation'
  AND e.occurred_at >= now() - interval '24 hours'
  AND c ->> 'passed' = 'false'
ORDER BY e.occurred_at DESC, e.id DESC;

-- 4. Configuration and input metrics used for a specific pair.
-- Change the pair literal in both places below.
SELECT occurred_at, event_type, reason,
       snapshot #> '{pairs,BTC/USDT:USDT}' AS pair_snapshot,
       snapshot -> 'configuration' AS effective_configuration
FROM leader_rotation_events
WHERE snapshot -> 'pairs' ? 'BTC/USDT:USDT'
ORDER BY occurred_at DESC
LIMIT 100;

-- 5. Confirmed rotations: completion / exceptions / elapsed execution time.
SELECT rotation_token, min(weak_pair) AS weak_pair, min(target_pair) AS target_pair,
       min(channel) AS channel,
       min(occurred_at) FILTER (WHERE event_type = 'plan_created') AS planned_at,
       min(occurred_at) FILTER (WHERE event_type = 'entry_approved') AS authorized_at,
       min(occurred_at) FILTER (WHERE event_type = 'completed') AS completed_at,
       bool_or(event_type = 'review_required') AS needs_review,
       bool_or(event_type = 'cancelled') AS cancelled
FROM leader_rotation_events
WHERE rotation_token IS NOT NULL
GROUP BY rotation_token
ORDER BY min(occurred_at) DESC;

-- 6. Compare parameter versions without keeping a second configuration table.
SELECT md5((snapshot -> 'configuration')::text) AS configuration_id,
       min(occurred_at) AS first_seen, max(occurred_at) AS last_seen,
       count(*) FILTER (WHERE event_type = 'plan_created') AS planned,
       count(*) FILTER (WHERE event_type = 'completed') AS completed,
       count(*) FILTER (WHERE event_type = 'review_required') AS exceptions
FROM leader_rotation_events
GROUP BY md5((snapshot -> 'configuration')::text)
ORDER BY max(occurred_at) DESC;

-- 7. A completed rotation can be linked to the actual old Trade for realized PnL.
-- External holdings have no old Trade ID; they intentionally remain NULL.
SELECT e.occurred_at, e.rotation_token, e.weak_pair, e.target_pair,
       t.id AS old_trade_id, t.open_date, t.close_date, t.close_profit_abs,
       t.exit_reason, e.snapshot -> 'holdings' AS target_trade_snapshot
FROM leader_rotation_events e
LEFT JOIN trades t ON t.id = (e.snapshot #>> '{rotation,weak_trade_id}')::integer
WHERE e.event_type = 'completed'
ORDER BY e.occurred_at DESC;

-- 8. Inspect multi-timeframe contexts stored for one pair.
-- Replace all occurrences of the pair literal below as needed.
SELECT occurred_at, event_type, reason,
       snapshot #> '{pairs,BTC/USDT:USDT,multi_timeframe,holding}' AS holding,
       snapshot #> '{pairs,BTC/USDT:USDT,multi_timeframe,background}' AS background,
       snapshot #> '{pairs,BTC/USDT:USDT,multi_timeframe,entry}' AS entry,
       snapshot #> '{pairs,BTC/USDT:USDT,multi_timeframe,rotation}' AS rotation,
       snapshot #> '{pairs,BTC/USDT:USDT,multi_timeframe,emergency}' AS emergency,
       snapshot #> '{pairs,BTC/USDT:USDT,multi_timeframe,exit_reason}' AS exit_reason
FROM leader_rotation_events
WHERE snapshot -> 'pairs' ? 'BTC/USDT:USDT'
ORDER BY occurred_at DESC, id DESC
LIMIT 100;
