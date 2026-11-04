# Job Hunt Agents 🤖

A multi-agent system that runs every morning on GitHub Actions, finds fresh junior tech jobs in Israel, checks how well each one fits, researches the company, writes a tailored CV for the best matches, and emails a digest.

Built with Python, Google Gemini (free tier) and an orchestrator–workers architecture.

## Architecture

```
                    ┌──────────────────┐
                    │   Orchestrator   │  decides who runs, in what order, on which job
                    └────────┬─────────┘
       ┌──────────┬──────────┼───────────┬────────────┐
       ▼          ▼          ▼           ▼            ▼
   🔎 Scout   ⚖️ Matcher  🏢 Researcher 📝 CV Writer  📤 Sender
       │          │          │           │            │
       └──────────┴──────────┴─────┬─────┴────────────┘
                                   ▼
                     Shared board (SQLite, jobs.db)
          new → matched / rejected → researched → cv_ready → sent
```

| Agent | Responsibility |
|---|---|
| **Scout** | Searches the web for fresh junior postings matching roles and locations |
| **Matcher** | Honest 1–10 fit score with strengths, gaps and deal-breakers (all jobs in one call) |
| **Researcher** | Researches the company beyond the job board: product, stack, news, official apply link |
| **CV Writer** | Writes a one-page tailored CV (.docx) and a short cover letter, using only real facts from the profile |
| **Sender** | Emails one digest with every CV attached. Never applies to companies on its own |

### Design decisions
- **Blackboard pattern.** Agents never call each other. Each writes its full result to a shared SQLite board, and the next one reads from it. The orchestrator only receives one-line summaries, which keeps its context small.
- **Idempotent runs.** Jobs are keyed by a hash of company and title, so a posting is never processed or sent twice, across days.
- **Fault isolation.** A failing worker returns an error string instead of crashing the run.
- **Free-tier aware.** About 8 model calls per run: batched matching, capped CVs per run, and backoff on rate limits.
- **Two providers.** Free mode (Gemini plus a multi-engine web search with fallback) or paid mode (Claude with built-in web search and an LLM orchestrator that plans the run itself through tool use).
- **No invented experience.** The CV writer is restricted to facts in the profile.
- **Privacy.** The personal profile is injected from a GitHub secret and never committed.

## Run on GitHub Actions
1. Fork or clone this repo.
2. Add the repository secrets: `GEMINI_API_KEY`, `PROFILE_MD` (your CV as markdown, see `profile.example.md`), `MY_EMAIL`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`.
3. Actions → **Daily job hunt** → **Run workflow**. After that it runs Sunday–Friday at 07:30 Israel time.

Without `GMAIL_APP_PASSWORD` it runs in dry-run mode, and the CVs and email are downloadable from the run's artifacts.

## Run locally
```bash
pip install -r requirements.txt
cp .env.example .env          # add your keys
cp profile.example.md profile.md   # your CV
python orchestrator.py
```

## Project structure
| File | Role |
|---|---|
| `orchestrator.py` | Orchestrator: LLM tool-use loop (paid) or fixed pipeline (free) |
| `workers.py` | The five agents and their system prompts |
| `state.py` | Shared SQLite board |
| `llm.py` | Provider-agnostic model calls, JSON extraction, retry |
| `search.py` | Free web search with engine fallback |
| `cv_docx.py` | Markdown → Word CV |
| `mailer.py` | Hebrew RTL HTML digest with attachments |
