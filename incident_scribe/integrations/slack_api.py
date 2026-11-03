"""Pull a thread straight from Slack with a bot token — no export file needed.

Uses ``conversations.replies`` (paginated) and, when the token has
``users:read``, ``users.info`` to turn user IDs into display names. Requires a
bot token (``xoxb-…``) with ``channels:history`` (or ``groups:history`` for
private channels) in ``SLACK_BOT_TOKEN``.

Stdlib only: one HTTPS GET per page is not worth a dependency.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from ..parser import parse_slack_export
from ..schema import MessageStream

SLACK_API = "https://slack.com/api/"
MAX_PAGES = 50  # 50 × 200 messages is a long incident; stop rather than loop forever

Fetch = Callable[[str, dict[str, str], str], dict[str, Any]]


class SlackAPIError(RuntimeError):
    pass


def _http_get(method: str, params: dict[str, str], token: str) -> dict[str, Any]:
    url = SLACK_API + method + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - fixed https host
        return json.loads(resp.read().decode("utf-8"))


def fetch_thread(
    channel: str,
    thread_ts: str,
    *,
    token: str | None = None,
    fetch: Fetch = _http_get,
    resolve_names: bool = True,
) -> MessageStream:
    token = token or os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        raise SlackAPIError("Set SLACK_BOT_TOKEN to a bot token with channels:history.")

    items: list[dict[str, Any]] = []
    cursor = ""
    for _ in range(MAX_PAGES):
        params = {"channel": channel, "ts": thread_ts, "limit": "200"}
        if cursor:
            params["cursor"] = cursor
        page = fetch("conversations.replies", params, token)
        if not page.get("ok"):
            raise SlackAPIError(f"conversations.replies failed: {page.get('error', 'unknown')}")
        items.extend(page.get("messages", []))
        cursor = page.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            break

    if resolve_names:
        names: dict[str, str] = {}
        for item in items:
            uid = item.get("user")
            if not uid or uid in names:
                continue
            info = fetch("users.info", {"user": uid}, token)
            if info.get("ok"):
                profile = info["user"].get("profile", {})
                names[uid] = profile.get("display_name") or info["user"].get("name", uid)
            else:
                names[uid] = uid  # missing users:read scope is not fatal
        for item in items:
            if item.get("user") in names:
                item["user_name"] = names[item["user"]]

    stream = parse_slack_export(json.dumps(items))
    return MessageStream(messages=stream.messages, source_type="slack_api")
