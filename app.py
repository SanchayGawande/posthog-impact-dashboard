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

from github_client import fetch_merged_prs, fetch_reviews_for_prs, fetch_closed_issues, token_status
from impact_model import compute_all_scores, DEFAULT_PARAMS, methodology_text

# ─── Page Config ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="PostHog Engineering Impact Dashboard",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Font Awesome CDN ─────────────────────────────────────────────────
st.markdown(
    '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">',
    unsafe_allow_html=True,
)

def fa(name: str, extra_style: str = "") -> str:
    """Return an inline Font Awesome icon HTML snippet."""
    style = f' style="{extra_style}"' if extra_style else ""
    return f'<i class="fa-solid fa-{name}"{style}></i>'

# ─── Custom CSS ───────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Tighter padding */
    .block-container { padding-top: 1rem; padding-bottom: 0rem; }
    /* Smaller headings */
    h1 { font-size: 1.6rem !important; margin-bottom: 0.2rem !important; }
    h2 { font-size: 1.2rem !important; }
    h3 { font-size: 1.05rem !important; }
    /* Metric cards */
    [data-testid="stMetricValue"] { font-size: 1.5rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.8rem !important; }
    /* Compact tables */
    .stDataFrame { font-size: 0.85rem; }
    /* Badge styling */
    .token-badge {
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
        display: inline-block;
        margin-top: 0.5rem;
    }
    .token-active { background: #1a3a2a; color: #4ade80; border: 1px solid #22c55e; }
    .token-inactive { background: #3a2a1a; color: #fbbf24; border: 1px solid #f59e0b; }
    /* Sidebar */
    [data-testid="stSidebar"] { padding-top: 1rem; }
    /* Expander */
    .streamlit-expanderHeader { font-size: 0.9rem !important; }
    /* FA icon spacing inside markdown */
    .fa-solid { margin-right: 6px; }
</style>
""", unsafe_allow_html=True)

# ─── Sidebar: Model Parameters ───────────────────────────────────────
st.sidebar.markdown(f'<h2>{fa("gear")} Model Parameters</h2>', unsafe_allow_html=True)
st.sidebar.caption("Adjust weights, caps, and bonuses. Scores update instantly.")

params = DEFAULT_PARAMS.copy()

st.sidebar.markdown("### Component Weights")
params["shipped_weight"] = st.sidebar.slider("Shipped Weight", 0.0, 1.0, DEFAULT_PARAMS["shipped_weight"], 0.05)
params["collab_weight"] = st.sidebar.slider("Collaboration Weight", 0.0, 1.0, DEFAULT_PARAMS["collab_weight"], 0.05)
params["ops_weight"] = st.sidebar.slider("Operational Weight", 0.0, 1.0, DEFAULT_PARAMS["ops_weight"], 0.05)

# Normalize weights
w_total = params["shipped_weight"] + params["collab_weight"] + params["ops_weight"]
if w_total > 0:
    params["shipped_weight"] /= w_total
    params["collab_weight"] /= w_total
    params["ops_weight"] /= w_total

st.sidebar.markdown("### Shipped Impact")
params["pr_size_cap"] = st.sidebar.slider("PR Size Cap", 1.0, 15.0, DEFAULT_PARAMS["pr_size_cap"], 0.5)
params["comment_cap"] = st.sidebar.slider("Comment Cap", 1, 30, DEFAULT_PARAMS["comment_cap"], 1)
params["comment_weight"] = st.sidebar.slider("Comment Weight", 0.0, 1.0, DEFAULT_PARAMS["comment_weight"], 0.05)
params["issue_close_bonus"] = st.sidebar.slider("Issue Close Bonus", 1.0, 3.0, DEFAULT_PARAMS["issue_close_bonus"], 0.1)
params["priority_label_bonus"] = st.sidebar.slider("Priority Label Bonus", 1.0, 3.0, DEFAULT_PARAMS["priority_label_bonus"], 0.1)

st.sidebar.markdown("### Collaboration Impact")
params["review_base_weight"] = st.sidebar.slider("Review Base Weight", 0.0, 3.0, DEFAULT_PARAMS["review_base_weight"], 0.1)
params["review_approved_weight"] = st.sidebar.slider("Review Approved Weight", 0.0, 3.0, DEFAULT_PARAMS["review_approved_weight"], 0.1)
params["review_depth_cap"] = st.sidebar.slider("Review Depth Cap", 1, 10, DEFAULT_PARAMS["review_depth_cap"], 1)
params["collab_comment_weight"] = st.sidebar.slider("Review Depth Weight", 0.0, 1.0, DEFAULT_PARAMS["collab_comment_weight"], 0.05)

st.sidebar.markdown("### Operational Impact")
params["issue_close_weight"] = st.sidebar.slider("Issue Close Weight", 0.0, 2.0, DEFAULT_PARAMS["issue_close_weight"], 0.1)
params["velocity_weight"] = st.sidebar.slider("Velocity Weight", 0.0, 1.0, DEFAULT_PARAMS["velocity_weight"], 0.05)

# ─── Header Row ───────────────────────────────────────────────────────
h1, h2, h3 = st.columns([3, 2, 2])
with h1:
    st.markdown(f'<h1>{fa("rocket")} PostHog Engineering Impact</h1>', unsafe_allow_html=True)
    st.caption("Top 5 most impactful engineers · Last 90 days")
with h2:
    now = datetime.datetime.utcnow()
    window_start = now - datetime.timedelta(days=90)
    st.markdown(f'**{fa("calendar-days")} Window:** {window_start.strftime("%b %d")} — {now.strftime("%b %d, %Y")}', unsafe_allow_html=True)
    st.caption(f"Last refreshed: {now.strftime('%Y-%m-%d %H:%M UTC')}")
with h3:
    is_active, status_msg = token_status()
    badge_class = "token-active" if is_active else "token-inactive"
    st.markdown(f'<div class="token-badge {badge_class}">{status_msg}</div>', unsafe_allow_html=True)

st.divider()

# ─── Data Fetching ───────────────────────────────────────────────────
try:
    prs_df = fetch_merged_prs(days=90)
    pr_authors = {}
    pr_numbers = []
    if not prs_df.empty:
        pr_authors = dict(zip(prs_df["number"], prs_df["author"]))
        pr_numbers = prs_df["number"].tolist()

    reviews_df = fetch_reviews_for_prs(pr_numbers, pr_authors)
    issues_df = fetch_closed_issues(days=90)

    data_loaded = True
except RuntimeError as e:
    st.error(f"{e}")
    data_loaded = False
    prs_df = pd.DataFrame()
    reviews_df = pd.DataFrame()
    issues_df = pd.DataFrame()

# ─── Metric Cards ─────────────────────────────────────────────────────
if data_loaded:
    m1, m2, m3, m4 = st.columns(4)
    total_prs = len(prs_df)
    total_reviews = len(reviews_df)
    total_issues = len(issues_df)
    engineers_active = len(set(
        list(prs_df["author"].unique() if not prs_df.empty else []) +
        list(reviews_df["reviewer"].unique() if not reviews_df.empty else [])
    ))

    with m1:
        st.markdown(f'{fa("cube")} **PRs Merged**', unsafe_allow_html=True)
        st.metric(label="PRs Merged", value=total_prs, label_visibility="collapsed")
    with m2:
        st.markdown(f'{fa("magnifying-glass")} **Code Reviews**', unsafe_allow_html=True)
        st.metric(label="Code Reviews", value=total_reviews, label_visibility="collapsed")
    with m3:
        st.markdown(f'{fa("bullseye")} **Issues Closed**', unsafe_allow_html=True)
        st.metric(label="Issues Closed", value=total_issues, label_visibility="collapsed")
    with m4:
        st.markdown(f'{fa("users")} **Engineers Active**', unsafe_allow_html=True)
        st.metric(label="Engineers Active", value=engineers_active, label_visibility="collapsed")

    st.divider()

# ─── Scoring ──────────────────────────────────────────────────────────
if data_loaded:
    scores_df = compute_all_scores(prs_df, reviews_df, issues_df, params)
    top5 = scores_df.head(5).copy()

    if top5.empty:
        st.warning("No engineer data found for the selected time window.")
    else:
        # ─── Two-Column Layout ────────────────────────────────────────
        left_col, right_col = st.columns([1, 1], gap="large")

        # ─── Left: Top 5 Table ────────────────────────────────────────
        with left_col:
            st.markdown(f'<h3>{fa("trophy")} Top 5 Engineers</h3>', unsafe_allow_html=True)

            display_cols = ["Engineer", "Total Impact", "Shipped", "Collaboration", "Operational", "PRs Merged", "Reviews Given"]
            st.dataframe(
                top5[display_cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Total Impact": st.column_config.NumberColumn(format="%.2f"),
                    "Shipped": st.column_config.NumberColumn(format="%.2f"),
                    "Collaboration": st.column_config.NumberColumn(format="%.2f"),
                    "Operational": st.column_config.NumberColumn(format="%.2f"),
                },
            )

            # Score breakdown expanders
            st.markdown("#### Score Breakdowns")
            for _, row in top5.iterrows():
                with st.expander(f"{row['Engineer']} — Total: {row['Total Impact']:.2f}"):
                    st.markdown(f"""
**Shipped Impact**: {row['Shipped']:.2f}
- Raw PR score sum: {row['_shipped_raw']:.2f} → Diminished: log₂(1 + {row['_shipped_raw']:.2f}) × 10 = {row['Shipped']:.2f}
- PRs merged: {row['PRs Merged']}
- Weighted: {params['shipped_weight']:.0%} × {row['Shipped']:.2f} = {params['shipped_weight'] * row['Shipped']:.2f}

**Collaboration Impact**: {row['Collaboration']:.2f}
- Raw review score sum: {row['_collab_raw']:.2f} → Diminished: log₂(1 + {row['_collab_raw']:.2f}) × 10 = {row['Collaboration']:.2f}
- Reviews given: {row['Reviews Given']}
- Weighted: {params['collab_weight']:.0%} × {row['Collaboration']:.2f} = {params['collab_weight'] * row['Collaboration']:.2f}

**Operational Impact**: {row['Operational']:.2f}
- Issues score: {row['_ops_issues_score']:.2f} (closed: {row['_issues_closed']})
- Velocity score: {row['_ops_velocity_score']:.2f} (median merge: {row['_median_merge_hours']:.1f}h)
- Weighted: {params['ops_weight']:.0%} × {row['Operational']:.2f} = {params['ops_weight'] * row['Operational']:.2f}
""")

        # ─── Right: Engineer Drilldown ─────────────────────────────────
        with right_col:
            st.markdown(f'<h3>{fa("microscope")} Engineer Drilldown</h3>', unsafe_allow_html=True)

            selected = st.selectbox(
                "Select engineer",
                top5["Engineer"].tolist(),
                key="drilldown_select",
            )

            eng_row = top5[top5["Engineer"] == selected].iloc[0]

            # Top 3 Merged PRs
            st.markdown(f'##### {fa("code-merge")} Top Merged PRs', unsafe_allow_html=True)
            pr_scores = eng_row["_pr_scores"]
            if pr_scores:
                sorted_prs = sorted(pr_scores, key=lambda x: x["score"], reverse=True)[:3]
                for i, ps in enumerate(sorted_prs, 1):
                    pr_info = prs_df[prs_df["number"] == ps["number"]]
                    if not pr_info.empty:
                        pr = pr_info.iloc[0]
                        labels_str = ", ".join(pr["labels"]) if pr["labels"] else "none"
                        flags = []
                        if pr.get("body") and "Fixes #" in str(pr["body"]):
                            flags.append(f'{fa("bug")} Fixes issue')
                        if pr.get("body") and "Closes #" in str(pr["body"]):
                            flags.append(f'{fa("circle-check")} Closes issue')
                        flags_str = " | ".join(flags) if flags else ""
                        st.markdown(
                            f"{i}. [{ps['title']}]({pr['url']}) — **{ps['score']:.1f}** pts\n"
                            f"   `+{pr['additions']}/-{pr['deletions']}` · Labels: {labels_str}"
                            + (f" · {flags_str}" if flags_str else ""),
                            unsafe_allow_html=True,
                        )
            else:
                st.caption("No merged PRs found.")

            st.markdown("---")

            # Top 3 Review Contributions
            st.markdown(f'##### {fa("code-compare")} Top Review Contributions', unsafe_allow_html=True)
            review_scores = eng_row["_review_scores"]
            if review_scores:
                sorted_reviews = sorted(review_scores, key=lambda x: x["score"], reverse=True)[:3]
                for i, rs in enumerate(sorted_reviews, 1):
                    state_icon = fa("circle-check") if rs["state"] == "APPROVED" else fa("comment")
                    url = rs.get("url", "")
                    link = f"[PR #{rs['pr_number']}]({url})" if url else f"PR #{rs['pr_number']}"
                    st.markdown(f"{i}. {state_icon} {rs['state']} on {link} — **{rs['score']:.1f}** pts", unsafe_allow_html=True)
            else:
                st.caption("No reviews found.")

            st.markdown("---")

            # Weekly Impact Trend
            st.markdown(f'##### {fa("chart-line")} Weekly PR Activity', unsafe_allow_html=True)
            eng_prs = prs_df[prs_df["author"] == selected] if not prs_df.empty else pd.DataFrame()
            if not eng_prs.empty and "merged_at" in eng_prs.columns:
                weekly = eng_prs.set_index("merged_at").resample("W").size().reset_index(name="PRs Merged")
                weekly.columns = ["Week", "PRs Merged"]
                fig = px.line(
                    weekly, x="Week", y="PRs Merged",
                    markers=True,
                    template="plotly_dark",
                    color_discrete_sequence=["#FF694A"],
                )
                fig.update_layout(
                    height=250,
                    margin=dict(l=0, r=0, t=10, b=0),
                    xaxis_title="",
                    yaxis_title="PRs Merged",
                    showlegend=False,
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("No PR data available for trend chart.")

    st.divider()

    # ─── Methodology Expander ─────────────────────────────────────────
    with st.expander("Methodology — How Impact Scores Are Calculated"):
        st.markdown(methodology_text(params))

    st.divider()

    # ─── CSV Exports ──────────────────────────────────────────────────
    st.markdown(f'<h3>{fa("download")} Data Exports</h3>', unsafe_allow_html=True)
    e1, e2, e3 = st.columns(3)

    # Prepare export DataFrames
    export_cols = ["Engineer", "Total Impact", "Shipped", "Collaboration", "Operational", "PRs Merged", "Reviews Given"]
    engineer_csv = scores_df[export_cols].to_csv(index=False)

    prs_export = prs_df.copy() if not prs_df.empty else pd.DataFrame()
    if not prs_export.empty:
        prs_export["labels"] = prs_export["labels"].apply(lambda x: "; ".join(x) if isinstance(x, list) else "")
        prs_csv = prs_export.drop(columns=["body"], errors="ignore").to_csv(index=False)
    else:
        prs_csv = ""

    reviews_csv = reviews_df.to_csv(index=False) if not reviews_df.empty else ""

    with e1:
        st.download_button("Engineer Summary", engineer_csv, "engineer_summary.csv", "text/csv")
    with e2:
        st.download_button("All PRs", prs_csv, "prs.csv", "text/csv")
    with e3:
        st.download_button("All Reviews", reviews_csv, "reviews.csv", "text/csv")

    # Write to local data_export/ folder
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
        pass  # Non-critical — don't fail the app for file writes
