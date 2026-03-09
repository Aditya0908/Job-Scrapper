# Job Scraper Agent

An intelligent job search agent that scrapes multiple job sites, scores each listing against your profile, and returns a clean ranked list of relevant opportunities.

## Features

- **Multi-site scraping** — LinkedIn, Indeed, Naukri (extensible)
- **Anti-detection** — stealth browser with randomised fingerprints, human-like delays, session reuse
- **Local job matching** — TF-IDF + skill overlap scoring, zero paid APIs
- **Spam filtering** — promoted/sponsored listings are automatically penalised
- **Session persistence** — log in once manually, the agent reuses your cookies

## Setup

**Run all commands from the project root directory.**

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install Playwright browsers (one-time)
playwright install chromium

# 3. (Auto-Apply only) Copy example config and add your API key
cp .env.example .env
# Edit .env and set GEMINI_API_KEY (or OPENROUTER_API_KEY)
cp user_profile.example.json user_profile.json
# Edit user_profile.json with your details and resume path
```

## Usage

### Step 1: Save your login sessions (one-time per site)

This opens a real browser — log in normally, then press Enter:

```bash
python login_helper.py linkedin
python login_helper.py naukri
python login_helper.py indeed
```

Sessions are saved to `~/.job_scraper/sessions/` and reused automatically.

### Step 2: Create your profile

```json
{
  "role": "Full Stack Engineer",
  "skills": ["Python", "React", "Node.js", "PostgreSQL", "Docker"],
  "experience_years": 3,
  "location": "Remote/India"
}
```

Save this as `profile.json` (see `profile.example.json`).

### Step 3: Run the agent

```bash
# Scrape: search all sites
python main.py scrape --profile-file profile.json

# Scrape specific sites only
python main.py scrape --profile-file profile.json --sites linkedin naukri

# Inline profile (no file needed)
python main.py scrape --profile '{"role":"Backend Engineer","skills":"Python,Go","experience_years":5,"location":"Bangalore"}'

# Show browser for debugging
python main.py scrape --profile-file profile.json --no-headless

# Save results to JSON
python main.py scrape --profile-file profile.json --output results.json

# Auto-Apply (LinkedIn Easy Apply only; run from project root)
python main.py apply --url "https://www.linkedin.com/jobs/view/JOB_ID/" \
  --profile-file user_profile.json --site linkedin --no-headless --dry-run
```

## How Scoring Works

Each job gets a **fit score (0-100)** based on:

| Factor | Weight | What it measures |
|---|---|---|
| JD Similarity | 50% | TF-IDF cosine similarity between your profile and the job description |
| Skill Match | 30% | Fraction of your listed skills found in the JD |
| Experience | 10% | Whether your years of experience fall in the job's stated range |
| Location | 10% | Location compatibility (remote preference, city match) |

Promoted/sponsored listings receive a **-30 point penalty** and are filtered from the final output.

## Architecture

```
main.py                  CLI entry point
├── agent.py             Orchestrator — ties scraping + scoring
├── models.py            UserProfile, JobPosting data classes
├── scrapers/
│   ├── base.py          Abstract base scraper
│   ├── linkedin.py      LinkedIn public job search
│   ├── indeed.py        Indeed public job search
│   └── naukri.py        Naukri.com job search
├── utils/
│   ├── stealth.py       Anti-detection browser engine
│   └── matcher.py       TF-IDF + heuristic scoring engine
└── login_helper.py      One-time manual login session saver
```

## Anti-Detection Strategy

The agent avoids getting flagged as a bot by:

1. **Stealth JS injection** — hides `navigator.webdriver`, spoofs plugins/permissions
2. **Randomised fingerprints** — viewport size, user-agent, timezone vary per session
3. **Human-like behaviour** — random delays between actions, gradual scrolling, character-by-character typing
4. **Session reuse** — uses cookies from your real login (you log in once manually)
5. **No credential storage** — the agent never sees your password

## Adding a New Job Site

1. Create `scrapers/yoursite.py` inheriting from `BaseScraper`
2. Implement the `scrape(profile)` method
3. Register it in `agent.py`'s `ALL_SCRAPERS` dict
