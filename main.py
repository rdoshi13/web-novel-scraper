import os
import queue
import subprocess
import sys
import threading
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


class ScraperLauncher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Web Novel Scraper")
        self.root.geometry("780x520")
        self.root.minsize(680, 430)

        self.messages = queue.Queue()
        self.process = None
        self.process_lock = threading.Lock()
        self.stop_requested = False
        self.worker = None

        self.site_var = tk.StringVar(value="NovelBin")
        self.url_var = tk.StringVar(value=SCRAPERS["NovelBin"]["example"])
        self.chapters_var = tk.StringVar(value="5")
        self.wait_var = tk.StringVar(value="0")
        self.output_var = tk.StringVar(value=BASE_DIR)

        self.build()
        self.on_site_change()
        self.root.after(100, self.flush_messages)

    def build(self):
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(6, weight=1)

        ttk.Label(frame, text="Scraper").grid(row=0, column=0, sticky=tk.W, pady=4)
        site_menu = ttk.OptionMenu(
            frame,
            self.site_var,
            self.site_var.get(),
            *SCRAPERS.keys(),
            command=lambda _: self.on_site_change(),
        )
        site_menu.grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Novel URL").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=self.url_var).grid(
            row=1,
            column=1,
            columnspan=2,
            sticky=tk.EW,
            pady=4,
        )

        ttk.Label(frame, text="Chapters").grid(row=2, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=self.chapters_var, width=16).grid(
            row=2,
            column=1,
            sticky=tk.W,
            pady=4,
        )
        ttk.Label(frame, text='Use a number or "all"').grid(
            row=2,
            column=2,
            sticky=tk.W,
            pady=4,
        )

        self.wait_label = ttk.Label(frame, text="Wait seconds")
        self.wait_label.grid(row=3, column=0, sticky=tk.W, pady=4)
        self.wait_entry = ttk.Entry(frame, textvariable=self.wait_var, width=16)
        self.wait_entry.grid(row=3, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Output folder").grid(row=4, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=self.output_var).grid(
            row=4,
            column=1,
            sticky=tk.EW,
            pady=4,
        )
        ttk.Button(frame, text="Browse", command=self.choose_output_folder).grid(
            row=4,
            column=2,
            sticky=tk.E,
            padx=(8, 0),
            pady=4,
        )

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=5, column=0, columnspan=3, sticky=tk.EW, pady=(12, 8))

        self.start_button = ttk.Button(button_frame, text="Start", command=self.start_scrape)
        self.start_button.pack(side=tk.LEFT)

        self.stop_button = ttk.Button(
            button_frame,
            text="Stop",
            command=self.stop_scrape,
            state=tk.DISABLED,
        )
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))

        self.progress = ttk.Progressbar(button_frame, mode="indeterminate")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(16, 0))

        self.log = tk.Text(frame, height=14, wrap=tk.WORD, state=tk.DISABLED)
        self.log.grid(row=6, column=0, columnspan=3, sticky=tk.NSEW)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.log.yview)
        scrollbar.grid(row=6, column=3, sticky=tk.NS)
        self.log.configure(yscrollcommand=scrollbar.set)

    def on_site_change(self):
        config = SCRAPERS[self.site_var.get()]
        self.url_var.set(config["example"])

        if config["supports_wait"]:
            self.wait_label.grid()
            self.wait_entry.grid()
        else:
            self.wait_label.grid_remove()
            self.wait_entry.grid_remove()

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
            elif kind == "done":
                flush_batch()
                self.set_running(False)
                self.append_log(message)
                messagebox.showinfo("Done", message)
            elif kind == "error":
                flush_batch()
                self.set_running(False)
                self.append_log(message)
                messagebox.showerror("Error", message)

        flush_batch()
        self.root.after(100, self.flush_messages)

    def set_running(self, running):
        if running:
            self.start_button.configure(state=tk.DISABLED)
            self.stop_button.configure(state=tk.NORMAL)
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
        chapters = self.chapters_var.get().strip()

        if not url:
            raise ValueError("Enter a novel URL.")
        if not chapters:
            raise ValueError('Enter a chapter count or "all".')

        command = [sys.executable, script_path, url]

        if site == "ReadNovelFull":
            if chapters.lower() == "all":
                command.append("--all")
            else:
                int(chapters)
                command.extend(["--limit", chapters])
        else:
            if chapters.lower() != "all":
                int(chapters)
            command.append(chapters)

        if config["supports_wait"]:
            wait = self.wait_var.get().strip() or "0"
            float(wait)
            command.extend(["--wait", wait])

        return command

    def start_scrape(self):
        try:
            command = self.build_command()
        except ValueError as e:
            messagebox.showerror("Invalid input", str(e))
            return
        except FileNotFoundError as e:
            messagebox.showerror("Missing scraper", str(e))
            return

        output_folder = self.output_var.get().strip() or BASE_DIR
        os.makedirs(output_folder, exist_ok=True)

        self.stop_requested = False
        self.set_running(True)
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

    def run(self):
        self.root.mainloop()


def main():
    ScraperLauncher().run()


if __name__ == "__main__":
    main()
