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
                    parts = line.strip().split('=', 1)
                    if len(parts) == 2:
                        k, v = parts
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")

def upload_to_s3(file_path, bucket, object_name):
    import boto3
    from botocore.exceptions import NoCredentialsError
    s3 = boto3.client('s3')
    try:
        s3.upload_file(file_path, bucket, object_name)
        print(f">>> Artifact {object_name} uploaded to S3 bucket {bucket}")
        return True
    except FileNotFoundError:
        print("The file was not found")
        return False
    except NoCredentialsError:
        print("Credentials not available")
        return False

def run_bridge(agent_id=None, identifier=None):
    load_env()
    try:
        if not agent_id:
            agent_id = os.environ.get("PAPERCLIP_AGENT_ID")
        
        if not agent_id:
            print(">>> ERROR: No Agent ID provided!")
            return False
            
        # Refined query to prioritize the specific identifier if provided
        query = f"SELECT identifier, title, description, company_id FROM issues WHERE assignee_agent_id = '{agent_id}'"
        if identifier:
            query += f" AND identifier = '{identifier}'"
        else:
            query += " AND status IN ('in_progress', 'todo')"
        query += " ORDER BY created_at DESC LIMIT 1;"
        
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
        
        sandbox_path = f"/tmp/zero-human-sandbox/{identifier}"
        subprocess.run(f"rm -rf {sandbox_path}", shell=True, check=False)
        subprocess.run(["mkdir", "-p", sandbox_path], check=False)
        
        # 1. The Architect
        architect_msg = f"You are The Architect. This is the first step in a multi-agent pipeline handling Ticket: {identifier} - {title}. Your goal is to research the codebase and output a high-level implementation plan. Instructions: {description}. Execute strictly autonomously in {sandbox_path}, use tools if needed, and exit smoothly when your phase is complete."
        print(f">>> Executing The Architect for Ticket {identifier} ...")
        subprocess.run(["/usr/bin/openclaw", "agent", "--agent", "main", "-m", architect_msg], env=env, check=True)

        # 2. Iterative Dev/QA Loop (Grunt & Pedant)
        max_retries = 3
        retry_count = 0
        while retry_count < max_retries:
            # The Grunt
            grunt_msg = f"You are The Grunt. This is a development step for Ticket: {identifier}. Your goal is to implement the changes requested. Instructions: {description}. work in {sandbox_path}. If this is a retry, incorporate the feedback from the Pedant below."
            if retry_count > 0:
                grunt_msg += f"\n\nPREVIOUS QA FEEDBACK: {last_qa_report}"
            
            print(f">>> Executing The Grunt (Attempt {retry_count + 1}) ...")
            subprocess.run(["/usr/bin/openclaw", "agent", "--agent", "main", "-m", grunt_msg], env=env, check=True)

            # The Pedant
            pedant_msg = f"You are The Pedant. Your goal is to conduct a syntax check and manual-style verification of the work done by The Grunt in {sandbox_path}. Instructions: {description}. If the work is incomplete or has errors, start your response with 'VERIFICATION_FAILED:' followed by the issues. If it is correct, start with 'VERIFICATION_PASSED'."
            print(f">>> Executing The Pedant for QA ...")
            result = subprocess.run(["/usr/bin/openclaw", "agent", "--agent", "main", "-m", pedant_msg], env=env, capture_output=True, text=True)
            
            last_qa_report = result.stdout if result.stdout else ""
            if "VERIFICATION_PASSED" in last_qa_report:
                print(">>> QA Passed! Proceeding to deployment.")
                break
            else:
                print(f">>> QA Failed (Attempt {retry_count + 1}). Looping back to Grunt.")
                retry_count += 1
                if retry_count == max_retries:
                    print(">>> Max retries reached. Failing the pipeline.")
                    # Handle failure
                    safe_msg = f"**Pipeline failed after {max_retries} attempts!**\n\nThe Pedant kept failing verification:\n\n```plaintext\n{last_qa_report[-800:]}\n```"
                    safe_msg_sql = safe_msg.replace("'", "''")
                    subprocess.run(["psql", "-h", "localhost", "-p", "5433", "-U", "paperclip", "-d", "paperclip", "-c", 
                                    f"INSERT INTO issue_comments (id, company_id, issue_id, author_agent_id, body, created_at, updated_at) VALUES (gen_random_uuid(), (SELECT company_id FROM issues WHERE identifier='{identifier}'), (SELECT id FROM issues WHERE identifier='{identifier}'), '{agent_id}', '{safe_msg_sql}', NOW(), NOW());"], env=env)
                    subprocess.run(["psql", "-h", "localhost", "-p", "5433", "-U", "paperclip", "-d", "paperclip", "-c", f"UPDATE issues SET status = 'error', completed_at = NOW() WHERE identifier = '{identifier}';"], env=env)
                    return False

        # 3. The Scribe
        scribe_msg = f"You are The Scribe. The work in {sandbox_path} has been verified for Ticket: {identifier}. Your goal is to document the changes and create the final Pull Request (or final report). Instructions: {description}. Exit smoothly when complete."
        print(f">>> Executing The Scribe for Deployment ...")
        subprocess.run(["/usr/bin/openclaw", "agent", "--agent", "main", "-m", scribe_msg], env=env, check=True)

        # 4. S3 Persistence (v2 Placeholder)
        bucket_name = os.environ.get("AWS_S3_BUCKET")
        if bucket_name:
            import tarfile
            archive_name = f"{identifier}_workspace.tar.gz"
            archive_path = os.path.join("/tmp", archive_name)
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(sandbox_path, arcname=os.path.basename(sandbox_path))
            upload_to_s3(archive_path, bucket_name, f"builds/{archive_name}")
            os.remove(archive_path)

        # Complete issue in Postgres
        print(f">>> All agents successfully executed. Resolving {identifier} in Database.")
        subprocess.run(["psql", "-h", "localhost", "-p", "5433", "-U", "paperclip", "-d", "paperclip", "-c", f"UPDATE issues SET status = 'done', completed_at = NOW() WHERE identifier = '{identifier}';"], env=env)
        
        return True
        
    except Exception as e:
        print(f"Bridge execution failed: {e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent_id", help="Overriding agent ID")
    parser.add_argument("--issue_id", help="Specific issue identifier")
    args = parser.parse_args()
    
    success = run_bridge(agent_id=args.agent_id, identifier=args.issue_id)
    sys.exit(0 if success else 1)
