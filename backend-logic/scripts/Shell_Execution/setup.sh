#!/bin/bash
# Permanently annihilate any legacy .netrc override tokens to enforce .env tunneling!
rm -f ~/.netrc
mkdir -p ~/.openclaw/agents/main/agent
cat << EOF > ~/.openclaw/agents/main/agent/auth-profiles.json
{
  "openai": {
    "base": {
      "apiKey": "$OPENAI_API_KEY"
    }
  }
}
EOF
openclaw models | head -n 25
