-- Re-apply grants to tables created by the init scripts
-- The grants in 01-init-db.sql only applied to existing tables at that time.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO role_web_data;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO role_web_data;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO role_ai_reader;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO role_ai_reader;
