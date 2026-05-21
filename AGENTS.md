# AGENTS.md

Repository-specific guidance for coding agents working in this project.

## Project Overview

- This is a small Python web novel scraper that creates EPUB files.
- `main.py` is the local Tkinter launcher and routes to the individual website-named scraper scripts.
- Active scraper targets are `readnovelfull.com`, `webnoveltranslations.com`, and `novelbin.com`.

## Repository Conventions

- Keep changes small and preserve the script-oriented structure unless explicitly asked to refactor.
- The launcher invokes scraper files as subprocesses; keep their command-line interfaces compatible with `main.py`.
- Existing scrapers use `requests`, `BeautifulSoup`, and `ebooklib.epub`; follow those patterns for new sources.
- Be polite to target sites: keep configurable throttling, browser-like headers, and error handling when changing network code.
- EPUB output is generated in the selected/current working directory. Avoid committing generated `.epub` files unless explicitly requested.
- Scraper files are named after the supported websites.

## Setup Notes

- There is currently no `requirements.txt`, `pyproject.toml`, or package manager config. Infer dependencies from imports when needed.
- Python dependencies used by the current scripts include:
  - `requests`
  - `beautifulsoup4`
  - `ebooklib`
  - `pandas` for `readnovelfull.py`
  - optional `lxml` for faster parsing in `novelbin.py`
- `tkinter` is used for the local GUI and usually ships with Python.

## Common Commands

- GUI launcher:
  ```bash
  python main.py
  ```
- ReadNovelFull scraper:
  ```bash
  python readnovelfull.py https://readnovelfull.com/heaven-officials-blessing-novel.html --all
  ```
- WebNovelTranslations scraper:
  ```bash
  python webnoveltranslations.py https://webnoveltranslations.com/novel/the-reincarnated-assassin-is-a-genius-swordsman/ all
  ```
- NovelBin scraper:
  ```bash
  python novelbin.py https://novelbin.com/b/the-warriors-ballad/ 5
  ```
- Syntax check all Python files:
  ```bash
  python -m py_compile main.py readnovelfull.py webnoveltranslations.py novelbin.py
  ```

## Testing And Validation

- No automated test suite is currently present.
- For Python changes, run the `py_compile` command above as the narrowest validation.
- For GUI launcher changes, verify the generated command shape for each scraper.
- For scraper behavior changes, prefer testing with a low chapter limit before using `--all` or `all`.
- Avoid live network validation unless it is necessary for the task, because scraper results depend on external site availability and markup.

## Change Discipline

- Inspect `main.py`, the relevant scraper, and README before editing.
- Add or update documentation when supported sites, commands, or required dependencies change.
- Do not modify unrelated files such as `.gitignore`, `.vscode/settings.json`, or generated cache files as part of normal scraper changes.
- Preserve user changes in this repository; the worktree may contain uncommitted files.
