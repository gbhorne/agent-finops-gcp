-- 04_dashboard_views.sql
-- Dashboard views for Looker Studio—runtime data only
-- Billing export views added separately once Cloud Billing export is configured

CREATE OR REPLACE VIEW `finops-gcp-agent.agent_finops_mart.dashboard_executive_summary` AS
SELECT
  agent_name,
  environment,
  mtd_run_count,
  mtd_est_cost_usd,
  avg_cost_per_run_usd,
  SAFE_MULTIPLY(avg_cost_per_run_usd, 1000) AS est_cost_per_1k_runs_usd,
  avg_latency_ms
FROM `finops-gcp-agent.agent_finops_mart.runtime_mtd`;

CREATE OR REPLACE VIEW `finops-gcp-agent.agent_finops_mart.dashboard_daily_spend` AS
SELECT
  usage_date,
  agent_name,
  environment,
  workflow_name,
  run_count,
  est_model_cost_usd,
  est_cost_per_run_usd,
  avg_latency_ms,
  input_tokens,
  output_tokens,
  error_count,
  retry_count
FROM `finops-gcp-agent.agent_finops_mart.runtime_daily_agent`;

CREATE OR REPLACE VIEW `finops-gcp-agent.agent_finops_mart.dashboard_unit_economics` AS
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
FROM `finops-gcp-agent.agent_finops_mart.runtime_daily_agent`
WHERE environment = 'production';

CREATE OR REPLACE VIEW `finops-gcp-agent.agent_finops_mart.dashboard_prompt_impact` AS
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
  s.avg_latency_ms,
  s.step_executions
FROM `finops-gcp-agent.agent_finops_mart.token_trend_daily` t
LEFT JOIN `finops-gcp-agent.agent_finops_mart.runtime_step_cost` s
  ON t.usage_date = s.usage_date
 AND t.agent_name = s.agent_name
 AND t.step_name = s.step_name
 AND t.model_name = s.model_name;

CREATE OR REPLACE VIEW `finops-gcp-agent.agent_finops_mart.dashboard_anomalies` AS
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
  e.error_message,
  e.input_tokens,
  e.output_tokens
FROM `finops-gcp-agent.agent_finops_mart.run_cost_anomalies` a
LEFT JOIN `finops-gcp-agent.agent_finops_raw.agent_cost_events` e
  ON a.run_id = e.run_id
ORDER BY a.detected_ts DESC;

CREATE OR REPLACE VIEW `finops-gcp-agent.agent_finops_mart.dashboard_step_breakdown` AS
SELECT
  usage_date,
  agent_name,
  step_name,
  model_name,
  environment,
  step_executions,
  avg_input_tokens,
  avg_output_tokens,
  avg_step_cost_usd,
  total_step_cost_usd,
  avg_latency_ms
FROM `finops-gcp-agent.agent_finops_mart.runtime_step_cost`
ORDER BY usage_date DESC, total_step_cost_usd DESC;

CREATE OR REPLACE VIEW `finops-gcp-agent.agent_finops_mart.dashboard_budget_burn` AS
WITH daily_spend AS (
  SELECT
    DATE(event_ts) AS spend_date,
    SUM(estimated_model_cost_usd) AS daily_cost_usd
  FROM `finops-gcp-agent.agent_finops_raw.agent_cost_events`
  WHERE DATE(event_ts) >= DATE_TRUNC(CURRENT_DATE(), MONTH)
    AND environment = 'production'
  GROUP BY 1
)
SELECT
  SUM(daily_cost_usd) AS mtd_cost_usd,
  100.00 AS monthly_budget_usd,
  SAFE_DIVIDE(SUM(daily_cost_usd), 100.00) * 100 AS budget_burn_pct,
  SAFE_DIVIDE(
    SUM(daily_cost_usd),
    NULLIF(DATE_DIFF(CURRENT_DATE(), DATE_TRUNC(CURRENT_DATE(), MONTH), DAY), 0)
  ) * DATE_DIFF(
    DATE_TRUNC(DATE_ADD(CURRENT_DATE(), INTERVAL 1 MONTH), MONTH),
    DATE_TRUNC(CURRENT_DATE(), MONTH),
    DAY
  ) AS projected_month_end_cost_usd
FROM daily_spend;
