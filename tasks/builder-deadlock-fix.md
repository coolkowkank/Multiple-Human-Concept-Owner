# Builder task: fix null-handoff deadlock + stall-clock timezone bug

You are the Builder. Implement the following fixes in this repository,
committing your own work. Context and bounds: docs/proposals/groq-deadlock-fix.md
(read it first). Base: branch live/builder-deadlock-fix off team-launcher.

1. launcher/supervisor.py `_check_stall`: `turn_since` is a UTC "Z" stamp but
   is parsed with time.mktime (LOCAL time). In non-UTC timezones every new
   turn is instantly judged stalled (observed: spurious seat SIGTERMs ~4s
   after each handoff in a UTC+2 run). Parse it as UTC (e.g.
   calendar.timegm or a timezone-aware datetime). Add a regression test
   that pins a non-UTC local timezone.
2. launcher/supervisor.py: when status == "running" and turn is None,
   treat it as a routing failure: re-issue the turn to the coordinator,
   and escalate to a human gate after 2 consecutive occurrences. A null
   turn WITH a DONE status is a valid terminal state - never fire the
   routing-failure path there.
3. launcher/runtime.py or launcher/adapters.py: when a seat response lacks
   a usable "handoff", record a loud validation note in the log entry. Do
   NOT fabricate, rewrite or silently correct the model's routing
   decision; the model's actual output stays in the record untouched.
4. Allowed-path hygiene: exclude __pycache__ from what seats can commit
   (the experiment committed .pyc files).

Tests for each behavior; the full suite must pass. Do not touch:
provider/account configuration, docs/proposals (coordinator-owned), the
reviewer-skip acceptance guard (separate follow-up, out of scope).
