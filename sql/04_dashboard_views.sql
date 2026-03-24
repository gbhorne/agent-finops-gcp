-- 04_dashboard_views.sql
-- Combined views joining billing actuals with runtime unit economics
-- These views are the direct data sources for Looker Studio dashboard pages

-- Executive summary view
-- Joins MTD billing actuals with MTD runtime estimates
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.dashboard_executive_summary` AS
SELECT
  r.agent_name,
  r.environment,
  r.mtd_run_count,
  r.mtd_est_cost_usd                                          AS mtd_runtime_est_cost_usd,
  b.mtd_billed_cost_usd,
  SAFE_DIVIDE(r.mtd_est_cost_usd, r.mtd_run_count)            AS avg_cost_per_run_usd,
  SAFE_DIVIDE(r.mtd_est_cost_usd, r.mtd_run_count) * 1000     AS est_cost_per_1k_runs_usd,
  r.avg_latency_ms,
  r.avg_cost_per_run_usd
FROM `finops-demo-2026.agent_finops_mart.runtime_mtd` r
LEFT JOIN `finops-demo-2026.agent_finops_mart.billing_mtd` b
  ON r.agent_name = b.project_id;

-- Daily spend trend -- billing actuals + runtime estimates side by side
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.dashboard_daily_spend` AS
SELECT
  COALESCE(r.usage_date, b.usage_date)    AS usage_date,
  COALESCE(r.agent_name, 'unknown')       AS agent_name,
  COALESCE(r.environment, 'unknown')      AS environment,
  r.run_count,
  r.est_model_cost_usd,
  r.est_cost_per_run_usd,
  b.billed_cost_usd,
  b.service_name
FROM `finops-demo-2026.agent_finops_mart.runtime_daily_agent` r
FULL OUTER JOIN `finops-demo-2026.agent_finops_mart.billing_ai_services` b
  ON r.usage_date = b.usage_date
 AND r.project_id = b.project_id;

-- Agent unit economics page -- cost breakdown by agent and workflow
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.dashboard_unit_economics` AS
SELECT
  usage_date,
  agent_name,
  workflow_name,
  urgency,
  model_name,
  environment,
  run_count,
  est_model_cost_usd,
  est_cost_per_run_usd,
  avg_latency_ms,
  p99_latency_ms,
  input_tokens,
  output_tokens,
  error_count,
  retry_count
FROM `finops-demo-2026.agent_finops_mart.runtime_daily_agent`
WHERE environment = 'production';

-- Prompt and model impact page -- token trend and cost before/after changes
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.dashboard_prompt_impact` AS
SELECT
  t.usage_date,
  t.agent_name,
  t.step_name,
  t.model_name,
  t.avg_input_tokens,
  t.avg_output_tokens,
  t.avg_total_tokens,
  s.avg_step_cost_usd,
  s.total_step_cost_usd,
  s.avg_latency_ms
FROM `finops-demo-2026.agent_finops_mart.token_trend_daily` t
LEFT JOIN `finops-demo-2026.agent_finops_mart.runtime_step_cost` s
  ON t.usage_date = s.usage_date
 AND t.agent_name = s.agent_name
 AND t.step_name = s.step_name
 AND t.model_name = s.model_name;

-- Budget and anomaly page
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.dashboard_anomalies` AS
SELECT
  a.detected_ts,
  a.run_id,
  a.agent_name,
  a.step_name,
  a.environment,
  a.urgency,
  a.estimated_model_cost_usd,
  a.baseline_avg_cost_usd,
  a.deviation_multiplier,
  a.anomaly_reason,
  e.latency_ms,
  e.retry_count,
  e.status,
  e.error_message
FROM `finops-demo-2026.agent_finops_mart.run_cost_anomalies` a
LEFT JOIN `finops-demo-2026.agent_finops_raw.agent_cost_events` e
  ON a.run_id = e.run_id
ORDER BY a.detected_ts DESC;
