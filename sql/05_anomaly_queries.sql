-- 05_anomaly_queries.sql
-- Anomaly detection queries
-- Schedule the main anomaly query as a BigQuery scheduled query running every hour
-- Results populate agent_finops_mart.run_cost_anomalies

-- Main anomaly detection query
-- Flags runs where estimated cost exceeded baseline avg + 3 standard deviations
-- Schedule this as a BigQuery scheduled query: every 1 hour
CREATE OR REPLACE TABLE `finops-demo-2026.agent_finops_mart.run_cost_anomalies` AS
WITH baseline AS (
  SELECT
    agent_name,
    step_name,
    environment,
    AVG(estimated_model_cost_usd)     AS avg_run_cost,
    STDDEV(estimated_model_cost_usd)  AS stddev_run_cost
  FROM `finops-demo-2026.agent_finops_raw.agent_cost_events`
  WHERE event_ts >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
    AND status = 'success'
  GROUP BY agent_name, step_name, environment
),
recent_runs AS (
  SELECT
    e.*,
    b.avg_run_cost                    AS baseline_avg_cost_usd,
    b.stddev_run_cost                 AS baseline_stddev_cost_usd,
    SAFE_DIVIDE(
      e.estimated_model_cost_usd - b.avg_run_cost,
      NULLIF(b.stddev_run_cost, 0)
    )                                 AS z_score
  FROM `finops-demo-2026.agent_finops_raw.agent_cost_events` e
  JOIN baseline b
    ON e.agent_name = b.agent_name
   AND e.step_name = b.step_name
   AND e.environment = b.environment
  WHERE e.event_ts >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
)
SELECT
  CURRENT_TIMESTAMP()               AS detected_ts,
  run_id,
  agent_name,
  step_name,
  environment,
  urgency,
  estimated_model_cost_usd,
  baseline_avg_cost_usd,
  baseline_stddev_cost_usd,
  z_score                           AS deviation_multiplier,
  CASE
    WHEN estimated_model_cost_usd > baseline_avg_cost_usd * 5
      THEN 'Cost exceeded 5x baseline—possible retry loop or oversized input'
    WHEN estimated_model_cost_usd > baseline_avg_cost_usd * 3
      THEN 'Cost exceeded 3x baseline—investigate input size or prompt change'
    WHEN z_score > 3
      THEN 'Statistical outlier—cost more than 3 standard deviations above mean'
    ELSE 'Anomaly detected'
  END                               AS anomaly_reason
FROM recent_runs
WHERE z_score > 3
   OR estimated_model_cost_usd > baseline_avg_cost_usd * 3;

-- Daily mart rebuild query
-- Schedule as a BigQuery scheduled query running nightly at 01:00 UTC
CREATE OR REPLACE TABLE `finops-demo-2026.agent_finops_mart.agent_cost_daily`
PARTITION BY cost_date AS
SELECT
  DATE(event_ts)                                              AS cost_date,
  agent_name,
  workflow_name,
  environment,
  urgency,
  model_name,
  COUNT(DISTINCT run_id)                                      AS run_count,
  COUNT(*)                                                    AS step_count,
  SUM(input_tokens)                                           AS input_tokens,
  SUM(output_tokens)                                          AS output_tokens,
  SUM(total_tokens)                                           AS total_tokens,
  SUM(estimated_model_cost_usd)                               AS estimated_model_cost_usd,
  SAFE_DIVIDE(
    SUM(estimated_model_cost_usd),
    COUNT(DISTINCT run_id)
  )                                                           AS avg_cost_per_run_usd,
  AVG(latency_ms)                                             AS avg_latency_ms,
  APPROX_QUANTILES(latency_ms, 100)[OFFSET(99)]              AS p99_latency_ms,
  COUNTIF(status = 'error')                                   AS error_count,
  SUM(retry_count)                                            AS retry_count
FROM `finops-demo-2026.agent_finops_raw.agent_cost_events`
GROUP BY 1, 2, 3, 4, 5, 6;

-- Top expensive runs in the last 7 days—for anomaly dashboard table
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.top_expensive_runs` AS
SELECT
  run_id,
  agent_name,
  workflow_name,
  step_name,
  urgency,
  environment,
  DATE(event_ts)                    AS run_date,
  estimated_model_cost_usd,
  total_tokens,
  latency_ms,
  retry_count,
  status
FROM `finops-demo-2026.agent_finops_raw.agent_cost_events`
WHERE DATE(event_ts) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY estimated_model_cost_usd DESC
LIMIT 100;

-- Budget burn rate view—shows projected month-end spend vs budget
-- Replace 500.00 with your actual monthly budget
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.budget_burn_rate` AS
WITH daily_spend AS (
  SELECT
    DATE(event_ts)                  AS spend_date,
    SUM(estimated_model_cost_usd)   AS daily_cost_usd
  FROM `finops-demo-2026.agent_finops_raw.agent_cost_events`
  WHERE DATE(event_ts) >= DATE_TRUNC(CURRENT_DATE(), MONTH)
    AND environment = 'production'
  GROUP BY 1
)
SELECT
  SUM(daily_cost_usd)                                             AS mtd_cost_usd,
  500.00                                                          AS monthly_budget_usd,
  SAFE_DIVIDE(SUM(daily_cost_usd), 500.00) * 100                 AS budget_burn_pct,
  SAFE_DIVIDE(
    SUM(daily_cost_usd),
    DATE_DIFF(CURRENT_DATE(), DATE_TRUNC(CURRENT_DATE(), MONTH), DAY)
  ) * DATE_DIFF(
    DATE_TRUNC(DATE_ADD(CURRENT_DATE(), INTERVAL 1 MONTH), MONTH),
    DATE_TRUNC(CURRENT_DATE(), MONTH),
    DAY
  )                                                               AS projected_month_end_cost_usd
FROM daily_spend;
