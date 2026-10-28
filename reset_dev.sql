-- ============================================================================
-- WARNING: DESTRUCTIVE SCRIPT FOR DEVELOPMENT RESET ONLY
-- DO NOT RUN IN PRODUCTION. RUNNING THIS WILL PERMANENTLY ERASE ALL SPMS DATA.
-- ============================================================================

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS forum_replies;
DROP TABLE IF EXISTS forum_threads;
DROP TABLE IF EXISTS assessments;
DROP TABLE IF EXISTS feedback;
DROP TABLE IF EXISTS submissions;
DROP TABLE IF EXISTS topic_requests;
DROP TABLE IF EXISTS topic_assignments;
DROP TABLE IF EXISTS deadlines;
DROP TABLE IF EXISTS topics;
DROP TABLE IF EXISTS guidelines;
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS supervisors;
DROP TABLE IF EXISTS academic_sessions;
DROP TABLE IF EXISTS departments;
DROP TABLE IF EXISTS users;

SET FOREIGN_KEY_CHECKS = 1;
