# This script scrapes chapters from NovelBin and compiles them into an EPUB file.
# It is for https://novelbin.com/ novels.

import argparse
import os
import queue
import re
import threading
import time
import tkinter as tk
from copy import copy
from html import escape
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, FeatureNotFound
from ebooklib import epub


headers = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
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
    Fetches a NovelBin page and returns a parsed BeautifulSoup document.
    """
    response = session.get(url, timeout=20)
    response.raise_for_status()

    if "Just a moment" in response.text and "Cloudflare" in response.text:
        raise RuntimeError(
            "NovelBin returned a Cloudflare challenge page instead of novel content."
        )

    return parse_html(response.content)


def clean_chapter_html(content_tag):
    """
    Removes unwanted elements and returns cleaned chapter HTML.
    """
    chapter_body = copy(content_tag)

    blacklist = [
        "script",
        "style",
        "ins",
        "iframe",
        "form",
        "button",
        ".adsbygoogle",
        ".ad",
        ".ads",
        "[id*='ads']",
        "[class*='ads']",
    ]
    for selector in blacklist:
        for unwanted in chapter_body.select(selector):
            unwanted.decompose()

    for image in chapter_body.select("img"):
        image.decompose()

    nav_words = ("next", "previous", "table", "index", "back", "home")
    for link in chapter_body.select("a[href]"):
        if any(word in link.get_text(" ", strip=True).lower() for word in nav_words):
            link.decompose()

    for element in list(chapter_body.select("*")):
        if element.name in ("br", "hr", "img"):
            continue
        if not element.get_text(strip=True) and not element.select_one("img"):
            element.decompose()

    return str(chapter_body)


def get_novel_info(novel_url):
    """
    Scrapes the title and author from a NovelBin novel detail page.
    """
    soup = fetch_soup(novel_url)

    title_tag = soup.select_one("h1") or soup.select_one("h3.title")
    novel_title = title_tag.get_text(strip=True) if title_tag else "Unknown Novel"

    author_tag = soup.select_one(".info-meta a[href*='/a/']")
    author_name = author_tag.get_text(strip=True) if author_tag else "Unknown Author"

    return novel_title, author_name, soup


def get_first_chapter_url(novel_url, soup=None):
    """
    Finds the first chapter URL from the detail page.
    """
    soup = soup or fetch_soup(novel_url)

    first_chapter = soup.select_one("a.btn-read-now[href]")
    if not first_chapter:
        first_chapter = soup.select_one("#list-chapter a[href*='/chapter-']")

    if not first_chapter:
        return None

    return urljoin(novel_url, first_chapter["href"])


def get_next_chapter_url(chapter_url, soup):
    """
    Finds the next chapter URL from a chapter page.
    """
    next_link = soup.select_one("a.js-chapter-nav[data-chapter-nav='next']")
    if not next_link:
        return None

    next_url = next_link.get("data-chapter-url") or next_link.get("href")
    if not next_url or next_url.startswith("javascript:"):
        return None

    return urljoin(chapter_url, next_url)


def log_message(message, log=None):
    if log:
        log(message)
    else:
        print(message)


def scrape_chapter(chapter_url, log=None):
    """
    Scrapes the title, content, and next chapter URL from a NovelBin chapter page.
    """
    log_message(f"Scraping chapter from: {chapter_url}", log)
    soup = fetch_soup(chapter_url)

    title_tag = soup.select_one("h2") or soup.select_one("a.chr-title")
    chapter_title = title_tag.get_text(strip=True) if title_tag else None

    if not chapter_title:
        match = re.search(r"/chapter-([^/?#]+)/?", chapter_url)
        chapter_title = f"Chapter {match.group(1).replace('-', '.')}" if match else "Unknown Chapter"

    content_tag = soup.select_one("#chr-content.chr-c") or soup.select_one("#chr-content")
    if not content_tag:
        log_message(f"Failed to find chapter content for {chapter_url}", log)
        return None

    content = clean_chapter_html(content_tag)
    if not content:
        log_message(f"Warning: no readable content found for {chapter_url}", log)

    return {
        "title": chapter_title,
        "content": content,
        "next_url": get_next_chapter_url(chapter_url, soup),
    }


def scrape_novel(novel_url, chapters_to_scrape, wait_time=0, log=None):
    """
    Scrapes chapters by starting at the first chapter and following NovelBin's next links.
    """
    novel_title, novel_author, novel_soup = get_novel_info(novel_url)
    first_chapter_url = get_first_chapter_url(novel_url, novel_soup)

    if not first_chapter_url:
        log_message("Failed to find the first chapter URL.", log)
        return novel_title, novel_author, []

    scrape_all = chapters_to_scrape.lower() == "all"
    chapter_limit = None

    if not scrape_all:
        try:
            chapter_limit = int(chapters_to_scrape)
        except ValueError:
            log_message("Invalid input for number of chapters. Please use a number or 'all'.", log)
            return novel_title, novel_author, []

        if chapter_limit <= 0:
            log_message("Please provide a positive number of chapters.", log)
            return novel_title, novel_author, []

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

    return novel_title, novel_author, scraped_chapters


def safe_filename(title):
    """
    Converts a novel title into a simple EPUB filename.
    """
    filename = re.sub(r"[^\w\s.-]", "", title).strip().replace(" ", "_")
    return f"{filename or 'novelbin_novel'}.epub"


def create_epub(novel_data, novel_title, novel_author, output_filename, log=None):
    """
    Creates an EPUB file from the scraped novel data.
    """
    log_message(f"\nCreating EPUB file: {output_filename}...", log)
    book = epub.EpubBook()

    book.set_identifier(novel_title.replace(" ", "_").lower())
    book.set_title(novel_title)
    book.set_language("en")
    book.add_author(novel_author)

    chapters = []
    for i, chapter_data in enumerate(novel_data):
        chapter = epub.EpubHtml(
            title=chapter_data["title"],
            file_name=f"chap_{i + 1}.xhtml",
            lang="en",
        )
        html_content = f"<h1>{escape(chapter_data['title'])}</h1>\n"
        html_content += chapter_data["content"]
        chapter.content = html_content

        book.add_item(chapter)
        chapters.append(chapter)

    book.toc = tuple(chapters)
    book.spine = ["nav"] + chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(output_filename, book, {})
    log_message(f"EPUB file '{output_filename}' created successfully.", log)


class ScraperGui:
    """
    Simple Tkinter UI for running the NovelBin scraper.
    """
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("NovelBin Scraper 3.5")
        self.root.geometry("720x460")
        self.root.minsize(620, 380)

        self.messages = queue.Queue()
        self.worker = None

        self.url_var = tk.StringVar()
        self.chapters_var = tk.StringVar(value="5")
        self.wait_var = tk.StringVar(value="0")
        self.output_var = tk.StringVar(value="")

        self.build()
        self.root.after(100, self.flush_messages)

    def build(self):
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)

        ttk.Label(frame, text="Novel URL").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=self.url_var).grid(
            row=0,
            column=1,
            columnspan=2,
            sticky=tk.EW,
            pady=4,
        )

        ttk.Label(frame, text="Chapters").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=self.chapters_var, width=14).grid(
            row=1,
            column=1,
            sticky=tk.W,
            pady=4,
        )
        ttk.Label(frame, text='Use a number or "all"').grid(
            row=1,
            column=2,
            sticky=tk.W,
            pady=4,
        )

        ttk.Label(frame, text="Wait seconds").grid(row=2, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=self.wait_var, width=14).grid(
            row=2,
            column=1,
            sticky=tk.W,
            pady=4,
        )

        ttk.Label(frame, text="Output folder").grid(row=3, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=self.output_var).grid(
            row=3,
            column=1,
            sticky=tk.EW,
            pady=4,
        )
        ttk.Button(frame, text="Browse", command=self.choose_output_folder).grid(
            row=3,
            column=2,
            sticky=tk.E,
            padx=(8, 0),
            pady=4,
        )

        self.start_button = ttk.Button(frame, text="Start", command=self.start_scrape)
        self.start_button.grid(row=4, column=0, sticky=tk.W, pady=(12, 8))

        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.grid(
            row=4,
            column=1,
            columnspan=2,
            sticky=tk.EW,
            pady=(12, 8),
        )

        self.log = tk.Text(frame, height=12, wrap=tk.WORD, state=tk.DISABLED)
        self.log.grid(row=5, column=0, columnspan=3, sticky=tk.NSEW)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.log.yview)
        scrollbar.grid(row=5, column=3, sticky=tk.NS)
        self.log.configure(yscrollcommand=scrollbar.set)

    def choose_output_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_var.set(folder)

    def append_log(self, message):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def flush_messages(self):
        while True:
            try:
                kind, message = self.messages.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                self.append_log(message)
            elif kind == "done":
                self.progress.stop()
                self.start_button.configure(state=tk.NORMAL)
                self.append_log(message)
                messagebox.showinfo("Done", message)
            elif kind == "error":
                self.progress.stop()
                self.start_button.configure(state=tk.NORMAL)
                self.append_log(message)
                messagebox.showerror("Error", message)

        self.root.after(100, self.flush_messages)

    def start_scrape(self):
        url = self.url_var.get().strip()
        chapters = self.chapters_var.get().strip()
        output_folder = self.output_var.get().strip()

        if not url:
            messagebox.showerror("Missing URL", "Enter a NovelBin novel URL.")
            return

        if not chapters:
            messagebox.showerror("Missing chapters", 'Enter a chapter count or "all".')
            return

        try:
            wait_time = float(self.wait_var.get().strip() or "0")
        except ValueError:
            messagebox.showerror("Invalid wait", "Wait seconds must be a number.")
            return

        self.start_button.configure(state=tk.DISABLED)
        self.progress.start(10)
        self.append_log("Starting scrape...")

        self.worker = threading.Thread(
            target=self.run_scrape,
            args=(url, chapters, wait_time, output_folder),
            daemon=True,
        )
        self.worker.start()

    def run_scrape(self, url, chapters, wait_time, output_folder):
        try:
            title, author, scraped_chapters = scrape_novel(
                url,
                chapters,
                wait_time=wait_time,
                log=self.queue_log,
            )

            if not scraped_chapters:
                self.messages.put(("error", "No chapters were scraped. EPUB file was not created."))
                return

            output_filename = safe_filename(title)
            if output_folder:
                output_filename = os.path.join(output_folder, output_filename)

            create_epub(
                scraped_chapters,
                title,
                author,
                output_filename,
                log=self.queue_log,
            )
            self.messages.put(("done", f"EPUB saved as {output_filename}"))
        except Exception as e:
            self.messages.put(("error", str(e)))

    def queue_log(self, message):
        self.messages.put(("log", message))

    def run(self):
        self.root.mainloop()


def run_gui():
    ScraperGui().run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape a NovelBin novel and save as EPUB.")
    parser.add_argument("novel_url", nargs="?", type=str, help="NovelBin novel URL to scrape.")
    parser.add_argument(
        "chapters_to_scrape",
        nargs="?",
        type=str,
        help='Number of chapters to scrape from the start, or "all" for all chapters.',
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=0,
        help="Seconds to wait between chapter requests. Default: 0.",
    )
    parser.add_argument("--gui", action="store_true", help="Open the simple Tkinter GUI.")
    args = parser.parse_args()

    if args.gui:
        run_gui()
        raise SystemExit

    if not args.novel_url or not args.chapters_to_scrape:
        parser.error('novel_url and chapters_to_scrape are required unless using --gui.')

    title, author, chapters = scrape_novel(
        args.novel_url,
        args.chapters_to_scrape,
        wait_time=args.wait,
    )

    if chapters:
        create_epub(chapters, title, author, safe_filename(title))
    else:
        print("\nNo chapters were scraped. EPUB file will not be created.")
