#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from datetime import date


def send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


for raw in sys.stdin:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        continue
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        send({"id": request_id, "result": {"userAgent": "fake", "platformFamily": "windows", "platformOs": "windows"}})
    elif method == "initialized":
        continue
    elif method == "account/read":
        send(
            {
                "id": request_id,
                "result": {
                    "account": {"type": "chatgpt", "email": "user@example.com", "planType": "pro"},
                    "requiresOpenaiAuth": True,
                },
            }
        )
    elif method == "account/rateLimits/read":
        send(
            {
                "id": request_id,
                "result": {
                    "rateLimits": {
                        "limitId": "codex",
                        "limitName": "Codex",
                        "primary": {"usedPercent": 25, "windowDurationMins": 300, "resetsAt": 1800000000},
                        "secondary": {"usedPercent": 48, "windowDurationMins": 10080, "resetsAt": 1800100000},
                        "rateLimitReachedType": None,
                    },
                    "rateLimitsByLimitId": {
                        "codex": {
                            "limitId": "codex",
                            "limitName": "Codex",
                            "primary": {"usedPercent": 25, "windowDurationMins": 300, "resetsAt": 1800000000},
                            "secondary": {"usedPercent": 48, "windowDurationMins": 10080, "resetsAt": 1800100000},
                        },
                        "codex_other": {
                            "limitId": "codex_other",
                            "limitName": "Reviews",
                            "primary": {"usedPercent": 12, "windowDurationMins": 60, "resetsAt": 1800000100},
                            "secondary": None,
                        },
                    },
                    "rateLimitResetCredits": {"availableCount": 2, "credits": []},
                },
            }
        )
    elif method == "account/usage/read":
        send(
            {
                "id": request_id,
                "result": {
                    "summary": {
                        "lifetimeTokens": 1234567,
                        "peakDailyTokens": 45678,
                        "longestRunningTurnSec": 540,
                        "currentStreakDays": 8,
                        "longestStreakDays": 14,
                    },
                    "dailyUsageBuckets": [{"startDate": date.today().isoformat(), "tokens": 12345}],
                },
            }
        )
    elif method == "hang":
        time.sleep(2)
    elif request_id is not None:
        send({"id": request_id, "error": {"code": -32601, "message": "not found"}})
