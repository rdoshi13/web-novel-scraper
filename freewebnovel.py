# This script scrapes chapters from FreeWebNovel and compiles them into an EPUB file.
# It is for https://freewebnovel.com/ novels.

import argparse
import os
import re
import time
from copy import copy
from html import escape
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, FeatureNotFound
from ebooklib import epub


headers = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


session = requests.Session()
session.headers.update(headers)


def parse_html(html):
    """
    Parses HTML with lxml when available, falling back to Python's built-in parser.
    """
    try:
        return BeautifulSoup(html, "lxml")
    except FeatureNotFound:
        return BeautifulSoup(html, "html.parser")


def fetch_soup(url):
    """
    Fetches a FreeWebNovel page and returns a parsed BeautifulSoup document.
    """
    response = session.get(url, timeout=20)
    response.raise_for_status()

    if "Just a moment" in response.text and "Cloudflare" in response.text:
        raise RuntimeError(
            "FreeWebNovel returned a Cloudflare challenge page instead of novel content."
        )

    return parse_html(response.content)


def log_message(message, log=None):
    if log:
        log(message)
    else:
        print(message)


def get_image_url(soup, base_url):
    """
    Finds the novel cover image URL from the detail page.
    """
    cover_tag = (
        soup.select_one('meta[property="og:image"]')
        or soup.select_one(".book img")
        or soup.select_one(".novel-cover img")
        or soup.select_one(".m-imgtxt img")
        or soup.select_one('img[alt]')
    )
    if not cover_tag:
        return None

    image_url = (
        cover_tag.get("content")
        or cover_tag.get("data-src")
        or cover_tag.get("data-original")
        or cover_tag.get("src")
    )
    return urljoin(base_url, image_url) if image_url else None


def get_cover_filename(response):
    """
    Chooses a cover filename based on the response content type.
    """
    content_type = response.headers.get("content-type", "").lower()
    if "png" in content_type:
        return "cover.png"
    if "webp" in content_type:
        return "cover.webp"
    return "cover.jpg"


def add_cover(book, cover_url, log=None):
    """
    Downloads and embeds the novel cover in the EPUB.
    """
    if not cover_url:
        log_message("No cover image found.", log)
        return

    try:
        response = session.get(cover_url, timeout=20)
        response.raise_for_status()
        if not response.headers.get("content-type", "").lower().startswith("image/"):
            log_message(f"Cover URL did not return an image: {cover_url}", log)
            return
        book.set_cover(get_cover_filename(response), response.content)
        log_message(f"Added cover image: {cover_url}", log)
    except requests.exceptions.RequestException as e:
        log_message(f"Failed to download cover image: {e}", log)


def clean_text(text):
    return re.sub(r"\s+", " ", text).strip()


def get_novel_info(novel_url):
    """
    Scrapes the title, author, cover image, and first page soup.
    """
    soup = fetch_soup(novel_url)

    title_tag = (
        soup.select_one("h1")
        or soup.select_one("h3")
        or soup.select_one('meta[property="og:title"]')
    )
    if title_tag and title_tag.name == "meta":
        novel_title = title_tag.get("content", "").split("|")[0].strip()
    elif title_tag:
        novel_title = title_tag.get_text(strip=True)
    else:
        novel_title = "Unknown Novel"

    author_tag = (
        soup.select_one('a[href*="/author/"]')
        or soup.select_one('a[href*="/authors/"]')
        or soup.select_one('a[href*="/creator/"]')
    )
    novel_author = author_tag.get_text(strip=True) if author_tag else "Unknown Author"

    cover_url = get_image_url(soup, novel_url)
    return novel_title, novel_author, cover_url, soup


def get_first_chapter_url(novel_url, soup=None):
    """
    Finds the first chapter URL from the detail page.
    """
    soup = soup or fetch_soup(novel_url)

    for link in soup.select("a[href]"):
        link_text = clean_text(link.get_text(" ", strip=True)).lower()
        href = link.get("href", "")
        if link_text in ("read first", "chapter 1") or re.search(r"/chapter-?1/?$", href):
            return urljoin(novel_url, href)

    first_chapter = soup.select_one('a[href*="/chapter-"]')
    if first_chapter:
        return urljoin(novel_url, first_chapter["href"])

    return None


def find_link_by_text(soup, phrase):
    phrase = phrase.lower()
    for link in soup.select("a[href]"):
        if phrase in clean_text(link.get_text(" ", strip=True)).lower():
            return link
    return None


