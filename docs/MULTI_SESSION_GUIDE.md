# 🚀 Multi-Session Orchestrator Guide
## Parallel Claude Code Development with Real-Time Coordination

---

## 📋 Overview

The **Multi-Session Orchestrator** enables multiple Claude Code AI sessions to work on the same project **in parallel** while coordinating efficiently.

### What It Does:
- ✅ Tracks multiple Claude sessions simultaneously
- ✅ Distributes tasks to sessions automatically
- ✅ Real-time communication between sessions
- ✅ Conflict detection and prevention
- ✅ Shared state and progress tracking
- ✅ Automatic task queue management

### Why You Want This:
```
Without Orchestrator:
Session A works on feature X (30 min)
Session B waits...
Session C waits...
Total time: 30 min (serial)

With Orchestrator:
Session A works on feature X (10 min)
Session B works on feature Y (10 min)
Session C runs tests (10 min)
All in parallel!
Total time: 10 min (parallel) ✅
```

---

## 🔧 Installation

### Prerequisites
```bash
pip install fastapi uvicorn websockets pydantic
```

### Start the Orchestrator Server

```bash
python orchestrator_server.py
```

Output:
```
╔═══════════════════════════════════════════════════════════╗
║   Multi-Session Orchestrator Server                       ║
║   Coordinating Claude Code parallel development           ║
╚═══════════════════════════════════════════════════════════╝

WebSocket: ws://localhost:8000/ws/{session_name}
REST API:  http://localhost:8000
Status:    http://localhost:8000/status
Health:    http://localhost:8000/health

Starting server...
```

---

## 📲 Usage for Claude Code Sessions

### Quick Start: Single Session

```python
import asyncio
from orchestrator_client import OrchestratorClient

async def main():
    # Connect to orchestrator
    client = OrchestratorClient(
        orchestrator_url="ws://localhost:8000",
        session_name="Backend-Developer"
    )
    
    await client.connect()
    
    # Get next task
    task = await client.request_task()
    print(f"Working on: {task['title']}")
    
    # Update status
    await client.update_status(f"Implementing {task['title']}")
    
    # Notify about file changes
    await client.notify_file_change("app/models.py", "modified")
    
    # Complete task
    await client.complete_task(task['id'], result="Done!")
    
    await client.disconnect()

asyncio.run(main())
```

---

## 🎯 Typical Workflow: 3 Parallel Sessions

### Session 1: Frontend Developer
```python
async def frontend_session():
    client = OrchestratorClient(session_name="Frontend")
    await client.connect()
    
    while True:
        task = await client.request_task()
        if not task:
            break
        
        await client.update_status(f"Building {task['title']}")
        
        # Do frontend work...
        await client.notify_file_change("src/components/Header.tsx", "created")
        await client.notify_file_change("src/styles/header.css", "created")
        
        await client.complete_task(task['id'])
        await client.notify_sessions("Frontend components ready for integration!")
    
    await client.disconnect()
```

### Session 2: Backend Developer
```python
async def backend_session():
    client = OrchestratorClient(session_name="Backend")
    await client.connect()
    
    while True:
        task = await client.request_task()
        if not task:
            break
        
        await client.update_status(f"Implementing {task['title']}")
        
        # Do backend work...
        await client.notify_file_change("app/api/routes.py", "modified")
        await client.notify_file_change("app/services/user_service.py", "created")
        
        await client.complete_task(task['id'])
        await client.notify_sessions("API endpoints ready!")
    
    await client.disconnect()
```

### Session 3: QA/Testing
```python
async def qa_session():
    client = OrchestratorClient(session_name="QA-Tester")
    await client.connect()
    
    # Register handler for file changes
    async def on_file_change(message):
        file = message['data']['file_path']
        print(f"Detected change: {file}")
        # Run tests on changed files
    
    await client.register_handler("file_changed", on_file_change)
    
    while True:
        task = await client.request_task()
        if not task:
            break
        
        await client.update_status(f"Testing {task['title']}")
        
        # Run tests...
        test_result = "✅ All tests passed"
        await client.complete_task(task['id'], result=test_result)
        await client.notify_sessions(f"QA: {test_result}")
    
    await client.disconnect()
```

