# Performance Trends Dashboard

## Overview
A comprehensive metrics comparison page that tracks agent, model, and quality performance over time with period-over-period comparisons and automatic detection of improvements/degradations.

## Features Built

### 1. **Backend API** (`/api/metrics/trends`)
- **Compares two time periods**: Current period vs previous period or baseline
- **Computes deltas**: Absolute changes and percentage changes for all metrics
- **Parameters**:
  - `hours`: Time period (24, 168 for 7 days, 720 for 30 days)
  - `compare_to`: "previous" or "baseline"
  - `rm_id`: Filter by RM (optional)
  - `csp_id`: Filter by CSP (optional)
  - `intent`: Filter by intent type (optional)
  - `prompt_version`: Filter by prompt version (optional)

### 2. **Frontend Dashboard** (`/metrics-trends`)
Located at: `/static/metrics-trends.html`

#### Time Period Selection
- **24 hours** - Last 24 hours
- **7 days** - Last 7 days (default)
- **30 days** - Last 30 days

#### Granularity Options
- **Daily** - Day-by-day breakdown
- **Weekly** - Week-by-week breakdown

#### Comparison Modes
- **Previous period** - Compare current period to the same period before it
- **Baseline** - Compare to the deployed baseline version

#### Filters
- **RM Filter** - View metrics for a specific RM
- **Intent Filter** - View metrics for a specific intent type

#### Display Sections

##### Status Summary
Cards showing:
- **Improving** metrics (count + list)
- **Stable** metrics
- **Degrading** metrics (count + list)

Cards are color-coded:
- 🟢 Green = Improving
- ⚫ Gray = Stable  
- 🔴 Red = Degrading

##### Agent Performance Metrics
- Total Calls (with breakdown: inbound/outbound)
- Avg Duration (with median)
- Ticket Raise Rate (%)
- Escalation Rate (%)
- Not Understood Rate (%)
- Agent Handled Rate (%)

Each metric shows:
- Current value
- Subtitle context
- Delta from previous period with % change

##### Model Performance Metrics
- Intent Accuracy (%)
- STT Confidence (%)
- Latency P50/P95 (ms)
- Cost per Call (₹)
- Slot Completeness (%)
- Turns per Call

##### Quality & Corrections Metrics
- Acceptance Rate (%) - What % of RM's changes were accepted
- Correction Delta (%) - How much text was changed on average
- Avg Chars Changed - Number of characters modified per correction

##### Detailed Comparison Table
Shows side-by-side:
| Metric | Current | Previous | Change | % Change |
|--------|---------|----------|--------|----------|

##### Insights & Alerts
Automatically generated insights:
- 📞 High volume alerts
- ⚠️ High escalation warnings
- ❌ Low accuracy alerts
- ✅ Accuracy improvements
- ✏️ High correction rate notices
- 💰 Cost tracking

## Key Metrics Tracked

### Agent Metrics
- Calls (absolute count)
- Avg Duration (seconds)
- Ticket Raise Rate (%)
- Escalation Rate (%)
- Not Understood Rate (%)
- Agent Handled Rate (%)

### Model Metrics
- Intent Accuracy (%)
- STT Confidence (%)
- Latency P50 (ms)
- Cost per Call (INR)
- Slot Completeness (%)
- Misunderstood Turn Rate (%)

### Quality/Feedback Metrics
- RM Acceptance Rate (%)
- Correction Delta (%) - Average text changes
- Avg Characters Changed

## How to Use

### Accessing the Dashboard
1. Navigate to `/metrics-trends` in the harness
2. Or click "Performance Trends" in the sidebar navigation (available for admin/ops roles only)

### Viewing Trends
1. **Select time period**: Choose 24h, 7d, or 30d
2. **Choose granularity**: Daily or weekly
3. **Set comparison**: Previous period or baseline
4. **Apply filters** (optional): Select specific RM or intent
5. **Click Refresh**: Auto-updates every 4 seconds

### Interpreting Results
- **Green arrow ↑** = Metric improved compared to previous period
- **Red arrow ↓** = Metric degraded compared to previous period
- **Percentage** = How much change as a percentage

#### Understanding Direction
Metrics are context-aware:
- **Higher is better**: Intent accuracy, STT confidence, acceptance rate
- **Lower is better**: Escalation rate, not understood rate, correction delta
- **Neutral**: Absolute counts (calls, turns)

## Data Accuracy Notes

- Metrics are computed from the last N hours of actual call data
- Comparisons exclude ongoing calls (only "ended" calls)
- Ticket metrics require RM review/confirmation for accuracy tracking
- STT confidence requires Whisper processing
- Intent accuracy requires RM to label tickets (ground truth)

## Performance Implications

### What's Improving
✅ Lower escalation rates indicate better agent understanding
✅ Higher intent accuracy shows better model performance
✅ Lower correction delta means RM is accepting more of agent's output
✅ Higher STT confidence means clearer audio/microphones

### What's Degrading
❌ Rising not understood rate suggests user input issues
❌ Falling acceptance rate may indicate prompt needs tuning
❌ Increasing latency can indicate model performance issues
❌ Rising correction delta shows RM must fix more agent output

## Drill-Down Capabilities

Filter by:
- **RM**: See individual performance
- **Intent**: See how specific intents perform (e.g., "balance_inquiry" vs "support")
- **Prompt version**: Compare performance across different agent prompts
- **CSP segment**: (Future) View by CSP category/region

## Behind the Scenes

### Backend Implementation
File: `app/metrics.py`
- `metrics_trends()` function
- Computes period-over-period deltas
- Automatically detects improving/degrading metrics
- Supports all filtering parameters

### API Endpoint
File: `app/main.py` (line ~707)
- `/api/metrics/trends` 
- GET request
- Returns: Current metrics, previous metrics, deltas, and summary

### Frontend
File: `static/metrics-trends.html`
- Responsive grid layout
- Color-coded metric cards
- Live updates every 4 seconds
- Filter options with dynamic dropdown loading
