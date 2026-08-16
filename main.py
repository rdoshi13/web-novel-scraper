import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SCRAPERS = {
    "ReadNovelFull": {
        "script": "readnovelfull.py",
        "supports_wait": False,
        "example": "https://readnovelfull.com/heaven-officials-blessing-novel.html",
    },
    "WebNovelTranslations": {
        "script": "webnoveltranslations.py",
        "supports_wait": False,
        "example": "https://webnoveltranslations.com/novel/the-reincarnated-assassin-is-a-genius-swordsman/",
    },
    "NovelBin": {
        "script": "novelbin.py",
        "supports_wait": True,
        "example": "https://novelbin.com/b/the-warriors-ballad/",
    },
    "FreeWebNovel": {
        "script": "freewebnovel.py",
        "supports_wait": True,
        "example": "https://freewebnovel.com/novel/the-primal-hunter",
    },
}

# Every scraper logs a "Scraping chapter ..." line (either "Scraping chapter
# from: <url>" or "Scraping chapter <n>: <title>") right before it fetches a
# chapter. Counting these lines gives a live, scraper-agnostic progress
# signal without needing to touch any of the scraper scripts.
CHAPTER_LOG_PREFIX = "Scraping chapter"

# Cap the log widget at this many lines, trimming from the top, so an "all
# chapters" run on a 1000+ chapter novel doesn't grow the Text widget (and
# its undo/tag bookkeeping) without bound.
MAX_LOG_LINES = 5000

# The four scrapers report the finished EPUB in one of two phrasings:
# freewebnovel.py/novelbin.py/webnoveltranslations.py print
# "EPUB file '<name>' created successfully.", while readnovelfull.py (and
# freewebnovel.py a second time, from its own final print()) uses
# "... EPUB saved as '<name>'". Match either to get the filename.
EPUB_SAVED_RE = re.compile(r"EPUB (?:file '([^']+)' created successfully|saved as '([^']+)')")

SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".web-novel-scraper.json")

PAD_S = 4
PAD_M = 8
PAD_L = 12


