# PostHog Engineering Impact Dashboard

A single-page Streamlit dashboard that identifies the **top 5 most impactful engineers** in the [PostHog/posthog](https://github.com/PostHog/posthog) GitHub repository over the last 90 days.

## Features

- **Explainable Impact Scoring** — 3-component model (Shipped 50%, Collaboration 35%, Operational 15%) with all formulas visible
- **Real GitHub Data** — fetched via GitHub GraphQL API with 30-minute caching
- **Interactive Parameters** — adjust all weights and caps via sidebar sliders
- **Engineer Drilldown** — top PRs, reviews, and weekly trend charts
- **CSV Exports** — download `engineer_summary.csv`, `prs.csv`, `reviews.csv`
- **Bot Exclusion** — filters out dependabot, github-actions, and `[bot]` accounts

## Local Setup

```bash
# 1. Clone the repo
git clone https://github.com/<your-user>/posthog-impact-dashboard.git
cd posthog-impact-dashboard

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your GitHub token
export GITHUB_TOKEN="ghp_your_token_here"

# 4. Run the dashboard
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

## Deploy on Render

1. Push this repo to GitHub.
2. Go to [Render](https://render.com) → **New** → **Web Service** → connect your GitHub repo.
3. Render will auto-detect `render.yaml` and configure the service.
4. Add `GITHUB_TOKEN` as an environment variable in the Render dashboard.
5. Deploy — the app will be live at `https://posthog-impact-dashboard.onrender.com`.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | Yes (for full data) | GitHub Personal Access Token with `repo` scope |

## Tech Stack

- Python 3.11, Streamlit, Requests, Pandas, Plotly
