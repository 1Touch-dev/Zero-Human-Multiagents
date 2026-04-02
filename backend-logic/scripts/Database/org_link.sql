DO $$
DECLARE
    architect_id uuid;
BEGIN
    SELECT id INTO architect_id FROM agents WHERE name = 'The Architect' LIMIT 1;
    UPDATE agents SET reports_to = architect_id WHERE name IN ('The Grunt', 'The Pedant', 'The Scribe');
END $$;
