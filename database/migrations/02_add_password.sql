-- Add password support for email/password signup
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);
