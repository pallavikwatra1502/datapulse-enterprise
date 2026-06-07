
import gradio as gr
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import random
import datetime
import networkx as nx

ROOT = Path(__file__).parent
DATA = ROOT / "data"

datasets = pd.read_csv(DATA / "datasets.csv")
quality = pd.read_csv(DATA / "quality_results.csv")
pipelines = pd.read_csv(DATA / "pipeline_runs.csv")
incidents = pd.read_csv(DATA / "incidents.csv")
lineage = pd.read_csv(DATA / "lineage_edges.csv")

def platform_metrics(owner="All"):
    q, p, inc = filter_data(owner)
    quality_pass = round((q["status"].eq("Passed").mean() * 100), 1) if len(q) else 0
    sla_score = round((p["sla_status"].eq("Met").mean() * 100), 1) if len(p) else 0
    open_inc = int(inc[~inc["status"].eq("Resolved")].shape[0])
    critical = int(datasets[datasets["criticality"].eq("Tier 0")].shape[0])
    health = max(0, round((quality_pass * 0.42) + (sla_score * 0.42) - (open_inc * 0.8) + 12, 1))
    return health, quality_pass, sla_score, open_inc, critical

def filter_data(owner="All"):
    if owner == "All":
        return quality.copy(), pipelines.copy(), incidents.copy()
    ds = set(datasets[datasets["owner_team"].eq(owner)]["dataset"])
    return (
        quality[quality["owner_team"].eq(owner)].copy(),
        pipelines[pipelines["dataset"].isin(ds)].copy(),
        incidents[incidents["owner_team"].eq(owner)].copy()
    )

def metric_html(owner="All"):
    health, qpass, sla, open_inc, critical = platform_metrics(owner)
    html = f"""
    <div class="metric-grid">
      <div class="metric-card"><span>Platform Health</span><strong>{health}/100</strong></div>
      <div class="metric-card"><span>Quality Pass Rate</span><strong>{qpass}%</strong></div>
      <div class="metric-card"><span>Pipeline SLA Score</span><strong>{sla}%</strong></div>
      <div class="metric-card"><span>Open Incidents</span><strong>{open_inc}</strong></div>
      <div class="metric-card"><span>Tier 0 Datasets</span><strong>{critical}</strong></div>
    </div>
    """
    return html

def overview(owner="All"):
    q, p, inc = filter_data(owner)
    q_status = q.groupby("status").size().reset_index(name="count")
    fig1 = px.bar(q_status, x="status", y="count", title="Data Quality Status")
    fig1.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")

    sla = p.groupby("sla_status").size().reset_index(name="count")
    fig2 = px.pie(sla, names="sla_status", values="count", title="Pipeline SLA Compliance")
    fig2.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")

    sev = inc.groupby("severity").size().reset_index(name="count") if len(inc) else pd.DataFrame({"severity":[],"count":[]})
    fig3 = px.bar(sev, x="severity", y="count", title="Incident Severity")
    fig3.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return metric_html(owner), fig1, fig2, fig3

def live_pipeline_command_center(owner="All"):
    _, p, _ = filter_data(owner)
    latest = p.sort_values("run_date", ascending=False).groupby("pipeline").head(1).copy()
    # simulate live state movement on every click/refresh
    idx = latest.sample(min(3, len(latest))).index
    for i in idx:
        latest.loc[i, "status"] = random.choice(["Running", "Succeeded", "Delayed", "Failed"])
        if latest.loc[i, "status"] in ["Delayed", "Failed"]:
            latest.loc[i, "sla_status"] = "Breached"
    fig = px.scatter(
        latest,
        x="duration_minutes",
        y="records_processed",
        size="retry_count",
        color="status",
        hover_name="pipeline",
        hover_data=["dataset", "sla_minutes", "error_category", "backlog_events", "cpu_utilisation_pct"],
        title="Live Pipeline Command Center"
    )
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    display = latest[["pipeline","dataset","pipeline_type","status","sla_status","duration_minutes","sla_minutes","retry_count","error_category","backlog_events","cpu_utilisation_pct"]].sort_values(["status","duration_minutes"], ascending=[True, False])
    return fig, display

def quality_hub(owner="All"):
    q, _, _ = filter_data(owner)
    failed = q.sort_values(["status","criticality"], ascending=[True, True])
    by_type = q.groupby(["rule_type","status"]).size().reset_index(name="count")
    fig = px.bar(by_type, x="rule_type", y="count", color="status", title="Quality Rules by Type", barmode="stack")
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig, failed[["rule_id","dataset","owner_team","criticality","regulatory_mapping","rule_type","threshold_pct","current_score_pct","status","business_impact"]]

