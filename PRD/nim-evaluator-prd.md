# PRD: NIM free-tier model evaluator

## 1. What this is

A Python **script** (not an agent, not a framework, not a SaaS) that:
1. Checks which models on NVIDIA NIM's free tier actually work (many listed models 404 or timeout)
2. Runs each working model through a small fixed set of test tasks across 4 categories
3. Scores the results automatically (no LLM-judges-LLM where avoidable)
4. Outputs a simple routing file: which model is best for which category

End result: a JSON file like `{"coding": "qwen3-coder-480b", "math": "nemotron-3-super-120b", ...}` that any other script or agent can import and use instead of guessing which of 200 models to call.

## 2. Why this exists (context for the builder)

The author hit free-tier rate limits and had no way to know which NIM model was actually good at what, or which ones were dead listings vs working. Independent testing has confirmed ~38% of NIM's catalog returns 404/timeout on free tier despite being listed. No general-purpose, reusable tool exists that solves this — only a one-off blog post for someone else's company use case, and a generic speed/uptime dashboard with no task-specific scoring.

## 3. Explicit non-goals

- **This is not an agent.** No runtime decision-making, no LLM choosing what to do next. Every step is a fixed, predictable sequence. Do not add an "orchestrator," "planner," or any agentic framework (LangChain, CrewAI, etc.) anywhere in this project.
- Not a web app or dashboard in v1. Output is a file. A dashboard can come later if wanted.
- Not trying to evaluate all 200+ models exhaustively forever — fixed small task set, re-run weekly, not a research benchmark.
- Not handling paid-tier models, only NIM's free tier.

## 4. Engineering principles — follow these strictly

These instructions are mandatory, not suggestions:

- **Minimum necessary code.** If a task takes 10 lines, write 10 lines. Do not add abstraction layers, design patterns, or config systems "for future flexibility." Build for what's needed now.
- **Plain functions over classes**, unless there's clear shared state that genuinely needs a class. Most of this project is functions operating on dicts/lists — that's fine and preferred.
- **Standard library first.** Use `requests`, `json`, `time`, `os`, `csv`. Do not pull in a framework or ORM for what is fundamentally a script that calls an API in a loop and writes a file.
- **Synchronous code for v1.** No `asyncio`, no concurrency, even though it would run faster. Correctness and readability over speed at this stage. Async can be a documented "v2 idea," not part of the build.
- **No premature error-handling sprawl.** Catch the errors that will actually happen (timeouts, 404s, malformed JSON) with clear `try/except`. Don't wrap everything defensively "just in case."
- **Every function needs a one-line docstring explaining what it does and why**, not just what the code already shows. Comments should explain *why* a decision was made (e.g. "skip models that 404 — confirmed ~38% of catalog is phantom listings"), not narrate the obvious.
- **Type hints on function signatures.** Helps readability and catches bugs early — keep them simple (`list[str]`, `dict`, not complex generics).
- **No hardcoded API keys.** Read from environment variable `NIM_API_KEY`.

## 5. Learning mode — required for every phase

The person receiving this code is learning Python and DSA from scratch and wants to understand what's built, not just receive a working black box. For every phase below:

1. Build **only that phase**, then stop and wait for confirmation before continuing to the next.
2. Before showing code, give a plain-English explanation (3-5 sentences) of what this phase does and why it's structured that way.
3. Inside the code, comment any non-obvious Python construct (list comprehensions, `with` blocks, dict `.get()` defaults, etc.) briefly — assume basic Python knowledge (variables, loops, functions, dicts/lists) but not idioms yet.
4. After the phase works, suggest one small thing the person could try modifying themselves to test their understanding (e.g. "try changing the timeout value and see what happens to the results").

Do not generate all 5 phases in one response. Build incrementally, one phase per exchange, confirmed working before moving on.

## 6. Architecture

```
nim-evaluator/
  probe.py          # Phase 1: check which models are alive
  tasks.py          # Phase 2: the fixed task battery (data, not logic)
  grade.py          # Phase 3: scoring functions per category
  run.py            # Phase 3: orchestrates probe -> tasks -> grade -> output
  results.json       # Phase 3: raw output, model x task x score
  router.json         # Phase 5: final simple routing table
  .env.example        # documents NIM_API_KEY requirement
```

