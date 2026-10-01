-- SaaS Subscription Analytics — the SQL behind the dashboard
-- Engine: DuckDB (runs directly over the raw CSV, no load step needed).
-- Each query below powers one panel of docs/index.html.

-- Clean, typed view over the raw file. TotalCharges is blank for tenure-0
-- accounts, so it is cast defensively.
CREATE VIEW subs AS
SELECT
    customerID,
    Contract                                           AS contract,
    InternetService                                    AS internet_service,
    PaymentMethod                                      AS payment_method,
    TechSupport                                        AS tech_support,
    OnlineSecurity                                     AS online_security,
    CAST(tenure AS INTEGER)                            AS tenure,
    CAST(MonthlyCharges AS DOUBLE)                     AS monthly_charges,
    TRY_CAST(NULLIF(TRIM(TotalCharges), '') AS DOUBLE) AS total_charges,
    (Churn = 'Yes')                                    AS churned
FROM read_csv_auto('data/telco_churn.csv', header = True);

-- 1. Headline KPIs: base size, churn rate, active vs at-risk monthly revenue.
SELECT
    COUNT(*)                                                       AS customers,
    ROUND(100.0 * AVG(CASE WHEN churned THEN 1 ELSE 0 END), 1)     AS churn_rate,
    SUM(CASE WHEN NOT churned THEN monthly_charges ELSE 0 END)     AS active_mrr,
    SUM(CASE WHEN churned     THEN monthly_charges ELSE 0 END)     AS mrr_at_risk,
    ROUND(AVG(tenure), 1)                                          AS avg_tenure
FROM subs;

-- 2. Churn by contract type — the single biggest lever.
SELECT contract,
       COUNT(*)                                                   AS customers,
       ROUND(100.0 * AVG(CASE WHEN churned THEN 1 ELSE 0 END), 1) AS churn_rate
FROM subs
GROUP BY contract
ORDER BY churn_rate DESC;

-- 3. Churn by tenure cohort — isolates the risky early-life window.
SELECT cohort,
       COUNT(*)                                                   AS customers,
       ROUND(100.0 * AVG(CASE WHEN churned THEN 1 ELSE 0 END), 1) AS churn_rate
FROM (
    SELECT churned,
        CASE WHEN tenure <= 6  THEN '0-6 mo'
             WHEN tenure <= 12 THEN '7-12 mo'
             WHEN tenure <= 24 THEN '13-24 mo'
             WHEN tenure <= 48 THEN '25-48 mo'
             ELSE '49+ mo' END AS cohort,
        CASE WHEN tenure <= 6  THEN 1 WHEN tenure <= 12 THEN 2
             WHEN tenure <= 24 THEN 3 WHEN tenure <= 48 THEN 4 ELSE 5 END AS ord
    FROM subs
)
GROUP BY cohort, ord
ORDER BY ord;

-- 4. Retention curve: share still active at each tenure month.
SELECT tenure,
       ROUND(100.0 * AVG(CASE WHEN NOT churned THEN 1 ELSE 0 END), 1) AS retained_pct
FROM subs
GROUP BY tenure
HAVING COUNT(*) >= 20
ORDER BY tenure;

-- 5. Monthly revenue split (active vs lost) by contract.
SELECT contract,
       ROUND(SUM(CASE WHEN NOT churned THEN monthly_charges ELSE 0 END), 0) AS active_mrr,
       ROUND(SUM(CASE WHEN churned     THEN monthly_charges ELSE 0 END), 0) AS churned_mrr
FROM subs
GROUP BY contract
ORDER BY active_mrr DESC;

-- 6. Churn by internet service line.
SELECT internet_service,
       ROUND(100.0 * AVG(CASE WHEN churned THEN 1 ELSE 0 END), 1) AS churn_rate,
       COUNT(*)                                                   AS customers
FROM subs
GROUP BY internet_service
ORDER BY churn_rate DESC;

-- 7. Does adopting support features reduce churn? (feature impact)
SELECT 'Tech Support' AS feature, tech_support AS adopted,
       ROUND(100.0 * AVG(CASE WHEN churned THEN 1 ELSE 0 END), 1) AS churn_rate
FROM subs WHERE tech_support IN ('Yes', 'No') GROUP BY tech_support
UNION ALL
SELECT 'Online Security' AS feature, online_security AS adopted,
       ROUND(100.0 * AVG(CASE WHEN churned THEN 1 ELSE 0 END), 1) AS churn_rate
FROM subs WHERE online_security IN ('Yes', 'No') GROUP BY online_security
ORDER BY feature, adopted;