class FieldError(ValueError):
    """A validation error tied to a specific input field."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


def classify_log_line(line):
    """Picks a colour tag for a log line based on its content."""
    lower = line.strip().lower()
    if "error" in lower or "failed" in lower or "exited with code" in lower:
        return "error"
    if lower.startswith("warning"):
        return "warning"
    return None


class ScraperLauncher:
    STATUS_STYLES = {
        "normal": "Status.TLabel",
        "success": "StatusSuccess.TLabel",
        "error": "StatusError.TLabel",
    }

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Web Novel Scraper")

        self.messages = queue.Queue()
        self.process = None
        self.process_lock = threading.Lock()
        self.stop_requested = False
        self.worker = None
        self.is_running = False

        self.scraped_chapter_count = 0
        self.chapter_target = None
        self.run_start_time = None
        self.current_output_folder = None
        self.last_epub_path = None

        settings = self.load_settings()
        initial_site = settings.get("site")
        if initial_site not in SCRAPERS:
            initial_site = "NovelBin"

        self.site_var = tk.StringVar(value=initial_site)
        self.url_var = tk.StringVar(value=SCRAPERS[initial_site]["example"])
        self.chapter_mode_var = tk.StringVar(value="first")
        self.chapter_count_var = tk.StringVar(value="5")
        self.wait_var = tk.StringVar(value=settings.get("wait", "0"))
        self.output_var = tk.StringVar(value=settings.get("output_folder") or BASE_DIR)

        self.url_error_var = tk.StringVar(value="")
        self.chapters_error_var = tk.StringVar(value="")
        self.wait_error_var = tk.StringVar(value="")

        self.status_var = tk.StringVar(value="Ready.")
        self.progress_text_var = tk.StringVar(value="")
        self.epub_path_var = tk.StringVar(value="")
        self.auto_scroll_var = tk.BooleanVar(value=True)

        self.build_styles()
        self.build()
        self.on_site_change()
        self.on_chapter_mode_change()

        geometry = settings.get("geometry")
        if geometry:
            self.root.geometry(geometry)
        else:
            self.center_window(820, 640)
        self.root.minsize(760, 560)

        self.root.bind("<Return>", lambda _event: self.start_scrape())
        self.root.bind("<Escape>", lambda _event: self.stop_scrape())
        self.root.bind("<Command-l>", lambda _event: self.clear_log())
        self.root.bind("<Control-l>", lambda _event: self.clear_log())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.root.after(100, self.flush_messages)

    def load_settings(self):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_settings(self):
        settings = {
            "site": self.site_var.get(),
            "output_folder": self.output_var.get().strip(),
            "wait": self.wait_var.get().strip(),
            "geometry": self.root.geometry(),
        }
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(settings, f)
        except OSError:
            pass

    def on_close(self):
        self.save_settings()
        if self.process and self.process.poll() is None:
            self.stop_scrape()
        self.root.destroy()

    def build_styles(self):
        style = ttk.Style(self.root)
        style.configure("Status.TLabel", foreground="#555555")
        style.configure("StatusSuccess.TLabel", foreground="#1a7f37")
        style.configure("StatusError.TLabel", foreground="#c62828")
        style.configure("FieldError.TLabel", foreground="#c62828")
        style.configure("Field.TLabel")
        style.configure("FieldDisabled.TLabel", foreground="#999999")
        style.configure("Link.TLabel", foreground="#0645ad")

    def center_window(self, width, height):
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def build(self):
        frame = ttk.Frame(self.root, padding=PAD_L)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)

        self.build_source_section(frame).grid(
            row=0, column=0, columnspan=3, sticky=tk.EW, pady=(0, PAD_M)
        )
        self.build_chapters_section(frame).grid(
            row=1, column=0, columnspan=3, sticky=tk.EW, pady=(0, PAD_M)
        )
        self.build_output_section(frame).grid(
            row=2, column=0, columnspan=3, sticky=tk.EW, pady=(0, PAD_L)
        )

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=3, column=0, columnspan=3, sticky=tk.EW, pady=(0, PAD_S))
        button_frame.columnconfigure(2, weight=1)

        self.start_button = ttk.Button(button_frame, text="Start", command=self.start_scrape)
        self.start_button.grid(row=0, column=0, sticky=tk.W)

        self.stop_button = ttk.Button(
            button_frame,
            text="Stop",
            command=self.stop_scrape,
            state=tk.DISABLED,
        )
        self.stop_button.grid(row=0, column=1, sticky=tk.W, padx=(PAD_S, PAD_M))

        self.progress = ttk.Progressbar(button_frame, mode="indeterminate")
        self.progress.grid(row=0, column=2, sticky=tk.EW)

        info_frame = ttk.Frame(frame)
        info_frame.grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=(PAD_S, PAD_M))
        info_frame.columnconfigure(0, weight=1)

        self.status_label = ttk.Label(
            info_frame, textvariable=self.status_var, style="Status.TLabel"
        )
        self.status_label.grid(row=0, column=0, sticky=tk.W)

        self.progress_info_label = ttk.Label(
            info_frame, textvariable=self.progress_text_var, style="Field.TLabel"
        )
        self.progress_info_label.grid(row=0, column=1, sticky=tk.E)

        self.link_font = tkfont.nametofont("TkDefaultFont").copy()
        self.link_font.configure(underline=True)
        self.epub_link_label = ttk.Label(
            info_frame,
            textvariable=self.epub_path_var,
            style="Link.TLabel",
            font=self.link_font,
            cursor="pointinghand",
        )
        self.epub_link_label.grid(row=1, column=0, columnspan=2, sticky=tk.W)
        self.epub_link_label.bind("<Button-1>", self.reveal_epub)

        log_toolbar = ttk.Frame(frame)
        log_toolbar.grid(row=5, column=0, columnspan=3, sticky=tk.EW, pady=(0, PAD_S))
        log_toolbar.columnconfigure(3, weight=1)

        ttk.Button(log_toolbar, text="Copy log", command=self.copy_log).grid(
            row=0, column=0, sticky=tk.W
        )
        ttk.Button(log_toolbar, text="Save log", command=self.save_log).grid(
            row=0, column=1, sticky=tk.W, padx=(PAD_S, 0)
        )
        ttk.Button(log_toolbar, text="Clear", command=self.clear_log).grid(
            row=0, column=2, sticky=tk.W, padx=(PAD_S, 0)
        )
        ttk.Checkbutton(
            log_toolbar, text="Auto-scroll", variable=self.auto_scroll_var
        ).grid(row=0, column=4, sticky=tk.E)

        frame.rowconfigure(6, weight=1)
        self.log = tk.Text(
            frame,
            height=12,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=tkfont.nametofont("TkFixedFont"),
        )
        self.log.grid(row=6, column=0, columnspan=3, sticky=tk.NSEW)
        self.log.tag_configure("error", foreground="#c62828")
        self.log.tag_configure("warning", foreground="#b26a00")
        self.log.tag_configure("success", foreground="#1a7f37")
        self.log.tag_configure("command", foreground="#6e6e6e")

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.log.yview)
        scrollbar.grid(row=6, column=3, sticky=tk.NS)
        self.log.configure(yscrollcommand=scrollbar.set)

    def build_source_section(self, parent):
        section = ttk.LabelFrame(parent, text="Source", padding=(PAD_L, PAD_M))
        section.columnconfigure(1, weight=1)

        ttk.Label(section, text="Scraper").grid(row=0, column=0, sticky=tk.W, pady=PAD_S)
        site_combo = ttk.Combobox(
            section,
            textvariable=self.site_var,
            values=list(SCRAPERS.keys()),
            state="readonly",
        )
        site_combo.grid(row=0, column=1, columnspan=2, sticky=tk.W, pady=PAD_S)
        site_combo.bind("<<ComboboxSelected>>", self.on_site_change)

        ttk.Label(section, text="Novel URL").grid(row=1, column=0, sticky=tk.W, pady=PAD_S)
        self.url_entry = ttk.Entry(section, textvariable=self.url_var)
        self.url_entry.grid(row=1, column=1, columnspan=2, sticky=tk.EW, pady=PAD_S)

        ttk.Label(section, textvariable=self.url_error_var, style="FieldError.TLabel").grid(
            row=2, column=1, columnspan=2, sticky=tk.W
        )

        return section

    def build_chapters_section(self, parent):
        section = ttk.LabelFrame(parent, text="Chapters", padding=(PAD_L, PAD_M))
        section.columnconfigure(2, weight=1)

        ttk.Radiobutton(
            section,
            text="All chapters",
            variable=self.chapter_mode_var,
            value="all",
            command=self.on_chapter_mode_change,
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=PAD_S)

        ttk.Radiobutton(
            section,
            text="First",
            variable=self.chapter_mode_var,
            value="first",
            command=self.on_chapter_mode_change,
        ).grid(row=1, column=0, sticky=tk.W, pady=PAD_S)

        self.chapter_count_entry = ttk.Spinbox(
            section,
            from_=1,
            to=100000,
            textvariable=self.chapter_count_var,
            width=8,
        )
        self.chapter_count_entry.grid(row=1, column=1, sticky=tk.W, padx=(PAD_S, PAD_S), pady=PAD_S)
        ttk.Label(section, text="chapters").grid(row=1, column=2, sticky=tk.W, pady=PAD_S)

        ttk.Label(section, textvariable=self.chapters_error_var, style="FieldError.TLabel").grid(
            row=2, column=0, columnspan=3, sticky=tk.W
        )

        self.wait_label = ttk.Label(section, text="Wait seconds", style="Field.TLabel")
        self.wait_label.grid(row=3, column=0, sticky=tk.W, pady=PAD_S)
        self.wait_entry = ttk.Entry(section, textvariable=self.wait_var, width=10)
        self.wait_entry.grid(row=3, column=1, sticky=tk.W, pady=PAD_S)
        ttk.Label(section, text="between chapter requests").grid(
            row=3, column=2, sticky=tk.W, pady=PAD_S
        )

        ttk.Label(section, textvariable=self.wait_error_var, style="FieldError.TLabel").grid(
            row=4, column=0, columnspan=3, sticky=tk.W
        )

        return section

    def build_output_section(self, parent):
        section = ttk.LabelFrame(parent, text="Output", padding=(PAD_L, PAD_M))
        section.columnconfigure(1, weight=1)

        ttk.Label(section, text="Folder").grid(row=0, column=0, sticky=tk.W, pady=PAD_S)
        ttk.Entry(section, textvariable=self.output_var).grid(
            row=0, column=1, sticky=tk.EW, pady=PAD_S
        )
        ttk.Button(section, text="Browse", command=self.choose_output_folder).grid(
            row=0, column=2, sticky=tk.E, padx=(PAD_M, 0), pady=PAD_S
        )
        ttk.Button(section, text="Open", command=self.open_output_folder).grid(
            row=0, column=3, sticky=tk.E, padx=(PAD_S, 0), pady=PAD_S
        )

        return section

    def on_site_change(self, *_):
        config = SCRAPERS[self.site_var.get()]

        current_url = self.url_var.get().strip()
        known_examples = {c["example"] for c in SCRAPERS.values()}
        if not current_url or current_url in known_examples:
            self.url_var.set(config["example"])

        supports_wait = config["supports_wait"]
        state = tk.NORMAL if supports_wait else tk.DISABLED
        style = "Field.TLabel" if supports_wait else "FieldDisabled.TLabel"
        self.wait_entry.configure(state=state)
        self.wait_label.configure(style=style)
        if not supports_wait:
            self.wait_error_var.set("")

    def on_chapter_mode_change(self):
        is_first = self.chapter_mode_var.get() == "first"
        self.chapter_count_entry.configure(state=tk.NORMAL if is_first else tk.DISABLED)
        if not is_first:
            self.chapters_error_var.set("")

    def choose_output_folder(self):
        folder = filedialog.askdirectory(initialdir=self.output_var.get() or BASE_DIR)
        if folder:
            self.output_var.set(folder)

    def open_output_folder(self):
        folder = self.output_var.get().strip() or BASE_DIR
        if not os.path.isdir(folder):
            messagebox.showerror("Folder not found", f"{folder} does not exist.")
            return
        self._reveal_path(folder, select=False)

    def reveal_epub(self, _event=None):
        if not self.last_epub_path or not os.path.exists(self.last_epub_path):
            return
        self._reveal_path(self.last_epub_path, select=True)

    def _reveal_path(self, path, select):
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", "-R", path] if select else ["open", path], check=False)
            elif sys.platform.startswith("win"):
                if select:
                    subprocess.run(["explorer", "/select,", path], check=False)
                else:
                    os.startfile(path)
            else:
                subprocess.run(["xdg-open", os.path.dirname(path) if select else path], check=False)
        except OSError as e:
            messagebox.showerror("Couldn't open", str(e))

    def append_log(self, message, tag=None):
        self.append_log_segments([(message, tag)])

    def append_log_segments(self, segments):
        """Inserts (text, tag_or_None) pairs in a single Text.insert() call."""
        if not segments:
            return

        at_bottom = self._is_log_at_bottom()

        self.log.configure(state=tk.NORMAL)
        for text, tag in segments:
            if not text.endswith("\n"):
                text += "\n"
            if tag:
                self.log.insert(tk.END, text, tag)
            else:
                self.log.insert(tk.END, text)

        self._trim_log()

        if self.auto_scroll_var.get() and at_bottom:
            self.log.see(tk.END)

        self.log.configure(state=tk.DISABLED)

    def _is_log_at_bottom(self):
        _, bottom = self.log.yview()
        return bottom >= 0.999

    def _trim_log(self):
        line_count = int(self.log.index("end-1c").split(".")[0])
        excess = line_count - MAX_LOG_LINES
        if excess > 0:
            self.log.delete("1.0", f"{excess + 1}.0")

    def copy_log(self):
        content = self.log.get("1.0", tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(content)

    def clear_log(self):
        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)

    def save_log(self):
        initial_dir = self.output_var.get().strip() or BASE_DIR
        path = filedialog.asksaveasfilename(
            initialdir=initial_dir,
            initialfile=f"{self.site_var.get()}_scrape.log",
            defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log.get("1.0", tk.END))
        except OSError as e:
            messagebox.showerror("Save failed", str(e))
            return

        self.set_status(f"Log saved to {path}", "success")

    def set_status(self, message, kind="normal"):
        self.status_var.set(message)
        self.status_label.configure(style=self.STATUS_STYLES.get(kind, "Status.TLabel"))

    def update_progress_label(self):
        elapsed = int(time.time() - self.run_start_time) if self.run_start_time else 0
        minutes, seconds = divmod(elapsed, 60)

        if self.chapter_target:
            self.progress["value"] = min(self.scraped_chapter_count, self.chapter_target)
            chapters_part = f"Chapter {self.scraped_chapter_count} / {self.chapter_target}"
        elif self.scraped_chapter_count:
            chapters_part = f"Chapter {self.scraped_chapter_count} scraped"
        else:
            chapters_part = "Starting..."

        self.progress_text_var.set(f"{chapters_part}   {minutes:02d}:{seconds:02d}")

    # Cap how many queued messages a single flush_messages() tick will drain.
    # A buffered subprocess can dump thousands of lines into the queue at
    # once when it finally flushes; inserting them all in one Tk callback
    # would freeze the UI for that whole burst. Draining in bounded chunks
    # (one chunk per 100ms tick) keeps the event loop responsive instead.
    MAX_MESSAGES_PER_TICK = 200

    def flush_messages(self):
        segments = []

        def flush_batch():
            if segments:
                self.append_log_segments(segments)
                segments.clear()

        for _ in range(self.MAX_MESSAGES_PER_TICK):
            try:
                kind, message = self.messages.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                segments.append((message, classify_log_line(message)))
                if message.lstrip().startswith(CHAPTER_LOG_PREFIX):
                    self.scraped_chapter_count += 1
                epub_match = EPUB_SAVED_RE.search(message)
                if epub_match and self.current_output_folder:
                    filename = epub_match.group(1) or epub_match.group(2)
                    self.last_epub_path = os.path.join(self.current_output_folder, filename)
                    self.epub_path_var.set(f"Open {filename}")
            elif kind == "done":
                flush_batch()
                self.set_running(False)
                self.append_log(message, tag="success")
                self.set_status(message, "success")
            elif kind == "error":
                flush_batch()
                self.set_running(False)
                self.append_log(message, tag="error")
                self.set_status(message, "error")
                messagebox.showerror("Error", message)

        flush_batch()
        if self.is_running:
            self.update_progress_label()
        self.root.after(100, self.flush_messages)

    def set_running(self, running):
        self.is_running = running
        if running:
            self.start_button.configure(state=tk.DISABLED)
            self.stop_button.configure(state=tk.NORMAL)
            if self.progress.cget("mode") == "indeterminate":
                self.progress.start(10)
        else:
            self.progress.stop()
            self.start_button.configure(state=tk.NORMAL)
            self.stop_button.configure(state=tk.DISABLED)
            self.process = None

    def build_command(self):
        site = self.site_var.get()
        config = SCRAPERS[site]
        script_path = os.path.join(BASE_DIR, config["script"])

        if not os.path.exists(script_path):
            raise FileNotFoundError(f"Could not find {config['script']}")

        url = self.url_var.get().strip()
        if not url:
            raise FieldError("url", "Enter a novel URL.")

        if self.chapter_mode_var.get() == "all":
            chapters = "all"
        else:
            chapters_raw = self.chapter_count_var.get().strip()
            if not chapters_raw:
                raise FieldError("chapters", "Enter a chapter count.")
            try:
                count = int(chapters_raw)
            except ValueError:
                raise FieldError("chapters", "Chapter count must be a whole number.")
            if count <= 0:
                raise FieldError("chapters", "Chapter count must be positive.")
            chapters = str(count)

        command = [sys.executable, script_path, url]

        if site == "ReadNovelFull":
            if chapters == "all":
                command.append("--all")
            else:
                command.extend(["--limit", chapters])
        else:
            command.append(chapters)

        if config["supports_wait"]:
            wait_raw = self.wait_var.get().strip() or "0"
            try:
                wait = float(wait_raw)
            except ValueError:
                raise FieldError("wait", "Wait seconds must be a number.")
            if wait < 0:
                raise FieldError("wait", "Wait seconds can't be negative.")
            command.extend(["--wait", str(wait)])

        return command

    def clear_field_errors(self):
        self.url_error_var.set("")
        self.chapters_error_var.set("")
        self.wait_error_var.set("")

    def show_field_error(self, field, message):
        error_vars = {
            "url": self.url_error_var,
            "chapters": self.chapters_error_var,
            "wait": self.wait_error_var,
        }
        focus_widgets = {
            "url": self.url_entry,
            "chapters": self.chapter_count_entry,
            "wait": self.wait_entry,
        }

        error_var = error_vars.get(field)
        if error_var is not None:
            error_var.set(message)

        self.set_status(message, "error")

        widget = focus_widgets.get(field)
        if widget is not None:
            widget.focus_set()

    def start_scrape(self):
        if self.is_running:
            return

        self.clear_field_errors()

        try:
            command = self.build_command()
        except FieldError as e:
            self.show_field_error(e.field, str(e))
            return
        except FileNotFoundError as e:
            messagebox.showerror("Missing scraper", str(e))
            return

        output_folder = self.output_var.get().strip() or BASE_DIR
        os.makedirs(output_folder, exist_ok=True)

        self.stop_requested = False
        self.scraped_chapter_count = 0
        self.run_start_time = time.time()
        self.current_output_folder = output_folder
        self.last_epub_path = None
        self.epub_path_var.set("")
        self.chapter_target = (
            None
            if self.chapter_mode_var.get() == "all"
            else int(self.chapter_count_var.get().strip())
        )
        self.progress_text_var.set("Starting...")

        self.progress.stop()
        if self.chapter_target:
            self.progress.configure(mode="determinate", maximum=self.chapter_target, value=0)
        else:
            self.progress.configure(mode="indeterminate")

        self.set_running(True)
        self.set_status(f"Scraping {self.site_var.get()}...", "normal")
        self.append_log("$ " + " ".join(command), tag="command")
        self.append_log(f"Output folder: {output_folder}")

        self.worker = threading.Thread(
            target=self.run_command,
            args=(command, output_folder),
            daemon=True,
        )
        self.worker.start()

    def run_command(self, command, output_folder):
        try:
            # PYTHONUNBUFFERED forces the child's stdout to be line-buffered even
            # though it's writing to a pipe rather than a terminal. Without it,
            # CPython block-buffers at 8KB and the log appears to freeze until
            # the buffer fills or the process exits.
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}

            process = subprocess.Popen(
                command,
                cwd=output_folder,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )

            with self.process_lock:
                self.process = process
                if self.stop_requested:
                    process.terminate()

            for line in process.stdout:
                self.messages.put(("log", line))

            return_code = process.wait()
            if self.stop_requested:
                self.messages.put(("done", "Scraper stopped."))
            elif return_code == 0:
                self.messages.put(("done", "Scraper finished successfully."))
            else:
                self.messages.put(("error", f"Scraper exited with code {return_code}."))
        except Exception as e:
            self.messages.put(("error", str(e)))

    # How long to give a terminated process to exit on its own before
    # force-killing it.
    STOP_GRACE_MS = 3000

    def stop_scrape(self):
        with self.process_lock:
            self.stop_requested = True
            process = self.process
            if process and process.poll() is None:
                process.terminate()
                self.append_log("Stopping scraper...")
                self.root.after(self.STOP_GRACE_MS, lambda: self._force_kill_if_alive(process))
            elif process is None:
                # Start was clicked but the worker thread hasn't created the
                # process yet. run_command() checks stop_requested right after
                # Popen() returns and will terminate it immediately.
                self.append_log("Stopping scraper...")
        self.set_status("Stopping...")

    def _force_kill_if_alive(self, process):
        if process.poll() is None:
            process.kill()
            self.append_log(
                "Scraper didn't exit after being asked to stop; force-killed it.",
                tag="warning",
            )

    def run(self):
        self.root.mainloop()


def main():
    ScraperLauncher().run()


if __name__ == "__main__":
    main()
