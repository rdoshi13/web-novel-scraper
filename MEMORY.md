# Repo Memory

Persistent working memory for AI agents and future maintainers. Read this before making changes. Update it after making changes that matter.

## Project Summary

This is a small personal Python web novel scraper that creates EPUB files. It has a Tkinter launcher in `main.py` and separate website-named scraper scripts for each supported source.

## Architecture

- `main.py` defines the desktop launcher, validates user inputs, and runs scraper scripts as subprocesses in the chosen output folder.
- `readnovelfull.py`, `webnoveltranslations.py`, `novelbin.py`, and `freewebnovel.py` are standalone CLI scrapers that fetch novel/chapter pages with `requests`, parse HTML with BeautifulSoup, and generate EPUBs with `ebooklib.epub`.
- `build_app.sh` packages the Tkinter launcher into a macOS app with PyInstaller.
- Generated EPUBs may appear under `novels/` or the selected output directory; they should not be committed unless explicitly requested.

## Decisions

- 2026-07-07: Keep each source as a separate script with a compatible CLI so `main.py` can route to it without introducing a shared framework.
- 2026-07-07: FreeWebNovel follows next-chapter links from the first chapter instead of relying on paginated chapter-list ranges.

## Gotchas

- There is no package manager config. Dependencies are inferred from imports: `requests`, `beautifulsoup4`, `ebooklib`, `pandas` for `readnovelfull.py`, and optional `lxml` for faster parsing.
- FreeWebNovel may return a Cloudflare challenge page to plain HTTP clients. `freewebnovel.py` detects this and exits without creating an empty EPUB.
- Avoid live scraper validation unless needed because target site markup and availability can change.

## Commands

```bash
python main.py
python readnovelfull.py https://readnovelfull.com/heaven-officials-blessing-novel.html --all
python webnoveltranslations.py https://webnoveltranslations.com/novel/the-reincarnated-assassin-is-a-genius-swordsman/ all
python novelbin.py https://novelbin.com/b/the-warriors-ballad/ 5
python freewebnovel.py https://freewebnovel.com/novel/the-primal-hunter 5
python -m py_compile main.py readnovelfull.py webnoveltranslations.py novelbin.py freewebnovel.py
```

## Change Log

### 2026-07-07 — Codex

- Changed: Added FreeWebNovel scraper support, launcher registration, README/AGENTS documentation, and repo memory.
- Why: The project needed one more scraper target for `https://freewebnovel.com/home` while preserving the existing script-oriented design.
- Files: `freewebnovel.py`, `main.py`, `README.md`, `AGENTS.md`, `MEMORY.md`.
- Follow-ups: If FreeWebNovel blocks `requests` from the user's network, test whether browser cookies, a manual export flow, or an approved browser automation path is appropriate.