No package structure, no `src/` layout, no `setup.py` needed for a script this size. Flat files are correct here.

## 7. Phase-by-phase spec

### Phase 1 — probe availability
- Fetch the full model list from NIM's `/v1/models` endpoint.
- For each model, send one minimal test prompt (e.g. "Say OK") with a short timeout (10-15s).
- Record: model name, alive (bool), response time, error type if failed.
- Output: `alive_models.json` — a filtered list of models confirmed working.
- **Definition of done**: running `python probe.py` prints a count like "142 of 203 models responded" and writes the file.

### Phase 2 — task battery
Define a fixed, small set of test tasks as plain data (a Python list of dicts), not generated dynamically. 11 tasks total, 4 categories:

**Coding (3 tasks)**
1. Bug-fix task: a short function with a planted bug (off-by-one or null crash). Grade by running the fixed output against 2-3 test cases.
2. From-scratch task (e.g. "write a function that merges two sorted lists"). Grade by running against fixed test cases.
3. Code review task: a function with one specific planted issue. Grade by checking if the model's response mentions the known issue (keyword/substring check).

**Math/reasoning (3 tasks)**
1. Multi-step word problem with one correct numeric answer. Grade by extracting a number from the response and comparing to the known answer.
2. Logic/constraint puzzle with one correct answer. Same grading approach.
3. A derivation problem — only the final numeric answer is graded, reasoning text is ignored.

**Writing/Q&A (2-3 tasks)**
1. Summarize a fixed paragraph; grade by checking 3 specified keywords are present in the response.
2. Format-following test (e.g. "respond in exactly 3 bullet points, under 50 words total"). Grade by checking bullet count and word count programmatically.

**Tool-calling (2 tasks)**
1. Give 2 fake tool definitions and a task needing one. Grade by checking the actual `tool_calls` field in the API response (not the text content — this catches models that fake tool calls in plain text).
2. A task needing 2 sequential tool calls. Grade by checking both tools were called, in the response.

Each task is a dict: `{"id": str, "category": str, "prompt": str, "grader": callable_name, "expected": value}`. Keep this as static data in `tasks.py`, not fetched or generated at runtime.

### Phase 3 — score and rank
- For each alive model, run all 11 tasks, call the matching grader function from `grade.py`, record pass/fail or score per task.
- Grader functions are small and category-specific: `grade_code(output, test_cases) -> bool`, `grade_math(output, expected_number) -> bool`, `grade_format(output, constraints) -> bool`, `grade_tool_call(response_obj, expected_tools) -> bool`.
- Aggregate per model per category into a simple average score.
- Write `results.json`: `{model_name: {category: score, latency: float}}`.
- **Definition of done**: `python run.py` produces a readable table (just `print()`, no need for a library) ranking models per category.

### Phase 4 — automate (only after phases 1-3 work manually)
- Wrap `run.py` in a GitHub Actions workflow on a weekly cron schedule.
- Store `NIM_API_KEY` as a repo secret.
- Commit the updated `results.json`/`router.json` back to the repo on each run.

### Phase 5 — output
- From `results.json`, pick the top-scoring model per category (tie-break on lower latency).
- Write `router.json`: `{"coding": "model_name", "math": "model_name", "writing": "model_name", "tool_calling": "model_name"}`.
- This is the file other scripts/agents actually consume.

## 8. Build order instruction for the AI coding tool

Build and confirm Phase 1 completely before starting Phase 2. Do not write Phase 3-5 code until Phase 1 and 2 are confirmed working by the user. If asked to "just build the whole thing," push back and confirm the user wants to skip the incremental review — the default behavior is one phase at a time.

## 9. Open questions to ask the user before building (do not assume)

- Does the user already have a NIM API key set up, or does setup need to be walked through first?
- Preferred way to store the API key locally (`.env` file with `python-dotenv`, or just an exported shell variable)? Default to `.env` + `python-dotenv` if no preference given — it's simple and standard.
