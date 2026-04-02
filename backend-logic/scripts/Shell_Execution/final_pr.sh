#!/bin/bash
rm -rf /tmp/zero-human-sandbox
mkdir -p /tmp/zero-human-sandbox
chown paperclip:paperclip /tmp/zero-human-sandbox
su - paperclip -c 'rm -f /home/paperclip/.openclaw/agents/main/sessions/*.lock'

su - paperclip -c 'env OPENAI_API_KEY="'"$OPENAI_API_KEY"'" GITHUB_TOKEN="'"$GITHUB_TOKEN"'" /usr/bin/openclaw agent --agent main -m "Go to /tmp/zero-human-sandbox. You MUST execute strictly autonomously: 1. Run git init. 2. Run git remote add origin https://github.com/Abhishek-AMK/zero-human-sandbox.git. 3. Run git fetch --all. 4. Run git checkout -b zero-human-finale. 5. Create a file ZeroHumanProof.md containing exactly: \\\\\\\"This file was autonomously generated and pushed via the OpenClaw execution engine.\\\\\\\" 6. Run git add . 7. Run git commit -m \\\\\\\"Autonomous Agent Push\\\\\\\". 8. Run git push -u origin zero-human-finale. 9. Run gh pr create --head zero-human-finale --title \\\\\\\"Final Zero-Human MVP Proof\\\\\\\" --body \\\\\\\"Successfully executed the Pull Request directly from the Agent\\\\\\\". 10. Exit cleanly."'