def sla_monitor(owner="All"):
    _, p, _ = filter_data(owner)
    recent = p.sort_values("run_date", ascending=False).head(100)
    fig = px.scatter(
        recent, x="sla_minutes", y="duration_minutes", color="sla_status",
        size="retry_count", hover_name="pipeline", hover_data=["dataset","status","error_category"],
        title="Pipeline Runtime vs SLA"
    )
    fig.add_shape(type="line", x0=0, y0=0, x1=max(recent["sla_minutes"].max(), 1), y1=max(recent["sla_minutes"].max(), 1), line=dict(dash="dash", color="#62f5d0"))
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    breached = recent[recent["sla_status"].eq("Breached")][["run_id","pipeline","dataset","run_date","duration_minutes","sla_minutes","status","error_category","retry_count"]]
    return fig, breached

def lineage_explorer(dataset_name="regulatory_reporting"):
    nodes = list(pd.unique(lineage[["source","target"]].values.ravel()))
    G = nx.DiGraph()
    for _, r in lineage.iterrows():
        G.add_edge(r["source"], r["target"], label=r["relationship"])

    downstream = set()
    if dataset_name in G:
        downstream = nx.descendants(G, dataset_name)
    impacted = lineage[(lineage["source"].eq(dataset_name)) | (lineage["target"].isin(downstream)) | (lineage["target"].eq(dataset_name))]

    labels = nodes
    index = {n:i for i,n in enumerate(labels)}
    fig = go.Figure(data=[go.Sankey(
        node=dict(label=labels, pad=15, thickness=15, color=["#62f5d0" if n==dataset_name else "#72a7ff" for n in labels]),
        link=dict(
            source=[index[s] for s in lineage["source"]],
            target=[index[t] for t in lineage["target"]],
            value=[1] * len(lineage),
            color=["rgba(255,255,255,.18)"] * len(lineage)
        )
    )])
    fig.update_layout(title_text="Enterprise Data Lineage", font_color="#eef6ff", paper_bgcolor="rgba(0,0,0,0)")
    impact = f"Selected dataset: {dataset_name}\n\nDownstream impacted assets:\n" + "\n".join([f"- {x}" for x in sorted(downstream)]) if downstream else f"No downstream assets found for {dataset_name}."
    return fig, impact, impacted

def incident_center(owner="All"):
    _, _, inc = filter_data(owner)
    table = inc[["incident_id","dataset","severity","status","owner_team","trigger","business_impact","root_cause_hint","recommended_action"]].sort_values(["status","severity"])
    sev = inc.groupby(["severity","status"]).size().reset_index(name="count") if len(inc) else pd.DataFrame({"severity":[],"status":[],"count":[]})
    fig = px.bar(sev, x="severity", y="count", color="status", title="Incident Status by Severity", barmode="group")
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig, table

def ask_copilot(question, owner="All"):
    q, p, inc = filter_data(owner)
    question_l = (question or "").lower()
    if not question_l.strip():
        return "Ask about failed quality rules, SLA breaches, lineage impact, incidents, RCA, or executive summary."

    if "executive" in question_l or "summary" in question_l:
        health, qpass, sla, open_inc, critical = platform_metrics(owner)
        return f"""Executive Summary

Platform health is {health}/100. Data quality pass rate is {qpass}%, pipeline SLA compliance is {sla}%, and there are {open_inc} open incidents.

Priority:
1. Resolve Tier 0 data product incidents.
2. Investigate SLA breaches affecting regulatory and finance datasets.
3. Fix failed schema drift, freshness and completeness rules.
4. Validate downstream reporting impact through lineage.
"""

    if "quality" in question_l or "failed" in question_l or "rule" in question_l:
        bad = q[q["status"].eq("Failed")].head(8)
        if bad.empty:
            return "No failed quality rules found for the selected owner."
        return "Failed data quality checks:\n" + "\n".join([f"- {r.dataset}: {r.rule_type} scored {r.current_score_pct}% vs threshold {r.threshold_pct}%. Impact: {r.business_impact}" for r in bad.itertuples()])

    if "sla" in question_l or "pipeline" in question_l or "delayed" in question_l:
        bad = p[p["sla_status"].eq("Breached")].head(8)
        if bad.empty:
            return "No SLA breaches found for the selected owner."
        return "Pipeline SLA issues:\n" + "\n".join([f"- {r.pipeline} on {r.dataset}: {r.duration_minutes} minutes vs {r.sla_minutes} SLA. Cause: {r.error_category}" for r in bad.itertuples()])

    if "lineage" in question_l or "impact" in question_l or "downstream" in question_l:
        return """Lineage Impact Summary

Critical paths:
- security_events + iam_inventory → audit_evidence → regulatory_reporting → Board Risk Dashboard
- payments_fact + customer_profile → fraud_signals → risk_feature_store
- cloud_cost_daily → FinOps Dashboard

If upstream quality or SLA failures occur, downstream dashboards and regulatory reporting can become stale or inaccurate.
"""

    if "incident" in question_l or "root cause" in question_l or "rca" in question_l:
        open_inc = inc[~inc["status"].eq("Resolved")].head(8)
        if open_inc.empty:
            return "No open incidents found for the selected owner."
        return "Open Incident RCA:\n" + "\n".join([f"- {r.incident_id} | {r.dataset} | {r.severity}: likely cause {r.root_cause_hint}. Recommended action: {r.recommended_action}" for r in open_inc.itertuples()])

    return "I can help with executive summary, failed quality rules, SLA breaches, lineage impact, incidents and root-cause analysis."

