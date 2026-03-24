-- 02_billing_views.sql
-- Views over Cloud Billing export tables
-- Requires Cloud Billing export to be enabled and pointed at billing_raw dataset
-- See README for export configuration steps

-- Daily billed cost by service and SKU
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.billing_daily_service` AS
SELECT
  DATE(usage_start_time)      AS usage_date,
  project.id                  AS project_id,
  project.name                AS project_name,
  service.description         AS service_name,
  sku.description             AS sku_name,
  location.region             AS region,
  SUM(cost)                   AS billed_cost_usd,
  SUM(cost_at_list)           AS list_cost_usd,
  SUM(credits.amount)         AS credits_usd
FROM `finops-demo-2026.billing_raw.gcp_billing_export_resource_v1_*`
CROSS JOIN UNNEST(credits) AS credits
GROUP BY 1, 2, 3, 4, 5, 6;

-- Monthly billed cost by service -- for executive summary cards
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.billing_monthly_service` AS
SELECT
  DATE_TRUNC(usage_date, MONTH)   AS billing_month,
  project_id,
  service_name,
  SUM(billed_cost_usd)            AS billed_cost_usd,
  SUM(list_cost_usd)              AS list_cost_usd,
  SUM(credits_usd)                AS credits_usd
FROM `finops-demo-2026.agent_finops_mart.billing_daily_service`
GROUP BY 1, 2, 3;

-- AI-specific services only -- Vertex AI, Healthcare API, Pub/Sub, Firestore, DLP
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.billing_ai_services` AS
SELECT
  usage_date,
  project_id,
  service_name,
  sku_name,
  billed_cost_usd
FROM `finops-demo-2026.agent_finops_mart.billing_daily_service`
WHERE service_name IN (
  'Vertex AI',
  'Cloud Healthcare API',
  'Cloud Pub/Sub',
  'Cloud Firestore',
  'Cloud Data Loss Prevention',
  'BigQuery',
  'Cloud Storage',
  'Cloud Run'
);

-- Month-to-date total billed cost -- used in executive summary card
CREATE OR REPLACE VIEW `finops-demo-2026.agent_finops_mart.billing_mtd` AS
SELECT
  project_id,
  SUM(billed_cost_usd) AS mtd_billed_cost_usd
FROM `finops-demo-2026.agent_finops_mart.billing_daily_service`
WHERE usage_date >= DATE_TRUNC(CURRENT_DATE(), MONTH)
GROUP BY 1;
