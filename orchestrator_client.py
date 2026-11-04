#!/usr/bin/env python3
"""
Multi-Session Orchestrator Client
Used by Claude Code sessions to coordinate with other sessions
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Callable, Dict, Optional
import websockets
import requests
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OrchestratorClient:
    def __init__(self, orchestrator_url: str = "ws://localhost:8000",
                 session_name: str = "Claude Session"):
        """
        Initialize orchestrator client

        Args:
            orchestrator_url: WebSocket URL of orchestrator server
            session_name: Name of this Claude Code session
        """
        self.orchestrator_url = orchestrator_url
        self.session_name = session_name
        self.session_id = str(uuid.uuid4())
        self.websocket = None
        self.rest_url = orchestrator_url.replace("ws://", "http://").replace("wss://", "https://")
        self.message_handlers: Dict[str, Callable] = {}
        self.current_task = None
        self.running = False

    async def connect(self):
        """Connect to orchestrator server"""
        try:
            ws_url = f"{self.orchestrator_url}/ws/{self.session_name}"
            self.websocket = await websockets.connect(ws_url)
            self.running = True
            logger.info(f"✓ Connected to orchestrator: {self.session_name}")

            # Start listening for messages
            asyncio.create_task(self._listen_for_messages())

            # Start heartbeat
            asyncio.create_task(self._heartbeat())

        except Exception as e:
            logger.error(f"✗ Failed to connect: {e}")
            raise

    async def disconnect(self):
        """Disconnect from orchestrator"""
        self.running = False
        if self.websocket:
            await self.websocket.close()
        logger.info(f"✓ Disconnected: {self.session_name}")

    async def _listen_for_messages(self):
        """Listen for incoming messages from orchestrator"""
        try:
            async for message in self.websocket:
                data = json.loads(message)

                # Log message
                msg_type = data.get("type")
                logger.info(f"📨 Received: {msg_type}")

                # Route to handlers
                if msg_type in self.message_handlers:
                    await self.message_handlers[msg_type](data)

                # Handle system messages
                if msg_type == "task_assigned":
                    self.current_task = data.get("data")
                    logger.info(f"📋 Task assigned: {self.current_task.get('title')}")
                    await self._on_task_assigned(data.get("data"))

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"✗ Message listening error: {e}")

    async def _heartbeat(self):
        """Send periodic heartbeat to server"""
        while self.running:
            try:
                await self.send_message("heartbeat", {})
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

    async def send_message(self, msg_type: str, data: dict):
        """Send message to orchestrator"""
        if not self.websocket:
            logger.warning("Not connected to orchestrator")
            return

        message = {
            "from_session": self.session_id,
            "type": msg_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }

        try:
            await self.websocket.send(json.dumps(message))
            logger.debug(f"Sent: {msg_type}")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    async def broadcast(self, msg_type: str, data: dict):
        """Broadcast message to all sessions"""
        await self.send_message(msg_type, data)

    async def notify_sessions(self, message: str):
        """Send alert to all other sessions"""
        await self.send_message("alert", {"message": message})

    async def request_task(self):
        """Request next task from orchestrator"""
        try:
            response = requests.post(
                f"{self.rest_url}/tasks",
                json={"status": "pending"}
            )
            if response.status_code == 200:
                task = response.json()
                self.current_task = task
                logger.info(f"📋 Requested task: {task.get('title')}")
                return task
        except Exception as e:
            logger.error(f"Failed to request task: {e}")
        return None

    async def complete_task(self, task_id: str, result: str = ""):
        """Mark current task as complete"""
        await self.send_message("task_complete", {
            "task_id": task_id,
            "result": result
        })
        self.current_task = None
        logger.info(f"✅ Task completed: {task_id}")

    async def block_task(self, task_id: str, reason: str = ""):
        """Mark task as blocked (waiting for dependency)"""
        await self.send_message("task_blocked", {
            "task_id": task_id,
            "reason": reason
        })
        logger.warning(f"⛔ Task blocked: {task_id} - {reason}")

    async def update_status(self, working_on: str):
        """Update current work status"""
        await self.send_message("status_update", {
            "working_on": working_on,
            "timestamp": datetime.now().isoformat()
        })
        logger.info(f"Working on: {working_on}")

    async def notify_file_change(self, file_path: str, action: str = "modified"):
        """Notify other sessions of file changes"""
        await self.send_message("file_changed", {
            "file_path": file_path,
            "action": action,  # created | modified | deleted
            "timestamp": datetime.now().isoformat()
        })
        logger.info(f"📝 File {action}: {file_path}")

    async def register_handler(self, msg_type: str, handler: Callable):
        """Register handler for specific message type"""
        self.message_handlers[msg_type] = handler

    async def _on_task_assigned(self, task: dict):
        """Default handler for task assignment"""
        logger.info(f"""
        ╔══════════════════════════════════════╗
        ║ New Task Assigned                    ║
        ╠══════════════════════════════════════╣
        ║ ID: {task.get('id', 'unknown')[:20]}
        ║ Title: {task.get('title', 'unknown')[:30]}
        ║ Priority: {task.get('priority', 0)}
        ╚══════════════════════════════════════╝
        """)

    def get_status(self) -> dict:
        """Get orchestrator status"""
        try:
            response = requests.get(f"{self.rest_url}/status")
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get status: {e}")
        return {}

    def get_tasks(self, status: str = None) -> list:
        """Get list of tasks"""
        try:
            url = f"{self.rest_url}/tasks"
            if status:
                url += f"?status={status}"
            response = requests.get(url)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get tasks: {e}")
        return []

    def create_task(self, title: str, description: str, priority: int = 1) -> dict:
        """Create a new task"""
        try:
            response = requests.post(
                f"{self.rest_url}/tasks",
                json={
                    "title": title,
                    "description": description,
                    "priority": priority,
                    "status": "pending"
                }
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"Failed to create task: {e}")
        return {}

# ============================================================================
# Example Usage
# ============================================================================

async def example_session():
    """Example Claude Code session using orchestrator"""

    # Initialize client
    client = OrchestratorClient(
        orchestrator_url="ws://localhost:8000",
        session_name="Frontend-Developer"
    )

    # Connect to orchestrator
    await client.connect()

    # Register custom message handlers
    async def on_file_changed(message):
        logger.info(f"Another session changed file: {message['data']['file_path']}")

    await client.register_handler("file_changed", on_file_changed)

    try:
        # Get current status
        status = client.get_status()
        logger.info(f"Orchestrator status: {status}")

        # Create a new task
        logger.info("Creating new tasks...")
        for i in range(3):
            task = client.create_task(
                title=f"Feature {i+1}",
                description=f"Implement feature {i+1}",
                priority=3-i
            )
            logger.info(f"Created task: {task}")

        # Work on tasks
        while True:
            # Request a task
            task = await client.request_task()

            if not task:
                logger.info("No more tasks available")
                break

            # Simulate work
            logger.info(f"Starting work on: {task.get('title')}")
            await client.update_status(f"Implementing {task.get('title')}")

            # Notify others of file changes
            await client.notify_file_change("src/components/NewFeature.tsx", "created")
            await client.notify_file_change("src/services/api.ts", "modified")

            # Simulate some work
            await asyncio.sleep(2)

            # Complete task
            await client.complete_task(
                task.get("id"),
                result="Successfully implemented feature"
            )

            # Notify other sessions
            await client.notify_sessions(f"Completed: {task.get('title')}")

    finally:
        await client.disconnect()

if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║   Multi-Session Orchestrator Client                       ║
    ║   Claude Code Session Coordinator                         ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    # Run example
    asyncio.run(example_session())
