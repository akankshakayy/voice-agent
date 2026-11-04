#!/usr/bin/env python3
"""
Example: 3 Parallel Claude Code Sessions
Working on Sahayak DC Recording Feature
"""

import asyncio
import json
from datetime import datetime
from orchestrator_client import OrchestratorClient

# ============================================================================
# SESSION 1: Backend Developer
# ============================================================================

async def backend_developer_session():
    """Session A: Implements DC call recording backend"""

    client = OrchestratorClient(session_name="Backend-Developer")
    await client.connect()

    print("""
    ╔════════════════════════════════════════════════════════╗
    ║ SESSION 1: Backend Developer                          ║
    ║ Focus: DC recording logic & API endpoints             ║
    ╚════════════════════════════════════════════════════════╝
    """)

    task_count = 0

    while True:
        # Get next task
        task = await client.request_task()

        if not task:
            break

        task_count += 1
        task_id = task.get('id')
        title = task.get('title')

        print(f"\n📋 Task {task_count}: {title}")
        await client.update_status(f"Implementing {title}")

        # Simulate backend work
        if "database" in title.lower():
            print("  → Adding call_type column to recordings table")
            await asyncio.sleep(1)
            print("  → Creating migration script")
            await client.notify_file_change("app/db.py", "modified")
            await asyncio.sleep(1)

        elif "api" in title.lower():
            print("  → Adding call_type parameter to /api/recordings")
            await asyncio.sleep(1)
            print("  → Implementing filtering logic")
            await client.notify_file_change("app/main.py", "modified")
            await client.notify_file_change("app/recordings.py", "modified")
            await asyncio.sleep(1)
            print("  → Testing endpoints")

        elif "transcription" in title.lower():
            print("  → Skipping transcription for DC calls")
            await asyncio.sleep(1)
            print("  → Marking as done immediately")
            await client.notify_file_change("app/recordings.py", "modified")
            await asyncio.sleep(1)

        # Complete task
        print(f"  ✅ Complete: {title}")
        await client.complete_task(task_id, result="Backend implementation done")

        # Notify other sessions
        await client.notify_sessions(f"✅ Backend: {title} ready for integration")

    print("\n🎉 Backend Developer Session Complete!")
    await client.disconnect()

# ============================================================================
# SESSION 2: Frontend Developer
# ============================================================================

async def frontend_developer_session():
    """Session B: Implements DC UI tabs and controls"""

    client = OrchestratorClient(session_name="Frontend-Developer")
    await client.connect()

    print("""
    ╔════════════════════════════════════════════════════════╗
    ║ SESSION 2: Frontend Developer                         ║
    ║ Focus: DC recording UI & tabs                         ║
    ╚════════════════════════════════════════════════════════╝
    """)

    task_count = 0

    while True:
        # Get next task
        task = await client.request_task()

        if not task:
            break

        task_count += 1
        task_id = task.get('id')
        title = task.get('title')

        print(f"\n🎨 Task {task_count}: {title}")
        await client.update_status(f"Building {title}")

        # Simulate frontend work
        if "ui" in title.lower() or "tab" in title.lower():
            print("  → Creating RM/DC tab components")
            await asyncio.sleep(1)
            await client.notify_file_change("static/recordings.html", "modified")
            print("  → Adding tab switching logic")
            await asyncio.sleep(1)
            print("  → Styling tabs with CSS")

        elif "filter" in title.lower():
            print("  → Adding call_type filtering")
            await asyncio.sleep(1)
            await client.notify_file_change("static/recordings.html", "modified")
            print("  → Implementing tab state management")
            await asyncio.sleep(1)

        # Complete task
        print(f"  ✅ Complete: {title}")
        await client.complete_task(task_id, result="Frontend UI ready")

        # Notify other sessions
        await client.notify_sessions(f"✅ Frontend: {title} ready for testing")

    print("\n🎉 Frontend Developer Session Complete!")
    await client.disconnect()

# ============================================================================
# SESSION 3: QA/Tester
# ============================================================================

