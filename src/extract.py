from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

_PROMPT_PATH = Path(__file__).parent / "prompts" / "extract.md"
_USAGE_FIELDS = (
    "ts",
    "model",
    "attempt",
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def render_extract_prompt(
    *,
    title: str,
    channel: str,
    channel_url: str,
    published_at: str,
    duration_seconds: int,
    description: str,
    channel_hint_categories: list[str],
    seed_categories: list[str],
    existing_creator_page: str,
    resources_index_snapshot: str,
    transcript: str,
) -> str:
    template = _PROMPT_PATH.read_text()
    replacements = {
        "title": title,
        "channel": channel,
        "channel_url": channel_url,
        "published_at": published_at,
        "duration_seconds": str(duration_seconds),
        "description": description or "(empty)",
        "channel_hint_categories": ", ".join(channel_hint_categories) or "(none)",
        "seed_categories": ", ".join(seed_categories) or "(none)",
        "existing_creator_page": existing_creator_page or "(none)",
        "resources_index_snapshot": resources_index_snapshot or "(empty)",
        "transcript": transcript,
    }
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


class ExtractionError(Exception):
    pass


_REQUIRED_FIELDS = (
    "session_summary", "instructions_and_howto", "key_takeaways",
    "resources", "categories", "proposed_new_categories",
    "tags", "domain", "creator_bio_additions", "connections",
)

_VALID_DOMAINS = {"claude-code", "prompt-eng", "model-compare", "sdk-api", "workflow"}
_VALID_RESOURCE_GROUPS = {"Tools", "Documentation", "Articles", "Uncategorised"}
_LIST_FIELDS = (
    "key_takeaways", "resources", "categories",
    "proposed_new_categories", "tags", "connections",
)


def parse_extraction_response(raw: str) -> dict:
    cleaned = raw.strip()
    fence_match = re.match(r"^```(?:json)?\s*\n(.*?)\n```$", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"response not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ExtractionError("response JSON is not an object")
    for field in _REQUIRED_FIELDS:
        if field not in data:
            raise ExtractionError(f"missing required field: {field}")
    for field in _LIST_FIELDS:
        if not isinstance(data[field], list):
            raise ExtractionError(
                f"field '{field}' must be a list, got {type(data[field]).__name__}"
            )
    if data["domain"] not in _VALID_DOMAINS:
        raise ExtractionError(f"invalid domain: {data['domain']}")
    for res in data["resources"]:
        if not isinstance(res, dict):
            raise ExtractionError(f"resource entries must be objects, got {type(res).__name__}")
        if res.get("group") not in _VALID_RESOURCE_GROUPS:
            raise ExtractionError(
                f"invalid resource group: {res.get('group')!r}"
            )
    return data


_SPLIT_MARKER = "## Inputs"


def split_prompt_for_caching(rendered: str) -> tuple[str, str]:
    idx = rendered.index(_SPLIT_MARKER)
    return rendered[:idx].rstrip(), rendered[idx:]


MAX_JSON_RETRIES = 2
MAX_OUTPUT_TOKENS = 8000
DEFAULT_MODEL = "claude-sonnet-4-6"
_RETRY_NUDGE = (
    "That response was not valid JSON matching the required schema. "
    "Return ONLY the JSON object, no prose and no fences."
)


def _cached_user_content(static: str, variable: str) -> list[dict]:
    return [
        {"type": "text", "text": static, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": variable},
    ]


def _log_usage(path: Path, *, model: str, attempt: int, response) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    row = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": model,
        "attempt": attempt,
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }
    if not all(isinstance(row[k], int) for k in _USAGE_FIELDS if k not in ("ts", "model")):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(_USAGE_FIELDS))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def call_extract(
    client,
    *,
    prompt: str,
    model: str = DEFAULT_MODEL,
    usage_log_path: Path | None = None,
) -> dict:
    static, variable = split_prompt_for_caching(prompt)
    last_raw: str | None = None
    for attempt in range(MAX_JSON_RETRIES + 1):
        if attempt == 0:
            messages = [
                {"role": "user", "content": _cached_user_content(static, variable)},
            ]
        else:
            messages = [
                {"role": "user", "content": _cached_user_content(static, variable)},
                {"role": "assistant", "content": last_raw or ""},
                {"role": "user", "content": _RETRY_NUDGE},
            ]
        response = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=messages,
        )
        if usage_log_path is not None:
            _log_usage(usage_log_path, model=model, attempt=attempt + 1, response=response)
        raw = response.content[0].text
        last_raw = raw
        try:
            return parse_extraction_response(raw)
        except ExtractionError as exc:
            if attempt == MAX_JSON_RETRIES:
                raise ExtractionError(
                    f"extraction failed after {MAX_JSON_RETRIES + 1} attempts: {exc}"
                ) from exc
    raise AssertionError("unreachable")
