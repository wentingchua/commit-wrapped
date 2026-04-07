# ⬡ Commit Wrapped

A Spotify Wrapped-style breakdown of your GitHub commit history — available as both a **CLI tool** and a **deployed web app**.

Sign in with GitHub and get a visual report of your activity stats, language breakdown, commit message habits, and a generated personality summary based on how you actually code.

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-purple?style=flat-square)

---

## Features

**Activity Stats**
- Total commits over a chosen time window (30 / 60 / 90 / 180 days)
- Current and longest commit streaks
- Most productive day of the week and hour of the day
- Most active repository

**Language Breakdown**
- All languages across your repos, ranked by bytes written

**Commit Message Analysis**
- Top 10 verbs and top 10 words from your commit messages
- fix: vs feat: commit ratio
- Your shortest and longest commit message

**Vibe Summary**
- A generated personality blurb based on your patterns — e.g. *"Night Owl Coder — 40% of your commits drop after midnight. You fix more than you build."*

---

## Web App

The web version uses GitHub OAuth — no personal access token needed.

### Run locally

```bash
git clone https://github.com/your-username/commit-wrapped
cd commit-wrapped
pip install -r requirements.txt
cp .env.example .env   # fill in GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, SECRET_KEY
uvicorn app:app --reload
```

Open [http://localhost:8000](http://localhost:8000), sign in with GitHub, and generate your Wrapped.

### Deploy to Render

1. Fork this repo
2. Create a GitHub OAuth App at [github.com/settings/developers](https://github.com/settings/developers)
   - Callback URL: `https://your-app.onrender.com/auth/callback`
3. Create a new Web Service on Render and connect your fork — `render.yaml` handles the rest
4. Add your `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, and `GITHUB_REDIRECT_URI` as environment variables

---

## CLI Tool

For local use with a personal access token.

```bash
python main.py        # last 30 days
python main.py 90     # custom range
```

Outputs a rich terminal report with panels, colour-coded bars, and streaks.

### Setup

Create a `.env` file:

```
GITHUB_TOKEN=your_personal_access_token
GITHUB_USERNAME=your_github_username
```

Token only needs the `public_repo` scope.

---

## Project Structure

```
commit-wrapped/
├── analyser.py      # data layer — GitHub API calls + stats computation
├── app.py           # FastAPI web app + GitHub OAuth
├── main.py          # CLI entry point (uses Rich for terminal output)
├── templates/
│   └── index.html   # single-page frontend
├── static/
│   └── style.css    # dark theme styles
├── render.yaml      # Render deployment config
└── requirements.txt
```

---

## Tech Stack

| Layer | Tool |
|---|---|
| Web framework | FastAPI |
| Auth | GitHub OAuth 2.0 |
| GitHub data | GitHub REST API v3 |
| Frontend | Vanilla HTML / CSS / JS |
| CLI output | Rich |
| Deployment | Render |

---

## Environment Variables

| Variable | Used by | Description |
|---|---|---|
| `GITHUB_TOKEN` | CLI | Personal access token (`public_repo` scope) |
| `GITHUB_USERNAME` | CLI | Your GitHub username |
| `GITHUB_CLIENT_ID` | Web | OAuth App client ID |
| `GITHUB_CLIENT_SECRET` | Web | OAuth App client secret |
| `GITHUB_REDIRECT_URI` | Web | OAuth callback URL |
| `SECRET_KEY` | Web | Session signing key (any random string) |

---

## License

MIT
