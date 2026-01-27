-- Google Tokens Table for Brain SaaS
-- Stores OAuth tokens for Google Workspace integration

CREATE TABLE IF NOT EXISTS google_tokens (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) UNIQUE NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create index for faster lookups by user_id
CREATE INDEX IF NOT EXISTS idx_google_tokens_user_id ON google_tokens(user_id);

-- Comment for documentation
COMMENT ON TABLE google_tokens IS 'Stores Google OAuth tokens for Brain SaaS users';
