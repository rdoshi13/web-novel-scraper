# web-novel-scraper

A personal web scraper for web novels that creates EPUB files.

## How to run

### GUI launcher

```bash
python main.py
```

The launcher supports:

- ReadNovelFull
- WebNovelTranslations
- NovelBin
- FreeWebNovel

### Build a double-clickable macOS app

Install PyInstaller once:

```bash
python -m pip install pyinstaller
```

Then build the app:

```bash
./build_app.sh
```

The app will be created at:

```text
dist/Web Novel Scraper.app
```

Re-run `./build_app.sh` after changing `main.py` or any scraper file.

### Individual scrapers

ReadNovelFull:

```bash
python readnovelfull.py https://readnovelfull.com/heaven-officials-blessing-novel.html --all
```

WebNovelTranslations:

```bash
python webnoveltranslations.py https://webnoveltranslations.com/novel/the-reincarnated-assassin-is-a-genius-swordsman/ all
```

NovelBin:

```bash
python novelbin.py https://novelbin.com/b/the-warriors-ballad/ 5
```

FreeWebNovel:

```bash
python freewebnovel.py https://freewebnovel.com/novel/the-primal-hunter 5
```

Use `all` instead of a number to scrape every available chapter.
