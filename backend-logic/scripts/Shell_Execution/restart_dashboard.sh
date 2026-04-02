#!/bin/bash
# Physically sync the latest .env back to the RunPod
echo "🚀 Zero-Human MVP: Pushing .env parameters to RunPod..."
scp -o StrictHostKeyChecking=no -P 22168 -i ~/.ssh/id_ed25519 .env root@194.68.245.210:/home/paperclip/Zero-Human-MVP/.env

# Restart the Node Web Server
echo "🔄 Rebooting Paperclip Internal Web Server..."
ssh -o StrictHostKeyChecking=no -p 22168 -i ~/.ssh/id_ed25519 root@194.68.245.210 << 'EOF'
su - paperclip << 'INNER_EOF'
ps -ef | awk '/node.*paperclip/ && !/awk/ {print $2}' | xargs kill -9 2>/dev/null
ps -ef | awk '/npm exec paperclipai/ && !/awk/ {print $2}' | xargs kill -9 2>/dev/null
sleep 2

cd paperclip
rm -f /home/paperclip/paperclip.log
# Ingest the keys safely into background daemon
export $(grep -v '^#' /home/paperclip/Zero-Human-MVP/.env | xargs)

nohup env OPENAI_API_KEY="$OPENAI_API_KEY" GITHUB_TOKEN="$GITHUB_TOKEN" OPENCLAW_MODEL="$OPENCLAW_MODEL" DATABASE_URL="postgresql://paperclip:paperclip@localhost:5433/paperclip" npx paperclipai run > /home/paperclip/paperclip.log 2>&1 &

echo "✅ Paperclip Web Interface Successfully Reloaded!"
INNER_EOF
EOF
