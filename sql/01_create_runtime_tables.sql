-- 01_create_runtime_tables.sql
-- Creates the raw runtime cost event table and the daily mart table
-- Run against project: finops-gcp-agent

-- Dataset: agent_finops_raw
CREATE SCHEMA IF NOT EXISTS `finops-gcp-agent.agent_finops_raw`
OPTIONS (
  description = 'Raw runtime cost events emitted by agent pipelines',
  location = 'US'
);

-- Dataset: agent_finops_mart
CREATE SCHEMA IF NOT EXISTS `finops-gcp-agent.agent_finops_mart`
OPTIONS (
  description = 'Transformed cost reporting tables and views for Looker Studio',
  location = 'US'
);

-- Dataset: billing_raw
-- Note: Cloud Billing export destination is configured in GCP Console under Billing > Billing export
-- The export creates tables automatically. Create the dataset here so it is ready.
CREATE SCHEMA IF NOT EXISTS `finops-gcp-agent.billing_raw`
OPTIONS (
  description = 'Cloud Billing export tables -- populated automatically by GCP billing export',
  location = 'US'
);

-- Core runtime cost event table
-- Partitioned by event date, clustered by agent_name and environment
-- One row per pipeline step per run
CREATE TABLE IF NOT EXISTS `finops-gcp-agent.agent_finops_raw.agent_cost_events` (
  event_ts              TIMESTAMP     NOT NULL,
  run_id                STRING        NOT NULL,
  agent_name            STRING        NOT NULL,
  workflow_name         STRING,
  step_name             STRING,
  environment           STRING,
  project_id            STRING,
  region                STRING,
  model_name            STRING,
  request_type          STRING,
  urgency               STRING,
  input_tokens          INT64,
  output_tokens         INT64,
  total_tokens          INT64,
  estimated_model_cost_usd  NUMERIC,
  storage_reads         INT64,
  storage_writes        INT64,
  db_reads              INT64,
  db_writes             INT64,
  pubsub_messages       INT64,
  dlp_bytes_inspected   INT64,
  latency_ms            INT64,
  retry_count           INT64,
  status                STRING,
  error_message         STRING,
  resource_labels       JSON
)
PARTITION BY DATE(event_ts)
CLUSTER BY agent_name, environment, workflow_name, step_name
OPTIONS (
  description = 'Runtime cost events emitted per pipeline step per run',
  partition_expiration_days = 365
);

-- Daily aggregated mart table
-- Rebuilt nightly by scheduled query in BigQuery
-- One row per agent + workflow + environment + urgency + model per day
CREATE TABLE IF NOT EXISTS `finops-gcp-agent.agent_finops_mart.agent_cost_daily` (
  cost_date                   DATE,
  agent_name                  STRING,
  workflow_name               STRING,
  environment                 STRING,
  urgency                     STRING,
  model_name                  STRING,
  run_count                   INT64,
  step_count                  INT64,
  input_tokens                INT64,
  output_tokens               INT64,
  total_tokens                INT64,
  estimated_model_cost_usd    NUMERIC,
  avg_cost_per_run_usd        NUMERIC,
  avg_latency_ms              FLOAT64,
  p99_latency_ms              FLOAT64,
  error_count                 INT64,
  retry_count                 INT64
)
PARTITION BY cost_date
CLUSTER BY agent_name, environment
OPTIONS (
  description = 'Daily aggregated cost mart -- rebuilt nightly by scheduled query'
);

-- Anomaly table -- populated by scheduled anomaly detection query
CREATE TABLE IF NOT EXISTS `finops-gcp-agent.agent_finops_mart.run_cost_anomalies` (
  detected_ts               TIMESTAMP,
  run_id                    STRING,
  agent_name                STRING,
  step_name                 STRING,
  environment               STRING,
  urgency                   STRING,
  estimated_model_cost_usd  NUMERIC,
  baseline_avg_cost_usd     NUMERIC,
  baseline_stddev_cost_usd  NUMERIC,
  deviation_multiplier      FLOAT64,
  anomaly_reason            STRING
)
OPTIONS (
  description = 'Runs where cost exceeded baseline by more than 3 standard deviations'
);
