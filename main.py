import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


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

PAD_S = 4
PAD_M = 8
PAD_L = 12


class FieldError(ValueError):
    """A validation error tied to a specific input field."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


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

        self.site_var = tk.StringVar(value="NovelBin")
        self.url_var = tk.StringVar(value=SCRAPERS["NovelBin"]["example"])
        self.chapter_mode_var = tk.StringVar(value="first")
        self.chapter_count_var = tk.StringVar(value="5")
        self.wait_var = tk.StringVar(value="0")
        self.output_var = tk.StringVar(value=BASE_DIR)

        self.url_error_var = tk.StringVar(value="")
        self.chapters_error_var = tk.StringVar(value="")
        self.wait_error_var = tk.StringVar(value="")

        self.status_var = tk.StringVar(value="Ready.")
        self.progress_text_var = tk.StringVar(value="")

        self.build_styles()
        self.build()
        self.on_site_change()
        self.on_chapter_mode_change()
        self.center_window(820, 640)
        self.root.minsize(760, 560)
        self.root.after(100, self.flush_messages)

    def build_styles(self):
        style = ttk.Style(self.root)
        style.configure("Status.TLabel", foreground="#555555")
        style.configure("StatusSuccess.TLabel", foreground="#1a7f37")
        style.configure("StatusError.TLabel", foreground="#c62828")
        style.configure("FieldError.TLabel", foreground="#c62828")
        style.configure("Field.TLabel")
        style.configure("FieldDisabled.TLabel", foreground="#999999")

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
        frame.rowconfigure(5, weight=1)

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

        self.log = tk.Text(frame, height=12, wrap=tk.WORD, state=tk.DISABLED)
        self.log.grid(row=5, column=0, columnspan=3, sticky=tk.NSEW)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.log.yview)
        scrollbar.grid(row=5, column=3, sticky=tk.NS)
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

        return section

    def on_site_change(self, *_):
        config = SCRAPERS[self.site_var.get()]
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

    def append_log(self, message):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, message)
        if not message.endswith("\n"):
            self.log.insert(tk.END, "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

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
        batched_lines = []

        def flush_batch():
            if batched_lines:
                self.append_log("".join(batched_lines))
                batched_lines.clear()

        for _ in range(self.MAX_MESSAGES_PER_TICK):
            try:
                kind, message = self.messages.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                batched_lines.append(message)
                if message.lstrip().startswith(CHAPTER_LOG_PREFIX):
                    self.scraped_chapter_count += 1
            elif kind == "done":
                flush_batch()
                self.set_running(False)
                self.append_log(message)
                self.set_status(message, "success")
            elif kind == "error":
                flush_batch()
                self.set_running(False)
                self.append_log(message)
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
        self.append_log("$ " + " ".join(command))
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

    def stop_scrape(self):
        with self.process_lock:
            self.stop_requested = True
            if self.process and self.process.poll() is None:
                self.process.terminate()
                self.append_log("Stopping scraper...")
            elif self.process is None:
                # Start was clicked but the worker thread hasn't created the
                # process yet. run_command() checks stop_requested right after
                # Popen() returns and will terminate it immediately.
                self.append_log("Stopping scraper...")
        self.set_status("Stopping...")

    def run(self):
        self.root.mainloop()


def main():
    ScraperLauncher().run()


if __name__ == "__main__":
    main()
