import os, sys, subprocess, psycopg2

def load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if '=' in line and not line.strip().startswith('#'):
                    k, v = line.strip().split('=', 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")

def main():
    load_env()
    try:
        conn = psycopg2.connect("postgresql://paperclip:paperclip@localhost:5433/paperclip")
        cur = conn.cursor()
        cur.execute("SELECT identifier, title, description FROM issues WHERE status != 'done' ORDER BY created_at DESC LIMIT 1;")
        issue = cur.fetchone()
        if not issue: sys.exit(0)
        
        identifier, title, description = issue
        message = f"Go to /tmp/zero-human-sandbox. You MUST execute strictly autonomously: {description}"
        
        os.system("rm -rf /tmp/zero-human-sandbox")
        os.system("mkdir -p /tmp/zero-human-sandbox")
        os.system("rm -f /home/paperclip/.openclaw/agents/main/sessions/*.lock")
        
        os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "")
        
        target_model = os.environ.get("OPENCLAW_MODEL", "openai/gpt-4o")
        subprocess.run(["/usr/bin/openclaw", "models", "set", target_model])
        
        subprocess.run(["/usr/bin/openclaw", "agent", "--agent", "main", "-m", message])
        
        cur.execute("UPDATE issues SET status = 'done' WHERE identifier = %s;", (identifier,))
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
