"""
3-component explainable impact scoring model.
Total Impact = (50% × Shipped) + (35% × Collaboration) + (15% × Operational)
All weights and caps are adjustable via sidebar sliders.
"""

import math
import re
import pandas as pd
import numpy as np

DEFAULT_PARAMS = {
    "shipped_weight": 0.50,
    "collab_weight": 0.35,
    "ops_weight": 0.15,
    "pr_size_cap": 8.0,
    "comment_cap": 10,
    "comment_weight": 0.3,
    "issue_close_bonus": 1.5,
    "priority_label_bonus": 1.3,
    "review_depth_cap": 5,
    "review_approved_weight": 1.5,
    "review_base_weight": 1.0,
    "collab_comment_cap": 5,
    "collab_comment_weight": 0.2,
    "issue_close_weight": 0.5,
    "velocity_weight": 0.3,
}

PRIORITY_LABELS = {"bug", "performance", "security", "reliability", "infra"}
ISSUE_CLOSE_PATTERN = re.compile(r"(fix(es|ed)?|clos(es|ed)?|resolv(es|ed)?)\s+#\d+", re.IGNORECASE)


def _log2_diminish(raw: float, scale: float = 10.0) -> float:
    """Apply diminishing returns: log₂(1 + raw) × scale."""
    return math.log2(1 + raw) * scale


def compute_pr_score(pr: dict, params: dict) -> float:
    """Compute the score for a single merged PR."""
    additions = pr.get("additions", 0)
    deletions = pr.get("deletions", 0)
    comments = pr.get("comments", 0)
    review_comments = pr.get("review_comments", 0)
    body = pr.get("body", "") or ""
    labels = pr.get("labels", [])

    # Size score with cap
    size_score = min(math.log2(1 + additions + deletions), params["pr_size_cap"])

    # Comment bonus
    total_comments = min(comments + review_comments, params["comment_cap"])
    comment_bonus = total_comments * params["comment_weight"]

    pr_score = size_score + comment_bonus

    # Issue close bonus
    if ISSUE_CLOSE_PATTERN.search(body):
        pr_score *= params["issue_close_bonus"]

    # Priority label bonus
    label_names = {l.lower() if isinstance(l, str) else l for l in labels}
    if label_names & PRIORITY_LABELS:
        pr_score *= params["priority_label_bonus"]

    return pr_score


def compute_shipped_impact(prs_df: pd.DataFrame, author: str, params: dict) -> tuple:
    """Compute Shipped Impact for an engineer.

    Returns: (final_score, raw_sum, pr_scores_list)
    """
    author_prs = prs_df[prs_df["author"] == author]
    if author_prs.empty:
        return 0.0, 0.0, []

    pr_scores = []
    for _, pr in author_prs.iterrows():
        score = compute_pr_score(pr.to_dict(), params)
        pr_scores.append({"number": pr["number"], "title": pr["title"], "score": score})

    raw_sum = sum(p["score"] for p in pr_scores)
    final = _log2_diminish(raw_sum)
    return final, raw_sum, pr_scores


def compute_review_score(review: dict, params: dict) -> float:
    """Compute the score for a single code review."""
    state = review.get("state", "")
    body = review.get("body", "") or ""

    # Base weight
    if state == "APPROVED":
        weight = params["review_approved_weight"]
    else:
        weight = params["review_base_weight"]

    # Review depth bonus
    depth_bonus = min(len(body) / 200, params["review_depth_cap"]) * params["collab_comment_weight"]

    return weight + depth_bonus


def compute_collab_impact(reviews_df: pd.DataFrame, reviewer: str, params: dict) -> tuple:
    """Compute Collaboration Impact for an engineer.

    Returns: (final_score, raw_sum, review_scores_list)
    """
    reviewer_reviews = reviews_df[reviews_df["reviewer"] == reviewer]
    if reviewer_reviews.empty:
        return 0.0, 0.0, []

    review_scores = []
    for _, review in reviewer_reviews.iterrows():
        score = compute_review_score(review.to_dict(), params)
        review_scores.append({
            "pr_number": review["pr_number"],
            "state": review["state"],
            "score": score,
            "url": review.get("url", ""),
        })

    raw_sum = sum(r["score"] for r in review_scores)
    final = _log2_diminish(raw_sum)
    return final, raw_sum, review_scores


def compute_ops_impact(
    issues_df: pd.DataFrame,
    prs_df: pd.DataFrame,
    engineer: str,
    params: dict
) -> tuple:
    """Compute Operational Impact for an engineer.

    Returns: (final_score, issues_score, velocity_score, issues_closed_count, median_merge_hours)
    """
    # Issues closed
    if not issues_df.empty:
        engineer_issues = issues_df[issues_df["assignee"] == engineer]
        issues_count = len(engineer_issues)
    else:
        issues_count = 0
    issues_score = math.log2(1 + issues_count * params["issue_close_weight"]) * 5

    # Merge velocity
    author_prs = prs_df[prs_df["author"] == engineer]
    if not author_prs.empty and "merged_at" in author_prs.columns and "created_at" in author_prs.columns:
        merge_times = (author_prs["merged_at"] - author_prs["created_at"]).dt.total_seconds() / 3600
        merge_times = merge_times.dropna()
        if not merge_times.empty:
            median_hours = merge_times.median()
        else:
            median_hours = 168  # Default to 1 week
    else:
        median_hours = 168

    velocity_score = 1 / (1 + median_hours / 168) * params["velocity_weight"] * 10

    final = issues_score + velocity_score
    return final, issues_score, velocity_score, issues_count, median_hours


