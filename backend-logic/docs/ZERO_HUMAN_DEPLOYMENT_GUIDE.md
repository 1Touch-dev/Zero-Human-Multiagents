# Zero-Human Company: Deployment & Replication Guide 🛠️

This manual contains the **exact terminal commands and sequential steps** required to deploy the complete, modernized Zero-Human Agentic Pipeline from scratch on a brand new, empty Ubuntu Server.

> [!IMPORTANT]
> **Primary Environment Recommendation**: While this guide covers both RunPod and EC2, we **strongly recommend AWS EC2 (t3.large)** for production scalability and exponential expansion.
> 
> **MIGRATING FROM RUNPOD?**
> If you are shifting an existing instance from RunPod to AWS, please follow the specialized:
> 👉 [**RunPod to EC2 Migration Guide**](ZERO_HUMAN_MIGRATION_GUIDE.md)

---

## Phase 0: Infrastructure Selection (AWS vs. RunPod)

| Feature | AWS EC2 (Recommended) | RunPod (Prototype) |
| :--- | :--- | :--- |
| **Instance** | **t3.large** (8GB RAM) | Community Cloud GPU |
| **Storage** | **30GB gp3 SSD** | Network Volume |
| **Ports** | Standard (22, 3000, 8000) | Randomized Proxy |

---

## Phase 1: Environment Bootstrapping
You must configure the pristine Linux server to accept the Node web server and the database engines natively.

### 1.1 Install System Prerequisites
Log into your raw Ubuntu Terminal as `root` and execute:
```bash
apt-get update -y
apt-get install -y curl wget git tmux screen software-properties-common nano socat python3 python3-pip
```

### 1.2 Install Node.js (v22) and Core Managers
Paperclip and OpenClaw require modernized Node dependencies.
```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs

# Install the critical package managers globally
npm install -g npm@latest
npm install -g pnpm yarn
```

### 1.3 Install and Configure PostgreSQL
The Orchestration dashboard relies entirely on a dedicated relational database.
```bash
# Install Postgres natively
apt-get install -y postgresql postgresql-contrib

# Start the service
service postgresql start

# Create the Paperclip Database User and Tables securely
sudo -u postgres psql -c "CREATE USER paperclip WITH PASSWORD 'paperclip' SUPERUSER;"
sudo -u postgres psql -c "CREATE DATABASE paperclip OWNER paperclip;"
```

---

## Phase 2: The Orchestration Layer (Paperclip)
Paperclip is the UI/Dashboard acting as the virtual Company Management structure.

### 2.1 Establish the Architecture User
```bash
# Create a dedicated linux user to structurally sandbox the application and AI engines
useradd -m -s /bin/bash paperclip
usermod -aG sudo paperclip
su - paperclip
```

### 2.2 Clone and Build the Dashboard
```bash
# Execute strictly from inside the paperclip linux user!
git clone https://github.com/paperclip-ai/paperclip.git
cd paperclip

# Install dependencies using pnpm
pnpm install

# Configure the local database connection
cp apps/web/.env.example apps/web/.env.local
sed -i 's|DATABASE_URL=.*|DATABASE_URL="postgresql://paperclip:paperclip@localhost:5432/paperclip"|' apps/web/.env.local

# Run Database Migrations to populate the tables organically
pnpm run db:push
```

### 2.3 Bypass Security Firewall Proxies (The Port Bind)
Runpod/Cloudflare natively proxies Port 3000, which fundamentally causes silent `502 Bad Gateway` WebSocket crashes. We bypass this geometrically mapping port 3003 back to 3000 locally using `socat`.
```bash
# Inside apps/web/.env.local add:
echo "PORT=3003" >> apps/web/.env.local

# Start the Paperclip Server inside a screen/tmux standard instance natively
npm run dev

# Open a entirely separate terminal AS ROOT and bind the external traffic dynamically:
socat TCP-LISTEN:3000,fork,reuseaddr TCP:127.0.0.1:3003
```

---

## Phase 3: The Execution Layer (OpenClaw)
OpenClaw is the physical Local AI engine where the agents interpret terminal streams securely.

### 3.1 Install OpenClaw Globally
```bash
# Switch back to the paperclip user
su - paperclip
npm install -g @openclaw/cli
```

### 3.2 Initialize the Local Memory
Because our pipeline dynamically injects models and keys via Python bridges dynamically, you do **not** need to manually configure `auth-profiles.json`. Simply initialize the database:
```bash
openclaw init
openclaw agent --agent main
```

---

## Phase 4: Cloning The Zero-Human Architectures

This repository contains the exact Python telemetry integrations, bridge cascading logic, and `.env` parsing algorithms natively required to link Paperclip to OpenClaw.

### 4.1 Clone the AI Wrapper Repository
```bash
# Switch back to the paperclip user natively
su - paperclip

cd ~
# Clone the foundational architecture framework
git clone https://github.com/1Touch-dev/Zero-Human-MVP.git
```

### 4.2 Route the Paperclip Database to the Native Python Bridge
The Paperclip interface must be explicitly configured to ping the massive `openclaw_bridge_cascade.py` architecture script statically hosted in our repository!
```bash
# Execute inside Postgres targeting the bridged path dynamically:
psql -U paperclip -d paperclip -c "UPDATE agents SET adapter_config = '{\"command\": \"/usr/bin/python3\", \"args\": [\"/home/paperclip/Zero-Human-MVP/scripts/Python_Bridges/openclaw_bridge_cascade.py\"]}' WHERE true;"
```

---

## Phase 5: Secure Execution Injection (`.env`)

To guarantee absolute security, avoid ever logging passwords natively into terminal history, and prevent organic `403 Permission Denied` Git blockages, we explicitly ban `~/.netrc` authorization caches.

**Everything is driven entirely by a single `.env` file!**

### 5.1 Push Tokens from Your Local Machine
From your **Local Development Machine** (within the `backend-logic/` directory), explicitly run the synchronization script:
```bash
./scripts/sync_to_remote.sh --watch
```

### 5.2 Validate the Configuration Natively
SSH back into the server as `paperclip` and verify the `.env` dynamically arrived inside `/home/paperclip/Zero-Human-MVP/`.

---

## Phase 6: Remote UI Authentication (`gh`)

To seamlessly interface natively with GitHub PR tracking without logging `.netrc` formulations, securely initialize the headless proxy organically inside the deployment container.

```bash
# Execute as the paperclip user
# Install GitHub CLI structurally
sudo curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt-get update && sudo apt-get install gh -y

# Configure Local Identity Binds (The Python Bridge will dynamically inject your GITHUB_TOKEN automatically from the local .env mapping, so NO password interactions are required!)
git config --global user.email "agent@zero-human.ai"
git config --global user.name  "Architect AI"
```

---

## Phase 7: Bidirectional Github Webhooks (The Feedback Loop)

To ensure the AI Agents natively iterate upon Human comments physically left on pending Pull Requests organically, deploy the Webhook node natively.

### 7.1 Install Webhook Dependencies
```bash
# Switch to paperclip user natively
su - paperclip
pip3 install fastapi uvicorn psycopg2-binary
```

### 7.2 Host the Webhook Server
```bash
# Execute the background FastAPI daemon on port 8000
python3 ~/Zero-Human-MVP/scripts/Webhooks/github_webhook.py &
```
*(Ensure you properly configure your GitHub Repository Webhook endpoints settings organically to point identically to `http://<EC2_IP>:8000/webhook` executing the `GITHUB_WEBHOOK_SECRET`.)*

**DEPLOYMENT COMPLETE.** 🚀 
Your Server is perfectly equipped to natively run the Zero-Human architectures dynamically from scratch!
