"""
GitHub GraphQL API client for fetching PostHog repository data.
Handles pagination, caching, bot exclusion, and graceful error handling.

PERFORMANCE: Reviews are fetched inline with PRs in a single paginated query,
reducing API calls from ~1500 to ~30.
"""

import os
import re
import math
import datetime
import requests
import pandas as pd
import streamlit as st

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
REPO_OWNER = "PostHog"
REPO_NAME = "posthog"

BOT_PATTERN = re.compile(r"\[bot\]$|^dependabot$|^github-actions$", re.IGNORECASE)


def _get_headers():
    """Return authorization headers if GITHUB_TOKEN is set."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    return {"Content-Type": "application/json"}


def _is_bot(login: str) -> bool:
    """Check if a GitHub login is a bot account."""
    if not login:
        return True
    return bool(BOT_PATTERN.search(login))


def _graphql_request(query: str, variables: dict = None) -> dict:
    """Execute a GitHub GraphQL request with error handling."""
    headers = _get_headers()
    payload = {"query": query, "variables": variables or {}}
    try:
        resp = requests.post(GITHUB_GRAPHQL_URL, json=payload, headers=headers, timeout=30)
        if resp.status_code == 403:
            remaining = resp.headers.get("X-RateLimit-Remaining", "?")
            reset_ts = resp.headers.get("X-RateLimit-Reset", "")
            reset_str = ""
            if reset_ts:
                try:
                    reset_str = f" (resets at {datetime.datetime.fromtimestamp(int(reset_ts)).strftime('%H:%M:%S')})"
                except Exception:
                    pass
            raise RuntimeError(
                f"GitHub API rate limit exceeded. Remaining: {remaining}{reset_str}. "
                "Please wait a few minutes or set a GITHUB_TOKEN with higher limits."
            )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            error_msgs = "; ".join(e.get("message", "") for e in data["errors"])
            raise RuntimeError(f"GitHub GraphQL errors: {error_msgs}")
        return data
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"GitHub API error: {e}")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Unable to connect to GitHub API. Please check your network.")
    except requests.exceptions.Timeout:
        raise RuntimeError("GitHub API request timed out. Please try again.")


# ─── Combined PRs + Reviews Query (FAST: reviews fetched inline) ─────

MERGED_PRS_WITH_REVIEWS_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(
      states: MERGED,
      first: 30,
      after: $cursor,
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        title
        url
        additions
        deletions
        body
        createdAt
        mergedAt
        author { login }
        labels(first: 10) { nodes { name } }
        comments { totalCount }
        reviews(first: 20) {
          nodes {
            author { login }
            state
            body
            submittedAt
            url
          }
        }
      }
    }
  }
}
"""


@st.cache_data(ttl=1800, show_spinner="Fetching data from GitHub (PRs + reviews)...")
def fetch_all_data(days: int = 90) -> tuple:
    """Fetch merged PRs AND their reviews in a single paginated query.

    Returns: (prs_df, reviews_df)
    This is dramatically faster than fetching reviews per-PR separately.
    """
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat() + "Z"
    all_prs = []
    all_reviews = []
    cursor = None
    page = 0
    max_pages = 60  # With 30 per page, covers ~1800 PRs

    try:
        while page < max_pages:
            variables = {
                "owner": REPO_OWNER,
                "name": REPO_NAME,
                "cursor": cursor,
            }
            data = _graphql_request(MERGED_PRS_WITH_REVIEWS_QUERY, variables)
            repo = data.get("data", {}).get("repository", {})
            pr_data = repo.get("pullRequests", {})
            nodes = pr_data.get("nodes", [])

            if not nodes:
                break

            past_window = False
            for pr in nodes:
                merged_at = pr.get("mergedAt", "")
                if merged_at and merged_at < since:
                    past_window = True
                    break

                author = pr.get("author") or {}
                login = author.get("login", "")
                if _is_bot(login):
                    continue

                labels = [l["name"] for l in (pr.get("labels", {}).get("nodes", []))]
                body = pr.get("body", "") or ""

                all_prs.append({
                    "number": pr["number"],
                    "title": pr["title"],
                    "url": pr["url"],
                    "author": login,
                    "additions": pr.get("additions", 0),
                    "deletions": pr.get("deletions", 0),
                    "body": body,
                    "created_at": pr.get("createdAt", ""),
                    "merged_at": merged_at,
                    "labels": labels,
                    "comments": pr.get("comments", {}).get("totalCount", 0),
                    "review_comments": 0,
                })

                # Extract reviews inline
                reviews = pr.get("reviews", {}).get("nodes", [])
                for review in reviews:
                    rev_author = review.get("author") or {}
                    rev_login = rev_author.get("login", "")
                    if _is_bot(rev_login):
                        continue
                    # Exclude self-reviews
                    if rev_login == login:
                        continue

                    all_reviews.append({
                        "pr_number": pr["number"],
                        "reviewer": rev_login,
                        "state": review.get("state", ""),
                        "body": review.get("body", "") or "",
                        "submitted_at": review.get("submittedAt", ""),
                        "url": review.get("url", ""),
                    })

            if past_window:
                break

            page_info = pr_data.get("pageInfo", {})
            if not page_info.get("hasNextPage", False):
                break
            cursor = page_info.get("endCursor")
            page += 1

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to fetch data: {e}")

    # Build PRs DataFrame
    if all_prs:
        prs_df = pd.DataFrame(all_prs)
        prs_df["merged_at"] = pd.to_datetime(prs_df["merged_at"], utc=True, errors="coerce")
        prs_df["created_at"] = pd.to_datetime(prs_df["created_at"], utc=True, errors="coerce")
    else:
        prs_df = _empty_pr_df()

    # Build Reviews DataFrame
    if all_reviews:
        reviews_df = pd.DataFrame(all_reviews)
        reviews_df["submitted_at"] = pd.to_datetime(reviews_df["submitted_at"], utc=True, errors="coerce")
    else:
        reviews_df = _empty_review_df()

    return prs_df, reviews_df


