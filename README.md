Job Hunt Agents 🤖
A multi-agent system that runs every morning on GitHub Actions, finds fresh junior tech jobs in Israel, checks how well each one fits, researches the company, writes a tailored CV for the best matches, and emails a digest.
It also ships with an MCP server that exposes the jobs database to Claude Desktop, Claude Code and Cursor, so you can ask an AI assistant about your job pipeline in natural language.
Built with Python, free-tier LLMs (Groq, with Google Gemini as fallback, or Claude in paid mode), SQLite, FastMCP and GitHub Actions.
Contents
Architecture
Design decisions
MCP server
Run on GitHub Actions
Run locally
Tests
Project structure
Architecture
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
                                   │
                                   ▼
                      🔌 MCP server (read-only)
                Claude Desktop · Claude Code · Cursor
```
Agent	Responsibility
Scout	Searches the web for fresh junior postings matching roles and locations
Matcher	Honest 1–10 fit score with strengths, gaps and deal-breakers (all jobs in one call)
Researcher	Researches the company beyond the job board: product, stack, news, official apply link
CV Writer	Writes a one-page tailored CV (.docx) and a short cover letter, using only real facts from the profile
Sender	Emails one digest with every CV attached. Never applies to companies on its own
Design decisions
Blackboard pattern. Agents never call each other. Each writes its full result to a shared SQLite board, and the next one reads from it. The orchestrator only receives one-line summaries, which keeps its context small.
Idempotent runs. Jobs are keyed by a hash of company and title, so a posting is never processed or sent twice, across days.
Fault isolation. A failing worker returns an error string instead of crashing the run.
Free-tier aware. About 8 model calls per run: batched matching, capped CVs per run, and backoff on rate limits.
Two providers. Free mode (Gemini plus a multi-engine web search with fallback) or paid mode (Claude with built-in web search and an LLM orchestrator that plans the run itself through tool use).
No invented experience. The CV writer is restricted to facts in the profile.
Privacy. The personal profile is injected from a GitHub secret and never committed.
MCP server
The `mcp_server/` package is a Model Context Protocol server built with Python and FastMCP. It lets an MCP client (Claude Desktop, Claude Code, Cursor) answer questions about the jobs database that the agents fill every morning.
Tools
Tool	What it does
`search_jobs`	Search by text (title, company, description), location, minimum fit score and status. Best fit first, then newest. Up to 50 results.
`get_job`	Full record of one job: fit analysis, company research and the description (cut at 4,000 characters). The tailored CV and cover letter are included only on request.
`top_matches`	The best-fitting jobs that passed the matcher, optionally limited to the last N days, each with a one-line reason and the gaps from the fit analysis.
`board_stats`	Overview of the board: jobs per pipeline stage, total, average fit score and when the newest job was added.
Safety
Read-only. The database is opened in SQLite read-only mode (`mode=ro`), so any write through the server fails.
Protected queries. Every query is parameterized, and `%` and `_` in search text are escaped so they are treated as plain characters.
Input validation. `status` must be one of the pipeline stages, `min_score` must be 0–10, `days` 1–365, and `limit` is clamped to 1–50. Long descriptions are truncated.
Errors, not crashes. A missing database or a SQLite failure comes back as an error message to the client. Logs go to stderr (stdout carries the protocol) and contain row counts only, never job content.
Personal documents stay out by default. The tailored CV and cover letter are returned only when `include_documents` is true.
Quick start
```
pip install -r requirements.txt
python mcp_server/seed_demo.py      # writes mcp_server/demo_jobs.db (12 fictional jobs)
JOBS_DB=mcp_server/demo_jobs.db mcp dev mcp_server/server.py   # opens the MCP Inspector
```
On Windows PowerShell:
```
$env:JOBS_DB="mcp_server/demo_jobs.db"; mcp dev mcp_server/server.py
```
The demo board has jobs in every pipeline stage, so all four tools return something. Every company, URL and document in it is made up.
By default the server reads `jobs.db` in the repo root (the real board). Set `JOBS_DB` to point it at another database, such as the demo one.
Connect to Claude Desktop
Add this to `claude_desktop_config.json` (use absolute paths):
```json
{
  "mcpServers": {
    "job-hunt": {
      "command": "python",
      "args": ["/absolute/path/to/job-hunt-agents/mcp_server/server.py"],
      "env": { "JOBS_DB": "/absolute/path/to/job-hunt-agents/mcp_server/demo_jobs.db" }
    }
  }
}
```
`env` is optional: without it the server reads the real `jobs.db`. Restart Claude Desktop after saving.
Connect to Claude Code
```
claude mcp add job-hunt -- python /absolute/path/to/job-hunt-agents/mcp_server/server.py
```
Connect to Cursor
Add the same `command` and `args` under `mcpServers` in `.cursor/mcp.json`.
Example prompts
"Which jobs scored 8 or higher this week?"
"Show me the top 5 matches and what each one is missing."
"Give me the full details for job <id>, including the tailored CV."
"How many jobs are at each stage of the pipeline?"
Run on GitHub Actions
Fork or clone this repo.
Add the repository secrets: `GROQ_API_KEY` (free at console.groq.com), `GEMINI_API_KEY` (fallback), `PROFILE_MD` (your CV as markdown, see `profile.example.md`), `MY_EMAIL`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`.
Actions → Daily job hunt → Run workflow. After that it runs Sunday–Friday at 07:30 Israel time.
Without `GMAIL_APP_PASSWORD` it runs in dry-run mode, and the CVs and email are downloadable from the run's artifacts.
Run locally
```
pip install -r requirements.txt
cp .env.example .env          # add your keys
cp profile.example.md profile.md   # your CV
python orchestrator.py
```
Tests
```
pip install -r requirements.txt
pytest
```
<!-- TODO: add one line on what the MCP tests cover, e.g. tool output, read-only enforcement, invalid input -->
Project structure
Path	Role
`orchestrator.py`	Orchestrator: LLM tool-use loop (paid) or fixed pipeline (free)
`workers.py`	The five agents and their system prompts
`state.py`	Shared SQLite board
`llm.py`	Provider chain (Groq → Gemini, or Claude), JSON extraction, rate-limit-aware retry
`search.py`	Free web search with engine fallback
`cv_docx.py`	Markdown → Word CV
`mailer.py`	Hebrew RTL HTML digest with attachments
`mcp_server/server.py`	Read-only MCP server over the jobs database (4 tools)
`mcp_server/seed_demo.py`	Creates a fictional demo database
`tests/`	pytest suite for the MCP server