def get_next_chapter_url(chapter_url, soup):
    """
    Finds the next chapter URL from a chapter page.
    """
    next_link = (
        soup.select_one("a.next[href]")
        or soup.select_one(".next a[href]")
        or soup.select_one('a[rel="next"]')
        or find_link_by_text(soup, "next chapter")
    )
    if not next_link:
        return None

    next_url = next_link.get("href")
    if not next_url or next_url.startswith("javascript:"):
        return None

    return urljoin(chapter_url, next_url)


def clean_chapter_html(content_tag):
    """
    Removes controls, scripts, ads, and links from a chapter content block.
    """
    chapter_body = copy(content_tag)

    blacklist = [
        "script",
        "style",
        "ins",
        "iframe",
        "form",
        "button",
        "select",
        "option",
        ".adsbygoogle",
        ".ad",
        ".ads",
        ".comments",
        ".comment",
        ".chapter-nav",
        ".m-comment",
        "[id*='ads']",
        "[class*='ads']",
        "[class*='comment']",
    ]
    for selector in blacklist:
        for unwanted in chapter_body.select(selector):
            unwanted.decompose()

    nav_words = ("next chapter", "prev chapter", "previous chapter", "add to library")
    for link in chapter_body.select("a[href]"):
        if any(word in clean_text(link.get_text(" ", strip=True)).lower() for word in nav_words):
            link.decompose()

    for element in list(chapter_body.select("*")):
        if element.name in ("br", "hr"):
            continue
        if element.name == "img":
            element.decompose()
            continue
        if not element.get_text(strip=True):
            element.decompose()

    return str(chapter_body)


def score_content_candidate(tag):
    text = tag.get_text("\n", strip=True)
    paragraphs = tag.find_all("p")
    nav_penalty = sum(
        word in text.lower()
        for word in ("font size", "background", "comments", "login/signup")
    )
    return len(text) + (len(paragraphs) * 300) - (nav_penalty * 2000)


def get_content_tag(soup):
    """
    Finds the chapter body with several known FreeWebNovel-style fallbacks.
    """
    selectors = [
        "#article",
        "#chapter-content",
        ".chapter-content",
        ".chapter-c",
        ".cha-words",
        ".txt",
        ".reading-content",
        ".entry-content",
        "article",
    ]
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag and len(tag.get_text(" ", strip=True)) > 200:
            return tag

    candidates = [
        tag
        for tag in soup.find_all(["div", "section", "main"])
        if len(tag.get_text(" ", strip=True)) > 500
    ]
    if candidates:
        return max(candidates, key=score_content_candidate)

    return None


def get_chapter_title(chapter_url, soup):
    title_tag = (
        soup.select_one('meta[property="og:title"]')
        or soup.title
        or soup.select_one(".chapter-title")
        or soup.select_one(".chr-title")
        or soup.select_one("h2")
        or soup.select_one("h1")
    )
    if title_tag and title_tag.name == "meta":
        title = title_tag.get("content", "").split("|")[0].strip()
    elif title_tag and title_tag.name == "title":
        title = title_tag.string or ""
    elif title_tag:
        title = title_tag.get_text(" ", strip=True)
    else:
        title = ""

    if title:
        title = re.sub(r"\s+-\s+Free Web Novel\s*$", "", title, flags=re.IGNORECASE)
        chapter_match = re.search(r"(chapter\s+\d+[^|]*)", title, flags=re.IGNORECASE)
        if chapter_match:
            chapter_title = re.sub(
                r"\s+-\s+Free Web Novel\s*$",
                "",
                chapter_match.group(1),
                flags=re.IGNORECASE,
            )
            return clean_text(chapter_title)

        pieces = [clean_text(piece) for piece in re.split(r"\s+[-|]\s+", title)]
        for piece in pieces:
            if piece.lower().startswith("chapter"):
                return piece
        return clean_text(title)

    match = re.search(r"/chapter-([^/?#]+)/?", chapter_url)
    return f"Chapter {match.group(1).replace('-', '.')}" if match else "Unknown Chapter"


def scrape_chapter(chapter_url, log=None):
    """
    Scrapes the title, content, and next chapter URL from a FreeWebNovel chapter page.
    """
    log_message(f"Scraping chapter from: {chapter_url}", log)
    soup = fetch_soup(chapter_url)

    chapter_title = get_chapter_title(chapter_url, soup)
    content_tag = get_content_tag(soup)
    if not content_tag:
        log_message(f"Failed to find chapter content for {chapter_url}", log)
        return None

    content = clean_chapter_html(content_tag)
    if not content or len(parse_html(content).get_text(" ", strip=True)) < 100:
        log_message(f"Warning: no readable content found for {chapter_url}", log)

    return {
        "title": chapter_title,
        "content": content,
        "next_url": get_next_chapter_url(chapter_url, soup),
    }


