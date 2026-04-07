#!/usr/bin/env python3
"""GitHub Commit Wrapped — a terminal year-in-review for your commits."""

import os
import sys
import re
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

from typing import Optional

import requests
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from rich.text import Text
from rich import box
from rich.rule import Rule
from rich.padding import Padding

load_dotenv()

console = Console()

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
    """Fetch all pages from a GitHub list endpoint."""
    results = []
    params = {**(params or {}), "per_page": 100}
    while url:
        resp = session.get(url, params=params)
        if resp.status_code == 403:
            console.print("[red]Rate limited or forbidden. Check your token permissions.[/red]")
            sys.exit(1)
        if resp.status_code != 200:
            break
        data = resp.json()
        if isinstance(data, list):
            results.extend(data)
        else:
            results.append(data)
        # Follow Link header for next page
        url = None
        params = {}
        if "next" in resp.links:
            url = resp.links["next"]["url"]
    return results


def fetch_repos(session: requests.Session, username: str) -> list:
    """Fetch all public repos for a user."""
    with console.status("[cyan]Fetching repositories…[/cyan]"):
        repos = paginate(session, f"https://api.github.com/users/{username}/repos",
                         {"type": "owner", "sort": "updated"})
    return repos


def fetch_commits_for_repo(session: requests.Session, username: str,
                            repo_name: str, since: datetime) -> list:
    """Fetch commits by the user in a single repo since a given date."""
    url = f"https://api.github.com/repos/{username}/{repo_name}/commits"
    params = {
        "author": username,
        "since": since.isoformat(),
    }
    commits = paginate(session, url, params)
    return commits