def compute_all_scores(
    prs_df: pd.DataFrame,
    reviews_df: pd.DataFrame,
    issues_df: pd.DataFrame,
    params: dict = None,
) -> pd.DataFrame:
    """Compute impact scores for all engineers.

    Returns a DataFrame with columns:
    Engineer, Total Impact, Shipped, Collaboration, Operational,
    PRs Merged, Reviews Given, plus breakdown details.
    """
    if params is None:
        params = DEFAULT_PARAMS.copy()

    # Collect all unique engineers
    engineers = set()
    if not prs_df.empty:
        engineers.update(prs_df["author"].unique())
    if not reviews_df.empty:
        engineers.update(reviews_df["reviewer"].unique())

    if not engineers:
        return _empty_scores_df()

    rows = []
    for eng in engineers:
        shipped, shipped_raw, pr_scores = compute_shipped_impact(prs_df, eng, params)
        collab, collab_raw, review_scores = compute_collab_impact(reviews_df, eng, params)
        ops, ops_issues, ops_velocity, issues_count, median_hours = compute_ops_impact(
            issues_df, prs_df, eng, params
        )

        total = (
            params["shipped_weight"] * shipped
            + params["collab_weight"] * collab
            + params["ops_weight"] * ops
        )

        pr_count = len(prs_df[prs_df["author"] == eng]) if not prs_df.empty else 0
        review_count = len(reviews_df[reviews_df["reviewer"] == eng]) if not reviews_df.empty else 0

        rows.append({
            "Engineer": eng,
            "Total Impact": round(total, 2),
            "Shipped": round(shipped, 2),
            "Collaboration": round(collab, 2),
            "Operational": round(ops, 2),
            "PRs Merged": pr_count,
            "Reviews Given": review_count,
            # Breakdown details (for expanders)
            "_shipped_raw": round(shipped_raw, 2),
            "_collab_raw": round(collab_raw, 2),
            "_ops_issues_score": round(ops_issues, 2),
            "_ops_velocity_score": round(ops_velocity, 2),
            "_issues_closed": issues_count,
            "_median_merge_hours": round(median_hours, 1),
            "_pr_scores": pr_scores,
            "_review_scores": review_scores,
        })

    df = pd.DataFrame(rows)
    df = df.sort_values("Total Impact", ascending=False).reset_index(drop=True)
    return df


def _empty_scores_df() -> pd.DataFrame:
    """Return an empty DataFrame with the correct scores schema."""
    return pd.DataFrame(columns=[
        "Engineer", "Total Impact", "Shipped", "Collaboration", "Operational",
        "PRs Merged", "Reviews Given",
        "_shipped_raw", "_collab_raw", "_ops_issues_score", "_ops_velocity_score",
        "_issues_closed", "_median_merge_hours", "_pr_scores", "_review_scores",
    ])


def methodology_text(params: dict) -> str:
    """Generate plain-English methodology explanation with current parameter values."""
    return f"""
### Impact Scoring Methodology

**Total Impact = ({params['shipped_weight']:.0%} × Shipped) + ({params['collab_weight']:.0%} × Collaboration) + ({params['ops_weight']:.0%} × Operational)**

---

#### A) Shipped Impact (Merged PRs Authored) — Weight: {params['shipped_weight']:.0%}
For each merged PR by this engineer:
- **Size score** = min(log₂(1 + additions + deletions), cap={params['pr_size_cap']})
- **Comment bonus** = min(comments + review_comments, cap={params['comment_cap']}) × {params['comment_weight']}
- **PR score** = size_score + comment_bonus
- If PR body contains `Fixes #`, `Closes #`, etc → multiply by **{params['issue_close_bonus']}×**
- If PR has priority labels (bug, performance, security, reliability, infra) → multiply by **{params['priority_label_bonus']}×**
- Sum all PR scores → apply **diminishing returns**: `log₂(1 + raw_sum) × 10`

#### B) Collaboration Impact (Reviews on Others' PRs) — Weight: {params['collab_weight']:.0%}
For each review on a merged PR (excluding self-reviews):
- **Base weight**: {params['review_base_weight']} (or {params['review_approved_weight']} if APPROVED)
- **Review depth bonus**: min(body_length / 200, cap={params['review_depth_cap']}) × {params['collab_comment_weight']}
- **Review score** = weight + depth_bonus
- Sum all → **diminishing returns**: `log₂(1 + raw_sum) × 10`

#### C) Operational Impact — Weight: {params['ops_weight']:.0%}
- **Issues closed** (via assignee): `log₂(1 + count × {params['issue_close_weight']}) × 5`
- **Merge velocity**: `1 / (1 + median_merge_hours / 168) × {params['velocity_weight']} × 10`
- Total = issues_score + velocity_score

---

*All scores use diminishing returns (logarithmic scaling) to prevent gaming.
Bot accounts (dependabot, github-actions, [bot]) are excluded.*
"""