def scrape_novel(novel_url, chapters_to_scrape, wait_time=0, log=None):
    """
    Scrapes chapters by starting at the first chapter and following next links.
    """
    novel_title, novel_author, cover_url, novel_soup = get_novel_info(novel_url)
    first_chapter_url = get_first_chapter_url(novel_url, novel_soup)

    if not first_chapter_url:
        log_message("Failed to find the first chapter URL.", log)
        return novel_title, novel_author, cover_url, []

    scrape_all = chapters_to_scrape.lower() == "all"
    chapter_limit = None

    if not scrape_all:
        try:
            chapter_limit = int(chapters_to_scrape)
        except ValueError:
            log_message("Invalid input for number of chapters. Please use a number or 'all'.", log)
            return novel_title, novel_author, cover_url, []

        if chapter_limit <= 0:
            log_message("Please provide a positive number of chapters.", log)
            return novel_title, novel_author, cover_url, []

    chapter_url = first_chapter_url
    scraped_chapters = []
    seen_urls = set()

    while chapter_url and chapter_url not in seen_urls:
        if chapter_limit is not None and len(scraped_chapters) >= chapter_limit:
            break

        seen_urls.add(chapter_url)

        try:
            chapter_data = scrape_chapter(chapter_url, log=log)
        except requests.exceptions.RequestException as e:
            log_message(f"Error fetching URL {chapter_url}: {e}", log)
            break
        except RuntimeError as e:
            log_message(str(e), log)
            break

        if not chapter_data:
            break

        if chapter_data["content"]:
            scraped_chapters.append(
                {"title": chapter_data["title"], "content": chapter_data["content"]}
            )

        chapter_url = chapter_data["next_url"]
        if wait_time > 0:
            time.sleep(wait_time)

    return novel_title, novel_author, cover_url, scraped_chapters


def safe_filename(title):
    """
    Converts a novel title into a simple EPUB filename.
    """
    filename = re.sub(r"[^\w\s.-]", "", title).strip().replace(" ", "_")
    return f"{filename or 'freewebnovel_novel'}.epub"


def create_epub(novel_data, novel_title, novel_author, output_filename, cover_url=None, log=None):
    """
    Creates an EPUB file from the scraped novel data.
    """
    log_message(f"\nCreating EPUB file: {output_filename}...", log)
    book = epub.EpubBook()

    book.set_identifier(novel_title.replace(" ", "_").lower())
    book.set_title(novel_title)
    book.set_language("en")
    book.add_author(novel_author)
    add_cover(book, cover_url, log=log)

    chapters = []
    for i, chapter_data in enumerate(novel_data):
        chapter = epub.EpubHtml(
            title=chapter_data["title"],
            file_name=f"chap_{i + 1}.xhtml",
            lang="en",
        )
        chapter.content = f"<h1>{escape(chapter_data['title'])}</h1>\n{chapter_data['content']}"

        book.add_item(chapter)
        chapters.append(chapter)

    book.toc = tuple(chapters)
    book.spine = ["nav"] + chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(output_filename, book, {})
    log_message(f"EPUB file '{output_filename}' created successfully.", log)


def main():
    parser = argparse.ArgumentParser(description="Scrape a FreeWebNovel novel and save as EPUB.")
    parser.add_argument("novel_url", type=str, help="URL of the novel to scrape.")
    parser.add_argument(
        "chapters_to_scrape",
        type=str,
        help='Number of chapters to scrape from the start, or "all" for all chapters.',
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=1,
        help="Seconds to wait between chapter requests.",
    )
    args = parser.parse_args()

    novel_title, novel_author, cover_url, scraped_chapters = scrape_novel(
        args.novel_url,
        args.chapters_to_scrape,
        wait_time=args.wait,
    )

    if not scraped_chapters:
        print("No chapters were scraped. EPUB file was not created.")
        return

    output_filename = safe_filename(novel_title)
    create_epub(
        scraped_chapters,
        novel_title,
        novel_author,
        output_filename,
        cover_url=cover_url,
    )
    print(f"Scraping and EPUB conversion complete! EPUB saved as '{output_filename}'")


if __name__ == "__main__":
    main()
