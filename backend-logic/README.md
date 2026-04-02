# Zero-Human MVP
## Autonomous Multi-Agent AI Operating System

### Core Repository: [1Touch-dev/Zero-Human-Multiagents](https://github.com/1Touch-dev/Zero-Human-Multiagents.git)

## 0. Technical System Architecture & Handoff Guide
If you are an onboarding engineer, system administrator, or DevOps architect inheriting this system, your complete guide covering architectural integrations, RunPod infrastructure, backend `.env` token injection, and database debugging sequences is prominently available here:

👉 [**Zero-Human Platform: Architecture & Operations Manual**](docs/ZERO_HUMAN_ARCHITECTURE_AND_OPERATIONS.md)

## 1. Agentic Architecture Hierarchy
Following the `Agentic_Engineering.pdf` specification, the Paperclip backend intercepts active tasks and triggers a highly secure Python proxy (`openclaw_bridge_cascade.py`) which delegates assignments seamlessly across four sequenced nodes:
1. **The Architect (Planner):** Ingests the initial Goal and structures the technical framework inside the sterile `/tmp/zero-human-sandbox/` directory.
2. **The Grunt (Developer):** Physically authors the source code files and executes local terminal validation scripts natively.
3. **The Pedant (QA Reviewer):** Scrutinizes the Grunt's output logic and runs rigorous code validation.
4. **The Scribe (Deployer):** Packages the code, authors documentation, handles `git commit`, and physically launches Pull Requests securely back to the production repository!

## 2. Multi-Tenant Automations (Phase 3 Backend)
The MVP utilizes dynamic Database Integrations to secure user access tokens statelessly! We do not globally hardcode `.netrc` passwords.

### Connecting Your Authenticators & Models (`.env` Config)
To vastly simplify user operations, both your `OPENAI_API_KEY`, your `GITHUB_TOKEN`, and your **Active AI Model** are entirely managed through a standard `.env` configuration file sitting securely in the root of your `Zero-Human-MVP` folder!

1. Create or edit the `.env` file locally:
```bash
OPENAI_API_KEY="sk-proj-REDACTED"
GITHUB_TOKEN="github_pat_REDACTED"
OPENCLAW_MODEL="openai/gpt-4o"
```

> **Model Overrides:** Want to run `gpt-5.4-codex` or `anthropic/claude-3.5-sonnet` instead? Simply change the `OPENCLAW_MODEL` flag. Our Python bridges will dynamically detect the override and instantly hot-swap the underlying AI Engine before executing the task cascade!

2. Simply run the sync script `./scripts/sync_to_runpod.sh` from your terminal!
3. **Important:** Because the Paperclip Web Dashboard runs continuously in the background on the RunPod, it won't magically absorb new `.env` changes immediately. You MUST run `./scripts/Shell_Execution/restart_dashboard.sh` from your terminal. This instantly SSH links your tokens and securely reboots the remote Node service so it never desyncs!

The `.env` file is permanently ignored from GitHub tracking (via `.gitignore`), but our Rsync utility safely ferries it into the RunPod. The internal Python scripts natively parse this file on the system, insulating your credentials from both the repository and the execution logs perfectly!

## 3. End-User Testing & Operations

### Dashboard UI Initiation
End-Users natively trigger the pipeline without touching terminals.
1. Navigate to the **Paperclip Web Dashboard**.
2. Click **New Issue** (or the **+** button).
3. Explicitly define the target goal indicating exactly which codebase repo it should natively touch.
> ⚠️ **CRITICAL PROMPTING RULE:** You MUST explicitly provide the Pull Request flags into the task so the background pipeline doesn't hang forever waiting on an invisible Git CLI `[Y/n]` interactive menu!
> **Bulletproof Prompt Example:** *"Clone `https://github.com/1Touch-dev/Zero-Human-Multiagents.git`. Build a new React Navigation Header. Run git commit and git push. Crucially, you MUST run exactly `gh pr create --head feature-xyz --title 'New Feature' --body 'AI Generated'`. Do NOT use interactive terminal prompts or simple gh commands."*
4. **Assign the ticket to "The Architect"**. 
5. Sit back! The status will automatically cycle from `Todo` -> `In Progress` -> `Done` silently!

