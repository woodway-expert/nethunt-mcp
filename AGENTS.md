# Repository Guidelines

## Project Structure & Module Organization
`src/nethunt_mcp/` contains the package code. `server.py` registers FastMCP tools and resources, `service.py` holds NetHunt business logic, `client.py` wraps NetHunt API calls, `config.py` loads environment settings, and `errors.py` centralizes normalized errors. Tests live in `tests/` and mirror the package layout with files such as `test_service.py` and `test_server.py`. Repo-level behavior is defined in `pyproject.toml`, `.editorconfig`, `.gitattributes`, `.gitignore`, and `.dockerignore`. Runtime examples and container assets live in `.env.example`, `Dockerfile`, `compose.yaml`, and `README.md`.

## Build, Test, and Development Commands
Create a local environment with `python -m venv .venv`, then install dev dependencies with `.\.venv\Scripts\python -m pip install -e .[dev]`. Run the MCP server in default `stdio` mode with `.\.venv\Scripts\nethunt-mcp`. Execute the full test suite with `.\.venv\Scripts\python -m pytest`. Build the container with `docker build -t nethunt-mcp:latest .`. For HTTP transport smoke tests, use `docker compose up --build` and connect to `http://127.0.0.1:8000/mcp`.

## Coding Style & Naming Conventions
Target Python 3.12+ and keep 4-space indentation, explicit type hints, and small focused functions. Match existing naming: `snake_case` for modules, functions, and variables; `PascalCase` for classes; `UPPER_CASE` for constants. `.editorconfig` sets UTF-8, LF endings, and trimmed whitespace; `.gitattributes` keeps Windows script files on CRLF. Preserve the JSON response contract (`ok`, `data`, `meta`, `error`) and the explicit confirmation guards around destructive writes. No formatter or linter is configured in `pyproject.toml`, so keep imports tidy and follow nearby code closely.

## Testing Guidelines
Use `pytest` with `pytest-asyncio`; async tests should be marked with `@pytest.mark.asyncio`. Name new test files `test_<module>.py` and keep tests focused on a single behavior. Prefer fake clients or services over live NetHunt API calls. Cover success paths, validation failures, and preview/confirmation flows for `delete_record` and `raw_post`.

## Commit & Pull Request Guidelines
The repository is initialized on `main`, but there is no established commit history yet. Use short imperative commit subjects such as `Add delete confirmation contract` and keep each commit scoped to one behavior change. PRs should explain the user-visible effect, list verification steps run, and call out any environment or transport changes. Screenshots are usually unnecessary for this backend project; sample requests, CLI commands, or response payloads are more useful.

## Security & Configuration Tips
Never commit real values from `.env`; use `.env.example` as the template and keep local artifacts covered by `.gitignore`. NetHunt authentication requires both `NETHUNT_EMAIL` and `NETHUNT_API_KEY`. Treat delete and raw write operations as high-risk paths and keep their confirmation requirements intact.
