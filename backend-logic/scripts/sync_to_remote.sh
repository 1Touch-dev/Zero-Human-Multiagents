#!/usr/bin/env bash

# sync_to_remote.sh
# -----------------------------------------------------------------------------
# Zero-Human MVP Synchronization Utility
# -----------------------------------------------------------------------------
# This script continuously or manually pushes all local architecture modifications
# (Python Bridges, SQL Schemas, Webhooks, Docs) securely to your remote server 
# (AWS EC2, RunPod, etc).
# 
# Usage:
#   ./scripts/sync_to_remote.sh          # One-time manual sync
#   ./scripts/sync_to_remote.sh --watch  # Continuous syncing
# -----------------------------------------------------------------------------

# Configuration (Load from .env securely)
if [ -f .env ]; then
    set -o allexport
    source .env
    set +o allexport
fi

# DEFAULT SETTINGS (Override these in your local .env)
RUNPOD_USER="${RUNPOD_USER:-ubuntu}"
RUNPOD_IP="${RUNPOD_IP:-0.0.0.0}" # Placeholder: Set your EC2 IP in .env
RUNPOD_PORT="${RUNPOD_PORT:-22}"
REMOTE_DIR="${REMOTE_DIR:-/home/ubuntu/Zero-Human-MVP}"
SSH_KEY_PATH="${SSH_KEY_PATH:-~/.ssh/Agentic-AI-Key.pem}"
LOCAL_DIR="$(pwd)"

echo "🚀 Zero-Human MVP: Initializing Sync to Remote Server ($RUNPOD_IP:$RUNPOD_PORT)..."

sync_files() {
    echo "[$(date +'%T')] Synchronizing Workspace to RunPod..."
    
    # Construct SSH command with optional identity file
    SSH_CMD="ssh -p $RUNPOD_PORT -o StrictHostKeyChecking=no"
    if [ -f "$SSH_KEY_PATH" ]; then
        SSH_CMD="$SSH_CMD -i \"$SSH_KEY_PATH\""
    fi

    # Exclude internal IDE directories, git histories, and caches to save bandwidth
    rsync -avz --delete \
        -e "$SSH_CMD" \
        --exclude '.git/' \
        --exclude '.gemini/' \
        --exclude '__pycache__/' \
        --exclude '.DS_Store' \
        "$LOCAL_DIR/" "$RUNPOD_USER@$RUNPOD_IP:$REMOTE_DIR"
        
    if [ $? -eq 0 ]; then
        echo "✅ Sync Successful."
    else
        echo "❌ Sync Failed. Check SSH connection and .env settings."
    fi
}

# Execution Logic
if [ "$1" == "--watch" ]; then
    if ! command -v fswatch &> /dev/null; then
        echo "fswatch could not be found. Please install it to use --watch (e.g., brew install fswatch)"
        exit 1
    fi
    echo "👀 Starting continuous watch on $LOCAL_DIR..."
    sync_files # Initial Sync before watching
    fswatch -o "$LOCAL_DIR" | while read num ; do
        sync_files
    done
else
    sync_files
fi
