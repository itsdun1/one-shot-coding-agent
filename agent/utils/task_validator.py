"""Validate task clarity before creating an expensive agent run.

Uses Claude Haiku for a cheap (~$0.001) validation call to check if
the task is clear enough to execute. Rejects vague requests before
wasting Sonnet tokens.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


async def validate_task(task_text: str) -> tuple[bool, str]:
    """Validate if a task is clear enough to execute.

    Args:
        task_text: The user's message text (stripped of bot mention).

    Returns:
        (is_valid, reason) — True if task is actionable, False with reason if not.
    """
    try:
        import httpx

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.debug("No ANTHROPIC_API_KEY, skipping validation")
            return True, ""

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 150,
                    "messages": [
                        {
                            "role": "user",
                            "content": f"""Evaluate if this coding task is clear and actionable. A valid task must:
1. Mention at least one specific file name (with extension like .js, .py, .ts)
2. Describe a concrete action (replace, add, remove, fix, update, create, refactor, move)

Task: "{task_text}"

Reply with ONLY valid JSON:
{{"valid": true}} or {{"valid": false, "reason": "brief reason"}}""",
                        }
                    ],
                },
            )
            response.raise_for_status()
            content = response.json()["content"][0]["text"].strip()

            import json
            # Parse JSON from response (handle markdown code blocks)
            if "```" in content:
                content = content.split("```")[1].strip()
                if content.startswith("json"):
                    content = content[4:].strip()
            result = json.loads(content)
            return result.get("valid", True), result.get("reason", "")

    except Exception as e:
        logger.debug("Task validation failed (allowing task): %s", e)
        return True, ""  # On error, allow the task
