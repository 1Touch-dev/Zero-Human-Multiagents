CREATE TABLE IF NOT EXISTS company_integrations (
    company_id UUID PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    github_token TEXT NOT NULL
);

-- Seed the initial prototype token for the default company so the pipeline doesn't break instantly
INSERT INTO company_integrations (company_id, github_token) 
VALUES ('00000000-0000-0000-0000-000000000001', '<YOUR_GITHUB_PAT>') 
ON CONFLICT (company_id) DO UPDATE SET github_token = EXCLUDED.github_token;
