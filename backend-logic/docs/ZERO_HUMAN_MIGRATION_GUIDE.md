# Migration Guide: RunPod to AWS EC2

This document provides exact, step-by-step instructions to migrate the **Zero-Human MVP** from its legacy RunPod environment to a scalable **AWS EC2** production instance.

## 1. High-Level Architecture Change

| Feature | Legacy (RunPod) | New (AWS EC2) |
| :--- | :--- | :--- |
| **Instance Type** | Shared GPU Node | **t3.large** (2 vCPU, 8GB RAM) |
| **Storage** | Ephemeral Pod | **30GB EBS (gp3)** |
| **OS** | Ubuntu 22.04 | **Ubuntu 24.04 LTS** |
| **Port Access** | Randomized Proxy | **Standard Ports (22, 3000, 8000)** |

---

## 2. Infrastructure Setup (AWS Console)

### Step 2.1: Launch the Instance
1.  **AMI**: Select **Ubuntu Server 24.04 LTS** (64-bit x86).
2.  **Instance Type**: Select **t3.large**.
3.  **Key Pair**: Create or select a `.pem` key (e.g., `Agentic-AI-Key`). **Download this to your local machine.**
4.  **Storage**: Change the default 8GB to **30GB**.

### Step 2.2: Configure Security Group (Firewall)
You MUST add the following Inbound Rules to your EC2 Security Group:

| Type | Port | Source | Description |
| :--- | :--- | :--- | :--- |
| **SSH** | 22 | `0.0.0.0/0` | Remote Terminal & Sync Access |
| **Custom TCP**| 3000 | `0.0.0.0/0` | **Paperclip Web Dashboard** |
| **Custom TCP**| 8000 | `0.0.0.0/0` | **GitHub Webhooks / FastAPI** |
| **Custom TCP**| 5432 | `Anywhere` | **PostgreSQL Access** (Optional) |

---

## 3. Local Configuration Migration

Before shifting the code, you must update your local `.env` file to point to the new AWS target.

1.  Open your local `.env` file (located in the project root).
2.  Update the following variables:
    ```env
    # AWS EC2 Public IPv4 Address
    RUNPOD_IP="54.xx.xx.xx" 
    
    # AWS Standard SSH Port
    RUNPOD_PORT="22" 
    
    # Path to your AWS .pem key
    SSH_KEY_PATH="~/Downloads/Agentic-AI-Key.pem"
    ```

---

## 4. Code & Database Migration

### Step 4.1: Sync Codebase to EC2
From your **Local Development Machine** (Mac, Linux, or Windows WSL), run the sync utility:
```bash
# From within backend-logic/
./scripts/sync_to_remote.sh
```

### Step 4.2: Restore Database (If migrating data)
If you need to move the existing RunPod database to EC2:
1.  **On RunPod**: `pg_dump -U paperclip paperclip > backup.sql`
2.  **On EC2**: `psql -U paperclip paperclip < backup.sql`
*(Note: If this is a fresh production start, skip to Step 5).*

---

## 5. Service Initialization (On EC2)

Connect to your new EC2 instance via SSH:
```bash
ssh -i ~/path/to/key.pem ubuntu@54.xx.xx.xx
```

Once inside, execute the following to initialize all AI agents and database schemas:
```bash
cd Zero-Human-MVP
./scripts/Shell_Execution/setup.sh
```

Finally, restart the dashboard to inhale the new AWS environment variables:
```bash
./scripts/Shell_Execution/restart_dashboard.sh
```

---

## 7. AI-Driven Migration Prompt (For Cursor/Codex/Claude)

If you are using an AI coding assistant (like Cursor or Codex) to perform this migration, you can use the following "Master Prompt." Copy and paste the block below, then fill in your specific IP addresses and Key paths.

> **AGENTIC MIGRATION PROMPT:**
> "I need to migrate the entire **Zero-Human MVP** application from a legacy RunPod instance to a new AWS EC2 instance.
> 
> **Source (RunPod)**: `ssh root@<SOURCE_IP> -p 22168 -i <ID_ED25519_PATH>`
> **Target (AWS EC2)**: `ssh ubuntu@<TARGET_IP> -i <AWS_PEM_PATH>`
> **Target Repository**: `https://github.com/1Touch-dev/Zero-Human-Multiagents.git`
> 
> **Instructions**:
> 1.  Establish a connection to both. 
> 2.  Safely copy the entire `/home/paperclip/Zero-Human-MVP` directory from RunPod to the EC2 `/home/ubuntu/` directory. **CRITICAL**: Do NOT delete anything from the source (RunPod).
> 3.  Maintain the file permissions and ownership.
> 4.  Update the `.env` file on the new EC2 instance to reflect the new local paths if necessary.
> 5.  Once the files are moved, navigate to `/home/ubuntu/Zero-Human-MVP` on the EC2 and run:
>
> 1. **Setup Orchestrator (Dashboard):**
>    ```bash
>    cd orchestrator
>    pnpm install
>    pnpm dev
>    ```
>
> 2. **Setup Backend (Bridges):**
>    ```bash
>    cd backend-logic
>    ./scripts/Shell_Execution/setup.sh
>    ```
> 6.  Verify that the Paperclip dashboard is reachable at `http://<TARGET_IP>:3000`."

---

## 8. Verification Checklist
- [ ] **Dashboard Access**: Visit `http://YOUR_EC2_IP:3000` in your browser.
- [ ] **Webhook Access**: Verify `http://YOUR_EC2_IP:8000/docs` loads (FastAPI).
- [ ] **Agent Run**: Create a "New Issue" in the dashboard and verify the Architect wakes up on the new EC2 instance.
