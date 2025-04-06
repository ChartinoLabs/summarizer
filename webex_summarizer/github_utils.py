"""GitHub API interaction functions."""

from datetime import datetime, timezone, tzinfo
from typing import List

from github import Github
from github.GithubException import GithubException
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from .types import CommitData

# Initialize Rich console
console = Console()

# Default organizations to ignore
ORGANIZATIONS_TO_IGNORE = [
    "AS-Community",
    "besaccess",
    "cx-usps-auto",
    "SVS-DELIVERY",
    "pyATS",
    "netascode",
    "CX-CATL",
]


def authenticate_github(token: str, base_url: str) -> Github:
    """Authenticate with GitHub Enterprise."""
    return Github(base_url=base_url, login_or_token=token)


def get_github_commits(
    gh: Github,
    date: datetime,
    local_tz: tzinfo,
    organizations_to_ignore: list[str] = ORGANIZATIONS_TO_IGNORE,
) -> List[CommitData]:
    """Get commits made by the authenticated user on a specific date."""
    commits: List[CommitData] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        main_task = progress.add_task("Checking repositories...", total=None)

        for repo in gh.get_user().get_repos():
            if repo.owner.login in organizations_to_ignore:
                continue

            progress.update(main_task, description=f"Checking repo: [cyan]{repo.name}[/] ({repo.owner.login})")

            try:
                for commit in repo.get_commits(author=gh.get_user().login):
                    commit_time = commit.commit.author.date.replace(
                        tzinfo=timezone.utc
                    ).astimezone(local_tz)
                    if commit_time.date() == date.date():
                        commits.append(
                            {
                                "time": commit_time,
                                "repo": repo.name,
                                "message": commit.commit.message,
                                "sha": commit.sha,
                            }
                        )
                    elif commit_time.date() < date.date():
                        break
            except GithubException as e:
                console.log(f"[red]Error fetching commits from {repo.name}: {e}[/]")

        progress.update(main_task, completed=1.0)

    return commits
