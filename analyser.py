"""Pure data layer — no Rich dependencies. Shared by CLI (main.py) and web (app.py)."""

import re
from datetime import datetime, timezone, timedelta
from collections import Counter
from typing import Optional

import requests

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "was", "are", "were", "be", "been", "being", "have",
    "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "this", "that", "these", "those", "i", "we", "you",
    "it", "its", "my", "your", "our", "their", "from", "by", "as", "into",
    "not", "no", "so", "if", "up", "out", "more", "some", "when", "all",
    "also", "than", "then", "s", "re", "co", "via", "#", "pr", "-",
}

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def make_session(token: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    return session


def paginate(session: requests.Session, url: str, params: dict = None) -> list:
    results = []
    params = {**(params or {}), "per_page": 100}
    while url:
        resp = session.get(url, params=params)
        if resp.status_code in (403, 401):
            raise PermissionError("GitHub API: forbidden or rate limited.")
        if resp.status_code != 200:
            break
        data = resp.json()
        if isinstance(data, list):
            results.extend(data)
        else:
            results.append(data)
        url = None
        params = {}
        if "next" in resp.links:
            url = resp.links["next"]["url"]
    return results


def fetch_repos(session: requests.Session, username: str) -> list:
    return paginate(
        session,
        f"https://api.github.com/users/{username}/repos",
        {"type": "owner", "sort": "updated"},
    )


def fetch_commits_for_repo(session: requests.Session, username: str,
                            repo_name: str, since: datetime) -> list:
    return paginate(
        session,
        f"https://api.github.com/repos/{username}/{repo_name}/commits",
        {"author": username, "since": since.isoformat()},
    )


def fetch_all_commits(session: requests.Session, username: str,
                      repos: list, days: int = 30) -> tuple:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    all_commits = []
    repo_counts = {}
    for repo in repos:
        commits = fetch_commits_for_repo(session, username, repo["name"], since)
        if commits:
            repo_counts[repo["name"]] = len(commits)
            all_commits.extend(commits)
    return all_commits, repo_counts


def fetch_repo_languages(session: requests.Session, username: str, repos: list) -> Counter:
    totals: Counter = Counter()
    for repo in repos:
        resp = session.get(
            f"https://api.github.com/repos/{username}/{repo['name']}/languages"
        )
        if resp.status_code == 200:
            totals.update(resp.json())
    return totals


# ---------------------------------------------------------------------------
# Compute functions
# ---------------------------------------------------------------------------

def parse_commit_dt(commit: dict) -> Optional[datetime]:
    try:
        dt_str = commit["commit"]["author"]["date"]
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None


def compute_activity_stats(commits: list, repo_counts: dict) -> dict:
    dates, hours, weekdays = [], [], []
    for c in commits:
        dt = parse_commit_dt(c)
        if dt:
            dates.append(dt.date())
            hours.append(dt.hour)
            weekdays.append(dt.weekday())

    unique_days = sorted(set(dates), reverse=True)
    today = datetime.now(timezone.utc).date()

    current_streak = 0
    if unique_days:
        check = today
        for d in sorted(set(dates), reverse=True):
            diff = (check - d).days
            if diff == 0:
                current_streak += 1
                check = d - timedelta(days=1)
            elif diff == 1:
                current_streak += 1
                check = d - timedelta(days=1)
            else:
                break

    longest_streak, run, prev = 0, 0, None
    for d in sorted(set(dates)):
        if prev is None or (d - prev).days == 1:
            run += 1
            longest_streak = max(longest_streak, run)
        else:
            run = 1
        prev = d

    hour_counter = Counter(hours)
    weekday_counter = Counter(weekdays)
    busiest_hour = hour_counter.most_common(1)[0][0] if hour_counter else None
    busiest_day_idx = weekday_counter.most_common(1)[0][0] if weekday_counter else None

    return {
        "total_commits": len(commits),
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "busiest_hour": busiest_hour,
        "busiest_day": DAYS[busiest_day_idx] if busiest_day_idx is not None else "N/A",
        "most_active_repo": max(repo_counts, key=repo_counts.get) if repo_counts else "N/A",
        "repo_counts": repo_counts,
        "hour_distribution": hour_counter,
        "weekday_distribution": weekday_counter,
    }


def compute_language_stats(lang_totals: Counter) -> list:
    total_bytes = sum(lang_totals.values())
    if total_bytes == 0:
        return []
    return [
        (lang, b, round(b / total_bytes * 100, 1))
        for lang, b in lang_totals.most_common(10)
    ]


def extract_messages(commits: list) -> list:
    return [
        c["commit"]["message"].strip()
        for c in commits
        if c.get("commit", {}).get("message", "").strip()
    ]


def compute_message_stats(messages: list) -> dict:
    if not messages:
        return {}
    verbs, all_words = [], []
    fix_count = feat_count = 0
    for msg in messages:
        first_line = msg.splitlines()[0].strip()
        if first_line.lower().startswith("fix"):
            fix_count += 1
        if first_line.lower().startswith("feat"):
            feat_count += 1
        words_in_line = re.findall(r"[a-zA-Z]+", first_line)
        if words_in_line:
            verbs.append(words_in_line[0].lower())
        for w in re.findall(r"[a-zA-Z]{3,}", msg.lower()):
            if w not in STOPWORDS:
                all_words.append(w)
    return {
        "top_verbs": Counter(verbs).most_common(10),
        "top_words": Counter(all_words).most_common(10),
        "fix_count": fix_count,
        "feat_count": feat_count,
        "shortest": min(messages, key=len)[:120],
        "longest": (max(messages, key=len)[:120] + "…") if len(max(messages, key=len)) > 120 else max(messages, key=len),
        "total_messages": len(messages),
    }


def generate_vibe(activity: dict, messages: dict) -> tuple:
    hour_dist = activity.get("hour_distribution", Counter())
    total = sum(hour_dist.values()) or 1
    night_pct = sum(hour_dist.get(h, 0) for h in range(0, 5)) / total * 100
    morning_pct = sum(hour_dist.get(h, 0) for h in range(5, 12)) / total * 100
    afternoon_pct = sum(hour_dist.get(h, 0) for h in range(12, 18)) / total * 100
    evening_pct = sum(hour_dist.get(h, 0) for h in range(18, 24)) / total * 100

    fix_count = messages.get("fix_count", 0)
    feat_count = messages.get("feat_count", 0)
    longest = activity.get("longest_streak", 0)
    busiest_day = activity.get("busiest_day", "")

    if night_pct > 30:
        time_title, time_blurb = "Night Owl Coder", f"{night_pct:.0f}% of your commits drop after midnight."
    elif morning_pct > 40:
        time_title, time_blurb = "Early Bird Engineer", f"You ship code before most people have coffee — {morning_pct:.0f}% of commits before noon."
    elif afternoon_pct > 40:
        time_title, time_blurb = "Afternoon Architect", f"Peak productivity hits post-lunch — {afternoon_pct:.0f}% of your commits land in the afternoon."
    else:
        time_title, time_blurb = "Evening Hacker", f"{evening_pct:.0f}% of your commits arrive in the evening hours."

    if fix_count > feat_count * 2:
        work_blurb = "You fix more than you build — guardian of green CI."
    elif feat_count > fix_count * 2:
        work_blurb = "Pure builder energy — features flow from your fingertips."
    else:
        work_blurb = "Balanced between shipping features and squashing bugs."

    if longest >= 14:
        streak_blurb = f"With a {longest}-day streak, consistency is your superpower."
    elif longest >= 7:
        streak_blurb = f"A solid {longest}-day streak shows real dedication."
    else:
        streak_blurb = "Commits arrive in bursts — you work in focused sprints."

    weekend_note = " The weekend? Just another workday." if busiest_day in ("Saturday", "Sunday") else ""
    return time_title, f"{time_blurb} {work_blurb} {streak_blurb}{weekend_note}"


# ---------------------------------------------------------------------------
# Orchestrator — returns fully JSON-serialisable dict
# ---------------------------------------------------------------------------

def run_analysis(token: str, username: str, days: int = 30) -> dict:
    session = make_session(token)
    repos = fetch_repos(session, username)
    if not repos:
        raise ValueError("No public repositories found for this user.")

    commits, repo_counts = fetch_all_commits(session, username, repos, days)
    lang_totals = fetch_repo_languages(session, username, repos)

    activity = compute_activity_stats(commits, repo_counts)
    lang_stats = compute_language_stats(lang_totals)
    messages = extract_messages(commits)
    msg_stats = compute_message_stats(messages)
    vibe_title, vibe_blurb = generate_vibe(activity, msg_stats)

    top_repos = sorted(repo_counts.items(), key=lambda x: x[1], reverse=True)[:8]

    return {
        "activity": {
            "total_commits": activity["total_commits"],
            "current_streak": activity["current_streak"],
            "longest_streak": activity["longest_streak"],
            "busiest_hour": activity["busiest_hour"],
            "busiest_day": activity["busiest_day"],
            "most_active_repo": activity["most_active_repo"],
            "top_repos": [{"name": n, "count": c} for n, c in top_repos],
            "hour_distribution": {str(k): v for k, v in activity["hour_distribution"].items()},
            "weekday_distribution": {str(k): v for k, v in activity["weekday_distribution"].items()},
        },
        "languages": [
            {"name": l, "bytes": b, "pct": p} for l, b, p in lang_stats
        ],
        "messages": {
            "top_verbs": [{"word": w, "count": c} for w, c in msg_stats.get("top_verbs", [])],
            "top_words": [{"word": w, "count": c} for w, c in msg_stats.get("top_words", [])],
            "fix_count": msg_stats.get("fix_count", 0),
            "feat_count": msg_stats.get("feat_count", 0),
            "shortest": msg_stats.get("shortest", ""),
            "longest": msg_stats.get("longest", ""),
            "total": msg_stats.get("total_messages", 0),
        } if msg_stats else {},
        "vibe": {"title": vibe_title, "blurb": vibe_blurb},
        "meta": {
            "username": username,
            "days": days,
            "total_commits": len(commits),
            "total_repos": len(repo_counts),
        },
    }
