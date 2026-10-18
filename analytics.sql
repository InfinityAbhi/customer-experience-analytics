-- SQLite queries used by run_analysis.py. NPS = % promoters - % detractors.
-- CSAT = % of responses with satisfaction 4 or 5 on a 1-5 scale.

-- Overall survey metrics.
SELECT
  COUNT(*) AS responses,
  ROUND(100.0 * SUM(CASE WHEN nps >= 9 THEN 1 WHEN nps <= 6 THEN -1 ELSE 0 END) / COUNT(*), 1) AS nps,
  ROUND(100.0 * SUM(CASE WHEN satisfaction >= 4 THEN 1 ELSE 0 END) / COUNT(*), 1) AS csat_top_two_pct,
  SUM(CASE WHEN comment <> '' THEN 1 ELSE 0 END) AS commented_responses
FROM responses;

-- Segment comparison. Churned is a survey label, not a causal churn estimate.
SELECT
  segment,
  COUNT(*) AS responses,
  ROUND(100.0 * SUM(CASE WHEN nps >= 9 THEN 1 WHEN nps <= 6 THEN -1 ELSE 0 END) / COUNT(*), 1) AS nps,
  ROUND(100.0 * SUM(CASE WHEN satisfaction >= 4 THEN 1 ELSE 0 END) / COUNT(*), 1) AS csat_top_two_pct
FROM responses
GROUP BY segment
ORDER BY nps ASC;

-- Friction themes among detractors who submitted optional text.
SELECT
  theme,
  COUNT(*) AS detractor_comments
FROM responses
WHERE nps <= 6 AND comment <> '' AND theme <> 'Other'
GROUP BY theme
ORDER BY detractor_comments DESC, theme;

-- Monthly trend. Grouping by survey submission month, not customer cohort.
SELECT
  survey_month,
  COUNT(*) AS responses,
  ROUND(100.0 * SUM(CASE WHEN nps >= 9 THEN 1 WHEN nps <= 6 THEN -1 ELSE 0 END) / COUNT(*), 1) AS nps,
  ROUND(100.0 * SUM(CASE WHEN satisfaction >= 4 THEN 1 ELSE 0 END) / COUNT(*), 1) AS csat_top_two_pct
FROM responses
GROUP BY survey_month
ORDER BY survey_month;
