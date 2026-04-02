INSERT INTO issues (id, company_id, project_id, identifier, title, description, status, assignee_agent_id, created_at, updated_at) 
SELECT 
    gen_random_uuid(), 
    company_id, 
    project_id, 
    'PAP-101', 
    'End-to-End Contact Form Deployment', 
    'Clone https://github.com/Abhishek-AMK/zero-human-sandbox-two.git. Create a modern functional HTML/CSS Contact Form. Provide fully working standalone HTML and CSS files. Use Native Git to commit and open a Pull Request back over the exact same URL.', 
    'todo', 
    '10000000-0000-0000-0000-000000000001', 
    NOW(), 
    NOW()
FROM issues 
LIMIT 1;