### Run All Sessions in Parallel
```python
import asyncio

async def run_all_sessions():
    # Create tasks for all sessions
    tasks = [
        frontend_session(),
        backend_session(),
        qa_session()
    ]
    
    # Run all in parallel
    await asyncio.gather(*tasks)

# Start all sessions
asyncio.run(run_all_sessions())
```

---

## 📊 Task Management

### Create Tasks via API

```bash
# Create a task
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Implement User Authentication",
    "description": "Add JWT-based auth to API",
    "priority": 1
  }'

# List all pending tasks
curl http://localhost:8000/tasks?status=pending

# List all tasks
curl http://localhost:8000/tasks
```

### Create Tasks from Claude Session

```python
# Create multiple tasks
tasks = [
    ("Implement API endpoints", "Create REST API for users", 3),
    ("Build frontend components", "Create React components", 2),
    ("Write unit tests", "Test coverage > 80%", 1),
    ("Setup database", "PostgreSQL with migrations", 3),
    ("Deploy to staging", "Container deployment", 1),
]

for title, desc, priority in tasks:
    client.create_task(title, desc, priority)
```

---

## 🔍 Monitor Status

### Check Orchestrator Status

```bash
# Health check
curl http://localhost:8000/health

# Full status
curl http://localhost:8000/status

# Response:
{
  "active_sessions": 3,
  "sessions": {
    "session-1": {
      "name": "Frontend",
      "status": "connected",
      "current_task": "Build header component"
    },
    "session-2": {
      "name": "Backend",
      "status": "connected",
      "current_task": "Implement user routes"
    },
    "session-3": {
      "name": "QA-Tester",
      "status": "connected",
      "current_task": null
    }
  },
  "pending_tasks": 2,
  "in_progress_tasks": 3
}
```

### From Python

```python
client = OrchestratorClient()
status = client.get_status()

print(f"Active sessions: {status['active_sessions']}")
print(f"Pending tasks: {status['pending_tasks']}")

for sid, info in status['sessions'].items():
    print(f"  {info['name']}: {info['status']}")
```

---

## 📞 Inter-Session Communication

### Send Alert to All Sessions

```python
await client.notify_sessions("⚠️ Breaking changes detected in API!")
```

### Broadcast Custom Message

```python
await client.broadcast("custom_alert", {
    "severity": "high",
    "message": "Database migration in progress",
    "estimated_time": "5 minutes"
})
```

### Listen for Specific Messages

```python
async def on_alert(message):
    print(f"ALERT: {message['data']['message']}")

await client.register_handler("custom_alert", on_alert)
```

---

## 🔄 Message Types

| Type | Sender | Usage |
|------|--------|-------|
| `heartbeat` | Session | Keep-alive signal |
| `task_assigned` | Server | Task assigned to session |
| `task_complete` | Session | Session completed a task |
| `task_blocked` | Session | Task waiting for dependency |
| `status_update` | Session | Update what session is working on |
| `file_changed` | Session | Notify of file modifications |
| `alert` | Session | Send alert to other sessions |
| `session_joined` | Server | New session connected |
| `session_left` | Server | Session disconnected |
| `task_created` | Server | New task created |

---

## 🎓 Sahayak Example: Full Workflow

### Setup: Create Tasks for DC Feature

```python
# Create feature tasks
client.create_task(
    title="DC Call Recording Backend",
    description="Implement DC call recording logic with call_type filtering",
    priority=3
)

client.create_task(
    title="DC Recordings API Endpoints",
    description="Add /api/recordings?call_type=dc filtering",
    priority=3
)

client.create_task(
    title="Frontend DC Tabs UI",
    description="Add RM/DC tabs to recordings page",
    priority=2
)

client.create_task(
    title="Integration Testing",
    description="Test DC calls end-to-end",
    priority=2
)

client.create_task(
    title="Deployment",
    description="Deploy r0035 with DC feature",
    priority=1
)
```