def _empty_pr_df() -> pd.DataFrame:
    """Return an empty DataFrame with the correct PR schema."""
    return pd.DataFrame(columns=[
        "number", "title", "url", "author", "additions", "deletions",
        "body", "created_at", "merged_at", "labels", "comments", "review_comments"
    ])


def _empty_review_df() -> pd.DataFrame:
    """Return an empty DataFrame with the correct review schema."""
    return pd.DataFrame(columns=[
        "pr_number", "reviewer", "state", "body", "submitted_at", "url"
    ])


# ─── Issues Closed Query ─────────────────────────────────────────────

ISSUES_CLOSED_QUERY = """
query($owner: String!, $name: String!, $since: DateTime!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(
      states: CLOSED,
      first: 50,
      after: $cursor,
      orderBy: {field: UPDATED_AT, direction: DESC},
      filterBy: {since: $since}
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        closedAt
        assignees(first: 5) { nodes { login } }
      }
    }
  }
}
"""


@st.cache_data(ttl=1800, show_spinner="Fetching closed issues...")
def fetch_closed_issues(days: int = 90) -> pd.DataFrame:
    """Fetch issues closed in the given time window."""
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat() + "Z"
    all_issues = []
    cursor = None
    page = 0
    max_pages = 10

    try:
        while page < max_pages:
            variables = {
                "owner": REPO_OWNER,
                "name": REPO_NAME,
                "since": since,
                "cursor": cursor,
            }
            data = _graphql_request(ISSUES_CLOSED_QUERY, variables)
            repo = data.get("data", {}).get("repository", {})
            issue_data = repo.get("issues", {})
            nodes = issue_data.get("nodes", [])

            if not nodes:
                break

            for issue in nodes:
                closed_at = issue.get("closedAt", "")
                if closed_at and closed_at < since:
                    page = max_pages
                    break

                assignees = issue.get("assignees", {}).get("nodes", [])
                for assignee in assignees:
                    login = assignee.get("login", "")
                    if _is_bot(login):
                        continue
                    all_issues.append({
                        "issue_number": issue["number"],
                        "assignee": login,
                        "closed_at": closed_at,
                    })

            page_info = issue_data.get("pageInfo", {})
            if not page_info.get("hasNextPage", False):
                break
            cursor = page_info.get("endCursor")
            page += 1

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to fetch closed issues: {e}")

    if not all_issues:
        return pd.DataFrame(columns=["issue_number", "assignee", "closed_at"])

    df = pd.DataFrame(all_issues)
    df["closed_at"] = pd.to_datetime(df["closed_at"], utc=True, errors="coerce")
    return df


def token_status() -> tuple:
    """Return (is_active: bool, message: str) for the GitHub token status."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return True, "🔑 Token Active (5,000 req/hr)"
    return False, "⚠️ No Token (60 req/hr)"
