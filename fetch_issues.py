import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO = "pydantic/pydantic"
OUT_FILE = Path("data/issues.jsonl")

load_dotenv()
token = os.environ["GITHUB_TOKEN"]

headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
}


def fetch_all_issues():
    url = f"https://api.github.com/repos/{REPO}/issues"
    params = {"per_page": 100, "state": "all"}
    page = 0

    with httpx.Client(headers=headers, timeout=30) as client:
        while url:
            response = client.get(url, params=params)
            response.raise_for_status()
            page += 1
            print(f"page {page}: {len(response.json())} items")

            for item in response.json():
                # The /issues endpoint also returns pull requests; only PRs have this key.
                if "pull_request" not in item:
                    yield item

            # GitHub puts the next page's URL in the Link header; it's absent on the last page.
            url = response.links.get("next", {}).get("url")
            params = None  # the next URL already carries per_page/state


def simplify(issue):
    return {
        "number": issue["number"],
        "title": issue["title"],
        "body": issue["body"] or "",
        "state": issue["state"],
        "state_reason": issue["state_reason"],
        "labels": [label["name"] for label in issue["labels"]],
        "author": issue["user"]["login"],
        "comments": issue["comments"],
        "created_at": issue["created_at"],
        "closed_at": issue["closed_at"],
        "url": issue["html_url"],
    }


OUT_FILE.parent.mkdir(exist_ok=True)
count = 0
with OUT_FILE.open("w") as f:
    for issue in fetch_all_issues():
        f.write(json.dumps(simplify(issue)) + "\n")
        count += 1

print(f"saved {count} issues to {OUT_FILE}")
