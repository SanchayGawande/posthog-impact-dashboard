# PostHog Engineering Impact Dashboard

A single-page Streamlit dashboard that identifies the **top 5 most impactful engineers** in the [PostHog/posthog](https://github.com/PostHog/posthog) GitHub repository over the last 90 days.

## Features

- **3-component scoring model**: Shipped (50%) + Collaboration (35%) + Operational (15%)
- **Real GitHub data** via GraphQL API — no mocked or hardcoded data
- **Fast load** — ~2 minutes first load, <10 seconds on cache (30-min TTL)
- **Explainable scores** — every metric has a visible breakdown
- **Adjustable parameters** — sidebar sliders recompute scores instantly without re-fetching
- **CSV exports** — download engineer summaries, PRs, and reviews

## Layout

| Section | Content |
|---------|---------|
| **Header** | Title, time window, token status badge |
| **KPI Cards** | PRs Merged · Engineers · Reviews · Issues Closed |
| **Main (left)** | Top 5 table + score breakdown expanders |
| **Main (right)** | Engineer drilldown: top PRs, reviews, weekly chart |
| **Bottom** | Methodology expander + CSV export buttons |

## Run Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Set your GitHub token
export GITHUB_TOKEN="ghp_YOUR_TOKEN_HERE"

# Run
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501).

## Deploy to Render

### Option A: Render Blueprint (recommended)

1. Push this repo to GitHub
2. Go to [dashboard.render.com](https://dashboard.render.com) → **New** → **Blueprint**
3. Connect your GitHub repo
4. Render will detect `render.yaml` and configure automatically
5. Set the environment variable `GITHUB_TOKEN` in the Render dashboard

### Option B: Manual Web Service

1. Go to [dashboard.render.com](https://dashboard.render.com) → **New** → **Web Service**
2. Connect your GitHub repo: `SanchayGawande/posthog-impact-dashboard`
3. Configure:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `streamlit run app.py --server.address 0.0.0.0 --server.port $PORT --server.headless true`
   - **Instance**: Free
4. Add environment variable: `GITHUB_TOKEN` = your GitHub PAT
5. Click **Create Web Service**

Your public URL will be: `https://posthog-impact-dashboard.onrender.com`

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI — layout, styling, charts |
| `github_client.py` | GitHub GraphQL API — paginated fetch of PRs, reviews, issues |
| `impact_model.py` | 3-component scoring with diminishing returns |
| `render.yaml` | Render deployment blueprint |
| `requirements.txt` | Python dependencies |
