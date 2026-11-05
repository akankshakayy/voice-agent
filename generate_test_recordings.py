#!/usr/bin/env python3
"""Generate test recording data to match production for development.

Creates realistic test data simulating 358 recordings from the Sahayak uploader.
"""
import sys
import time
from datetime import datetime, timedelta
from app import db

def create_test_recordings(count: int = 358) -> None:
    """Create test recordings matching production data."""

    print(f"📝 Creating {count} test recordings...")

    # Get existing tokens to map recordings to
    tokens = db.q("SELECT id FROM upload_tokens WHERE revoked_at IS NULL;")
    token_ids = [t['id'] for t in tokens] if tokens else [None]

    # Get some RMs and CSPs
    rms = db.q("SELECT id FROM rms LIMIT 5;")
    rm_ids = [r['id'] for r in rms] if rms else [None]

    csps = db.q("SELECT id FROM csps LIMIT 100;")
    csp_ids = [c['id'] for c in csps] if csps else [None]

    if not csps:
        print("⚠️  No CSPs in database. Creating a sample CSP first...")
        db.x("INSERT INTO csps(csp_code, name) VALUES(?, ?)", ("TEST_CSP", "Test CSP"))
        csps = db.q("SELECT id FROM csps LIMIT 1;")
        csp_ids = [c['id'] for c in csps]

    print(f"   Using {len(token_ids)} tokens, {len(rm_ids)} RMs, {len(csp_ids)} CSPs")

    # Generate recordings spread across the last 30 days
    base_time = time.time()
    start_time = base_time - (30 * 24 * 3600)  # 30 days ago

    inserted = 0
    for i in range(count):
        # Spread across 30 days
        days_ago = (i % 30)
        started_at = start_time + (days_ago * 24 * 3600) + (i % (24*3600))

        # Alternate between statuses
        statuses = ['done', 'done', 'done', 'pending', 'new']
        status = statuses[i % len(statuses)]

        # Map to tokens and RMs
        token_id = token_ids[i % len(token_ids)]
        rm_id = rm_ids[i % len(rm_ids)] if rm_ids != [None] else None
        csp_id = csp_ids[i % len(csp_ids)] if csp_ids != [None] else None

        # Create realistic file path
        date_str = datetime.fromtimestamp(started_at).strftime("%Y-%m-%d")
        file_id = f"test_{i:06d}_{int(started_at)}"
        file_path = f"rm{rm_id or 'x'}/{date_str}/{file_id}.mp4"

        try:
            db.x("""
                INSERT INTO recordings(
                    sha256, rm_id, token_id, device_id, file_path, orig_name,
                    size_bytes, started_at, duration_sec, direction, other_number,
                    csp_id, uploaded_at, status, attempts, is_csp_call, language,
                    call_type
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f"sha256_{i:06d}",  # sha256
                rm_id,  # rm_id
                token_id,  # token_id
                f"phone_{i}",  # device_id
                file_path,  # file_path
                f"Recording_{i:03d}.mp4",  # orig_name
                1024 * 100,  # size_bytes (100KB)
                started_at,  # started_at
                65 + (i % 60),  # duration_sec (65-125 seconds)
                'outgoing' if i % 2 == 0 else 'incoming',  # direction
                f"+91990000{i%10000:04d}",  # other_number
                csp_id,  # csp_id
                started_at + 300,  # uploaded_at (5 min later)
                status,  # status
                1,  # attempts
                1 if i % 3 == 0 else 0,  # is_csp_call
                'hinglish',  # language
                'csp_call' if i % 3 == 0 else 'test',  # call_type
            ))
            inserted += 1
        except Exception as e:
            print(f"   Error inserting recording {i}: {e}")
            continue

        if (i + 1) % 50 == 0:
            print(f"   Created {i + 1}/{count} recordings...")

    print(f"\n✓ Successfully created {inserted} test recordings")

    # Show summary
    result = db.q("SELECT COUNT(*) as cnt FROM recordings;")
    total = result[0]['cnt'] if result else 0

    result = db.q("SELECT status, COUNT(*) as cnt FROM recordings GROUP BY status;")
    print(f"\n  Total recordings: {total}")
    print("  By status:")
    for row in result:
        print(f"    {row['status']}: {row['cnt']}")

    result = db.q("""
        SELECT token_id, COUNT(*) as cnt FROM recordings
        WHERE token_id IS NOT NULL
        GROUP BY token_id
        ORDER BY cnt DESC
    """)
    print(f"\n  By upload token:")
    for row in result:
        print(f"    Token {row['token_id']}: {row['cnt']} recordings")

if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 358

    # Confirm
    result = db.q("SELECT COUNT(*) as cnt FROM recordings;")
    existing = result[0]['cnt'] if result else 0

    if existing > 2:
        print(f"⚠️  Database already has {existing} recordings")
        response = input("   Continue anyway? (y/n): ")
        if response.lower() != 'y':
            print("   Cancelled")
            sys.exit(0)

    create_test_recordings(count)
    print("\n✨ Done! Recordings page should now display data.")
