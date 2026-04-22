# Zero-Human V2 — Complete Operations Manual

> **Status**: ✅ Fully operational as of 2026-04-08  
> **Last Verified**: PAP-73 "Add /ping endpoint" — full cascade completed, code committed, PR raised on GitHub

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture: V1 vs V2](#2-architecture-v1-vs-v2)
3. [Component Deep-Dive](#3-component-deep-dive)
4. [Infrastructure & Services](#4-infrastructure--services)
5. [Environment Configuration (.env)](#5-environment-configuration-env)
6. [The 4-Agent Digital Team](#6-the-4-agent-digital-team)
7. [How a Task Flows End-to-End](#7-how-a-task-flows-end-to-end)
8. [Running a Fresh End-to-End Test](#8-running-a-fresh-end-to-end-test)
9. [Monitoring & Debugging](#9-monitoring--debugging)
10. [All Changes Made in This Session](#10-all-changes-made-in-this-session)
11. [Troubleshooting Guide](#11-troubleshooting-guide)
12. [System Reset / Clean Restart](#12-system-reset--clean-restart)

---

## 1. System Overview

Zero-Human V2 is an **autonomous, asynchronous multi-agent AI pipeline** that takes a plain-English issue description and delivers a working Pull Request on GitHub — with zero human intervention after issue creation.

```
You create an issue on the dashboard
         ↓
Architect plans it
         ↓
Grunt implements it (writes real code, commits, pushes branch)
         ↓
Pedant reviews and refines it
         ↓
Scribe raises a Pull Request on GitHub
         ↓
PR appears at github.com/Abhishek-AMK/zero-human-sandbox-two/pulls
```

**No manual commands. No triggers. Fully automated.**

---

## 2. Architecture: V1 vs V2

### V1 (Legacy — `Zero-Human-MVP-Legacy-Archive`)

| Aspect | V1 |
|---|---|
| Trigger | Manual: `npx paperclipai run` per agent |
| Execution | Synchronous, blocking CLI |
| Agents | One at a time, manually chained |
| PR creation | Manual git push after task |
| Queue | None |
| Observability | Terminal stdout only |

### V2 (Current — `Zero-Human-Multiagents-Dev`)

| Aspect | V2 |
|---|---|
| Trigger | **Automatic**: assign issue on dashboard → done |
| Execution | **Async**: FastAPI → Redis → Celery workers |
| Agents | **Full team automatic relay**: Architect → Grunt → Pedant → Scribe |
| PR creation | **Automatic**: Scribe clones repo, pushes, opens PR via GitHub API |
| Queue | **Redis + Celery**: persistent, retry-capable |
| Observability | `journalctl` real-time logs + PostgreSQL telemetry |

---

## 3. Component Deep-Dive

### 3.1 Project Layout

```
/home/ubuntu/Zero-Human-Multiagents-Dev/
├── backend-api/                    # FastAPI + Celery task definitions
│   ├── main.py                     # FastAPI app (POST /task, GET /health, GET /status/:id)
│   ├── tasks.py                    # Celery task: execute_agent_task
│   ├── celery_app.py               # Celery configuration (Redis broker)
│   ├── requirements.txt
│   └── .env                        # API-level env (symlink/copy of backend-logic/.env)
│
├── backend-logic/                  # Core AI bridge and tooling
│   ├── .env                        # Master environment file (only configure this one)
│   ├── venv/                       # Python virtualenv used by Celery
│   ├── scripts/
│   │   ├── Python_Bridges/
│   │   │   └── openclaw_bridge_cascade.py  # Main AI cascade script
│   │   └── Webhooks/
│   │       └── github_webhook.py   # GitHub webhook listener
│   ├── tools/
│   │   └── db_telemetry.py         # PostgreSQL telemetry logging
│   └── docs/
│       └── ZERO_HUMAN_V2_OPERATIONS.md  ← this file
│
├── orchestrator/                   # Paperclip Node.js orchestrator (runs agents)
│   └── package.json
│
/home/ubuntu/
└── zerohuman_heartbeat_runner.py   # Custom Python heartbeat — polls DB, dispatches tasks
```

### 3.2 The Cascade Bridge (`openclaw_bridge_cascade.py`)

This is the brain of the system. When Celery runs a task, it:

1. Loads environment variables from `.env` (without overwriting already-set vars)
2. Reads `PAPERCLIP_AGENT_ID` to determine which agent role to run
3. Connects to Paperclip API (`http://127.0.0.1:3202`) and finds the assigned issue
4. Runs that agent's phase via `paperclipai` CLI
5. After completion, **hands off** to the next agent in the cascade by:
   - Updating the issue's `assignee_agent_id` in PostgreSQL
   - Setting status back to `todo`
6. The Scribe (final agent) additionally:
   - Clones the workspace repo (`ZERO_HUMAN_WORKSPACE_REPO_URL`) to `/tmp/zero-human-sandbox`
   - Pushes the feature branch
   - Creates a GitHub PR via the GitHub API using `GITHUB_TOKEN`

### 3.3 The Heartbeat Runner (`/home/ubuntu/zerohuman_heartbeat_runner.py`)

A standalone Python script that replaces the old `pnpm paperclipai heartbeat` CLI.

**What it does every 15 seconds:**
1. Queries PostgreSQL for issues assigned to any of the 4 agents with `todo`/`in_progress` status, created within the last 7 days
2. For each found issue, POSTs to `http://127.0.0.1:8100/task` with the correct `agent_id`
3. Tracks a cooldown (3 minutes per issue) to prevent duplicate dispatches
4. The Celery worker receives the task and sets `PAPERCLIP_AGENT_ID` before running the cascade

**Agent ID mapping:**
```
10000000-0000-0000-0000-000000000001 → The Architect
20000000-0000-0000-0000-000000000001 → The Grunt
30000000-0000-0000-0000-000000000001 → The Pedant
40000000-0000-0000-0000-000000000001 → The Scribe
```

---

## 4. Infrastructure & Services

All services run as systemd units on the EC2 instance (`54.198.208.79`).

### Service Overview

| Service | Port | Purpose | Restart |
|---|---|---|---|
| `paperclip.service` | 3202 | Paperclip Dashboard backend | always |
| `paperclip-dev.service` | 3201 | Dashboard UI (dev server) | always |
| `paperclip-dev-proxy.service` | 3201→3202 | Port proxy | always |
| `zerohuman-backend-api` | 8100 | FastAPI task intake | always |
| `zerohuman-celery-worker` | — | Task executor (connects to Redis) | always |
| `zerohuman-heartbeat` | — | DB poller → dispatches to Celery | always |
| `zerohuman-webhook` | 8200 | GitHub webhook listener | always |

### Service Files

```
/etc/systemd/system/
├── zerohuman-backend-api.service
├── zerohuman-celery-worker.service
├── zerohuman-heartbeat.service
└── zerohuman-webhook.service
```

### Key Paths for Each Service

**zerohuman-celery-worker.service:**
```ini
WorkingDirectory=/home/ubuntu/Zero-Human-Multiagents-Dev/backend-api
EnvironmentFile=/home/ubuntu/Zero-Human-Multiagents-Dev/backend-api/.env
ExecStart=/home/ubuntu/Zero-Human-Multiagents-Dev/backend-logic/venv/bin/celery \
  -A celery_app worker --loglevel=info --concurrency=2 \
  --queues=heavy,light,celery --max-tasks-per-child=50
```

**zerohuman-heartbeat.service:**
```ini
ExecStart=/home/ubuntu/Zero-Human-Multiagents-Dev/backend-logic/venv/bin/python3 \
  /home/ubuntu/zerohuman_heartbeat_runner.py
```

---

## 5. Environment Configuration (.env)

**Master file location:** `/home/ubuntu/Zero-Human-Multiagents-Dev/backend-logic/.env`

This is the **only file you need to edit** to configure the system.

```bash
# ─────────────────────────────────────────────────────────
# AI Model Configuration
# ─────────────────────────────────────────────────────────
OPENAI_API_KEY="sk-proj-..."         # OpenAI API key for the AI agents
OPENCLAW_MODEL="openai/gpt-5.4"     # Model to use (can be any OpenAI-compatible model)

# ─────────────────────────────────────────────────────────
# GitHub Integration
# ─────────────────────────────────────────────────────────
GITHUB_TOKEN="ghp_..."              # GitHub Personal Access Token
                                    # Required permissions: repo, workflow, pull_requests
                                    # This token determines which GitHub account raises the PRs

# ─────────────────────────────────────────────────────────
# Centralized Repository Configuration (WHERE PRs ARE RAISED)
# ─────────────────────────────────────────────────────────
ZERO_HUMAN_WORKSPACE_REPO_URL="https://github.com/Abhishek-AMK/zero-human-sandbox-two.git"
ZERO_HUMAN_WORKSPACE_DEFAULT_REF="main"    # Default branch to clone
ZERO_HUMAN_PR_BASE_BRANCH="main"           # Target branch for PRs (base branch)

# ─────────────────────────────────────────────────────────
# Paperclip Internal (Do not change unless you know what you're doing)
# ─────────────────────────────────────────────────────────
PAPERCLIP_AGENT_ID="10000000-0000-0000-0000-000000000001"  # Default: Architect
                                                            # Overridden at runtime by Celery
PAPERCLIP_COMPANY_ID="00000000-0000-0000-0000-000000000001"
PAPERCLIP_API_URL="http://127.0.0.1:3202"
PAPERCLIP_API_KEY="local_trusted_dummy"
DATABASE_URL="postgresql://paperclip:paperclip@localhost:5432/paperclip"

# ─────────────────────────────────────────────────────────
# Infrastructure
# ─────────────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0
RUNPOD_IP="54.198.208.79"
RUNPOD_PORT="22"
RUNPOD_USER="ubuntu"
```

### Changing the Target Repository

To point the system at a **different GitHub repository**:

1. Edit `.env`:
   ```bash
   ZERO_HUMAN_WORKSPACE_REPO_URL="https://github.com/YOUR_ORG/YOUR_REPO.git"
   ZERO_HUMAN_WORKSPACE_DEFAULT_REF="main"
   ZERO_HUMAN_PR_BASE_BRANCH="main"
   ```
2. Ensure `GITHUB_TOKEN` has write access to that repository
3. Clear the sandbox: `rm -rf /tmp/zero-human-sandbox`
4. Restart: `sudo systemctl restart zerohuman-celery-worker`

---

## 6. The 4-Agent Digital Team

Each agent has a specific, bounded role. They hand off **sequentially** — each one finishes before the next begins.

### The Architect (`10000000-...0001`)
- **Role**: Planning and scoping
- **What it does**: Reads the issue description, creates a detailed implementation plan, writes `PAP-XX_ARCHITECT_PLAN.md` in the sandbox
- **What it does NOT do**: Write any code, create files, push to git
- **Handoff**: Sets `assignee_agent_id` → Grunt

### The Grunt (`20000000-...0001`)
- **Role**: Implementation
- **What it does**: Reads the Architect's plan, writes all code files, runs tests/verifications, creates git branch, commits, pushes
- **Outputs**: Working code pushed to branch `pap-XX-<slug>` in the target repo
- **Handoff**: Sets `assignee_agent_id` → Pedant

### The Pedant (`30000000-...0001`)
- **Role**: Code review and refinement
- **What it does**: Reviews the Grunt's implementation, checks code quality, fixes issues, adds missing tests or documentation
- **Handoff**: Sets `assignee_agent_id` → Scribe

### The Scribe (`40000000-...0001`)
- **Role**: PR creation and delivery
- **What it does**:
  1. Ensures the sandbox repo is cloned (`ZERO_HUMAN_WORKSPACE_REPO_URL`)
  2. Reviews the final state of the code
  3. Creates a GitHub Pull Request via the API: `POST /repos/{owner}/{repo}/pulls`
  4. PR targets `ZERO_HUMAN_PR_BASE_BRANCH` (default: `main`)
  5. Writes PR description summarizing all changes
- **Final step**: Sets issue status to `done`

---

## 7. How a Task Flows End-to-End

```
┌─────────────────────────────────────────────────────────────────┐
│  1. USER creates issue on Dashboard (http://54.198.208.79:3201)  │
│     - Sets Assignee: The Architect                               │
│     - Sets Status: todo                                          │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼ (within 15 seconds)
┌─────────────────────────────────────────────────────────────────┐
│  2. HEARTBEAT RUNNER polls PostgreSQL                            │
│     SELECT * FROM issues WHERE assignee_agent_id = ANY(...)     │
│       AND status IN ('todo','in_progress')                       │
│       AND created_at > NOW() - INTERVAL '7 days'                │
│     → Finds PAP-XX assigned to Architect                        │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. HEARTBEAT posts to FastAPI:                                  │
│     POST http://127.0.0.1:8100/task                             │
│     { "issue_id": "PAP-XX", "repo_url": "...", "agent_id": "10000000..." } │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. FASTAPI enqueues to CELERY (Redis queue)                    │
│     execute_agent_task.delay(payload)                            │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. CELERY WORKER picks up task                                  │
│     - Sets os.environ["PAPERCLIP_AGENT_ID"] = agent_id          │
│     - Calls openclaw_bridge_cascade.run_issue(issue_id)         │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  6. CASCADE BRIDGE runs the agent phase                         │
│     - Queries Paperclip API for the assigned issue              │
│     - Runs: pnpm paperclipai heartbeat run --agent-id ...       │
│     - Agent AI thinks, plans/codes/reviews/raises PR            │
│     - After completion: updates DB assignee → next agent        │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼ (repeat for each agent: Architect→Grunt→Pedant→Scribe)
┌─────────────────────────────────────────────────────────────────┐
│  7. SCRIBE creates the PR                                        │
│     - Clones repo to /tmp/zero-human-sandbox (if empty)         │
│     - Pushes branch, opens PR via GitHub API                    │
│     - PR visible at github.com/{owner}/{repo}/pulls             │
│     - Issue status set to "done"                                │
└─────────────────────────────────────────────────────────────────┘
```

**Total time**: ~30–45 minutes for 4 agents.

---

## 8. Running a Fresh End-to-End Test

### Prerequisites — Verify Services Are Running

```bash
# All should show "active (running)"
sudo systemctl status zerohuman-backend-api \
  zerohuman-celery-worker \
  zerohuman-heartbeat \
  --no-pager | grep -E "●|Active:"
```

### Step 1 — Create the Issue

1. Open the dashboard: **http://54.198.208.79:3201**
2. Click **"New Issue"**
3. Fill in:
   - **Title**: anything short and descriptive (e.g. `Add /status endpoint`)
   - **Description**: a clear technical task (e.g. `Add a GET /status route that returns server uptime and version. Update README with usage.`)
   - **Assignee**: `The Architect`
   - **Status**: `todo`
4. Click **Create**

> **That's it. You don't need to do anything else.**

### Step 2 — Watch Progress (Optional)

```bash
# Live Celery worker logs — see each agent phase
sudo journalctl -u zerohuman-celery-worker -f

# Live heartbeat — see when each agent is picked up
sudo journalctl -u zerohuman-heartbeat -f
```

### Step 3 — Track Agent Phases on the Dashboard

On the Paperclip dashboard:
- `The Architect` → status changes to `in_progress` → run appears → `succeeded`
- `The Grunt` → picks up, writes code, commits
- `The Pedant` → reviews and refines
- `The Scribe` → raises the PR → issue goes to `done`

### Step 4 — Verify the PR on GitHub

Open: **https://github.com/Abhishek-AMK/zero-human-sandbox-two/pulls**

You will see a new open PR titled `[PAP-XX] <your issue title>` targeting `main`.

### Expected Timeline

| Phase | Start | Duration |
|---|---|---|
| Heartbeat detects issue | T+0:15 | instant |
| Architect completes | T+5 min | ~5 min |
| Grunt completes (code + commit) | T+13 min | ~8 min |
| Pedant completes (review) | T+21 min | ~8 min |
| **Scribe creates PR** ← | **T+32 min** | **~8 min** |

---

## 9. Monitoring & Debugging

### Real-Time Logs

```bash
# Watch all agent phases execute
sudo journalctl -u zerohuman-celery-worker -f

# Watch when heartbeat dispatches tasks
sudo journalctl -u zerohuman-heartbeat -f

# Check FastAPI endpoint logs
sudo journalctl -u zerohuman-backend-api -f
```

### Check Issue Status in Database

```bash
PGPASSWORD=paperclip psql -h localhost -U paperclip -d paperclip \
  -c "SELECT identifier, title, status, assignee_agent_id 
      FROM issues 
      WHERE status IN ('todo','in_progress') 
      ORDER BY updated_at DESC 
      LIMIT 10;"
```

### Check Which Agent Is Assigned

```
10000000-0000-0000-0000-000000000001 = The Architect
20000000-0000-0000-0000-000000000001 = The Grunt
30000000-0000-0000-0000-000000000001 = The Pedant
40000000-0000-0000-0000-000000000001 = The Scribe
NULL (empty)                         = unassigned / done
```

### Check Redis Queue

```bash
# How many tasks are queued?
redis-cli LLEN celery

# See all queues
redis-cli INFO keyspace
```

### Check Celery Task Status

```bash
# Get the task_id from heartbeat logs, then:
curl http://127.0.0.1:8100/status/<task_id>
```

### Check What's In /tmp/zero-human-sandbox

```bash
ls -la /tmp/zero-human-sandbox/
git -C /tmp/zero-human-sandbox log --oneline -5
git -C /tmp/zero-human-sandbox branch -a
```

---

## 10. All Changes Made in This Session

This section documents every significant change made during the V2 activation and debugging session (2026-04-08).

### 10.1 `backend-logic/.env` — Added Critical Variables

**Changes:**
```bash
# Added Paperclip auth (enables cascade bridge to authenticate locally)
PAPERCLIP_AGENT_ID="10000000-0000-0000-0000-000000000001"
PAPERCLIP_COMPANY_ID="00000000-0000-0000-0000-000000000001"
PAPERCLIP_API_URL="http://127.0.0.1:3202"
PAPERCLIP_API_KEY="local_trusted_dummy"
DATABASE_URL="postgresql://paperclip:paperclip@localhost:5432/paperclip"

# Added centralized repo config (determines WHERE code is committed and PR raised)
ZERO_HUMAN_WORKSPACE_REPO_URL="https://github.com/Abhishek-AMK/zero-human-sandbox-two.git"
ZERO_HUMAN_WORKSPACE_DEFAULT_REF="main"
ZERO_HUMAN_PR_BASE_BRANCH="main"
```

**Why**: The cascade bridge was exiting early because it couldn't authenticate to Paperclip. The repo vars ensure the Scribe always knows the target repo.

### 10.2 `openclaw_bridge_cascade.py` — Fixed `load_env()` Clobbering Bug

**Change:**
```python
# BEFORE (broken):
os.environ[k.strip()] = v.strip().strip('"').strip("'")

# AFTER (fixed):
k = k.strip()
if k not in os.environ:  # ← KEY FIX
    os.environ[k] = v.strip().strip('"').strip("'")
```

**Why**: `load_env()` was called inside `main()` which overwrote `PAPERCLIP_AGENT_ID` back to the Architect's ID even when Celery had set it to the Grunt/Pedant/Scribe. This caused every agent to run as the Architect, making the cascade loop infinitely.

### 10.3 `openclaw_bridge_cascade.py` — Added Auto-Clone Logic

**Change**: Added sandbox initialization at the start of every Scribe run:
```python
workspace_repo_url = os.environ.get("ZERO_HUMAN_WORKSPACE_REPO_URL", "").strip()
if workspace_repo_url and not os.path.exists(os.path.join(workspace_dir, ".git")):
    subprocess.run(["git", "clone", workspace_repo_url, workspace_dir], check=True)
```

**Why**: The Scribe couldn't raise a PR because `/tmp/zero-human-sandbox` was empty with no git history.

### 10.4 `backend-api/tasks.py` — Removed Architect Hard-Reset

**Change**: Removed the block that set every issue's `assignee_agent_id` to the Architect before running:
```python
# REMOVED — this broke the cascade relay chain:
# UPDATE issues SET assignee_agent_id = '10000000-...' WHERE ...
```

**Why**: Every Celery task was resetting the assignee to the Architect before execution. Grunt/Pedant/Scribe phases were never actually reached.

### 10.5 `backend-api/tasks.py` — Added Per-Task Agent ID Injection

**Change:**
```python
agent_id = payload.get("agent_id", "").strip()
if agent_id:
    os.environ["PAPERCLIP_AGENT_ID"] = agent_id
```

**Why**: Each heartbeat dispatch now includes `agent_id` in the payload. The Celery task sets `PAPERCLIP_AGENT_ID` before calling the bridge so the correct agent phase runs.

### 10.6 `backend-api/tasks.py` — Fixed Celery Timeout

**Change:**
```python
# BEFORE:
AGENT_TASK_TIMEOUT_SECONDS = 600  # 10 minutes

# AFTER:
AGENT_TASK_TIMEOUT_SECONDS = 3600  # 60 minutes
```

**Why**: Each agent phase takes 5–10 minutes. The full 4-agent cascade inside one Celery task needs up to 40 minutes. The 10-minute timeout was killing every single run at exactly the 10-minute mark.

### 10.7 Created `/home/ubuntu/zerohuman_heartbeat_runner.py`

**What it is**: A new Python heartbeat runner that replaced the broken `pnpm paperclipai heartbeat` bash loop.

**Why**: The original heartbeat used `pnpm paperclipai heartbeat run --agent-id X` which:
- Required `--trigger`/`--source` args that didn't exist in the current CLI version
- Didn't dispatch tasks to Celery — it just signaled the Paperclip server
- Used the system Python (no psycopg2) instead of the venv

**New runner features:**
- Queries PostgreSQL directly for assigned issues
- Dispatches to FastAPI `/task` with correct `agent_id` in payload
- Implements per-issue cooldown (3 min) to prevent queue flooding
- Filters by `created_at > NOW() - INTERVAL '7 days'` to skip old issues
- Uses the venv Python that has all dependencies

### 10.8 Updated `zerohuman-heartbeat.service`

**Change**: Replaced bash loop calling `pnpm` with Python runner:
```ini
[Service]
ExecStart=/home/ubuntu/Zero-Human-Multiagents-Dev/backend-logic/venv/bin/python3 \
  /home/ubuntu/zerohuman_heartbeat_runner.py
```

---

## 11. Troubleshooting Guide

### Issue: "No assigned issue found in DB for this agent"

**Cause**: `PAPERCLIP_AGENT_ID` is incorrect when the bridge runs, so it can't find an issue assigned to that agent in Paperclip's database.

**Fix**: Ensure `tasks.py` correctly sets `os.environ["PAPERCLIP_AGENT_ID"] = agent_id` from the payload **before** calling `run_issue()`. Also verify `load_env()` doesn't overwrite it (the `if k not in os.environ` guard must be present).

### Issue: Cascade times out after exactly 10/600 seconds

**Cause**: `AGENT_TASK_TIMEOUT_SECONDS` was set too low.

**Fix**: Increase to 3600 (60 min) in `tasks.py`:
```python
AGENT_TASK_TIMEOUT_SECONDS = 3600
```

### Issue: Old issues keep getting picked up

**Cause**: The heartbeat was querying all `todo`/`in_progress` issues without any age filter.

**Fix**: The `created_at > NOW() - INTERVAL '7 days'` filter in `zerohuman_heartbeat_runner.py` handles this. Additionally, manually cancel old issues:
```sql
UPDATE issues SET status = 'cancelled' WHERE identifier IN ('PAP-3','PAP-41',...);
```

### Issue: Redis queue has stale retry tasks from old runs

**Fix**: Flush Redis and restart:
```bash
redis-cli FLUSHALL
sudo systemctl restart zerohuman-celery-worker zerohuman-heartbeat
```

### Issue: 422 Unprocessable Entity from `/task` endpoint

**Cause**: FastAPI's `TaskRequest` requires `issue_id`, `repo_url`, and `user_id`.

**Fix**: Ensure the heartbeat payload includes all required fields:
```python
{"issue_id": "PAP-XX", "repo_url": "https://...", "user_id": "zerohuman-heartbeat", "agent_id": "..."}
```

### Issue: Scribe can't push / PR not created

**Causes**: 
1. `GITHUB_TOKEN` lacks `repo` permission
2. `/tmp/zero-human-sandbox` is not a valid git repo with the correct remote
3. Branch wasn't pushed by Grunt

**Fix**:
```bash
# Check the sandbox state
git -C /tmp/zero-human-sandbox remote -v
git -C /tmp/zero-human-sandbox log --oneline -3
git -C /tmp/zero-human-sandbox branch -a

# If broken, clean and let the system recreate it
rm -rf /tmp/zero-human-sandbox
```

### Issue: Heartbeat shows "Connection refused" for API

**Cause**: `zerohuman-backend-api` (FastAPI on port 8100) is not running.

**Fix**:
```bash
sudo systemctl start zerohuman-backend-api
sudo systemctl status zerohuman-backend-api
```

---

## 12. System Reset / Clean Restart

Use this procedure whenever you want to start completely fresh with no history.

### Full Clean Reset

```bash
# 1. Stop zerohuman services (keep paperclip running)
sudo systemctl stop zerohuman-heartbeat zerohuman-celery-worker zerohuman-backend-api

# 2. Flush all queued/retry Celery tasks
redis-cli FLUSHALL

# 3. Cancel all active issues in the DB (keeps completed 'done' issues intact)
PGPASSWORD=paperclip psql -h localhost -U paperclip -d paperclip \
  -c "UPDATE issues SET status='cancelled', assignee_agent_id=NULL \
      WHERE status NOT IN ('done','cancelled');"

# 4. Clean the git sandbox
rm -rf /tmp/zero-human-sandbox

# 5. Restart everything
sudo systemctl start zerohuman-backend-api zerohuman-celery-worker zerohuman-heartbeat

# 6. Verify: heartbeat should say "No active issues. Sleeping."
sudo journalctl -u zerohuman-heartbeat -f
```

### Partial Reset (Keep Issue History, Just Clear Queue)

```bash
redis-cli FLUSHALL
sudo systemctl restart zerohuman-celery-worker zerohuman-heartbeat
```

### Restart All Services

```bash
sudo systemctl restart \
  zerohuman-backend-api \
  zerohuman-celery-worker \
  zerohuman-heartbeat \
  zerohuman-webhook
```

---

## Appendix: Quick Reference

### Service Commands

```bash
# Status of all
sudo systemctl status zerohuman-backend-api zerohuman-celery-worker zerohuman-heartbeat --no-pager

# Restart all zerohuman services
sudo systemctl restart zerohuman-backend-api zerohuman-celery-worker zerohuman-heartbeat

# Follow live logs
sudo journalctl -u zerohuman-celery-worker -f
sudo journalctl -u zerohuman-heartbeat -f
sudo journalctl -u zerohuman-backend-api -f
```

### Database Quick Checks

```bash
# Active issues
PGPASSWORD=paperclip psql -h localhost -U paperclip -d paperclip \
  -c "SELECT identifier, title, status FROM issues WHERE status IN ('todo','in_progress') ORDER BY identifier DESC;"

# Cancel all active issues
PGPASSWORD=paperclip psql -h localhost -U paperclip -d paperclip \
  -c "UPDATE issues SET status='cancelled', assignee_agent_id=NULL WHERE status NOT IN ('done','cancelled');"
```

### Key URLs

| Resource | URL |
|---|---|
| Dashboard | http://54.198.208.79:3201 |
| FastAPI | http://54.198.208.79:8100 |
| FastAPI Health | http://54.198.208.79:8100/health |
| GitHub PRs | https://github.com/Abhishek-AMK/zero-human-sandbox-two/pulls |

---

*Document generated: 2026-04-08 | Zero-Human V2 operational*
