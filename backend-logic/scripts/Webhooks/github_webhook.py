#!/usr/bin/env python3
import os
import hmac
import hashlib
import psycopg2
import re
import json
import urllib.error
import urllib.request
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
import uvicorn

app = FastAPI(title="Zero-Human GitHub Webhook Server")

GITHUB_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "default_secret")
DB_DSN = os.environ.get("DATABASE_URL", "postgresql://paperclip:paperclip@localhost:5433/paperclip")
BACKEND_API_URL = os.environ.get("BACKEND_API_URL", "http://localhost:8100").rstrip("/")

def verify_signature(payload: bytes, signature_header: str):
    if not signature_header:
        raise HTTPException(status_code=403, detail="Missing X-Hub-Signature-256")
    
    hash_object = hmac.new(GITHUB_SECRET.encode('utf-8'), msg=payload, digestmod=hashlib.sha256)
    expected_signature = "sha256=" + hash_object.hexdigest()
    
    if not hmac.compare_digest(expected_signature, signature_header):
        raise HTTPException(status_code=403, detail="Invalid signature")

def enqueue_task_via_backend_api(identifier: str, author: str, comment_body: str, event_data: dict) -> tuple[bool, str]:
    repository = event_data.get("repository", {})
    repo_url = repository.get("clone_url") or repository.get("html_url") or ""
    api_payload = {
        "issue_id": identifier,
        "repo_url": repo_url,
        "user_id": author or "github-webhook",
        "metadata": {
            "source": "github_webhook",
            "comment_body": comment_body,
            "event_action": event_data.get("action"),
            "event_type_hint": (
                "pull_request_review_comment" if event_data.get("pull_request") else "issue_comment"
            ),
            "issue_title": (event_data.get("issue", {}) or event_data.get("pull_request", {})).get("title", ""),
        },
    }
    request = urllib.request.Request(
        url=f"{BACKEND_API_URL}/task",
        data=json.dumps(api_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8", errors="replace").strip()
            data = json.loads(body) if body else {}
            task_id = str(data.get("task_id", "")).strip()
            if 200 <= response.status < 300 and task_id:
                return True, task_id
            return False, f"Unexpected /task response (status={response.status}, body={body})"
    except urllib.error.HTTPError as err:
        error_body = err.read().decode("utf-8", errors="replace")
        return False, f"/task HTTPError {err.code}: {error_body}"
    except urllib.error.URLError as err:
        return False, f"/task URLError: {err.reason}"
    except Exception as err:  # noqa: BLE001 - webhook should always fail open to fallback
        return False, f"/task unexpected error: {err}"


def fallback_requeue_in_db(identifier: str, author: str, comment_body: str):
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
            WHERE identifier = %s;
        """, (new_desc, identifier))
        
        conn.commit()
        cur.close()
        conn.close()
        
        print(f"Successfully re-queued {identifier} for AI revision via DB fallback.")
        
    except Exception as e:
         print(f"Database error processing webhook fallback: {e}")


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
    enqueued, result = enqueue_task_via_backend_api(identifier, author, comment_body, event_data)
    if enqueued:
        print(f"Enqueued {identifier} via backend API. task_id={result}")
        return

    print(f"Backend API enqueue failed for {identifier}: {result}. Falling back to DB re-queue.")
    fallback_requeue_in_db(identifier, author, comment_body)

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
