"""
SaaS Subscription Analytics — Churn, Retention & Revenue
--------------------------------------------------------
End-to-end build: reads a real public subscription dataset, runs the analysis
in SQL (DuckDB) over the raw CSV, and renders a self-contained interactive
dashboard (docs/index.html) with Plotly. No server required; the output is a
single static HTML file that hosts for free on GitHub Pages.

Author: Devansh Sharma
Dataset: Telco Customer Churn (7,043 subscribers) — public IBM sample.
Tools: DuckDB (SQL), pandas, Plotly.
"""
from pathlib import Path
import duckdb
import plotly.graph_objects as go
import plotly.io as pio

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "telco_churn.csv"
OUT = ROOT / "docs" / "index.html"

# Brand palette
INK = "#0f172a"
ACCENT = "#2563eb"
DANGER = "#dc2626"
GOOD = "#059669"
MUTED = "#64748b"
GRID = "#e2e8f0"

con = duckdb.connect()
# Load the raw CSV into a clean typed view. TotalCharges has blank strings for
# brand-new (tenure 0) accounts, so cast defensively.
con.execute(f"""
CREATE VIEW subs AS
SELECT
    customerID,
    Contract                                  AS contract,
    InternetService                           AS internet_service,
    PaymentMethod                             AS payment_method,
    TechSupport                               AS tech_support,
    OnlineSecurity                            AS online_security,
    CAST(tenure AS INTEGER)                   AS tenure,
    CAST(MonthlyCharges AS DOUBLE)            AS monthly_charges,
    TRY_CAST(NULLIF(TRIM(TotalCharges), '') AS DOUBLE) AS total_charges,
    (Churn = 'Yes')                           AS churned
FROM read_csv_auto('{CSV}', header=True);
""")


def q(sql: str):
    return con.execute(sql).fetchdf()


# ---------------------------------------------------------------- headline KPIs
kpis = q("""
SELECT
    COUNT(*)                                              AS customers,
    ROUND(100.0 * AVG(CASE WHEN churned THEN 1 ELSE 0 END), 1) AS churn_rate,
    SUM(CASE WHEN NOT churned THEN monthly_charges ELSE 0 END) AS active_mrr,
    SUM(CASE WHEN churned     THEN monthly_charges ELSE 0 END) AS mrr_at_risk,
    ROUND(AVG(tenure), 1)                                 AS avg_tenure
FROM subs;
""").iloc[0]

# ------------------------------------------------------------ churn by contract
by_contract = q("""
SELECT contract,
       COUNT(*)                                                   AS customers,
       ROUND(100.0*AVG(CASE WHEN churned THEN 1 ELSE 0 END), 1)   AS churn_rate
FROM subs
GROUP BY contract
ORDER BY churn_rate DESC;
""")

# ------------------------------------------------------- churn by tenure cohort
by_cohort = q("""
SELECT cohort,
       COUNT(*)                                                   AS customers,
       ROUND(100.0*AVG(CASE WHEN churned THEN 1 ELSE 0 END), 1)   AS churn_rate
FROM (
    SELECT churned,
        CASE
            WHEN tenure <= 6  THEN '0-6 mo'
            WHEN tenure <= 12 THEN '7-12 mo'
            WHEN tenure <= 24 THEN '13-24 mo'
            WHEN tenure <= 48 THEN '25-48 mo'
            ELSE '49+ mo'
        END AS cohort,
        CASE
            WHEN tenure <= 6  THEN 1 WHEN tenure <= 12 THEN 2
            WHEN tenure <= 24 THEN 3 WHEN tenure <= 48 THEN 4 ELSE 5
        END AS ord
    FROM subs
)
GROUP BY cohort, ord
ORDER BY ord;
""")

# ------------------------------------------------------- retention curve (proxy)
# Share of customers at each tenure month who are still active (not churned).
retention = q("""
SELECT tenure,
       ROUND(100.0*AVG(CASE WHEN NOT churned THEN 1 ELSE 0 END), 1) AS retained_pct
FROM subs
GROUP BY tenure
HAVING COUNT(*) >= 20
ORDER BY tenure;
""")

# --------------------------------------------------------- monthly revenue split
rev_by_contract = q("""
SELECT contract,
       ROUND(SUM(CASE WHEN NOT churned THEN monthly_charges ELSE 0 END), 0) AS active_mrr,
       ROUND(SUM(CASE WHEN churned     THEN monthly_charges ELSE 0 END), 0) AS churned_mrr
FROM subs
GROUP BY contract
ORDER BY active_mrr DESC;
""")

