-- 检查 PostgreSQL 连接数和限制

-- 1. 查看最大连接数限制
SHOW max_connections;

-- 2. 查看当前连接数
SELECT count(*) as current_connections FROM pg_stat_activity;

-- 3. 查看每个数据库的连接数
SELECT datname, count(*) as connections 
FROM pg_stat_activity 
GROUP BY datname 
ORDER BY connections DESC;

-- 4. 查看每个应用的连接数
SELECT application_name, count(*) as connections 
FROM pg_stat_activity 
GROUP BY application_name 
ORDER BY connections DESC;

-- 5. 查看 theshortgod_copy 数据库的连接详情
SELECT 
    pid, 
    usename, 
    application_name, 
    client_addr, 
    state,
    state_change,
    query_start,
    wait_event_type,
    wait_event
FROM pg_stat_activity 
WHERE datname = 'theshortgod_copy'
ORDER BY state_change DESC;

-- 6. 查看空闲连接
SELECT count(*) as idle_connections 
FROM pg_stat_activity 
WHERE state = 'idle' AND datname = 'theshortgod_copy';

-- 7. 查看活跃连接
SELECT count(*) as active_connections 
FROM pg_stat_activity 
WHERE state = 'active' AND datname = 'theshortgod_copy';

-- 7. 查看占用连接
SELECT pid, usename, state, query
FROM pg_stat_activity
WHERE
    state = 'idle in transaction';