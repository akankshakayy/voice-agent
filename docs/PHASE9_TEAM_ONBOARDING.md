# Team Onboarding Guide

Fresh setup from scratch for new team members.

## Prerequisites

- [ ] Git installed
- [ ] Python 3.10+ installed
- [ ] Docker installed (optional, for containerized testing)
- [ ] Access to akankshakayy/voice-agent GitHub repo
- [ ] Access to indev.eko.in environment

## Step 1: Clone Repository

```bash
# Clone the project
git clone https://github.com/akankshakayy/voice-agent.git
cd voice-agent

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Verify Python version
python --version  # Should be 3.10+
```

## Step 2: Install Dependencies

```bash
# Install required packages
pip install -r requirements.txt

# Verify installation
python -c "import app; print('✅ Dependencies installed')"
```

## Step 3: Setup Configuration (.env)

```bash
# Copy example config
cp .env.example .env

# Create local secrets file (DO NOT commit)
cat > .env.local << 'EOF'
# Development mode (no real CSP calls)
ENVIRONMENT=development
DEMO_DATA=1
REAL_CSP_CALLS=0

# API Keys (get from team)
ANTHROPIC_API_KEY=xxx
AUTOGMAP_API_KEY=xxx
PRACHI_RECORDING_SECRET=xxx
GOOGLE_CLIENT_SECRET=xxx

# Development settings
LOG_LEVEL=DEBUG
DB_PATH=data/eko_agent.db
EOF

# Verify secrets are set
grep -E "ANTHROPIC|AUTOGMAP" .env.local
```

## Step 4: Database Initialization

```bash
# Initialize database schema
python -m app.db_init

# Verify tables created
python -c "import app.db as db; print('✅ Database ready')"

# Load demo CSP data (optional, for testing)
python -m app.synthetic
```

## Step 5: Create First Admin User

```bash
# Create admin account
python << 'EOF'
from app.auth import create_user
create_user(
    email="your.email@eko.co.in",
    password="temp-password-123",  # Change on first login
    role="admin"
)
print("✅ Admin user created")
EOF
```

## Step 6: Start Application

```bash
# Start development server
uvicorn app.main:app --reload --port 8000

# Expected output:
# INFO:     Uvicorn running on http://127.0.0.1:8000
# INFO:     Application startup complete
```

## Step 7: Test Application

**Test 1: Health Check**
```bash
curl http://localhost:8000/health
# Should return: {"status": "ok", "database": "connected"}
```

**Test 2: Admin Login**
- Open: http://localhost:8000/admin
- Email: your.email@eko.co.in
- Password: temp-password-123
- Change password on first login

**Test 3: Upload Recording**
```bash
# Create test audio file (1 second silence)
ffmpeg -f lavfi -i anullsrc=r=16000:cl=mono -t 1 -q:a 9 -acodec libvorbis test.ogg

# Upload to dev server
curl -X POST http://localhost:8000/api/uploader/recordings \
  -F "audio=@test.ogg" \
  -F "phone=9876543210" \
  -F "mode=dc"
```

## Step 8: Run Tests

```bash
# Run full test suite
pytest tests/ -v

# Run specific test
pytest tests/test_agent.py::test_dmt_ticket_flow -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Expected: 90%+ tests passing
```

## Understanding the Architecture

### Directory Structure

```
voice-agent/
├── app/                          # Main application
│   ├── main.py                   # FastAPI app & routes
│   ├── agent.py                  # Call orchestrator
│   ├── llm_engine.py             # Claude/LLM integration
│   ├── auth.py                   # Authentication & roles
│   ├── db.py                     # SQLite database
│   ├── recordings.py             # Recording handling
│   ├── autogmap.py               # AutoGMap integration
│   └── telemetry.py              # Tracing & metrics
├── docs/                         # Documentation
├── tests/                        # Test suite
├── static/                       # Frontend (HTML/JS)
├── uploader/                     # Kotlin app source
├── requirements.txt              # Dependencies
├── .env.example                  # Config template
└── eko-deploy.toml              # Deployment config
```

### Key Concepts

**1. Multi-Mode Recording:**
- RM mode: Auto-upload loan calls to AutoGMap
- DC mode: Selective upload + consent to Prachi
- Employee mode: Auto-upload, no transcribe

**2. API Integrations:**
- **AutoGMap:** Pull numbers, push RM recordings
- **Prachi:** Push DC recordings via webhook
- **Google Sheets:** Sync DC list daily

**3. Authentication:**
- Google OAuth (preferred)
- Email + password (fallback)
- No admin approval (auto-admin for configured emails)

**4. Database:**
- SQLite (dev) / Postgres (future prod)
- 36 tables for complete multi-mode system
- Automatic migrations on startup

## Common Development Tasks

### Add New API Endpoint

```python
# In app/main.py
@app.post("/api/example")
def example_endpoint(data: dict):
    # Your logic here
    return {"result": "success"}

# Restart server to test
```

### Add Admin Page

```
1. Create HTML in static/pages/example.html
2. Add route in app/main.py: @app.get("/example")
3. Return: FileResponse("static/pages/example.html")
```

### Debug Recording Processing

```bash
# Check logs
tail -f data/logs/eko.log | grep "recording\|upload"

# Manual processing
python -c "
from app import recordings
recs = recordings.list_unprocessed()
for rec in recs:
    recordings.process_one(rec['id'])
"
```

### Run Database Queries

```bash
# SQLite CLI
sqlite3 data/eko_agent.db

# List tables
.tables

# Query recordings
SELECT id, phone, mode, duration_sec FROM recordings LIMIT 5;

# Exit
.quit
```

## Git Workflow

```bash
# Create feature branch
git checkout -b feature/your-feature-name

# Make changes
# ... edit files ...

# Commit with message
git add -A
git commit -m "feat: Add your feature

- Detailed explanation of changes
- Why this change matters"

# Push to GitHub
git push -u origin feature/your-feature-name

# Create pull request
# Open GitHub and create PR from your branch to main
```

## Useful Commands

```bash
# View logs (development)
tail -f data/logs/eko.log

# Restart server
# Press Ctrl+C, then: uvicorn app.main:app --reload

# View database schema
sqlite3 data/eko_agent.db ".schema"

# Reset database (DEV ONLY)
rm data/eko_agent.db
python -m app.db_init

# Run specific test file
pytest tests/test_autogmap_rate_limiting.py -v

# List all API endpoints
grep "@app\." app/main.py | head -20
```

## Debugging Tips

1. **Slow uploads?** Check `app/autogmap.py` rate limiting
2. **Database locked?** Check `app/telemetry.py` thread management
3. **Auth failing?** Check `.env.local` has GOOGLE_CLIENT_SECRET
4. **Tests failing?** Run `pytest` with `-v` for verbose output

## Getting Help

- **Code questions:** Check existing code in `app/` directory
- **API docs:** See `docs/PHASE9_UNIFIED_API_REFERENCE.md`
- **Config help:** See `.env.example` with comments
- **Team:** Slack @dev-team or email dev-team@eko.co.in

## Next Steps

1. [ ] Clone repo and install dependencies
2. [ ] Setup `.env.local` with team API keys
3. [ ] Initialize database
4. [ ] Start development server
5. [ ] Run test suite (should pass)
6. [ ] Create feature branch
7. [ ] Make your first contribution!

Welcome to the team! 🚀
