# Job Hunt MCP Server

A read-only [MCP](https://modelcontextprotocol.io) server over the agents' shared board (`jobs.db`).
It lets AI clients such as Claude Desktop, Claude Code and Cursor answer questions about the jobs in plain language.
It never writes: SQLite is opened in read-only mode and no tool accepts raw SQL.

## Tools
| Tool | What it does |
|---|---|
| `search_jobs` | Search by text (title, company, description), location, minimum fit score and status |
| `get_job` | One job's full record with its fit analysis and company research; CV and cover letter only on request |
| `top_matches` | Best-fitting jobs that passed the matcher, with the one-line reason and the gaps |
| `board_stats` | Jobs per stage, total, average fit score, newest job |

Fit scores use the matcher's **1–10** scale (7+ means "matched").

## Install
```bash
pip install -r requirements-mcp.txt
```
This is separate from `requirements.txt`, so the daily GitHub Actions run is unaffected.

## Demo data
```bash
python mcp_server/seed_demo.py          # writes mcp_server/demo_jobs.db with 12 fictional jobs
```
Point the server at it with `JOBS_DB=mcp_server/demo_jobs.db`. Without `JOBS_DB` it reads `jobs.db` at the repo root.

## Try it in the MCP Inspector
```bash
JOBS_DB=mcp_server/demo_jobs.db mcp dev mcp_server/server.py
```
PowerShell: `$env:JOBS_DB="mcp_server/demo_jobs.db"; mcp dev mcp_server/server.py`

## Claude Code
```bash
claude mcp add job-hunt --env JOBS_DB=/abs/path/to/jobs.db -- python /abs/path/to/job-hunt-agents/mcp_server/server.py
```

## Claude Desktop
Add to `claude_desktop_config.json` and restart Claude Desktop.

- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

Windows:
```json
{
  "mcpServers": {
    "job-hunt": {
      "command": "python",
      "args": ["C:\\Users\\you\\job-hunt-agents\\mcp_server\\server.py"],
      "env": { "JOBS_DB": "C:\\Users\\you\\job-hunt-agents\\jobs.db" }
    }
  }
}
```
macOS:
```json
{
  "mcpServers": {
    "job-hunt": {
      "command": "python3",
      "args": ["/Users/you/job-hunt-agents/mcp_server/server.py"],
      "env": { "JOBS_DB": "/Users/you/job-hunt-agents/jobs.db" }
    }
  }
}
```
Use the Python that has `mcp` installed (a full path to a virtualenv's `python` works too).

## Example questions
- "Which Full Stack jobs in Jerusalem scored 8 or more?"
- "What are the gaps in my top 3 matches?"
- "How many jobs are waiting at each stage?"
- "Show me the cover letter for the Nimbus Analytics job."
- "Which matched jobs were added this week?"

## Tests
```bash
pytest
```

## Safety
- Read-only SQLite connection (`mode=ro`); parameterized queries only.
- Inputs are validated: `limit` is clamped to 1–50; a bad `status`, `min_score` (0–10) or `days` (1–365) returns `{"error": ...}`.
- Malformed `fit_json` / `company_json` comes back as `null` instead of crashing.
- Logs go to stderr (stdout is the MCP channel) and never include job content.