async def qa_tester_session():
    """Session C: Tests DC recording functionality"""

    client = OrchestratorClient(session_name="QA-Tester")
    await client.connect()

    print("""
    ╔════════════════════════════════════════════════════════╗
    ║ SESSION 3: QA/Tester                                  ║
    ║ Focus: Testing & validation                           ║
    ╚════════════════════════════════════════════════════════╝
    """)

    # Register handler for file changes
    async def on_file_changed(message):
        file_path = message['data']['file_path']
        action = message['data']['action']
        print(f"  📝 Detected: {file_path} ({action})")

    await client.register_handler("file_changed", on_file_changed)

    task_count = 0

    while True:
        # Get next task
        task = await client.request_task()

        if not task:
            break

        task_count += 1
        task_id = task.get('id')
        title = task.get('title')

        print(f"\n🧪 Task {task_count}: {title}")
        await client.update_status(f"Testing {title}")

        # Simulate testing work
        if "unit" in title.lower():
            print("  → Running unit tests on recordings module")
            await asyncio.sleep(1)
            print("  → Testing call_type filtering logic")
            await asyncio.sleep(1)
            print("  → ✓ All tests passed")

        elif "integration" in title.lower():
            print("  → Testing API endpoints")
            await asyncio.sleep(1)
            print("  → Testing frontend UI interactions")
            await asyncio.sleep(1)
            print("  → Testing end-to-end DC call recording")
            await asyncio.sleep(1)
            print("  → ✓ Integration tests passed")

        elif "end-to-end" in title.lower():
            print("  → Running full E2E test suite")
            await asyncio.sleep(2)
            print("  → Simulating DC call upload")
            print("  → Verifying recording appears in DC tab")
            print("  → ✓ E2E tests passed")

        # Complete task
        print(f"  ✅ Complete: {title}")
        await client.complete_task(task_id, result="All tests passed ✓")

        # Notify other sessions
        await client.notify_sessions(f"✅ QA: {title} - all tests passed!")

    print("\n🎉 QA/Tester Session Complete!")
    await client.disconnect()

# ============================================================================
# Main: Orchestrate All Sessions
# ============================================================================

async def setup_tasks():
    """Create DC feature tasks"""
    client = OrchestratorClient()

    tasks = [
        ("Add call_type to database schema", "Add call_type column to recordings table", 3),
        ("Implement DC recording API endpoints", "Add /api/recordings?call_type=dc filtering", 3),
        ("Skip transcription for DC calls", "Modify processing to skip LLM for DC calls", 3),
        ("Create frontend DC tabs UI", "Add RM/DC tabs to recordings page", 2),
        ("Implement call_type filtering logic", "Frontend filtering by call_type", 2),
        ("Write unit tests", "Test DC recording logic and API", 2),
        ("Run integration tests", "Test frontend-backend integration", 2),
        ("End-to-end testing", "Full DC call recording workflow test", 1),
    ]

    print("📋 Creating tasks for DC feature development...\n")

    for title, desc, priority in tasks:
        task = client.create_task(title, desc, priority)
        print(f"  ✓ Created: {title}")

    print(f"\n✅ {len(tasks)} tasks created!\n")

async def main():
    """Run all sessions in parallel"""

    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║                                                          ║
    ║     🚀 MULTI-SESSION ORCHESTRATOR DEMO                  ║
    ║                                                          ║
    ║     Parallel Claude Code Development                    ║
    ║     DC Recording Feature Implementation                 ║
    ║                                                          ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    print("⏳ Setting up tasks...")
    await setup_tasks()

    print("\n🚀 Starting 3 parallel sessions...\n")
    print("=" * 60)

    # Run all sessions in parallel
    await asyncio.gather(
        backend_developer_session(),
        frontend_developer_session(),
        qa_tester_session()
    )

    print("\n" + "=" * 60)
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║                                                          ║
    ║  ✅ ALL SESSIONS COMPLETE!                              ║
    ║                                                          ║
    ║  DC Recording Feature Ready for Deployment              ║
    ║                                                          ║
    ║  Execution Time: ~3x Faster with Parallel Sessions      ║
    ║                                                          ║
    ╚══════════════════════════════════════════════════════════╝
    """)

if __name__ == "__main__":
    # Make sure orchestrator is running first!
    print("⚠️  Make sure orchestrator server is running!")
    print("    Run: python orchestrator_server.py\n")

    asyncio.run(main())
