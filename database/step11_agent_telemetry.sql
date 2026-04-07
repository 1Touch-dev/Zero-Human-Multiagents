-- Step 11: Agent telemetry schema extension
-- Adds: agent_runs, skill_runs, usage_logs

CREATE TABLE IF NOT EXISTS public.agent_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    issue_id uuid,
    issue_identifier text NOT NULL,
    heartbeat_run_id uuid,
    agent_id uuid,
    role_key text NOT NULL,
    github_mode text,
    status text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    duration_ms integer,
    error_message text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL
);

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_issue_id_issues_id_fk FOREIGN KEY (issue_id) REFERENCES public.issues(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_heartbeat_run_id_heartbeat_runs_id_fk FOREIGN KEY (heartbeat_run_id) REFERENCES public.heartbeat_runs(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_agent_id_agents_id_fk FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS agent_runs_issue_identifier_idx ON public.agent_runs(issue_identifier);
CREATE INDEX IF NOT EXISTS agent_runs_role_key_idx ON public.agent_runs(role_key);
CREATE INDEX IF NOT EXISTS agent_runs_started_at_idx ON public.agent_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS public.skill_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    agent_run_id uuid NOT NULL,
    issue_id uuid,
    skill_name text NOT NULL,
    model text,
    status text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    duration_ms integer,
    input_summary text,
    output_summary text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL
);

ALTER TABLE ONLY public.skill_runs
    ADD CONSTRAINT skill_runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.skill_runs
    ADD CONSTRAINT skill_runs_agent_run_id_agent_runs_id_fk FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.skill_runs
    ADD CONSTRAINT skill_runs_issue_id_issues_id_fk FOREIGN KEY (issue_id) REFERENCES public.issues(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS skill_runs_agent_run_id_idx ON public.skill_runs(agent_run_id);
CREATE INDEX IF NOT EXISTS skill_runs_skill_name_idx ON public.skill_runs(skill_name);
CREATE INDEX IF NOT EXISTS skill_runs_started_at_idx ON public.skill_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS public.usage_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    agent_run_id uuid,
    skill_run_id uuid,
    metric_key text NOT NULL,
    metric_value double precision,
    unit text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.usage_logs
    ADD CONSTRAINT usage_logs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.usage_logs
    ADD CONSTRAINT usage_logs_agent_run_id_agent_runs_id_fk FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.usage_logs
    ADD CONSTRAINT usage_logs_skill_run_id_skill_runs_id_fk FOREIGN KEY (skill_run_id) REFERENCES public.skill_runs(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS usage_logs_agent_run_id_idx ON public.usage_logs(agent_run_id);
CREATE INDEX IF NOT EXISTS usage_logs_skill_run_id_idx ON public.usage_logs(skill_run_id);
CREATE INDEX IF NOT EXISTS usage_logs_metric_key_idx ON public.usage_logs(metric_key);
CREATE INDEX IF NOT EXISTS usage_logs_recorded_at_idx ON public.usage_logs(recorded_at DESC);
