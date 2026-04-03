from celery import Celery
import os
import sys

# Add the current directory to sys.path to import openclaw_bridge_cascade
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from openclaw_bridge_cascade import run_bridge

app = Celery('zero_human', broker=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'))

@app.task(name='tasks.process_issue')
def process_issue(agent_id, issue_id):
    print(f">>> Celery task received: Processing issue {issue_id} for agent {agent_id}")
    success = run_bridge(agent_id=agent_id, identifier=issue_id)
    if success:
        return {"status": "success", "issue_id": issue_id}
    else:
        raise Exception(f"Bridge execution failed for issue {issue_id}")

if __name__ == '__main__':
    app.start()