def fetch_all_commits(session: requests.Session, username: str,
                      repos: list, days: int = 30) -> tuple[list, dict]:
    """
    Fetch commits from all repos in the last `days` days.
    Returns (commits_list, commit_counts_per_repo).
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    all_commits = []
    repo_counts: dict[str, int] = {}

    with console.status("[cyan]Fetching commits…[/cyan]") as status:
        for repo in repos:
            repo_name = repo["name"]
            status.update(f"[cyan]Fetching commits from [bold]{repo_name}[/bold]…[/cyan]")
            commits = fetch_commits_for_repo(session, username, repo_name, since)
            if commits:
                repo_counts[repo_name] = len(commits)
                all_commits.extend(commits)

    return all_commits, repo_counts


def fetch_repo_languages(session: requests.Session, username: str,
                          repos: list) -> Counter:
    """Aggregate language bytes across all repos."""
    totals: Counter = Counter()
    with console.status("[cyan]Fetching language data…[/cyan]") as status:
        for repo in repos:
            repo_name = repo["name"]
            status.update(f"[cyan]Language scan: [bold]{repo_name}[/bold]…[/cyan]")
            resp = session.get(
                f"https://api.github.com/repos/{username}/{repo_name}/languages"
            )
            if resp.status_code == 200:
                totals.update(resp.json())
    return totals


# ---------------------------------------------------------------------------
# Feature: Activity stats
# ---------------------------------------------------------------------------

def parse_commit_dt(commit: dict) -> Optional[datetime]:
    """Extract committed datetime from a commit object."""
    try:
        dt_str = commit["commit"]["author"]["date"]
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None


def compute_activity_stats(commits: list, repo_counts: dict) -> dict:
    """Compute streaks, busiest day/hour, most active repo."""
    dates = []
    hours = []
    weekdays = []

    for c in commits:
        dt = parse_commit_dt(c)
        if dt:
            dates.append(dt.date())
            hours.append(dt.hour)
            weekdays.append(dt.weekday())

    # Streaks — work on sorted unique days
    unique_days = sorted(set(dates), reverse=True)
    today = datetime.now(timezone.utc).date()

    current_streak = 0
    if unique_days:
        check = today
        for d in unique_days:
            if d == check or d == check - timedelta(days=1):
                if d == check - timedelta(days=1):
                    check = d
                elif d == check:
                    pass  # same day, don't advance
                current_streak += 1
                check = d
            else:
                break
        # recount properly
        current_streak = 0
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

    longest_streak = 0
    run = 0
    prev = None
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
    busiest_day = DAYS[busiest_day_idx] if busiest_day_idx is not None else "N/A"
    most_active_repo = max(repo_counts, key=repo_counts.get) if repo_counts else "N/A"

    return {
        "total_commits": len(commits),
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "busiest_hour": busiest_hour,
        "busiest_day": busiest_day,
        "most_active_repo": most_active_repo,
        "repo_counts": repo_counts,
        "hour_distribution": hour_counter,
        "weekday_distribution": weekday_counter,
    }


# ---------------------------------------------------------------------------
# Feature: Language breakdown
# ---------------------------------------------------------------------------

def compute_language_stats(lang_totals: Counter) -> list:
    """Return [(lang, bytes, pct)] sorted by bytes descending."""
    total_bytes = sum(lang_totals.values())
    if total_bytes == 0:
        return []
    result = []
    for lang, b in lang_totals.most_common(10):
        result.append((lang, b, b / total_bytes * 100))
    return result


# ---------------------------------------------------------------------------
# Feature: Commit message analysis
# ---------------------------------------------------------------------------

def extract_messages(commits: list) -> list[str]:
    messages = []
    for c in commits:
        try:
            msg = c["commit"]["message"].strip()
            if msg:
                messages.append(msg)
        except KeyError:
            pass
    return messages


def compute_message_stats(messages: list) -> dict:
    if not messages:
        return {}

    verbs = []
    all_words = []

    fix_count = 0
    feat_count = 0

    for msg in messages:
        first_line = msg.splitlines()[0].strip()
        # Conventional commit prefix stripping (feat:, fix:, etc.)
        if first_line.lower().startswith("fix"):
            fix_count += 1
        if first_line.lower().startswith("feat"):
            feat_count += 1

        # First word as verb (strip punctuation)
        words_in_line = re.findall(r"[a-zA-Z]+", first_line)
        if words_in_line:
            verbs.append(words_in_line[0].lower())

        # All words excluding stopwords
        for w in re.findall(r"[a-zA-Z]{3,}", msg.lower()):
            if w not in STOPWORDS:
                all_words.append(w)

    shortest = min(messages, key=len)
    longest = max(messages, key=len)

    return {
        "top_verbs": Counter(verbs).most_common(10),
        "top_words": Counter(all_words).most_common(10),
        "fix_count": fix_count,
        "feat_count": feat_count,
        "shortest": shortest[:120],
        "longest": (longest[:120] + "…") if len(longest) > 120 else longest,
        "total_messages": len(messages),
    }


# ---------------------------------------------------------------------------
# Feature: Vibe summary
# ---------------------------------------------------------------------------

def generate_vibe(activity: dict, messages: dict) -> tuple[str, str]:
    """Return (title, blurb) personality summary."""
    hour_dist = activity.get("hour_distribution", Counter())
    total = sum(hour_dist.values()) or 1

    night_pct = sum(hour_dist.get(h, 0) for h in range(0, 5)) / total * 100
    morning_pct = sum(hour_dist.get(h, 0) for h in range(5, 12)) / total * 100
    afternoon_pct = sum(hour_dist.get(h, 0) for h in range(12, 18)) / total * 100
    evening_pct = sum(hour_dist.get(h, 0) for h in range(18, 24)) / total * 100

    fix_count = messages.get("fix_count", 0)
    feat_count = messages.get("feat_count", 0)
    streak = activity.get("current_streak", 0)
    longest = activity.get("longest_streak", 0)
    busiest_day = activity.get("busiest_day", "")

    # Time-of-day persona
    if night_pct > 30:
        time_title = "Night Owl Coder"
        time_blurb = f"{night_pct:.0f}% of your commits drop after midnight."
    elif morning_pct > 40:
        time_title = "Early Bird Engineer"
        time_blurb = f"You ship code before most people have coffee — {morning_pct:.0f}% of commits before noon."
    elif afternoon_pct > 40:
        time_title = "Afternoon Architect"
        time_blurb = f"Peak productivity hits post-lunch — {afternoon_pct:.0f}% of your commits land in the afternoon."
    else:
        time_title = "Evening Hacker"
        time_blurb = f"{evening_pct:.0f}% of your commits arrive in the evening hours."

    # Fix vs feat persona
    if fix_count > feat_count * 2:
        work_blurb = "You fix more than you build — the guardian of green CI."
    elif feat_count > fix_count * 2:
        work_blurb = "Pure builder energy — features flow from your fingertips."
    else:
        work_blurb = "Balanced between shipping features and squashing bugs."

    # Streak flavour
    if longest >= 14:
        streak_blurb = f"With a {longest}-day streak, consistency is your superpower."
    elif longest >= 7:
        streak_blurb = f"A solid {longest}-day streak shows real dedication."
    else:
        streak_blurb = "Commits arrive in bursts — you work in focused sprints."

    # Weekend warrior?
    weekend_note = ""
    if busiest_day in ("Saturday", "Sunday"):
        weekend_note = " The weekend? Just another workday."

    title = time_title
    blurb = f"{time_blurb} {work_blurb} {streak_blurb}{weekend_note}"
    return title, blurb


# ---------------------------------------------------------------------------
# Rich rendering
# ---------------------------------------------------------------------------

LANG_COLORS = {
    "Python": "yellow", "JavaScript": "bright_yellow", "TypeScript": "cyan",
    "Rust": "red", "Go": "blue", "Ruby": "red", "Java": "magenta",
    "C": "white", "C++": "bright_cyan", "C#": "bright_magenta",
    "Shell": "green", "HTML": "orange1", "CSS": "blue", "Swift": "orange1",
    "Kotlin": "bright_magenta", "PHP": "bright_blue", "Scala": "red",
}


def _bar(value: float, total: float = 100, width: int = 20, color: str = "cyan") -> Text:
    filled = int(value / total * width)
    bar = "█" * filled + "░" * (width - filled)
    t = Text()
    t.append(bar, style=color)
    return t


def render_header(username: str, days: int) -> None:
    title = Text(justify="center")
    title.append("⬡ ", style="bright_yellow bold")
    title.append("GITHUB COMMIT WRAPPED", style="bold white")
    title.append(" ⬡", style="bright_yellow bold")
    sub = Text(f"@{username}  ·  last {days} days", justify="center", style="dim")
    console.print()
    console.print(Panel(title + "\n" + sub, border_style="bright_yellow", padding=(0, 4)))
    console.print()


def render_activity(stats: dict) -> None:
    busiest_hour = stats["busiest_hour"]
    hour_str = (
        f"{busiest_hour:02d}:00 – {busiest_hour:02d}:59"
        if busiest_hour is not None else "N/A"
    )

    # Top repos table
    repo_table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan",
                        pad_edge=False)
    repo_table.add_column("Repo", style="white", no_wrap=True)
    repo_table.add_column("Commits", justify="right", style="bright_yellow")
    repo_table.add_column("", min_width=20)

    top_repos = sorted(stats["repo_counts"].items(), key=lambda x: x[1], reverse=True)[:5]
    max_count = top_repos[0][1] if top_repos else 1
    for repo, count in top_repos:
        repo_table.add_row(repo, str(count), _bar(count, max_count, 18, "cyan"))

    # Key numbers grid
    def _stat(label: str, value: str, color: str = "bright_yellow") -> Panel:
        body = Text(value, style=f"bold {color}", justify="center")
        return Panel(body, title=f"[dim]{label}[/dim]", border_style="dim",
                     padding=(0, 2), expand=True)

    stat_panels = [
        _stat("total commits", str(stats["total_commits"]), "bright_yellow"),
        _stat("current streak", f"{stats['current_streak']}d", "green"),
        _stat("longest streak", f"{stats['longest_streak']}d", "cyan"),
        _stat("busiest day", stats["busiest_day"], "magenta"),
        _stat("peak hour", hour_str, "blue"),
    ]

    console.print(Panel(
        Columns(stat_panels, equal=True, expand=True),
        title="[bold cyan]ACTIVITY[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()
    console.print(Panel(
        repo_table,
        title="[bold cyan]TOP REPOS[/bold cyan]",
        border_style="cyan",
        padding=(0, 1),
    ))
    console.print()


def render_languages(lang_stats: list) -> None:
    if not lang_stats:
        console.print(Panel("[dim]No language data found.[/dim]",
                            title="[bold magenta]LANGUAGES[/bold magenta]",
                            border_style="magenta"))
        return

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold magenta",
                  pad_edge=False, expand=True)
    table.add_column("Language", style="white", no_wrap=True)
    table.add_column("Bytes", justify="right", style="dim")
    table.add_column("%", justify="right", style="bright_yellow", width=6)
    table.add_column("", min_width=24)

    for lang, b, pct in lang_stats:
        color = LANG_COLORS.get(lang, "white")
        b_fmt = f"{b:,}"
        table.add_row(lang, b_fmt, f"{pct:.1f}%", _bar(pct, 100, 22, color))

    console.print(Panel(table, title="[bold magenta]LANGUAGES[/bold magenta]",
                        border_style="magenta", padding=(0, 1)))
    console.print()


def render_messages(stats: dict) -> None:
    if not stats:
        return

    # Verbs and top words side by side
    def _word_table(title: str, data: list, color: str) -> Table:
        t = Table(box=box.SIMPLE, show_header=False, pad_edge=False, expand=True)
        t.add_column("Word", style="white")
        t.add_column("N", justify="right", style=color)
        t.add_column("", min_width=14)
        max_c = data[0][1] if data else 1
        for word, count in data[:10]:
            t.add_row(word, str(count), _bar(count, max_c, 12, color))
        return Panel(t, title=f"[bold {color}]{title}[/bold {color}]",
                     border_style=color, padding=(0, 1))

    verb_panel = _word_table("TOP VERBS", stats["top_verbs"], "green")
    word_panel = _word_table("TOP WORDS", stats["top_words"], "blue")
    console.print(Columns([verb_panel, word_panel], equal=True, expand=True))
    console.print()

    # Fix vs feat ratio
    fix = stats["fix_count"]
    feat = stats["feat_count"]
    total_labelled = fix + feat or 1
    fix_pct = fix / total_labelled * 100
    feat_pct = feat / total_labelled * 100

    ratio_text = Text()
    ratio_text.append(f"  fix:  {fix:3d}  ", style="red bold")
    ratio_text.append(_bar(fix_pct, 100, 30, "red"))
    ratio_text.append(f"  {fix_pct:.0f}%\n")
    ratio_text.append(f"  feat: {feat:3d}  ", style="green bold")
    ratio_text.append(_bar(feat_pct, 100, 30, "green"))
    ratio_text.append(f"  {feat_pct:.0f}%")

    console.print(Panel(ratio_text, title="[bold]FIX vs FEAT[/bold]",
                        border_style="dim", padding=(0, 1)))
    console.print()

    # Shortest / longest
    msg_table = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    msg_table.add_column("", style="dim", width=10)
    msg_table.add_column("", style="white")
    msg_table.add_row("shortest", f'"{stats["shortest"]}"')
    msg_table.add_row("longest", f'"{stats["longest"]}"')
    console.print(Panel(msg_table, title="[bold]COMMIT MESSAGES[/bold]",
                        border_style="dim", padding=(0, 1)))
    console.print()


def render_vibe(title: str, blurb: str) -> None:
    vibe_text = Text(justify="center")
    vibe_text.append(f"{title}\n", style="bold bright_yellow")
    vibe_text.append(blurb, style="italic white")
    console.print(Panel(
        Padding(vibe_text, (1, 2)),
        title="[bold bright_yellow]✦ YOUR VIBE ✦[/bold bright_yellow]",
        border_style="bright_yellow",
        padding=(0, 2),
    ))
    console.print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    token = os.getenv("GITHUB_TOKEN")
    username = os.getenv("GITHUB_USERNAME")

    if not token:
        console.print("[red]GITHUB_TOKEN not set. Add it to your .env file.[/red]")
        sys.exit(1)
    if not username:
        console.print("[red]GITHUB_USERNAME not set. Add it to your .env file.[/red]")
        sys.exit(1)

    days = 30
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            console.print("[yellow]Usage: python main.py [days]  (default: 30)[/yellow]")
            sys.exit(1)

    session = make_session(token)

    render_header(username, days)

    repos = fetch_repos(session, username)
    if not repos:
        console.print("[red]No repositories found.[/red]")
        sys.exit(1)

    commits, repo_counts = fetch_all_commits(session, username, repos, days=days)

    if not commits:
        console.print(Panel(
            f"[yellow]No commits found for [bold]@{username}[/bold] in the last {days} days.[/yellow]",
            border_style="yellow",
        ))
        sys.exit(0)

    lang_totals = fetch_repo_languages(session, username, repos)

    # Compute
    activity = compute_activity_stats(commits, repo_counts)
    lang_stats = compute_language_stats(lang_totals)
    messages = extract_messages(commits)
    msg_stats = compute_message_stats(messages)
    vibe_title, vibe_blurb = generate_vibe(activity, msg_stats)

    # Render
    render_activity(activity)
    render_languages(lang_stats)
    render_messages(msg_stats)
    render_vibe(vibe_title, vibe_blurb)

    console.print(Rule(style="dim"))
    console.print(f"[dim]  Analysed {len(commits)} commits across "
                  f"{len(repo_counts)} repos · @{username}[/dim]\n")


if __name__ == "__main__":
    main()
