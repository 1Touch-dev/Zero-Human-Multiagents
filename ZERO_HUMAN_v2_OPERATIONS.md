# Zero-Human Orchestrator v2: Operations & Testing Manual

This document defines the new Version 2 (MVP) testing protocol, which replaces the legacy version 1 procedures (RunPod/Manual Node/JSON loops).

---

## 1. System Architecture Differences

| Feature | **Legacy (v1)** | **New Orchestrator (v2)** |
| :--- | :--- | :--- |
| **Orchestration** | Node Daemon (`paperclipai run`) | FastAPI + Redis + Celery Worker Stack |
| **Logic Mode** | Synchronous (UI frozen until done) | Asynchronous (UI updates while AI works) |
| **Trigger** | "Automation Prompt" requirements | Standard goals + "The Architect" assignment |
| **Heartbeat** | Manual script triggers | Background loop (polling every 15s) |
| **Telemetry** | `cat session.json` files | `SELECT * FROM agent_runs` in PostgreSQL |

---

## 2. Updated Testing Protocol (UI-Only)

In Version 2, the requirement for appending `gh pr create` flags to your prompts has been **removed**. The system now handles GitHub orchestration automatically via the **"Scribe"** agent.

### **Step 1: The Trigger**
1. Open the [Paperclip Dashboard](http://54.198.208.79:3201).
2. Create a **New Issue** (e.g., `PAP-68`).
3. Set the **Assignee** to **"The Architect"**.
4. Set the **Status** to **"todo"**.
5. Add a **Comment** to initiate work.

### **Step 2: The Loop (Automatic)**
- The `zerohuman-heartbeat.service` on the EC2 scans for this assignment every **15 seconds**.
- On match, it queues an `execute_agent_task` in **Redis**.
- The `zerohuman-celery-worker` wakes up and executes the multi-agent cascade.

### **Step 3: Monitoring & Audit**
Instead of tailing JSON files in `~/.openclaw`, you now monitor live telemetry in the PostgreSQL database.

**View AI Reasonings & Progress (EC2 Shell):**
```bash
# Query the live telemetry audit trail
PGPASSWORD=paperclip psql -h localhost -U paperclip -d paperclip \
-c "SELECT role_key, status, started_at FROM agent_runs ORDER BY started_at DESC LIMIT 5;"
```

**View Live Worker Logs:**
```bash
# Watch the AI "think" in real-time
sudo journalctl -u zerohuman-celery-worker -f
```

---

## 3. Operations & Recovery

If the dashboard dashboard "feels dead" or does not trigger the AI after 30 seconds of assignment:

**1. Restart the Intelligence Stack:**
```bash
# Reload all systemd orchestrator services
sudo systemctl restart zerohuman-*
```

**2. Verify API Health:**
```bash
curl http://127.0.0.1:8100/health
# Expected: {"status":"ok"}
```

**3. Check Heartbeat Heart Rate:**
```bash
# Ensure the "Scanner" is polling for tasks
sudo journalctl -u zerohuman-heartbeat -n 20
```
