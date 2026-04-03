#!/usr/bin/env python3
import os
import hmac
import hashlib
import psycopg2
import re
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
import uvicorn

app = FastAPI(title="Zero-Human GitHub Webhook Server")

# V2 Addition: Celery Task Dispatcher
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'Python_Bridges'))
try:
    from tasks import process_issue
except ImportError:
    print(">>> WARNING: Could not import Celery 'process_issue' task. Falling back to DB-only updates.")
    process_issue = None

GITHUB_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "default_secret")
DB_DSN = os.environ.get("DATABASE_URL", "postgresql://paperclip:paperclip@localhost:5433/paperclip")

def verify_signature(payload: bytes, signature_header: str):
    if not signature_header:
        raise HTTPException(status_code=403, detail="Missing X-Hub-Signature-256")
    
    hash_object = hmac.new(GITHUB_SECRET.encode('utf-8'), msg=payload, digestmod=hashlib.sha256)
    expected_signature = "sha256=" + hash_object.hexdigest()
    
    if not hmac.compare_digest(expected_signature, signature_header):
        raise HTTPException(status_code=403, detail="Invalid signature")

def process_issue_comment(event_data: dict):
    """
    Parses GitHub issue comment payloads, matching the issue title to a Paperclip Ticket (e.g. [PAP-14]),
    and appends the human feedback directly to the Paperclip Postgres database to awaken the AI agents.
    """
    # Only process newly created comments
    if event_data.get("action") != "created":
        return

    comment_body = event_data.get("comment", {}).get("body", "")
    author = event_data.get("sender", {}).get("login", "")
    
    # We only care about humans commenting; ignore AI bot comments
    if "[BOT]" in author.upper() or author == "zero-human-ai":
        return

    issue_data = event_data.get("issue", {})
    # For pull_request_review_comment events, it's under 'pull_request'
    if not issue_data:
        issue_data = event_data.get("pull_request", {})

    issue_title = issue_data.get("title", "")
    
    # The Paperclip orchestration creates PRs with titles like "[PAP-14] Add Login Features"
    match = re.search(r'\[(PAP-\d+)\]', issue_title)
    if not match:
        print(f"Ignored: Could not extract PAP identifier from title: '{issue_title}'")
        return

    identifier = match.group(1)
    print(f"Received feedback for {identifier} from @{author}")

    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        
        # Fetch existing description to append the human's feedback to it
        cur.execute("SELECT description, status FROM issues WHERE identifier = %s;", (identifier,))
        res = cur.fetchone()
        
        if not res:
            print(f"Issue {identifier} not found in Paperclip DB.")
            return

        current_desc = res[0]
        issue_status = res[1]
        
        # Append feedback cleanly
        new_desc = current_desc + f"\n\n--- HUMAN FEEDBACK FROM @{author} ---\n{comment_body}"
        
        # Re-queue issue to 'todo' status to trigger the Paperclip heartbeat and awaken The Architect
        cur.execute("""
            UPDATE issues 
            SET status = 'todo', 
                description = %s,
                updated_at = NOW()
            WHERE identifier = %s
            RETURNING assignee_agent_id;
        """, (new_desc, identifier))
        
        assignee_agent_id = cur.fetchone()[0]
        
        conn.commit()
        cur.close()
        conn.close()
        
        print(f"Successfully re-queued {identifier} for AI revision.")
        
        # V2: Async Dispatch to Celery
        if process_issue:
            print(f">>> Dispatching Celery task for {identifier} (Agent: {assignee_agent_id})")
            process_issue.delay(assignee_agent_id, identifier)
        
    except Exception as e:
         print(f"Database error processing webhook: {e}")

@app.post("/webhook")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    signature = request.headers.get("X-Hub-Signature-256")
    payload = await request.body()
    
    # Authenticate the webhook payload
    verify_signature(payload, signature)
    
    event_type = request.headers.get("X-GitHub-Event")
    event_data = await request.json()

    # We want to listen to comments on issues and PR reviews
    if event_type in ["issue_comment", "pull_request_review_comment"]:
        background_tasks.add_task(process_issue_comment, event_data)
        return {"status": "Ack", "message": "Feedback processing initiated."}
    
    return {"status": "Ack", "message": "Ignored event type."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
