-- 03_runtime_views.sql
-- Views over runtime cost event data for unit economics reporting

-- Daily cost by agent and workflow
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.runtime_daily_agent` AS
SELECT
  DATE(event_ts)                                              AS usage_date,
  project_id,
  environment,
  agent_name,
  workflow_name,
  urgency,
  model_name,
  COUNT(DISTINCT run_id)                                      AS run_count,
  SUM(input_tokens)                                           AS input_tokens,
  SUM(output_tokens)                                          AS output_tokens,
  SUM(total_tokens)                                           AS total_tokens,
  SUM(estimated_model_cost_usd)                               AS est_model_cost_usd,
  SAFE_DIVIDE(
    SUM(estimated_model_cost_usd),
    COUNT(DISTINCT run_id)
  )                                                           AS est_cost_per_run_usd,
  AVG(latency_ms)                                             AS avg_latency_ms,
  APPROX_QUANTILES(latency_ms, 100)[OFFSET(99)]              AS p99_latency_ms,
  COUNTIF(status = 'error')                                   AS error_count,
  SUM(retry_count)                                            AS retry_count
FROM `finops-demo-2026.agent_finops_raw.agent_cost_events`
GROUP BY 1, 2, 3, 4, 5, 6, 7;

-- Step-level cost breakdown -- shows which pipeline step drives most cost
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.runtime_step_cost` AS
SELECT
  DATE(event_ts)                        AS usage_date,
  agent_name,
  workflow_name,
  step_name,
  environment,
  model_name,
  COUNT(*)                              AS step_executions,
  AVG(input_tokens)                     AS avg_input_tokens,
  AVG(output_tokens)                    AS avg_output_tokens,
  AVG(estimated_model_cost_usd)         AS avg_step_cost_usd,
  SUM(estimated_model_cost_usd)         AS total_step_cost_usd,
  AVG(latency_ms)                       AS avg_latency_ms
FROM `finops-demo-2026.agent_finops_raw.agent_cost_events`
WHERE step_name IS NOT NULL
GROUP BY 1, 2, 3, 4, 5, 6;

-- Month-to-date runtime cost summary -- for executive summary cards
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.runtime_mtd` AS
SELECT
  agent_name,
  environment,
  COUNT(DISTINCT run_id)                AS mtd_run_count,
  SUM(estimated_model_cost_usd)         AS mtd_est_cost_usd,
  SAFE_DIVIDE(
    SUM(estimated_model_cost_usd),
    COUNT(DISTINCT run_id)
  )                                     AS avg_cost_per_run_usd,
  AVG(latency_ms)                       AS avg_latency_ms
FROM `finops-demo-2026.agent_finops_raw.agent_cost_events`
WHERE DATE(event_ts) >= DATE_TRUNC(CURRENT_DATE(), MONTH)
  AND environment = 'production'
GROUP BY 1, 2;

-- Cost per 1,000 runs by agent -- headline unit economics metric
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.runtime_cost_per_1k` AS
SELECT
  agent_name,
  environment,
  DATE_TRUNC(DATE(event_ts), WEEK)      AS week_start,
  SAFE_DIVIDE(
    SUM(estimated_model_cost_usd),
    COUNT(DISTINCT run_id)
  ) * 1000                              AS est_cost_per_1k_runs_usd,
  COUNT(DISTINCT run_id)                AS run_count
FROM `finops-demo-2026.agent_finops_raw.agent_cost_events`
WHERE environment = 'production'
GROUP BY 1, 2, 3;

-- Token trend over time -- detects prompt inflation
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.token_trend_daily` AS
SELECT
  DATE(event_ts)            AS usage_date,
  agent_name,
  step_name,
  model_name,
  AVG(input_tokens)         AS avg_input_tokens,
  AVG(output_tokens)        AS avg_output_tokens,
  AVG(total_tokens)         AS avg_total_tokens,
  COUNT(*)                  AS sample_count
FROM `finops-demo-2026.agent_finops_raw.agent_cost_events`
WHERE step_name IS NOT NULL
GROUP BY 1, 2, 3, 4;

-- Cost by urgency/complexity -- shows how case mix drives cost
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.runtime_cost_by_urgency` AS
SELECT
  urgency,
  agent_name,
  environment,
  COUNT(DISTINCT run_id)                AS run_count,
  AVG(estimated_model_cost_usd)         AS avg_cost_per_run_usd,
  AVG(total_tokens)                     AS avg_tokens_per_run,
  AVG(latency_ms)                       AS avg_latency_ms
FROM `finops-demo-2026.agent_finops_raw.agent_cost_events`
WHERE DATE(event_ts) >= DATE_TRUNC(CURRENT_DATE(), MONTH)
GROUP BY 1, 2, 3;
