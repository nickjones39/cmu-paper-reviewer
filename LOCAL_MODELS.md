# Local models (fork add-on)

This fork of [prometheus-eval/cmu-paper-reviewer](https://github.com/prometheus-eval/cmu-paper-reviewer)
adds a **Local Models** mode. The reviewer agent runs against a model served on your own Mac (or LAN),
and the rest of the reviewer works as upstream ships it.

## Quick start (macOS)

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
uv pip install --python .venv/bin/python --no-deps lmnr==0.7.52
cp .env.local.example .env.local      # pick your default server/model
./run_local.sh                        # → http://127.0.0.1:8321
```

The form opens in **Local Models** mode. It scans the usual ports, preselects your default server and
model, and lists every model the server offers. A paper's text is extracted offline, so no email, cloud
key or consent step is involved. For LaTeX-quality PDFs install MacTeX. Otherwise WeasyPrint
(`brew install pango`) renders the review PDF.

## Supported servers

| Backend | Default address | Model list | Notes |
|---|---|---|---|
| Ollama | `127.0.0.1:11434` | `/api/tags` + `/api/show` (context, tools, vision) | Native API, so the context window (`num_ctx`) is set per review |
| LM Studio | `127.0.0.1:1234/v1` | `/api/v0/models` (loaded state, context, tool use) | |
| oMLX | `127.0.0.1:8000/v1` | `/v1/models` + `/v1/models/status` | API key read from `~/.omlx/settings.json` |
| Splash | `127.0.0.1:8000/v1` | `/v1/models` | `SPLASH_API_KEY` if enabled |
| mlx-serve | `127.0.0.1:11234/v1`, `:8095/v1` | `/v1/models` | ddalcu/mlx-serve and the PyPI `mlx-serve` |
| mlx_lm.server | `127.0.0.1:8080/v1` | `/v1/models` | |
| mlx-openai-server | `127.0.0.1:8000/v1` | `/v1/models` | |
| llama.cpp `llama-server` | `127.0.0.1:8080/v1` | `/v1/models` + `/props` (n_ctx) | start with `--jinja` for tools |
| vLLM / vllm-mlx | `127.0.0.1:8000/v1` | `/v1/models` | `--enable-auto-tool-choice` |
| Jan | `127.0.0.1:1337/v1` | `/v1/models` | |
| LocalAI | `127.0.0.1:8080/v1` | `/v1/models` | |
| Any OpenAI-compatible server | you choose | `/v1/models` | e.g. a gateway in front of several engines |

Several servers share 8000 and 8080. Detection tells them apart by fingerprint (`/health`, `/api/version`,
`/props`, `/api/v0/models`, `/openapi.json`, `owned_by`). The default server from `.env.local` is always
probed too, whatever its port.

To add a server, add one `Backend(...)` entry in `backend/localmodels/backends.py`.

## Configuration (`.env.local`)

`.env.local` is gitignored. Upstream's `.env` is left alone, because its settings class rejects unknown keys.

| Variable | Meaning |
|---|---|
| `LOCAL_DEFAULT_BACKEND`, `LOCAL_DEFAULT_BASE_URL`, `LOCAL_DEFAULT_MODEL` | Preselected in the form. Also used by the API when a `mode=local` submission leaves them out |
| `LOCAL_DEFAULT_LABEL` | Display name for the default server (e.g. "Mac Studio gateway") |
| `LOCAL_DEFAULT_CONTEXT` | Optional context window. Blank means the server's reported window |
| `<BACKEND>_API_KEY`, `LOCAL_LLM_API_KEY` | Keys for servers that require one. They stay on the server and are never sent to the browser |
| `LOCAL_LLM_TIMEOUT` | Seconds per model call (default 1800; long prefills are slow) |
| `LOCAL_APP_PORT` | Port for `run_local.sh` (default 8321) |
| `LOCAL_MODELS_ENABLED=0` | Hides local mode, e.g. for a public deployment of the fork |

How keys are picked, in order: the key typed in the form (sent once with the submission, cleared after the
review like a BYOK key), then the env var, then auto-detection. Auto-detected keys go only to loopback
addresses.

**Stable aliases.** A gateway alias such as `mac-studio-default-model` can be re-pointed at another model
between submission and review. At the start of every review the worker re-reads the window the server
serves and uses the smaller of that and the one you chose.

## How it works

- `backend/localmodels/` holds everything new: the registry, discovery, key resolution, LLM construction,
  offline PDF text extraction, the `/api/local/*` router, and `app.py`. `app.py` serves upstream's API and
  the unmodified `docs/` frontend from one origin, replaces `js/config.js`, and injects `js/local-models.js`
  into `index.html`.
- The choice travels inside the submission's existing `review_settings` JSON as `local_model`. There is no
  schema change beyond the new `local` enum value. Queue and BYOK submissions have any `local_model`
  stripped, so they can't steer the worker at an arbitrary URL.
- The agent talks to OpenAI-style servers as `openai/<model>`, and to Ollama as `ollama_chat/<model>`.
  Prompt caching, encrypted reasoning and thinking budgets are turned off for local runs. Native tool calling
  is on by default. Untick it in the form for models without tool support (OpenHands then falls back to
  prompt-based tools).
- Debates about a local review go to the same local model.
- Limits:
  - Offline extraction (pypdf) flattens equations and tables, and finds nothing in scanned PDFs. Add a
    Mistral key in *More options* for full OCR.
  - Without a Tavily key the agent reviews without literature search, which upstream reports as the
    biggest single factor in review quality.
  - The agent needs at least 16,384 tokens of context, and 64k+ works much better.

## Safety: the agent has a shell

Upstream's reviewer agent has terminal and file-editor tools, and upstream runs it inside Docker. With
`run_local.sh` the worker runs **as you, on your Mac**. The agent can run any command your user can, and
the paper it reads is untrusted input that could try to steer it. For papers you didn't write, run the
worker in a container: Docker or OrbStack, with `LOCAL_DEFAULT_BASE_URL=http://host.docker.internal:<port>/v1`.
Also keep secrets out of the worker's environment.

## Hook points (what to check after merging upstream)

Upstream files carry only these lines, each tagged `# [local-models fork]`:

| File | Hook |
|---|---|
| `backend/models.py` | `SubmissionMode.local` |
| `backend/routers/submissions.py` | `local_hooks.check_submission(...)` and `"local"` in the allowed modes |
| `backend/worker.py` | `is_byok` widened to local runs, and the local OCR branch before the BYOK branch |
| `backend/services/review_service.py` | `local_hooks.configure_review_service(self)` at the end of `__init__` |
| `backend/routers/debates.py` | `debate_llm_overrides(...)` and `merge_debate_kwargs(...)` around `litellm.completion` |
| `.gitignore` | `.env.local` |

The frontend needs no upstream edits. `local-models.js` wraps `updateSubmitButton`, `performUpload` and
`showConsentModal` from `docs/js/upload.js` at runtime. `tests/localmodels/test_hooks_present.py` fails
loudly if a merge removes a hook or upstream renames something the frontend wraps.

## Staying in sync with upstream

Remotes: `origin` is this fork (push here) and `upstream` is prometheus-eval (fetch only).

- **Automatic:** `.github/workflows/sync-upstream.yml` runs weekly (Monday morning NZ time) and on demand
  from the Actions tab. It merges `upstream/main` into `main`, runs `tests/localmodels`, and pushes only if
  they pass. Otherwise it opens an issue.
- **By hand:** `fork/sync-upstream.sh` does the same locally (add `--push` to push). It turns on
  `git rerere`, so a conflict you resolve once is replayed automatically next time.

Resolving a conflict: take upstream's version of the hunk, re-add the tagged line(s) from the table above,
then run `python -m pytest tests/localmodels -q`.

Develop fork features on branches off `main` and merge them in. Don't rebase `main` onto upstream: merging
keeps the history stable for anyone who cloned the fork.