### Execution

```
Time: T=0
├─ Session A (Backend): Starts "DC Call Recording Backend"
├─ Session B (Frontend): Starts "Frontend DC Tabs UI"
└─ Session C (QA): Waits for tasks

Time: T=10min
├─ Session A: ✅ Completes backend, notifies others
│   └─ Creates new tasks for API endpoints
├─ Session B: ✅ Completes frontend, notifies others
│   └─ "Frontend ready for backend integration"
└─ Session C: Starts "Integration Testing"

Time: T=20min
├─ Session A: Starts "DC Recordings API Endpoints"
├─ Session B: Starts "Deployment"
└─ Session C: ✅ Completes testing, reports results

Time: T=30min
├─ Session A: ✅ API endpoints complete
├─ Session B: ✅ Deployed to staging
└─ All sessions: Done! Feature shipped!
```

---

## 🚀 Deploy Orchestrator to Server

### 1. Copy Files to Server

```bash
scp orchestrator_server.py akanksha@indev.eko.in:~/orchestrator/
scp orchestrator_client.py akanksha@indev.eko.in:~/orchestrator/
scp requirements.txt akanksha@indev.eko.in:~/orchestrator/
```

### 2. Start on Server

```bash
ssh akanksha@indev.eko.in

cd ~/orchestrator
pip install -r requirements.txt
nohup python orchestrator_server.py > orchestrator.log 2>&1 &
```

### 3. Connect Sessions to Server

```python
# Change connection URL
client = OrchestratorClient(
    orchestrator_url="ws://indev.eko.in:8000",  # ← Server URL
    session_name="Frontend-Developer"
)
```

---

## 🔐 Security Notes

- Orchestrator listens on `0.0.0.0:8000` (open to all)
- Add firewall rules for production
- Consider adding authentication tokens
- Use WSS (secure WebSocket) for remote connections

---

## 📈 Performance Tips

1. **Task Priority**: Set priorities (1-10) so critical tasks run first
2. **Task Dependencies**: Link tasks so they run in correct order
3. **Session Count**: 3-5 sessions optimal; more might bottleneck
4. **Task Size**: Break large tasks into smaller chunks
5. **File Watching**: Minimize file notifications to reduce overhead

---

## 🐛 Troubleshooting

### Session can't connect
```
✗ Failed to connect: Connection refused
```
**Solution**: Make sure orchestrator server is running
```bash
python orchestrator_server.py
```

### Tasks stuck in pending
```
pending_tasks: 15
```
**Solution**: Check if sessions are actually requesting tasks
```python
task = await client.request_task()  # Sessions must do this
```

### No messages received
```
Registered handler but no messages appearing
```
**Solution**: Make sure handler is registered before messages arrive
```python
await client.register_handler("message_type", handler)
# THEN listen in a loop
```

---

## 📚 Reference

### Client API

```python
# Connection
await client.connect()
await client.disconnect()

# Tasks
task = await client.request_task()
await client.complete_task(task_id, result="...")
await client.block_task(task_id, reason="Waiting for...")

# Status
await client.update_status("Working on X")
client.get_status()
client.get_tasks(status="pending")
client.create_task(title, description, priority)

# Communication
await client.notify_sessions("Message")
await client.broadcast("msg_type", data)
await client.notify_file_change(file_path, action)
await client.register_handler("msg_type", async_handler)

# Messages
await client.send_message("type", data)
```

---

## ✅ Next Steps

1. **Start Orchestrator Server**
   ```bash
   python orchestrator_server.py
   ```

2. **Launch Your Sessions**
   ```bash
   # In separate terminals:
   python session_frontend.py
   python session_backend.py
   python session_qa.py
   ```

3. **Monitor Progress**
   ```bash
   watch curl http://localhost:8000/status
   ```

4. **Watch It Work! 🎉**
   Multiple Claude sessions coordinating in real-time!

---

**Questions?** Check the source code in `orchestrator_server.py` and `orchestrator_client.py`!
