#!/usr/bin/env python3
import sys
import subprocess
import os
import time

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
        agent_id = os.environ.get("PAPERCLIP_AGENT_ID")
        if not agent_id:
            sys.exit(1)
            
        # Query the DB for the assigned issue currently 'in_progress' or 'todo'
        cmd = ["psql", "-h", "localhost", "-p", "5433", "-U", "paperclip", "-d", "paperclip", "-t", "-c", 
            f"SELECT identifier, title, description, company_id FROM issues WHERE assignee_agent_id = '{agent_id}' AND status IN ('in_progress', 'todo') ORDER BY created_at DESC LIMIT 1;"]
        
        env = os.environ.copy()
        env["PGPASSWORD"] = "paperclip"
        env["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "")
        
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        output = result.stdout.strip()
        if not output: sys.exit(0)
             
        parts = output.split('|')
        if len(parts) < 4: sys.exit(1)
             
        identifier = parts[0].strip()
        title = parts[1].strip()
        description = '|'.join(parts[2:-1]).strip()
        company_id = parts[-1].strip()
        
        # Fallback multi-tenant system to flat .env configuration!
        gh_token = os.environ.get("GITHUB_TOKEN", "")
        if gh_token:
            env["GITHUB_TOKEN"] = gh_token
        else:
            print(">>> CRITICAL ERROR: No GITHUB_TOKEN found in .env! Aborting cascade.")
            sys.exit(1)
        
        agent_roles = ["The Architect", "The Grunt", "The Pedant", "The Scribe"]
        
        # Dynamically set the OpenClaw Active Model based on .env!
        target_model = os.environ.get("OPENCLAW_MODEL", "openai/gpt-4o")
        subprocess.run(["/usr/bin/openclaw", "models", "set", target_model], env=env, check=False)
        
        subprocess.run("rm -rf /tmp/zero-human-sandbox/*", shell=True, check=False)
        subprocess.run(["mkdir", "-p", "/tmp/zero-human-sandbox"], check=False)
        
        for role in agent_roles:
            message = f"You are {role}. This is step in a 4-agent cascade pipeline handling Ticket: {identifier} - {title}. Output explicit terminal logs narrating your specific role's action. Instructions: {description}. Execute strictly autonomously in /tmp/zero-human-sandbox/, use tools if needed, and exit smoothly when your phase is complete."
            print(f">>> Reassigning Ticket {identifier} to {role} ...")
            
            result = subprocess.run(["/usr/bin/openclaw", "agent", "--agent", "main", "-m", message], env=env, check=False, capture_output=True, text=True)
            
            if result.stdout: print(result.stdout)
            if result.stderr: print(result.stderr, file=sys.stderr)
            
            if result.returncode != 0:
                print(f"Agent {role} failed! Code: {result.returncode}")
                error_body = (result.stderr if result.stderr else result.stdout)[-800:].replace("'", "''")
                safe_msg = f"**{role} crashed during execution!**\n\nThe AI Pipeline encountered a terminal system error and failed to generate the Pull Request:\n\n```plaintext\n{error_body}\n```"
                
                subprocess.run(["psql", "-h", "localhost", "-p", "5433", "-U", "paperclip", "-d", "paperclip", "-c", 
                                f"INSERT INTO issue_comments (id, company_id, issue_id, author_agent_id, body, created_at, updated_at) VALUES (gen_random_uuid(), (SELECT company_id FROM issues WHERE identifier='{identifier}'), (SELECT id FROM issues WHERE identifier='{identifier}'), '{agent_id}', '{safe_msg}', NOW(), NOW());"], env=env)
                subprocess.run(["psql", "-h", "localhost", "-p", "5433", "-U", "paperclip", "-d", "paperclip", "-c", f"UPDATE issues SET status = 'error', completed_at = NOW() WHERE identifier = '{identifier}';"], env=env)
                sys.exit(1)
            time.sleep(1)
        
        # Complete issue in Postgres
        print(f">>> All agents successfully executed. Resolving {identifier} in Database.")
        subprocess.run(["psql", "-h", "localhost", "-p", "5433", "-U", "paperclip", "-d", "paperclip", "-c", f"UPDATE issues SET status = 'done', completed_at = NOW() WHERE identifier = '{identifier}';"], env=env)
        
        sys.exit(0)
        
    except Exception as e:
        print(f"Bridge execution failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
