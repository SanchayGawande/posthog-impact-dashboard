"""
PostHog Engineering Impact Dashboard
Single-page Streamlit app identifying the top 5 most impactful engineers
in the PostHog/posthog repository over the last 90 days.
"""

import os
import datetime
import pandas as pd
import plotly.express as px
import streamlit as st

from github_client import fetch_all_data, fetch_closed_issues, token_status
from impact_model import compute_all_scores, DEFAULT_PARAMS, methodology_text

# ─── Page Config (must be first Streamlit call) ──────────────────────
st.set_page_config(
    page_title="PostHog Engineering Impact",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── CSS: Fix header overlap, compact layout ─────────────────────────
st.markdown("""
<style>
    /* Fix header overlap — proper top spacing */
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 1rem;
        max-width: 100%;
    }
    /* Clean heading spacing — prevent text merge */
    h1 { font-size: 1.5rem !important; margin-top: 0.25rem !important; margin-bottom: 0.5rem !important; }
    h2 { font-size: 1.15rem !important; margin-top: 0.25rem !important; margin-bottom: 0.5rem !important; }
    h3 { font-size: 1.0rem !important; margin-top: 0.25rem !important; margin-bottom: 0.4rem !important; }
    /* Compact metric cards */
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
    /* Compact table */
    .stDataFrame { font-size: 0.85rem; }
    /* Token badge */
    .token-badge {
        padding: 3px 10px; border-radius: 10px; font-size: 0.75rem;
        font-weight: 600; display: inline-block; margin-top: 0.3rem;
    }
    .token-active { background: #1a3a2a; color: #4ade80; border: 1px solid #22c55e; }
    .token-inactive { background: #3a2a1a; color: #fbbf24; border: 1px solid #f59e0b; }
    /* Sidebar compact */
    [data-testid="stSidebar"] { padding-top: 0.5rem; }
    [data-testid="stSidebar"] h3 { font-size: 0.85rem !important; margin-top: 0.5rem !important; }
    /* Expander compact */
    .streamlit-expanderHeader { font-size: 0.85rem !important; }
    /* Remove excess divider spacing */
    hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
    /* PR list compact */
    .pr-item { margin-bottom: 0.4rem; line-height: 1.4; }
    .pr-badge {
        display: inline-block; padding: 1px 6px; border-radius: 8px;
        font-size: 0.65rem; font-weight: 500; margin-left: 3px;
        background: #262730; border: 1px solid #404040; color: #ccc;
    }
    .pr-size { color: #888; font-size: 0.75rem; font-family: monospace; }
</style>
""", unsafe_allow_html=True)

# ─── Sidebar: Model Parameters ───────────────────────────────────────
st.sidebar.markdown("## ⚙️ Model Parameters")
st.sidebar.caption("Scores update instantly when you adjust sliders.")

params = DEFAULT_PARAMS.copy()

st.sidebar.markdown("### Weights")
params["shipped_weight"] = st.sidebar.slider("Shipped", 0.0, 1.0, DEFAULT_PARAMS["shipped_weight"], 0.05)
params["collab_weight"] = st.sidebar.slider("Collaboration", 0.0, 1.0, DEFAULT_PARAMS["collab_weight"], 0.05)
params["ops_weight"] = st.sidebar.slider("Operational", 0.0, 1.0, DEFAULT_PARAMS["ops_weight"], 0.05)

# Normalize weights
w_total = params["shipped_weight"] + params["collab_weight"] + params["ops_weight"]
if w_total > 0:
    params["shipped_weight"] /= w_total
    params["collab_weight"] /= w_total
    params["ops_weight"] /= w_total

st.sidebar.markdown("### Shipped Caps")
params["pr_size_cap"] = st.sidebar.slider("PR Size Cap", 1.0, 15.0, DEFAULT_PARAMS["pr_size_cap"], 0.5)
params["comment_cap"] = st.sidebar.slider("Comment Cap", 1, 30, DEFAULT_PARAMS["comment_cap"], 1)
params["comment_weight"] = st.sidebar.slider("Comment Weight", 0.0, 1.0, DEFAULT_PARAMS["comment_weight"], 0.05)
params["issue_close_bonus"] = st.sidebar.slider("Issue Close Bonus", 1.0, 3.0, DEFAULT_PARAMS["issue_close_bonus"], 0.1)
params["priority_label_bonus"] = st.sidebar.slider("Priority Label Bonus", 1.0, 3.0, DEFAULT_PARAMS["priority_label_bonus"], 0.1)

st.sidebar.markdown("### Review Caps")
params["review_base_weight"] = st.sidebar.slider("Review Base Wt", 0.0, 3.0, DEFAULT_PARAMS["review_base_weight"], 0.1)
params["review_approved_weight"] = st.sidebar.slider("Approved Wt", 0.0, 3.0, DEFAULT_PARAMS["review_approved_weight"], 0.1)
params["review_depth_cap"] = st.sidebar.slider("Depth Cap", 1, 10, DEFAULT_PARAMS["review_depth_cap"], 1)
params["collab_comment_weight"] = st.sidebar.slider("Depth Weight", 0.0, 1.0, DEFAULT_PARAMS["collab_comment_weight"], 0.05)

st.sidebar.markdown("### Operational")
params["issue_close_weight"] = st.sidebar.slider("Issue Close Wt", 0.0, 2.0, DEFAULT_PARAMS["issue_close_weight"], 0.1)
params["velocity_weight"] = st.sidebar.slider("Velocity Wt", 0.0, 1.0, DEFAULT_PARAMS["velocity_weight"], 0.05)

# =====================================================================
# A) HEADER — Title left, time window + token badge right
# =====================================================================
header_left, header_right = st.columns([3, 2])
with header_left:
    st.markdown("# 🚀 PostHog Engineering Impact")
    st.caption("Top 5 most impactful engineers · last 90 days · PostHog/posthog")
with header_right:
    now = datetime.datetime.utcnow()
    window_start = now - datetime.timedelta(days=90)
    is_active, status_msg = token_status()
    badge_class = "token-active" if is_active else "token-inactive"

    st.markdown(
        f"**📅** {window_start.strftime('%b %d')} — {now.strftime('%b %d, %Y')}  "
        f"&nbsp;&nbsp;"
        f'<span class="token-badge {badge_class}">{status_msg}</span>',
        unsafe_allow_html=True,
    )
    st.caption(f"Refreshed {now.strftime('%H:%M UTC')}")

# =====================================================================
# DATA FETCHING (cached — no re-fetch on slider change)
# =====================================================================
try:
    prs_df, reviews_df = fetch_all_data(days=90)
    issues_df = fetch_closed_issues(days=90)
    data_loaded = True
except RuntimeError as e:
    st.error(f"🚨 {e}")
    data_loaded = False
    prs_df = pd.DataFrame()
    reviews_df = pd.DataFrame()
    issues_df = pd.DataFrame()

if not data_loaded:
    st.stop()

# =====================================================================
# B) KPI CARDS — compact row
# =====================================================================
total_prs = len(prs_df)
total_reviews = len(reviews_df)
total_issues = len(issues_df)
engineers_active = len(set(
    list(prs_df["author"].unique() if not prs_df.empty else []) +
    list(reviews_df["reviewer"].unique() if not reviews_df.empty else [])
))

k1, k2, k3, k4 = st.columns(4)
k1.metric("📦 PRs Merged", f"{total_prs:,}")
k2.metric("👷 Engineers", f"{engineers_active:,}")
k3.metric("🔍 Reviews", f"{total_reviews:,}")
k4.metric("🎯 Issues Closed", f"{total_issues:,}")

st.markdown("---")

# =====================================================================
# SCORING (recomputed on slider change — no re-fetch)
# =====================================================================
scores_df = compute_all_scores(prs_df, reviews_df, issues_df, params)
top5 = scores_df.head(5).copy()

if top5.empty:
    st.warning("No engineer data found for the selected time window.")
    st.stop()

# =====================================================================
# C) MAIN CONTENT — two columns
# =====================================================================
col_table, col_drill = st.columns([3, 2], gap="large")

# ── Left: Top 5 Table + Score Breakdowns ──────────────────────────────
with col_table:
    st.markdown("### 🏆 Top 5 Engineers")

    display_cols = ["Engineer", "Total Impact", "Shipped", "Collaboration", "Operational"]
    st.dataframe(
        top5[display_cols],
        use_container_width=True,
        hide_index=True,
        height=220,
        column_config={
            "Total Impact": st.column_config.NumberColumn(format="%.1f"),
            "Shipped": st.column_config.NumberColumn(format="%.1f"),
            "Collaboration": st.column_config.NumberColumn(format="%.1f"),
            "Operational": st.column_config.NumberColumn(format="%.1f"),
        },
    )

    # Compact score breakdowns
    for _, row in top5.iterrows():
        with st.expander(f"📊 {row['Engineer']} — {row['Total Impact']:.1f} pts"):
            b1, b2, b3 = st.columns(3)
            with b1:
                st.metric("Shipped", f"{row['Shipped']:.1f}", help=f"Raw: {row['_shipped_raw']:.1f} → log₂ diminished")
                st.caption(f"{row['PRs Merged']} PRs · wt {params['shipped_weight']:.0%}")
            with b2:
                st.metric("Collab", f"{row['Collaboration']:.1f}", help=f"Raw: {row['_collab_raw']:.1f} → log₂ diminished")
                st.caption(f"{row['Reviews Given']} reviews · wt {params['collab_weight']:.0%}")
            with b3:
                st.metric("Ops", f"{row['Operational']:.1f}", help=f"Issues: {row['_ops_issues_score']:.1f} + Velocity: {row['_ops_velocity_score']:.1f}")
                st.caption(f"{row['_issues_closed']} issues · {row['_median_merge_hours']:.0f}h merge")

# ── Right: Engineer Drilldown ─────────────────────────────────────────
with col_drill:
    st.markdown("### 🔎 Drilldown")

    selected = st.selectbox("Engineer", top5["Engineer"].tolist(), label_visibility="collapsed")
    eng_row = top5[top5["Engineer"] == selected].iloc[0]

    # Top 3 Merged PRs
    st.markdown("**Top PRs**")
    pr_scores = eng_row["_pr_scores"]
    if pr_scores:
        sorted_prs = sorted(pr_scores, key=lambda x: x["score"], reverse=True)[:3]
        for ps in sorted_prs:
            pr_info = prs_df[prs_df["number"] == ps["number"]]
            if not pr_info.empty:
                pr = pr_info.iloc[0]
                title_short = ps["title"][:60] + ("…" if len(ps["title"]) > 60 else "")
                labels_html = "".join(
                    f'<span class="pr-badge">{l}</span>' for l in (pr["labels"] or [])
                )
                st.markdown(
                    f'[{title_short}]({pr["url"]}) · '
                    f'<span class="pr-size">+{pr["additions"]}/-{pr["deletions"]}</span> · '
                    f'**{ps["score"]:.1f}** pts {labels_html}',
                    unsafe_allow_html=True,
                )
    else:
        st.caption("No PRs")

    st.markdown("---")

    # Top 3 Reviews
    st.markdown("**Top Reviews**")
    review_scores = eng_row["_review_scores"]
    if review_scores:
        sorted_reviews = sorted(review_scores, key=lambda x: x["score"], reverse=True)[:3]
        for rs in sorted_reviews:
            icon = "✅" if rs["state"] == "APPROVED" else "💬"
            url = rs.get("url", "")
            link = f"[#{rs['pr_number']}]({url})" if url else f"#{rs['pr_number']}"
            st.markdown(f"{icon} {rs['state']} on {link} — **{rs['score']:.1f}** pts")
    else:
        st.caption("No reviews")

    st.markdown("---")

    # Weekly trend mini chart
    st.markdown("**Weekly Activity**")
    eng_prs = prs_df[prs_df["author"] == selected] if not prs_df.empty else pd.DataFrame()
    if not eng_prs.empty and "merged_at" in eng_prs.columns:
        weekly = eng_prs.set_index("merged_at").resample("W").size().reset_index(name="PRs")
        weekly.columns = ["Week", "PRs"]
        fig = px.area(
            weekly, x="Week", y="PRs",
            template="plotly_dark",
            color_discrete_sequence=["#FF694A"],
        )
        fig.update_layout(
            height=180,
            margin=dict(l=0, r=0, t=5, b=0),
            xaxis_title="", yaxis_title="",
            showlegend=False,
        )
        fig.update_traces(line_shape="spline")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No trend data")

# =====================================================================
# D) BOTTOM — Methodology + Exports
# =====================================================================
st.markdown("---")

bot_left, bot_right = st.columns([1, 1])

with bot_left:
    with st.expander("📖 Methodology — How Scores Work"):
        st.markdown(methodology_text(params))

with bot_right:
    st.markdown("**📥 Exports**")

    export_cols = ["Engineer", "Total Impact", "Shipped", "Collaboration", "Operational", "PRs Merged", "Reviews Given"]
    engineer_csv = scores_df[export_cols].to_csv(index=False)

    prs_export = prs_df.copy() if not prs_df.empty else pd.DataFrame()
    if not prs_export.empty:
        prs_export["labels"] = prs_export["labels"].apply(lambda x: "; ".join(x) if isinstance(x, list) else "")
        prs_csv = prs_export.drop(columns=["body"], errors="ignore").to_csv(index=False)
    else:
        prs_csv = ""

    reviews_csv = reviews_df.to_csv(index=False) if not reviews_df.empty else ""

    e1, e2, e3 = st.columns(3)
    e1.download_button("📊 Summary", engineer_csv, "engineer_summary.csv", "text/csv", use_container_width=True)
    e2.download_button("📦 PRs", prs_csv, "prs.csv", "text/csv", use_container_width=True)
    e3.download_button("🔍 Reviews", reviews_csv, "reviews.csv", "text/csv", use_container_width=True)

    # Local file writes (non-critical)
    os.makedirs("data_export", exist_ok=True)
    try:
        with open("data_export/engineer_summary.csv", "w") as f:
            f.write(engineer_csv)
        if prs_csv:
            with open("data_export/prs.csv", "w") as f:
                f.write(prs_csv)
        if reviews_csv:
            with open("data_export/reviews.csv", "w") as f:
                f.write(reviews_csv)
    except Exception:
        pass
