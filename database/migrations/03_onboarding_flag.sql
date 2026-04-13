ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE;

-- Backfill: mark existing users who already have availability blocks as onboarded
UPDATE users SET onboarding_completed = TRUE
WHERE id IN (SELECT DISTINCT user_id FROM availability_blocks);
