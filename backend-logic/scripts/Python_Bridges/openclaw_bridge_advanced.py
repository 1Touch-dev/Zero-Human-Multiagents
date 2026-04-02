#!/usr/bin/env python3
import sys
import subprocess
import os

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
            print("No PAPERCLIP_AGENT_ID found in environment.", file=sys.stderr)
            sys.exit(1)
            
        print(f"Connecting to Postgres to fetch goal for agent {agent_id}...")
        
        # Query the DB for the assigned issue currently 'in_progress' or 'todo'
        cmd = [
            "psql", "-h", "localhost", "-p", "5433", "-U", "paperclip", "-d", "paperclip", 
            "-t", "-c", 
            f"SELECT identifier, title, description FROM issues WHERE assignee_agent_id = '{agent_id}' AND status IN ('in_progress', 'todo') ORDER BY created_at DESC LIMIT 1;"
        ]
        
        env = os.environ.copy()
        env["PGPASSWORD"] = "paperclip"
        
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        
        output = result.stdout.strip()
        if not output:
             print("No active issue found for this agent in the database.", file=sys.stderr)
             sys.exit(0) # Exit cleanly to prevent error loop
             
        # Parse the raw psql output (e.g. " PAP-4 | title | desc")
        parts = output.split('|')
        if len(parts) < 3:
             print(f"Failed to parse DB output: {output}", file=sys.stderr)
             sys.exit(1)
             
        identifier = parts[0].strip()
        title = parts[1].strip()
        description = '|'.join(parts[2:]).strip()
        
        agent_role = sys.argv[1] if len(sys.argv) > 1 else "Unknown Agent"
            
        message = f"You are {agent_role}. Your goal is:\n\nTask Ticket: {identifier}\nTitle: {title}\nInstructions: {description}\n\nExecute this strictly autonomously on the file system. Return ONLY when finished without asking for human oversight."
        
        print(f"Triggering OpenClaw for {agent_role} with issue: {title}")
        
        env["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "")
        
        # Dynamically set the Active AI Model
        target_model = os.environ.get("OPENCLAW_MODEL", "openai/gpt-4o")
        subprocess.run(["/usr/bin/openclaw", "models", "set", target_model], env=env, check=False)
        
        # Call openclaw
        subprocess.run(["/usr/bin/openclaw", "agent", "--agent", "main", "-m", message], env=env, check=True)
        
        # Force issue to complete in DB if openclaw succeeds
        subprocess.run([
            "psql", "-h", "localhost", "-p", "5433", "-U", "paperclip", "-d", "paperclip", 
            "-c", f"UPDATE issues SET status = 'done', completed_at = NOW() WHERE identifier = '{identifier}';"
        ], env=env, capture_output=True)
        
        print(f"Successfully executed and closed {identifier}")
        sys.exit(0)
        
    except Exception as e:
        print(f"Bridge execution failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