### Enforcing Strict Git Workflow Definitions
Because the pipeline's Bash execution container maintains physical `git push` access via the PAT token, **you must lock your repository** to enforce standardized DevOps.
- On Github, navigate to your target repository's **Settings -> Branches**.
- Secure the `main` branch by adding a protection rule requiring **"Require a pull request before merging"**.
- This physically bars the AI Agents from force-pushing untested code directly into production workflows, and structurally funnels them straight into automated `gh pr create` pull-request pipelines!

### Automated Headless Deployments
For automated QA testing without clicking the Dashboard, you can dynamically inject Goals directly into the server database via SSH:
```bash
ssh -p 22168 root@194.68.245.210 "su - paperclip -c 'env PGPASSWORD=paperclip psql -h localhost -p 5433 -U paperclip -d paperclip -c \"INSERT INTO issues ...\"'"
```

## 4. Live Synchronization (`sync_to_runpod.sh`)
This workspace is firmly linked to the deployed Pod framework. Whenever you structurally refine local files (like adjusting the internal agent prompts nested inside `openclaw_bridge_cascade.py` or building new `Database/` mappings):
```bash
./scripts/sync_to_runpod.sh
```
## 5. End-to-End Execution & Debugging Workflow

This operational sequence explicitly layouts the exact chain of commands required to completely log into the Cloud Pod, manually execute the OpenClaw AI instances, debug output telemetry from stalled sessions, and observe database traces on the live system.

### Step 1: Securely Entering the Server
Log into the root RunPod execution container directly from your Mac terminal:
```bash
ssh -o StrictHostKeyChecking=no -p 22168 -i ~/.ssh/id_ed25519 root@194.68.245.210
```

### Step 2: Accessing the Execution Container
Once inside the RunPod, securely switch to the `paperclip` user environment containing the GitHub CLI bindings and OpenClaw models:
```bash
su - paperclip
```

### Step 3: Natively Executing the Python Bridge (Manual Trigger)
If you wish to trigger the agents identically to the Web UI but execute them safely through our isolated Python execution bridge:
```bash
# Run this AFTER executing `su - paperclip`
python3 /home/paperclip/Zero-Human-MVP/scripts/Python_Bridges/openclaw_bridge_cascade.py
```

### Step 4: Live Telemetry & OpenClaw Debugging
If an Agent hangs endlessly on Git authentication or crashes organically without closing the Paperclip Pull Request sequence, dump the exact raw Terminal outputs from the underlying AI component natively:
```bash
# Dump the raw terminal loop from the very last AI session:
# Run this AFTER executing `su - paperclip`
cat $(ls -t ~/.openclaw/agents/main/sessions/*.json | head -1) | grep -C 5 -i github
```

### Step 5: Validating Database Issue Triggers
If you click "New Issue" in the Web UI but the AI doesn't wake up efficiently, verify the actual Postgres trigger states inside the Paperclip daemon natively:
```bash
# Run this AFTER executing `su - paperclip`
psql -d paperclip -c "SELECT identifier, status, title FROM issues ORDER BY created_at DESC LIMIT 5;"
```

### Global Service Reboot Hook
If you modify your `.env` tokens locally on your Mac, you MUST run these two isolated scripts from your local repository to safely inject the new tokens into the active UI Node server:
```bash
./scripts/sync_to_runpod.sh
./scripts/Shell_Execution/restart_dashboard.sh
```

### Step 4.2: Final Baseline Push (Manual)
If you need to re-initialize the baseline in the new repository:
```bash
git remote add origin https://github.com/1Touch-dev/Zero-Human-Multiagents.git
git branch -M main
git push -u origin main
```
