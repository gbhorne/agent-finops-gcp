# Architecture

## Overview

This project implements a two-layer cost observability platform for agentic AI workloads on Google Cloud.

**Layer 1: Cloud Billing Actuals**
Cloud Billing export to BigQuery provides ground-truth billed cost by service and SKU. This is what Google actually charges. It is aggregated at the project and service level and arrives with a 24-48 hour lag.

**Layer 2: Pipeline Unit Economics**
Runtime instrumentation inside each agent pipeline captures token consumption, service operation counts, and estimated cost per step at the moment of execution. This data is available in real time and provides per-run, per-step granularity that billing export cannot.

Both layers land in BigQuery. Scheduled queries build daily cost mart tables. Views join billing actuals with runtime estimates. Looker Studio connects to the views.

---

## Data Flow

```
Agent pipeline (Python)
  |
  |-- Calls Gemini on Vertex AI
  |     usageMetadata.prompt_token_count
  |     usageMetadata.candidates_token_count
  |
  |-- InstrumentedGemini wrapper (app/token_instrumentation.py)
  |     captures tokens per call
  |     estimates cost at runtime pricing
  |     accumulates into RunCostAccumulator
  |
  |-- CostEventWriter (app/cost_event_writer.py)
  |     writes structured cost event rows to BigQuery
  |     one row per pipeline step per run
  |
  v
BigQuery: agent_finops_raw.agent_cost_events
  (partitioned by date, clustered by agent_name + environment)
  |
  |-- Scheduled query: nightly mart rebuild
  |     agent_finops_mart.agent_cost_daily
  |
  |-- Scheduled query: hourly anomaly detection
  |     agent_finops_mart.run_cost_anomalies
  |
  |-- Views: runtime_daily_agent, runtime_step_cost, token_trend_daily...
  |
  v
Looker Studio dashboard
  |-- Executive Summary page
  |-- Agent Unit Economics page
  |-- Service Breakdown page
  |-- Prompt and Model Impact page
  |-- Budget and Anomaly page

Cloud Billing export (configured in GCP Console)
  |
  v
BigQuery: billing_raw.gcp_billing_export_resource_v1_*
  |
  |-- Views: billing_daily_service, billing_ai_services, billing_mtd
  |
  v
Looker Studio (joined with runtime data in dashboard_daily_spend view)
```

---

## BigQuery Datasets

| Dataset | Contents |
|---------|----------|
| `billing_raw` | Cloud Billing export tables—populated by GCP automatically |
| `agent_finops_raw` | Raw runtime cost events—one row per pipeline step per run |
| `agent_finops_mart` | Transformed reporting tables and views for Looker Studio |

---

## Key Design Decisions

**Why two layers instead of billing alone?**
Cloud billing aggregates all Vertex AI costs into one line item. There is no native way to see per-run or per-step costs from billing data. Runtime instrumentation is the only source of unit economics granularity.

**Why not try to join billing rows 1:1 with pipeline runs?**
Billing exports aggregate by service, SKU, and resource dimensions—not by application run_id. A direct join fails. The correct approach is to use billing for total actual spend and runtime instrumentation for unit economics, then join at shared dimensions (date, project, environment, service family).

**Why insert per step rather than per run?**
Step-level granularity enables the prompt impact analysis that is most valuable for cost optimization. A single run can show that step 3 (letter generation) consumed 73% of the total token cost, which is not visible from a run-level aggregate.

**Why partition by date and cluster by agent_name + environment?**
The most common query patterns filter by date range and agent. This partition and cluster combination minimizes bytes scanned for the standard dashboard queries.

---

## Looker Studio Dashboard Pages

### Page 1—Executive Summary
Metric cards: MTD billed cost, MTD estimated runtime cost, cost per 1,000 runs, average latency, budget burn %.
Charts: daily billed spend, daily run volume, daily cost per run trend, top services by spend.

### Page 2—Agent Unit Economics
Charts: cost by agent, cost by workflow, cost by urgency/complexity, input vs output token trend, average run cost over time, expensive run outliers scatter plot.

### Page 3—Service Breakdown
Charts: Vertex AI spend, BigQuery spend, Pub/Sub spend, Firestore spend, DLP spend. Service spend as % of total.

### Page 4—Prompt and Model Impact
Charts: average tokens per run by model version, average run cost before/after release date, latency vs cost scatter, output token inflation over time.

### Page 5—Budget and Anomaly
Cards: monthly budget, actual cost, forecast month-end, anomaly count.
Tables: runs exceeding 3x baseline cost, top failed runs with retry spikes, anomaly detail with root cause classification.

---

## Alerting

Two alert paths run in parallel.

**Billing-level alerts**
Configured in GCP Console under Billing > Budgets and alerts. Thresholds at 50%, 80%, 90%, 100% of monthly budget. Pub/Sub notification channel for programmatic response.

**Runtime anomaly alerts**
BigQuery scheduled query runs hourly, detects runs exceeding 3 standard deviations from the 30-day baseline, writes to `run_cost_anomalies` table. Cloud Monitoring alert polls the anomaly table and fires a notification channel (email, PagerDuty, Slack) when new rows are detected.
