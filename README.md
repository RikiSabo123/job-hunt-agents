# Job Hunt Agents 🤖

A multi-agent system that runs every morning on GitHub Actions, finds fresh junior tech jobs in Israel, checks how well each one fits, researches the company, writes a tailored CV for the best matches, and emails a digest.

It also ships with an **MCP server** that exposes the jobs database to Claude Desktop, Claude Code and Cursor, so you can ask an AI assistant about your job pipeline in natural language.

Built with Python, free-tier LLMs (Groq, with Google Gemini as fallback, or Claude in paid mode), SQLite, FastMCP and GitHub Actions.

## Contents

- [Architecture](#architecture)
- [Design decisions](#design-decisions)
- [MCP server](#mcp-server)
- [Run on GitHub Actions](#run-on-github-actions)
- [Run locally](#run-locally)
- [Tests](#tests)
- [Project structure](#project-structure)

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
                                   │
                                   ▼
                      🔌 MCP server (read-only)
                Claude Desktop · Claude Code · Cursor
```

| Agent          | Responsibility                                                                                         |
| -------------- | ------------------------------------------------------------------------------------------------------ |
| **Scout**      | Searches the web for fresh junior postings matching roles and locations                                |
| **Matcher**    | Honest 1–10 fit score with strengths, gaps and deal-breakers (all jobs in one call)                    |
| **Researcher** | Researches the company beyond the job board: product, stack, news, official apply link                 |
| **CV Writer**  | Writes a one-page tailored CV (.docx) and a short cover letter, using only real facts from the profile |
| **Sender**     | Emails one digest with every CV attached. Never applies to companies on its own                        |

### Design decisions

- **Blackboard pattern.** Agents never call each other. Each writes its full result to a shared SQLite board, and the next one reads from it. The orchestrator only receives one-line summaries, which keeps its context small.
- **Idempotent runs.** Jobs are keyed by a hash of company and title, so a posting is never processed or sent twice, across days.
- **Fault isolation.** A failing worker returns an error string instead of crashing the run.
- **Free-tier aware.** About 8 model calls per run: batched matching, capped CVs per run, and backoff on rate limits.
- **Two providers.** Free mode (Gemini plus a multi-engine web search with fallback) or paid mode (Claude with built-in web search and an LLM orchestrator that plans the run itself through tool use).
- **No invented experience.** The CV writer is restricted to facts in the profile.
- **Privacy.** The personal profile is injected from a GitHub secret and never committed.

## MCP server

The `mcp_server/` package is a [Model Context Protocol](https://modelcontextprotocol.io) server built with Python and FastMCP. It lets an MCP client query the jobs database that the agents fill every morning.

### Tools

<!-- TODO: replace the names and descriptions below with the real four tools from mcp_server/ -->

| Tool            | What it does                              |
| --------------- | ----------------------------------------- |
| `TOOL_NAME_1`   | TODO: one-line description                |
| `TOOL_NAME_2`   | TODO: one-line description                |
| `TOOL_NAME_3`   | TODO: one-line description                |
| `TOOL_NAME_4`   | TODO: one-line description                |

### Safety

<!-- TODO: keep only the points that are true in the code -->

- **Read-only access.** The server opens the database in read-only mode and exposes no tool that writes.
- **Protected queries.** All queries are parameterized; user input is never concatenated into SQL.
- **Input validation.** Arguments are validated (types, allowed values, limits) before they reach the database.
- **Demo database.** The repository ships with a fictional demo database, so you can try the server without any personal data.

### Connect to Claude Desktop

Add this to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "job-hunt": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "cwd": "/absolute/path/to/job-hunt-agents"
    }
  }
}
```

<!-- TODO: confirm the real entry point (module name or file) -->

### Connect to Claude Code

```
claude mcp add job-hunt -- python -m mcp_server
```

### Connect to Cursor

Add the same `command` and `args` under `mcpServers` in `.cursor/mcp.json`.

### Example prompts

- "Which jobs did the Matcher score 8 or higher this week?"
- "Show me the research notes for the last company in `cv_ready`."
- "How many postings were rejected, and what were the most common deal-breakers?"

## Run on GitHub Actions

1. Fork or clone this repo.
2. Add the repository secrets: `GROQ_API_KEY` (free at console.groq.com), `GEMINI_API_KEY` (fallback), `PROFILE_MD` (your CV as markdown, see `profile.example.md`), `MY_EMAIL`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`.
3. Actions → **Daily job hunt** → **Run workflow**. After that it runs Sunday–Friday at 07:30 Israel time.

Without `GMAIL_APP_PASSWORD` it runs in dry-run mode, and the CVs and email are downloadable from the run's artifacts.

## Run locally

```
pip install -r requirements.txt
cp .env.example .env          # add your keys
cp profile.example.md profile.md   # your CV
python orchestrator.py
```

## Tests

```
pip install -r requirements.txt
pytest
```

<!-- TODO: add one line on what the MCP tests cover, e.g. tool output, read-only enforcement, invalid input -->

## Project structure

| Path              | Role                                                                               |
| ----------------- | ---------------------------------------------------------------------------------- |
| `orchestrator.py` | Orchestrator: LLM tool-use loop (paid) or fixed pipeline (free)                    |
| `workers.py`      | The five agents and their system prompts                                           |
| `state.py`        | Shared SQLite board                                                                |
| `llm.py`          | Provider chain (Groq → Gemini, or Claude), JSON extraction, rate-limit-aware retry |
| `search.py`       | Free web search with engine fallback                                               |
| `cv_docx.py`      | Markdown → Word CV                                                                 |
| `mailer.py`       | Hebrew RTL HTML digest with attachments                                            |
| `mcp_server/`     | Read-only MCP server over the jobs database                                        |
| `tests/`          | pytest suite for the MCP server                                                    |