def rca_report(owner="All"):
    q, p, inc = filter_data(owner)
    health, qpass, sla, open_inc, critical = platform_metrics(owner)
    open_incidents = inc[~inc["status"].eq("Resolved")].head(10)
    report = f"""DataPulse Enterprise RCA Report
Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}

Owner Filter: {owner}
Platform Health: {health}/100
Data Quality Pass Rate: {qpass}%
Pipeline SLA Compliance: {sla}%
Open Incidents: {open_inc}
Tier 0 Datasets: {critical}

Top Open Incidents:
"""
    for r in open_incidents.itertuples():
        report += f"- {r.incident_id} | {r.dataset} | {r.severity} | {r.trigger} | Root cause: {r.root_cause_hint} | Action: {r.recommended_action}\n"
    report += """

Recommended Actions:
1. Prioritise Tier 0 and regulatory datasets.
2. Backfill failed or delayed partitions.
3. Add schema contract validation for source changes.
4. Escalate recurring SLA breaches to platform owners.
5. Validate downstream dashboards after remediation.
"""
    return report

custom_css = """
.gradio-container {
    background: radial-gradient(circle at top right, rgba(98,245,208,.15), transparent 32%), #071018 !important;
    color: #eef6ff !important;
}
.prose, .markdown, label, .gr-form, .gr-box, .gr-panel { color: #eef6ff !important; }
.hero {
    padding: 32px;
    border-radius: 24px;
    border: 1px solid rgba(98,245,208,.22);
    background: linear-gradient(135deg,rgba(16,27,40,.96),rgba(7,16,24,.96));
    margin-bottom: 18px;
}
.hero h1 { font-size: 48px; margin: 0 0 8px; }
.hero p { color: #a9b8ca; font-size: 17px; max-width: 980px; }
.metric-grid {
    display:grid;
    grid-template-columns: repeat(5, minmax(150px,1fr));
    gap: 12px;
}
.metric-card {
    padding: 18px;
    border-radius: 18px;
    background: rgba(255,255,255,.06);
    border: 1px solid rgba(255,255,255,.12);
}
.metric-card span { color:#a9b8ca; font-size:13px; display:block; }
.metric-card strong { color:#62f5d0; font-size:28px; display:block; margin-top:6px; }
"""

owners = ["All"] + sorted(datasets["owner_team"].unique().tolist())
dataset_names = sorted(datasets["dataset"].unique().tolist())

