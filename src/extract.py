from __future__ import annotations

import json
import re
from pathlib import Path

_PROMPT_PATH = Path(__file__).parent / "prompts" / "extract.md"


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
    if data["domain"] not in _VALID_DOMAINS:
        raise ExtractionError(f"invalid domain: {data['domain']}")
    for res in data["resources"]:
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


def call_extract(client, *, prompt: str, model: str) -> dict:
    last_raw: str | None = None
    try:
        static, variable = split_prompt_for_caching(prompt)
        use_caching = True
    except ValueError:
        use_caching = False
    for attempt in range(MAX_JSON_RETRIES + 1):
        if use_caching:
            if attempt == 0:
                messages = [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": static,
                         "cache_control": {"type": "ephemeral"}},
                        {"type": "text", "text": variable},
                    ],
                }]
            else:
                messages = [
                    {"role": "user", "content": [
                        {"type": "text", "text": static,
                         "cache_control": {"type": "ephemeral"}},
                        {"type": "text", "text": variable},
                    ]},
                    {"role": "assistant", "content": last_raw or ""},
                    {"role": "user", "content":
                        "That response was not valid JSON matching the required schema. "
                        "Return ONLY the JSON object, no prose and no fences."},
                ]
        elif attempt == 0:
            messages = [{"role": "user", "content": prompt}]
        else:
            messages = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": last_raw or ""},
                {"role": "user", "content":
                    "That response was not valid JSON matching the required schema. "
                    "Return ONLY the JSON object, no prose and no fences."},
            ]
        response = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=messages,
        )
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
