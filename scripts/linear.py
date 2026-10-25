#!/usr/bin/env python3
"""Minimal Linear client (stdlib only).

Used by the SessionEnd hook and by the Makefile. Credentials come from the
environment; the value is never printed.

    export LINEAR_API_KEY=lin_api_...
    python scripts/linear.py whoami
    python scripts/linear.py issues --project "$LINEAR_PROJECT_ID"
    python scripts/linear.py create --title "..." --project "$LINEAR_PROJECT_ID"
    python scripts/linear.py comment --issue CM-31 --body "..."
    python scripts/linear.py state --issue CM-31 --state "In Progress"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ENDPOINT = "https://api.linear.app/graphql"


class LinearError(RuntimeError):
    pass


def api_key() -> str:
    key = os.environ.get("LINEAR_API_KEY", "").strip()
    if not key:
        raise LinearError("LINEAR_API_KEY is not set")
    return key


def query(document: str, variables: dict | None = None) -> dict:
    payload = json.dumps({"query": document, "variables": variables or {}}).encode()
    request = urllib.request.Request(
        ENDPOINT,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": api_key(),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise LinearError(f"HTTP {exc.code}: {exc.read().decode()[:400]}") from exc
    except urllib.error.URLError as exc:
        raise LinearError(f"network error: {exc.reason}") from exc

    if body.get("errors"):
        raise LinearError(json.dumps(body["errors"])[:800])
    return body["data"]


WHOAMI = """query { viewer { id name email } }"""

PROJECT_ISSUES = """
query($project: String!) {
  project(id: $project) {
    name
    issues(first: 50, orderBy: updatedAt) {
      nodes { identifier title state { name } updatedAt }
    }
  }
}"""

TEAM_STATES = """
query($team: String!) {
  team(id: $team) { states { nodes { id name } } }
}"""

CREATE_ISSUE = """
mutation($team: String!, $title: String!, $description: String, $project: String) {
  issueCreate(input: {teamId: $team, title: $title, description: $description, projectId: $project}) {
    success
    issue { identifier url }
  }
}"""

ADD_COMMENT = """
mutation($issue: String!, $body: String!) {
  commentCreate(input: {issueId: $issue, body: $body}) {
    success
    comment { id url }
  }
}"""

UPDATE_STATE = """
mutation($issue: String!, $state: String!) {
  issueUpdate(id: $issue, input: {stateId: $state}) { success issue { identifier } }
}"""

RESOLVE_ISSUE = """
query($id: String!) {
  issue(id: $id) { id identifier identifier title team { id } }
}"""


def cmd_whoami(_: argparse.Namespace) -> int:
    data = query(WHOAMI)
    print(json.dumps(data["viewer"], indent=2))
    return 0


def cmd_issues(args: argparse.Namespace) -> int:
    data = query(PROJECT_ISSUES, {"project": args.project})
    project = data.get("project") or {}
    print(project.get("name", args.project))
    for issue in project.get("issues", {}).get("nodes", []):
        state = (issue.get("state") or {}).get("name", "?")
        print(f"  {issue['identifier']:<8} [{state}] {issue['title']}")
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    data = query(
        CREATE_ISSUE,
        {
            "team": args.team,
            "title": args.title,
            "description": args.description,
            "project": args.project,
        },
    )
    result = data["issueCreate"]
    if not result["success"]:
        raise LinearError("issueCreate returned success=false")
    print(json.dumps(result["issue"], indent=2))
    return 0


def cmd_comment(args: argparse.Namespace) -> int:
    data = query(ADD_COMMENT, {"issue": args.issue, "body": args.body})
    print(json.dumps(data["commentCreate"]["comment"], indent=2))
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    issue = query(RESOLVE_ISSUE, {"id": args.issue})["issue"]
    team = issue["team"]["id"]
    states = query(TEAM_STATES, {"team": team})["team"]["states"]["nodes"]
    match = next((s for s in states if s["name"].lower() == args.state.lower()), None)
    if match is None:
        names = ", ".join(s["name"] for s in states)
        raise LinearError(f"unknown state {args.state!r}. Available: {names}")
    data = query(UPDATE_STATE, {"issue": issue["id"], "state": match["id"]})
    print(json.dumps(data["issueUpdate"], indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("whoami").set_defaults(func=cmd_whoami)

    issues = sub.add_parser("issues")
    issues.add_argument("--project", default=os.environ.get("LINEAR_PROJECT_ID", ""))
    issues.set_defaults(func=cmd_issues)

    create = sub.add_parser("create")
    create.add_argument("--title", required=True)
    create.add_argument("--description", default="")
    create.add_argument("--team", default=os.environ.get("LINEAR_TEAM_ID", ""))
    create.add_argument("--project", default=os.environ.get("LINEAR_PROJECT_ID", ""))
    create.set_defaults(func=cmd_create)

    comment = sub.add_parser("comment")
    comment.add_argument("--issue", required=True)
    comment.add_argument("--body", required=True)
    comment.set_defaults(func=cmd_comment)

    state = sub.add_parser("state")
    state.add_argument("--issue", required=True)
    state.add_argument("--state", required=True)
    state.set_defaults(func=cmd_state)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (getattr(args, "project", None) or args.command in {"whoami", "comment", "state"}):
        print("LINEAR_PROJECT_ID is not set", file=sys.stderr)
        return 2
    try:
        return args.func(args)
    except LinearError as exc:
        print(f"linear: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())