# ------------------------------------------------------------ churn by internet
by_internet = q("""
SELECT internet_service,
       ROUND(100.0*AVG(CASE WHEN churned THEN 1 ELSE 0 END), 1) AS churn_rate,
       COUNT(*) AS customers
FROM subs
GROUP BY internet_service
ORDER BY churn_rate DESC;
""")

# -------------------------------------------------- feature adoption vs churn
# Do customers who adopt support features churn less? (Yes/No, excl. "no service")
feature_impact = q("""
SELECT 'Tech Support' AS feature, tech_support AS adopted,
       ROUND(100.0*AVG(CASE WHEN churned THEN 1 ELSE 0 END), 1) AS churn_rate
FROM subs WHERE tech_support IN ('Yes','No') GROUP BY tech_support
UNION ALL
SELECT 'Online Security' AS feature, online_security AS adopted,
       ROUND(100.0*AVG(CASE WHEN churned THEN 1 ELSE 0 END), 1) AS churn_rate
FROM subs WHERE online_security IN ('Yes','No') GROUP BY online_security
ORDER BY feature, adopted;
""")

# ============================================================ Plotly figures ===
LAYOUT = dict(
    template="plotly_white",
    font=dict(family="Inter, Helvetica, Arial, sans-serif", size=13, color=INK),
    margin=dict(l=48, r=24, t=16, b=40),
    height=320,
    paper_bgcolor="white", plot_bgcolor="white",
    xaxis=dict(gridcolor=GRID), yaxis=dict(gridcolor=GRID),
)


def bar(x, y, color, text=None, ytitle=""):
    fig = go.Figure(go.Bar(x=x, y=y, marker_color=color,
                           text=text, textposition="outside",
                           hovertemplate="%{x}<br>%{y}<extra></extra>"))
    fig.update_layout(**LAYOUT)
    fig.update_yaxes(title_text=ytitle)
    return fig


f_contract = bar(by_contract.contract, by_contract.churn_rate, DANGER,
                 [f"{v}%" for v in by_contract.churn_rate], "Churn rate (%)")

f_cohort = bar(by_cohort.cohort, by_cohort.churn_rate, ACCENT,
               [f"{v}%" for v in by_cohort.churn_rate], "Churn rate (%)")

f_retention = go.Figure(go.Scatter(
    x=retention.tenure, y=retention.retained_pct, mode="lines",
    line=dict(color=GOOD, width=3), fill="tozeroy",
    fillcolor="rgba(5,150,105,0.08)",
    hovertemplate="Tenure %{x} mo<br>%{y}% retained<extra></extra>"))
f_retention.update_layout(**LAYOUT)
f_retention.update_yaxes(title_text="Still active (%)", range=[0, 100])
f_retention.update_xaxes(title_text="Tenure (months)")

f_revenue = go.Figure()
f_revenue.add_bar(x=rev_by_contract.contract, y=rev_by_contract.active_mrr,
                  name="Active MRR", marker_color=GOOD)
f_revenue.add_bar(x=rev_by_contract.contract, y=rev_by_contract.churned_mrr,
                  name="Lost MRR", marker_color=DANGER)
f_revenue.update_layout(**LAYOUT, barmode="stack",
                        legend=dict(orientation="h", y=1.15, x=0))
f_revenue.update_yaxes(title_text="Monthly revenue ($)")

f_internet = bar(by_internet.internet_service, by_internet.churn_rate, MUTED,
                 [f"{v}%" for v in by_internet.churn_rate], "Churn rate (%)")

f_feature = go.Figure()
for adopted, col in [("No", DANGER), ("Yes", GOOD)]:
    d = feature_impact[feature_impact.adopted == adopted]
    f_feature.add_bar(x=d.feature, y=d.churn_rate, name=f"Adopted: {adopted}",
                      marker_color=col, text=[f"{v}%" for v in d.churn_rate],
                      textposition="outside")
f_feature.update_layout(**LAYOUT, barmode="group",
                        legend=dict(orientation="h", y=1.15, x=0))
f_feature.update_yaxes(title_text="Churn rate (%)")

figs = [
    ("Month-to-month contracts churn far more than annual ones",
     "Churn rate by contract type", f_contract),
    ("The first year is where subscribers leave", "Churn rate by tenure cohort", f_cohort),
    ("Retention climbs steeply with tenure", "Share still active by tenure month", f_retention),
    ("Most revenue at risk sits in month-to-month plans",
     "Monthly revenue, active vs lost, by contract", f_revenue),
    ("Fiber customers churn more than DSL", "Churn rate by internet service", f_internet),
    ("Adopting support features roughly halves churn",
     "Churn rate by feature adoption", f_feature),
]

