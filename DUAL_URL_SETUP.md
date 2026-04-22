# Dual URL Setup (Run Side-by-Side)

Use this when you want to keep an existing Paperclip URL (for example `:3000`) and run this repo on another URL/port at the same time.

## Goal

- Existing deployment stays live on `http://54.198.208.79:3000`
- New Multiagents deployment runs on `http://54.198.208.79:3101`

## 1) Start Multiagents on a different port

```bash
cd /home/ubuntu/Zero-Human-Multiagents/orchestrator
pnpm install
PORT=3101 ./scripts/dev-side-by-side.sh
```

The script defaults to host `0.0.0.0` and automatically sets authenticated deployment mode for safe external access.

## 2) Open the port in cloud firewall/security group

Allow inbound TCP `3101` on your VM/EC2 security group.

Without this step, `localhost:3101` may work on the server but `http://54.198.208.79:3101` will not open from your browser.

## 3) Verify both URLs

- Existing URL: `http://54.198.208.79:3000/PAP/dashboard`
- New URL: `http://54.198.208.79:3101`

Both can run together because they use different ports.

## 4) Optional custom port

```bash
PORT=3200 ./scripts/dev-side-by-side.sh
```

Then open inbound TCP `3200` and browse `http://54.198.208.79:3200`.
