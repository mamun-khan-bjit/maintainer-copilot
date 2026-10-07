import argparse
import time

from psycopg.types.json import Jsonb

from maintainer_copilot.config import settings
from maintainer_copilot.db import connect
from maintainer_copilot.github import GitHubClient

UPSERT_REPO = """
INSERT INTO repos (full_name, license, default_branch) VALUES (%s, %s, %s)
ON CONFLICT (full_name) DO UPDATE SET
    license = EXCLUDED.license, default_branch = EXCLUDED.default_branch, synced_at = now()
RETURNING id
"""

# visibility is deliberately not in the UPDATE list: a manual 'security' flag must survive re-syncs.
UPSERT_ISSUE = """
INSERT INTO issues (repo_id, number, title, body, state, state_reason, labels, author,
                    comments_count, created_at, updated_at, closed_at, url)
VALUES (%(repo_id)s, %(number)s, %(title)s, %(body)s, %(state)s, %(state_reason)s, %(labels)s,
        %(author)s, %(comments_count)s, %(created_at)s, %(updated_at)s, %(closed_at)s, %(url)s)
ON CONFLICT (repo_id, number) DO UPDATE SET
    title = EXCLUDED.title, body = EXCLUDED.body, state = EXCLUDED.state,
    state_reason = EXCLUDED.state_reason, labels = EXCLUDED.labels,
    comments_count = EXCLUDED.comments_count, updated_at = EXCLUDED.updated_at,
    closed_at = EXCLUDED.closed_at, synced_at = now()
"""

UPSERT_COMMENT = """
INSERT INTO comments (id, repo_id, issue_number, author, author_association, body,
                      created_at, updated_at, url)
VALUES (%(id)s, %(repo_id)s, %(issue_number)s, %(author)s, %(author_association)s, %(body)s,
        %(created_at)s, %(updated_at)s, %(url)s)
ON CONFLICT (id) DO UPDATE SET
    body = EXCLUDED.body, updated_at = EXCLUDED.updated_at, synced_at = now()
"""

UPSERT_DOC = """
INSERT INTO docs (repo_id, path, sha, content, url) VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (repo_id, path) DO UPDATE SET
    sha = EXCLUDED.sha, content = EXCLUDED.content, synced_at = now()
"""


def clean(text: str | None) -> str:
    # Postgres text can't store NUL bytes, and a few issue bodies contain them.
    return (text or "").replace("\x00", "")


def sync_repo(gh, conn, full_name):
    repo, _ = gh.get(f"/repos/{full_name}")
    license_id = (repo.get("license") or {}).get("spdx_id")
    repo_id = conn.execute(UPSERT_REPO, (full_name, license_id, repo["default_branch"])).fetchone()[0]
    return repo_id, repo["default_branch"]


def sync_issues(gh, conn, repo_id, full_name, max_issues):
    """Upsert the newest closed issues (PRs skipped); return [(number, comment_count)]."""
    params = {"state": "closed", "sort": "created", "direction": "desc", "per_page": 100}
    synced = []
    for item in gh.paginate(f"/repos/{full_name}/issues", params=params):
        if "pull_request" in item:
            continue
        conn.execute(UPSERT_ISSUE, {
            "repo_id": repo_id,
            "number": item["number"],
            "title": clean(item["title"]),
            "body": clean(item["body"]),
            "state": item["state"],
            "state_reason": item["state_reason"],
            "labels": [label["name"] for label in item["labels"]],
            "author": item["user"]["login"] if item["user"] else None,
            "comments_count": item["comments"],
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "closed_at": item["closed_at"],
            "url": item["html_url"],
        })
        synced.append((item["number"], item["comments"]))
        if len(synced) >= max_issues:
            break
    return synced


def sync_comments(gh, conn, repo_id, full_name, issues):
    count = 0
    for number, comment_count in issues:
        if comment_count == 0:
            continue  # saves a request per comment-less issue
        for item in gh.paginate(f"/repos/{full_name}/issues/{number}/comments", params={"per_page": 100}):
            conn.execute(UPSERT_COMMENT, {
                "id": item["id"],
                "repo_id": repo_id,
                "issue_number": number,
                "author": item["user"]["login"] if item["user"] else None,
                "author_association": item["author_association"],
                "body": clean(item["body"]),
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
                "url": item["html_url"],
            })
            count += 1
    return count


def sync_docs(gh, conn, repo_id, full_name, branch):
    tree, _ = gh.get(f"/repos/{full_name}/git/trees/{branch}", params={"recursive": "1"})
    if tree.get("truncated"):
        print("warning: repository tree was truncated; some docs may be missing")

    paths = [
        entry for entry in tree["tree"]
        if entry["type"] == "blob" and entry["path"].startswith("docs/") and entry["path"].endswith(".md")
    ]
    for entry in paths:
        content, _ = gh.get(f"/repos/{full_name}/contents/{entry['path']}", params={"ref": branch}, raw=True)
        url = f"https://github.com/{full_name}/blob/{branch}/{entry['path']}"
        conn.execute(UPSERT_DOC, (repo_id, entry["path"], entry["sha"], clean(content), url))
    return len(paths)


def main():
    parser = argparse.ArgumentParser(description="Sync closed issues, their comments and docs/ into Postgres.")
    parser.add_argument("--repo", default=settings.target_repo)
    parser.add_argument("--max-issues", type=int, default=500)
    args = parser.parse_args()

    started = time.monotonic()
    gh = GitHubClient(settings.github_token)

    with connect() as conn:
        repo_id, branch = sync_repo(gh, conn, args.repo)
        issues = sync_issues(gh, conn, repo_id, args.repo, args.max_issues)
        print(f"issues:   {len(issues)}")
        comment_count = sync_comments(gh, conn, repo_id, args.repo, issues)
        print(f"comments: {comment_count}")
        doc_count = sync_docs(gh, conn, repo_id, args.repo, branch)
        print(f"docs:     {doc_count}")

        # Size estimate for embedding/LLM budgeting: ~4 characters per token for English text.
        chars = conn.execute(
            "SELECT (SELECT coalesce(sum(length(title) + length(body)), 0) FROM issues WHERE repo_id = %(r)s)"
            "     + (SELECT coalesce(sum(length(body)), 0) FROM comments WHERE repo_id = %(r)s)"
            "     + (SELECT coalesce(sum(length(content)), 0) FROM docs WHERE repo_id = %(r)s)",
            {"r": repo_id},
        ).fetchone()[0]

        elapsed = time.monotonic() - started
        summary = {
            "issues": len(issues),
            "comments": comment_count,
            "docs": doc_count,
            "seconds": round(elapsed, 1),
            "approx_tokens": chars // 4,
            "rate_limit_remaining": gh.rate_remaining,
            **gh.stats,
        }
        conn.execute(
            "INSERT INTO audit_events (actor, action, target, details) VALUES (%s, %s, %s, %s)",
            ("sync", "github.sync", args.repo, Jsonb(summary)),
        )

    print(f"time:     {elapsed:.1f}s")
    print(f"requests: {gh.stats['requests']} ({gh.stats['not_modified']} were 304 Not Modified)")
    print(f"quota:    {gh.rate_remaining} requests left this hour")
    print(f"size:     ~{chars // 4:,} tokens of text")


if __name__ == "__main__":
    main()