with gr.Blocks(css=custom_css, title="DataPulse Enterprise") as demo:
    gr.HTML("""
    <div class="hero">
        <div style="color:#62f5d0;letter-spacing:4px;font-weight:800;text-transform:uppercase;font-size:12px;">Real-Time Data Engineering • Observability • SLA Monitoring • Lineage</div>
        <h1>DataPulse Enterprise</h1>
        <p>Live data operations command center for monitoring critical data products, pipeline reliability, quality gates, lineage impact and incident root-cause analysis.</p>
        <p style="color:#a9b8ca;">Created by Pallavi Kwatra</p>
    </div>
    """)

    owner = gr.Dropdown(owners, value="All", label="Owner / Platform Team Filter")

    with gr.Tab("Executive Command Center"):
        metrics = gr.HTML()
        with gr.Row():
            q_fig = gr.Plot()
            sla_fig = gr.Plot()
            inc_fig = gr.Plot()
        owner.change(overview, inputs=owner, outputs=[metrics, q_fig, sla_fig, inc_fig])
        demo.load(overview, inputs=owner, outputs=[metrics, q_fig, sla_fig, inc_fig])

    with gr.Tab("Real-Time Pipeline Monitoring"):
        refresh = gr.Button("Refresh Live Pipeline State")
        pipe_fig = gr.Plot()
        pipe_table = gr.Dataframe(label="Latest Pipeline Runs")
        refresh.click(live_pipeline_command_center, inputs=owner, outputs=[pipe_fig, pipe_table])
        owner.change(live_pipeline_command_center, inputs=owner, outputs=[pipe_fig, pipe_table])
        demo.load(live_pipeline_command_center, inputs=owner, outputs=[pipe_fig, pipe_table])

    with gr.Tab("Data Quality Hub"):
        quality_fig = gr.Plot()
        quality_table = gr.Dataframe(label="Quality Rules")
        owner.change(quality_hub, inputs=owner, outputs=[quality_fig, quality_table])
        demo.load(quality_hub, inputs=owner, outputs=[quality_fig, quality_table])

    with gr.Tab("Pipeline SLA Monitor"):
        sla_runtime_fig = gr.Plot()
        breach_table = gr.Dataframe(label="SLA Breaches")
        owner.change(sla_monitor, inputs=owner, outputs=[sla_runtime_fig, breach_table])
        demo.load(sla_monitor, inputs=owner, outputs=[sla_runtime_fig, breach_table])

    with gr.Tab("Lineage & Impact Explorer"):
        ds_select = gr.Dropdown(dataset_names, value="regulatory_reporting", label="Select Dataset")
        lineage_fig = gr.Plot()
        impact_text = gr.Textbox(label="Downstream Impact", lines=8)
        lineage_table = gr.Dataframe(label="Lineage Edges")
        ds_select.change(lineage_explorer, inputs=ds_select, outputs=[lineage_fig, impact_text, lineage_table])
        demo.load(lineage_explorer, inputs=ds_select, outputs=[lineage_fig, impact_text, lineage_table])

    with gr.Tab("Incident Center"):
        inc_status_fig = gr.Plot()
        inc_table = gr.Dataframe(label="Reliability Incidents")
        owner.change(incident_center, inputs=owner, outputs=[inc_status_fig, inc_table])
        demo.load(incident_center, inputs=owner, outputs=[inc_status_fig, inc_table])

    with gr.Tab("Reliability Copilot"):
        question = gr.Textbox(label="Ask DataPulse", placeholder="Ask: Give executive summary / Which SLA breached? / What is downstream impact? / Explain RCA")
        answer = gr.Textbox(label="Copilot Answer", lines=14)
        ask = gr.Button("Ask Reliability Copilot")
        ask.click(ask_copilot, inputs=[question, owner], outputs=answer)

    with gr.Tab("RCA Report"):
        report = gr.Textbox(label="Generated RCA Report", lines=18)
        report_btn = gr.Button("Generate RCA Report")
        report_btn.click(rca_report, inputs=owner, outputs=report)

    with gr.Tab("Architecture"):
        gr.Markdown("""
        ## Production Architecture

        ```text
        Data Sources
          ├─ BigQuery INFORMATION_SCHEMA
          ├─ Cloud Composer / Airflow Metadata
          ├─ Dataflow Job Metrics
          ├─ Cloud Logging
          ├─ Data Quality Results
          └─ Business Metadata / Ownership

                 ↓

        DataPulse Collection Layer
          ├─ Pipeline run ingestion
          ├─ Quality result ingestion
          ├─ SLA monitoring
          ├─ Lineage capture
          └─ Incident signal generation

                 ↓

        Reliability Intelligence Engine
          ├─ Platform health score
          ├─ SLA breach detection
          ├─ Quality failure prioritisation
          ├─ Downstream impact analysis
          └─ RCA recommendation engine

                 ↓

        Experience Layer
          ├─ Executive Command Center
          ├─ Pipeline Monitoring
          ├─ Data Quality Hub
          ├─ Lineage Explorer
          ├─ Incident Center
          └─ Reliability Copilot
        ```

        ## Production Extensions

        - BigQuery metadata connector
        - Cloud Composer DAG run connector
        - Dataflow monitoring connector
        - Dataplex / Data Catalog integration
        - Pub/Sub alert routing
        - Slack / Microsoft Teams notifications
        - Jira / ServiceNow incident creation
        """)

if __name__ == "__main__":
    demo.launch()
