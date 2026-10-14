# EXAONE plan replay fixtures

`tests/unit/test_plan_ai_replay.py` runs every `*/*.json` here through the real
parser (`ExaonePlanGenerationProvider._parse`) without calling Ollama.

- `synthetic/` — written by hand from logs when no raw answer existed (e.g. trip 93/94).
- `captured/` — real answers, sanitised by `app/services/external/ai/plan_ai_fixture.py`.

Capturing (off by default):

1. Set `PLAN_AI_FIXTURE_DIR=backend/data/ai_fixtures` (git-ignored) for the FastAPI process.
2. Each parsed EXAONE answer is written there with dates rebased to 2030-01-07,
   allow-listed titles only, public candidate facts only, and its outcome.
3. Review a file, copy it into `captured/`, and set `expected` to the outcome the
   fixed code must produce (`accepted` with `items`, or `rejected` with `validation_reason`).
