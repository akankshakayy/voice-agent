#!/usr/bin/env python3
"""
Multi-Session Orchestrator Server
Coordinates work between multiple Claude Code sessions
Enables parallel development with real-time synchronization
"""

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime
from typing import Dict, List, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pydantic import BaseModel
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# Data Models
# ============================================================================

class Task(BaseModel):
    id: str = None  # Auto-generated if not provided
    title: str
    description: str
    status: str = "pending"  # pending | in_progress | completed | blocked
    assigned_to: str = None  # Session ID
    priority: int = 1
    dependencies: List[str] = []
    created_at: str = None
    updated_at: str = None

class Session(BaseModel):
    id: str
    name: str
    status: str  # connected | working | idle | disconnected
    current_task: str = None
    working_on: str = None  # File path or task
    last_heartbeat: str = None

class Message(BaseModel):
    from_session: str
    to_session: str = None  # None = broadcast
    type: str  # status_update | task_complete | file_change | alert | query
    data: dict
    timestamp: str = None

# ============================================================================
# Database Setup
# ============================================================================

class OrchestratorDB:
    def __init__(self, db_path="orchestrator.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                name TEXT,
                status TEXT,
                current_task TEXT,
                working_on TEXT,
                last_heartbeat TIMESTAMP,
                created_at TIMESTAMP
            )
        """)

        # Tasks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT,
                description TEXT,
                status TEXT,
                assigned_to TEXT,
                priority INTEGER,
                dependencies TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
        """)

        # Messages table (for history)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                from_session TEXT,
                to_session TEXT,
                type TEXT,
                data TEXT,
                timestamp TIMESTAMP
            )
        """)

        # Work log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS work_log (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                task_id TEXT,
                action TEXT,
                details TEXT,
                timestamp TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()

    def execute(self, sql, params=()):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        conn.close()

    def query(self, sql, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(sql, params)
        results = cursor.fetchall()
        conn.close()
        return results

# ============================================================================
# Orchestrator Core
# ============================================================================

class SessionOrchestrator:
    def __init__(self):
        self.db = OrchestratorDB()
        self.active_sessions: Dict[str, WebSocket] = {}
        self.session_info: Dict[str, Session] = {}
        self.task_queue: List[Task] = []
        self.message_buffer: Dict[str, List[Message]] = {}

    async def register_session(self, session_id: str, name: str, websocket: WebSocket):
        """Register a new Claude Code session"""
        self.active_sessions[session_id] = websocket
        session = Session(
            id=session_id,
            name=name,
            status="connected",
            last_heartbeat=datetime.now().isoformat()
        )
        self.session_info[session_id] = session

        self.db.execute("""
            INSERT INTO sessions (id, name, status, last_heartbeat, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, name, "connected", datetime.now(), datetime.now()))

        # Notify all sessions of new connection
        await self.broadcast_message(Message(
            from_session="SYSTEM",
            type="session_joined",
            data={"session_id": session_id, "name": name},
            timestamp=datetime.now().isoformat()
        ))

        logger.info(f"✓ Session registered: {name} ({session_id})")

    async def unregister_session(self, session_id: str):
        """Remove a session when it disconnects"""
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]

        self.db.execute("""
            UPDATE sessions SET status = ? WHERE id = ?
        """, ("disconnected", session_id))

        await self.broadcast_message(Message(
            from_session="SYSTEM",
            type="session_left",
            data={"session_id": session_id},
            timestamp=datetime.now().isoformat()
        ))

        logger.info(f"✓ Session disconnected: {session_id}")

    async def assign_task(self, task: Task, session_id: str):
        """Assign a task to a specific session"""
        task.assigned_to = session_id
        task.status = "assigned"

        self.db.execute("""
            UPDATE tasks SET assigned_to = ?, status = ?, updated_at = ?
            WHERE id = ?
        """, (session_id, "assigned", datetime.now(), task.id))

        # Send task to session
        if session_id in self.active_sessions:
            await self.send_message(session_id, Message(
                from_session="SYSTEM",
                to_session=session_id,
                type="task_assigned",
                data=task.dict(),
                timestamp=datetime.now().isoformat()
            ))

    async def get_next_task(self, session_id: str) -> Task:
        """Get the next available task for a session"""
        # Find tasks in priority order
        results = self.db.query("""
            SELECT * FROM tasks
            WHERE status = 'pending'
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
        """)

        if results:
            row = results[0]
            task = Task(
                id=row["id"],
                title=row["title"],
                description=row["description"],
                status=row["status"],
                priority=row["priority"]
            )
            await self.assign_task(task, session_id)
            return task

        return None

    async def update_task_status(self, task_id: str, status: str, session_id: str):
        """Update task status (in_progress, completed, blocked)"""
        self.db.execute("""
            UPDATE tasks SET status = ?, assigned_to = ?, updated_at = ?
            WHERE id = ?
        """, (status, session_id if status == "in_progress" else None, datetime.now(), task_id))

        # Notify all sessions
        await self.broadcast_message(Message(
            from_session=session_id,
            type="task_status_update",
            data={"task_id": task_id, "status": status},
            timestamp=datetime.now().isoformat()
        ))

    async def send_message(self, to_session_id: str, message: Message):
        """Send message to a specific session"""
        if to_session_id in self.active_sessions:
            try:
                await self.active_sessions[to_session_id].send_json(message.dict())
            except Exception as e:
                logger.error(f"Failed to send message: {e}")

    async def broadcast_message(self, message: Message):
        """Broadcast message to all active sessions"""
        message.timestamp = datetime.now().isoformat()

        self.db.execute("""
            INSERT INTO messages (id, from_session, to_session, type, data, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (str(uuid.uuid4()), message.from_session, None, message.type,
              json.dumps(message.data), message.timestamp))

        disconnected = []
        for session_id, websocket in self.active_sessions.items():
            try:
                await websocket.send_json(message.dict())
            except Exception as e:
                logger.error(f"Failed to broadcast to {session_id}: {e}")
                disconnected.append(session_id)

        # Clean up disconnected sessions
        for session_id in disconnected:
            await self.unregister_session(session_id)

    def get_status(self) -> dict:
        """Get current orchestrator status"""
        return {
            "active_sessions": len(self.active_sessions),
            "sessions": {
                sid: {
                    "name": self.session_info.get(sid).name if sid in self.session_info else "Unknown",
                    "status": self.session_info.get(sid).status if sid in self.session_info else "unknown",
                    "current_task": self.session_info.get(sid).current_task if sid in self.session_info else None
                }
                for sid in self.active_sessions.keys()
            },
            "pending_tasks": len([t for t in self.task_queue if t.status == "pending"]),
            "in_progress_tasks": len([t for t in self.task_queue if t.status == "in_progress"])
        }

# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(title="Multi-Session Orchestrator", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = SessionOrchestrator()

# ============================================================================
# REST Endpoints
# ============================================================================

@app.get("/status")
async def get_status():
    """Get orchestrator status"""
    return orchestrator.get_status()

@app.post("/tasks")
async def create_task(task: Task):
    """Create a new task"""
    if not task.id:
        task.id = str(uuid.uuid4())

    task.created_at = datetime.now().isoformat()
    task.updated_at = datetime.now().isoformat()
    task.status = "pending"

    orchestrator.db.execute("""
        INSERT INTO tasks (id, title, description, status, priority, dependencies, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (task.id, task.title, task.description, task.status, task.priority,
          json.dumps(task.dependencies), task.created_at, task.updated_at))

    orchestrator.task_queue.append(task)

    await orchestrator.broadcast_message(Message(
        from_session="SYSTEM",
        type="task_created",
        data=task.dict(),
        timestamp=datetime.now().isoformat()
    ))

    logger.info(f"✓ Task created: {task.title}")
    return {"task_id": task.id}

@app.get("/tasks")
async def list_tasks(status: str = None):
    """List all tasks"""
    if status:
        results = orchestrator.db.query("""
            SELECT * FROM tasks WHERE status = ? ORDER BY priority DESC
        """, (status,))
    else:
        results = orchestrator.db.query("SELECT * FROM tasks ORDER BY priority DESC")

    return [dict(row) for row in results]

@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get specific task"""
    results = orchestrator.db.query("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if results:
        return dict(results[0])
    return {"error": "Task not found"}

# ============================================================================
# WebSocket Endpoint
# ============================================================================

@app.websocket("/ws/{session_name}")
async def websocket_endpoint(websocket: WebSocket, session_name: str):
    """WebSocket endpoint for Claude Code sessions"""
    session_id = str(uuid.uuid4())

    try:
        await websocket.accept()
        logger.info(f"✓ WebSocket accepted for session: {session_name}")
    except Exception as e:
        logger.error(f"✗ WebSocket accept failed: {e}")
        raise

    # Register session
    await orchestrator.register_session(session_id, session_name, websocket)

    try:
        while True:
            # Receive message from session
            message_data = await websocket.receive_json()
            message = Message(**message_data)

            # Handle different message types
            if message.type == "task_complete":
                task_id = message.data.get("task_id")
                await orchestrator.update_task_status(task_id, "completed", session_id)

                # Get next task
                next_task = await orchestrator.get_next_task(session_id)
                if next_task:
                    await orchestrator.send_message(session_id, Message(
                        from_session="SYSTEM",
                        to_session=session_id,
                        type="task_assigned",
                        data=next_task.dict(),
                        timestamp=datetime.now().isoformat()
                    ))

            elif message.type == "task_blocked":
                task_id = message.data.get("task_id")
                await orchestrator.update_task_status(task_id, "blocked", session_id)

            elif message.type == "status_update":
                orchestrator.session_info[session_id].working_on = message.data.get("working_on")
                await orchestrator.broadcast_message(message)

            elif message.type == "file_changed":
                await orchestrator.broadcast_message(message)

            elif message.type == "alert":
                await orchestrator.broadcast_message(message)

            elif message.type == "heartbeat":
                orchestrator.session_info[session_id].last_heartbeat = datetime.now().isoformat()

            else:
                await orchestrator.broadcast_message(message)

            logger.info(f"Message from {session_name}: {message.type}")

    except WebSocketDisconnect:
        await orchestrator.unregister_session(session_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await orchestrator.unregister_session(session_id)

# ============================================================================
# Health Check
# ============================================================================

@app.get("/health")
async def health():
    """Health check"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║   Multi-Session Orchestrator Server                       ║
    ║   Coordinating Claude Code parallel development           ║
    ╚═══════════════════════════════════════════════════════════╝

    WebSocket: ws://localhost:8000/ws/{session_name}
    REST API:  http://localhost:8000
    Status:    http://localhost:8000/status
    Health:    http://localhost:8000/health

    Starting server...
    """)

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
