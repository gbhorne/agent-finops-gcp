# Agent FinOps -- GCP

A full end-to-end FinOps build for agentic AI on Google Cloud. Two live agents (Google ADK and Vertex AI) process real documents using Gemini 2.5 Flash, capturing actual token costs from the Vertex AI API response and writing structured cost events to BigQuery. A Looker Studio dashboard visualizes real per-run costs, step-level token breakdown, and framework cost comparison.

**This is not a simulation.** Every cost figure in this repo came from real Gemini API calls against a live GCP project.

---

## Disclaimer

This project uses synthetic document inputs generated for demonstration purposes. No real customer data, proprietary information, or personally identifiable information is used at any stage. All cost figures reflect actual Vertex AI API usage on the finops-gcp-agent GCP project.

---

## Live Dashboard

### Executive Summary -- MTD cost, run count, token totals, daily spend trend

![Executive Summary Dashboard](docs/dashboard_executive_summary.png)

### Step Cost Breakdown -- cost per pipeline step by framework

![Step Cost Breakdown Dashboard](docs/dashboard_step_breakdown.png)

---

## What This Builds

Two document analysis agents -- identical pipeline logic, different frameworks -- both writing real cost data to the same BigQuery table:

| Agent | Framework | BigQuery tag |
|-------|-----------|-------------|
| ADK Document Analyzer | Google ADK + Gemini 2.5 Flash | adk-doc-analyzer |
| Vertex Document Analyzer | Vertex AI direct + Gemini 2.5 Flash | vertex-doc-analyzer |

Each agent runs a two-step pipeline:
1. Classify -- document type, priority, topic (one Gemini call)
2. Summarize -- structured executive summary with key points and action items (one Gemini call)

Every Gemini call captures actual token counts from usageMetadata.prompt_token_count and usageMetadata.candidates_token_count -- the same data Vertex AI uses for billing -- and calculates per-step cost at runtime pricing.

---

## Key Findings From Live Data

| Metric | vertex-doc-analyzer | adk-doc-analyzer |
|--------|--------------------|--------------------|
| Avg input tokens (classify) | 288 | 189 |
| Avg input tokens (summarize) | 267 | 169 |
| Avg latency (classify) | 3,971ms | 3,277ms |
| Avg cost per run | ~$0.00016 | ~$0.00013 |

The ADK framework adds less prompt overhead than the direct Vertex AI implementation -- observable in real token count data from live API calls.

---

## Architecture

```
Document input (text)
        |
        v
Agent pipeline (Python)
  Step 1: classify_document  --> Gemini 2.5 Flash call
  Step 2: generate_summary   --> Gemini 2.5 Flash call
        |
        | InstrumentedGemini wrapper captures:
        |   usageMetadata.prompt_token_count
        |   usageMetadata.candidates_token_count
        |   estimated_cost_usd (calculated at runtime)
        |   latency_ms
        |
        v
RunTracker accumulates cost across all steps
        |
        v
CostEventWriter writes to BigQuery
  finops-gcp-agent.agent_finops_raw.agent_cost_events
  (partitioned by date, clustered by agent_name)
        |
        v
BigQuery views (agent_finops_mart)
  runtime_daily_agent      daily cost aggregates
  runtime_step_cost        per-step cost breakdown
  dashboard_daily_spend    Looker Studio page 1
  dashboard_step_breakdown Looker Studio page 2
        |
        v
Looker Studio dashboard
  Page 1: Executive Summary
  Page 2: Step Cost Breakdown
```

---

## Repository Structure

```
agent-finops-gcp/
agents/
  cost_tracker.py         Core instrumentation: token capture and BigQuery writer
  adk_agent.py            Google ADK document analysis agent
  vertex_agent.py         Vertex AI document analysis agent and test runner
  agent.py                ADK entry point
sql/
  01_create_runtime_tables.sql  BigQuery datasets and tables
  02_billing_views.sql          Cloud Billing export views
  03_runtime_views.sql          Runtime cost views
  04_dashboard_views.sql        Looker Studio data source views
  05_anomaly_queries.sql        Anomaly detection and mart rebuild
app/
  token_instrumentation.py  Standalone instrumentation module
  cost_event_writer.py      BigQuery writer
  demo_agent.py             Simulated data loader
docs/
  ARCHITECTURE.md
  dashboard_executive_summary.png
  dashboard_step_breakdown.png
```

---

## Setup

### Prerequisites

- GCP project with billing enabled
- gcloud CLI authenticated
- Python 3.11+

### Step 1 -- Enable APIs

```bash
gcloud services enable bigquery.googleapis.com aiplatform.googleapis.com pubsub.googleapis.com run.googleapis.com --project=YOUR_PROJECT_ID
```

### Step 2 -- Create BigQuery datasets

```bash
bq mk --project_id=YOUR_PROJECT_ID --dataset agent_finops_raw
bq mk --project_id=YOUR_PROJECT_ID --dataset agent_finops_mart
```

### Step 3 -- Run SQL files

```bash
Get-Content sql\01_create_runtime_tables.sql | bq query --project_id=YOUR_PROJECT_ID --use_legacy_sql=false --format=none
Get-Content sql\03_runtime_views.sql | bq query --project_id=YOUR_PROJECT_ID --use_legacy_sql=false --format=none
Get-Content sql\04_dashboard_views.sql | bq query --project_id=YOUR_PROJECT_ID --use_legacy_sql=false --format=none
```

### Step 4 -- Install dependencies

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Step 5 -- Run the Vertex agent

```bash
$env:GOOGLE_GENAI_USE_VERTEXAI="true"
python -m agents.vertex_agent
```

Runs 3 document analyses, writes 6 cost event rows to BigQuery.

### Step 6 -- Run the ADK agent

```bash
adk web
```

Navigate to http://localhost:8000, select agents, and send any document text for analysis.

### Step 7 -- Connect Looker Studio

1. Go to lookerstudio.google.com
2. Create a new report
3. Add data source: BigQuery → your project → agent_finops_mart
4. Connect dashboard_daily_spend for Page 1 charts
5. Connect dashboard_executive_summary for scorecard metrics
6. Connect dashboard_step_breakdown for Page 2 bar chart and table

---

## Instrumenting Your Own Agent

Three lines to add cost tracking to any Python agent:

```python
from agents.cost_tracker import RunTracker, gemini_call, write_to_bigquery

tracker = RunTracker(agent_name="my-agent", workflow_name="my-workflow", environment="production")
result = gemini_call(prompt=my_prompt, step_name="my_step", tracker=tracker)
write_to_bigquery(tracker)
```

Token counts are captured from the Vertex AI usageMetadata response -- actual billed usage, not estimates.

---

## GCP Infrastructure

| Service | Role |
|---------|------|
| Vertex AI (Gemini 2.5 Flash) | Document classification and summarization |
| BigQuery (agent_finops_raw) | Raw cost events -- one row per step per run |
| BigQuery (agent_finops_mart) | Aggregated views for Looker Studio |
| Looker Studio | Live cost dashboard |
| Google ADK | ADK agent orchestration |

---

*Built by [Gregory Horne](https://github.com/gbhorne) -- GCP Agentic Systems and Agent FinOps portfolio.*