# ================================================================= HTML page ===
cards = [
    ("Customers", f"{int(kpis.customers):,}", MUTED),
    ("Churn rate", f"{kpis.churn_rate}%", DANGER),
    ("Active MRR", f"${int(kpis.active_mrr):,}", GOOD),
    ("MRR at risk", f"${int(kpis.mrr_at_risk):,}", DANGER),
    ("Avg tenure", f"{kpis.avg_tenure} mo", ACCENT),
]
card_html = "".join(
    f'<div class="card"><div class="card-label">{lbl}</div>'
    f'<div class="card-value" style="color:{col}">{val}</div></div>'
    for lbl, val, col in cards)

panels = []
for i, (headline, sub, fig) in enumerate(figs):
    div = pio.to_html(fig, full_html=False,
                      include_plotlyjs=("cdn" if i == 0 else False),
                      config={"displayModeBar": False, "responsive": True})
    panels.append(
        f'<section class="panel"><h3>{headline}</h3>'
        f'<p class="sub">{sub}</p>{div}</section>')
panels_html = "\n".join(panels)

REPO = "https://github.com/devshar999/saas-subscription-analytics"
html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SaaS Subscription Analytics — Devansh Sharma</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:Inter,Helvetica,Arial,sans-serif; color:{INK};
         background:#f8fafc; line-height:1.5; }}
  .wrap {{ max-width:1120px; margin:0 auto; padding:32px 20px 64px; }}
  header.top {{ border-bottom:1px solid {GRID}; padding-bottom:20px; margin-bottom:24px; }}
  h1 {{ font-size:26px; margin:0 0 6px; letter-spacing:-0.02em; }}
  .byline {{ color:{MUTED}; font-size:14px; }}
  .byline a {{ color:{ACCENT}; text-decoration:none; }}
  .cards {{ display:grid; grid-template-columns:repeat(5,1fr); gap:14px; margin:24px 0 8px; }}
  .card {{ background:white; border:1px solid {GRID}; border-radius:12px; padding:16px; }}
  .card-label {{ font-size:12px; color:{MUTED}; text-transform:uppercase; letter-spacing:0.04em; }}
  .card-value {{ font-size:24px; font-weight:700; margin-top:4px; }}
  .grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:18px; margin-top:20px; }}
  .panel {{ background:white; border:1px solid {GRID}; border-radius:12px; padding:18px 18px 6px; }}
  .panel h3 {{ font-size:15px; margin:0 0 2px; }}
  .panel .sub {{ font-size:13px; color:{MUTED}; margin:0 0 8px; }}
  footer {{ margin-top:32px; color:{MUTED}; font-size:13px; border-top:1px solid {GRID}; padding-top:18px; }}
  footer code {{ background:#eef2f7; padding:1px 6px; border-radius:5px; }}
  @media (max-width:840px) {{ .cards{{grid-template-columns:repeat(2,1fr)}} .grid{{grid-template-columns:1fr}} }}
</style></head>
<body><div class="wrap">
  <header class="top">
    <h1>SaaS Subscription Analytics: Churn, Retention &amp; Revenue</h1>
    <div class="byline">Built by <strong>Devansh Sharma</strong> &nbsp;|&nbsp;
      SQL (DuckDB) + Python + Plotly &nbsp;|&nbsp;
      <a href="{REPO}">Source &amp; SQL on GitHub</a></div>
  </header>

  <p style="max-width:760px;color:{MUTED};margin:0 0 4px">
    An end-to-end analysis of <strong>{int(kpis.customers):,}</strong> subscribers:
    where revenue leaks through churn, which cohorts are most at risk, and which
    product levers retain customers. All figures computed in SQL over the raw data;
    hover any chart for detail.
  </p>

  <div class="cards">{card_html}</div>
  <div class="grid">{panels_html}</div>

  <footer>
    <strong>Method:</strong> raw CSV loaded and analysed entirely in SQL via DuckDB,
    orchestrated in Python, visualised with Plotly, and shipped as one static page.
    <strong>Data:</strong> public Telco Customer Churn sample (7,043 subscribers),
    used here as a stand-in for SaaS subscription data.
    <strong>Reproduce:</strong> <code>python src/build_dashboard.py</code>.
    Full SQL and code: <a href="{REPO}" style="color:{ACCENT}">{REPO}</a>.
  </footer>
</div></body></html>"""

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(html, encoding="utf-8")
print(f"Wrote {OUT} ({OUT.stat().st_size//1024} KB)")
print(f"KPIs: customers={int(kpis.customers)} churn={kpis.churn_rate}% "
      f"MRR=${int(kpis.active_mrr):,} at_risk=${int(kpis.mrr_at_risk):,} "
      f"avg_tenure={kpis.avg_tenure}mo")
