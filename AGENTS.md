# Repository Guidelines

## Project Structure & Module Organization
This repository is a lightweight agent research workspace. Top-level files include `README.md` and `main.py`. Most working content lives under `template/`:

- `template/*.md`: research notes and requirement drafts, such as `03_调研.md` and `04_需求分析.md`
- `template/rag/`: Python retrieval examples, including Milvus hybrid search scripts
- `template/intent/`: saved reference articles in HTML format

Keep new research documents in `template/` and group code examples by topic in subdirectories.

## Build, Test, and Development Commands
There is no formal build system yet. Use focused commands for local validation:

- `python main.py`: run the current top-level Python entry point if it is implemented
- `python template/rag/01_hybrid_search.py`: run a Milvus retrieval example
- `git diff --stat`: review change scope before committing
- `git status --short`: verify staged and unstaged files

If you add runnable code, document required dependencies and environment variables near the script or in `README.md`.

## Coding Style & Naming Conventions
Use 4 spaces for Python indentation and follow PEP 8 naming:

- `snake_case` for variables, functions, and file names
- `UPPER_SNAKE_CASE` for constants such as `COLLECTION_NAME`

For Markdown, prefer short sections, flat bullet lists, and topic-based filenames like `02_RAG.md`. Keep examples practical and written in concise Chinese when extending the existing research docs.

## Testing Guidelines
There is no dedicated test suite or coverage target today. For code changes, run the smallest meaningful check locally, usually the modified script directly. For research documents, verify links, headings, and formatting by reviewing the rendered Markdown. If you add reusable Python logic, introduce `tests/` with `test_*.py` files and keep tests close to the changed behavior.

## Commit & Pull Request Guidelines
Recent history uses Conventional Commits, for example `docs(template): 补充多轮意图识别调研`. Follow `type(scope): summary` and keep scopes specific, such as `template`, `rag`, or `agent`.

Pull requests should include:

- a short description of what changed and why
- impacted paths, such as `template/03_调研.md`
- screenshots only when formatting or rendered output materially changed

Stage only intended files and review `git diff --cached` before committing.
