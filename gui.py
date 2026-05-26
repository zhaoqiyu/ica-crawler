import csv
import math
import queue
import threading
import tkinter as tk
import warnings
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import List, Optional, Tuple

import requests
import urllib3

import db
import downloader
import scraper

warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)


def _fetch_collections_from_api():
    session = requests.Session()
    session.headers["User-Agent"] = "vads-art-crawler/1.0"
    resp = session.get(
        "https://vads.ac.uk/digital/api/search/collection/IWM"
        "/searchterm/0/field/nosort/mode/all/conn/and/order/nosort/ad/asc/page/1/maxrecs/1",
        verify=False,
        timeout=15,
    )
    cols = resp.json().get("filters", {}).get("collections", [])
    return [(c["name"], c["alias"]) for c in cols]


class CrawlerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VADS Art Collection Crawler")
        self.minsize(640, 720)

        self._stop_event = threading.Event()
        self._log_q: queue.Queue = queue.Queue()
        self._progress_q: queue.Queue = queue.Queue()
        self._crawl_thread: Optional[threading.Thread] = None
        self._collections: List[Tuple[str, str]] = []  # (name, alias)

        self._build_ui()
        self._poll_queues()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}

        # Collections
        coll_frame = ttk.LabelFrame(self, text="Collections", padding=10)
        coll_frame.pack(fill="both", expand=False, **pad)

        ttk.Button(
            coll_frame, text="Load collections from website", command=self._load_collections
        ).pack(anchor="w")

        list_frame = tk.Frame(coll_frame)
        list_frame.pack(fill="both", expand=True, pady=(5, 0))

        sb = ttk.Scrollbar(list_frame, orient="vertical")
        self._listbox = tk.Listbox(
            list_frame,
            selectmode="multiple",
            height=8,
            yscrollcommand=sb.set,
            exportselection=False,
        )
        sb.config(command=self._listbox.yview)
        self._listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        ttk.Label(coll_frame, text="Or type aliases manually (space-separated):").pack(
            anchor="w", pady=(8, 0)
        )
        self._manual_var = tk.StringVar()
        ttk.Entry(coll_frame, textvariable=self._manual_var).pack(anchor="w", fill="x")

        # Settings
        sf = ttk.LabelFrame(self, text="Settings", padding=10)
        sf.pack(fill="x", **pad)
        sf.columnconfigure(1, weight=1)

        ttk.Label(sf, text="Item limit:").grid(row=0, column=0, sticky="w", pady=3)
        lf = tk.Frame(sf)
        lf.grid(row=0, column=1, sticky="w")
        self._limit_var = tk.IntVar(value=0)
        ttk.Spinbox(lf, from_=0, to=99999, textvariable=self._limit_var, width=8).pack(side="left")
        ttk.Label(lf, text="  (0 = crawl all)", foreground="grey").pack(side="left")

        ttk.Label(sf, text="Request delay (s):").grid(row=1, column=0, sticky="w", pady=3)
        self._delay_var = tk.DoubleVar(value=0.3)
        ttk.Spinbox(
            sf, from_=0.0, to=5.0, increment=0.1,
            textvariable=self._delay_var, width=8, format="%.1f"
        ).grid(row=1, column=1, sticky="w")

        ttk.Label(sf, text="Images folder:").grid(row=2, column=0, sticky="w", pady=3)
        imgf = tk.Frame(sf)
        imgf.grid(row=2, column=1, sticky="ew")
        self._images_var = tk.StringVar(value="images")
        ttk.Entry(imgf, textvariable=self._images_var).pack(side="left", fill="x", expand=True)
        ttk.Button(imgf, text="Browse…", command=self._browse_images).pack(side="left", padx=(4, 0))

        ttk.Label(sf, text="Database file:").grid(row=3, column=0, sticky="w", pady=3)
        dbf = tk.Frame(sf)
        dbf.grid(row=3, column=1, sticky="ew")
        self._db_var = tk.StringVar(value="ica.db")
        ttk.Entry(dbf, textvariable=self._db_var).pack(side="left", fill="x", expand=True)
        ttk.Button(dbf, text="Browse…", command=self._browse_db).pack(side="left", padx=(4, 0))

        # Action buttons
        af = tk.Frame(self)
        af.pack(fill="x", **pad)
        self._start_btn = ttk.Button(af, text="▶  Start Crawl", command=self._start)
        self._start_btn.pack(side="left", padx=(0, 8))
        self._stop_btn = ttk.Button(af, text="⏹  Stop", command=self._stop, state="disabled")
        self._stop_btn.pack(side="left")

        # Progress
        pf = ttk.LabelFrame(self, text="Progress", padding=10)
        pf.pack(fill="x", **pad)
        self._progress_var = tk.DoubleVar(value=0)
        ttk.Progressbar(pf, variable=self._progress_var, maximum=100).pack(fill="x")
        self._progress_label = ttk.Label(pf, text="Ready.")
        self._progress_label.pack(anchor="w", pady=(4, 0))

        # Log
        lf2 = ttk.LabelFrame(self, text="Log", padding=10)
        lf2.pack(fill="both", expand=True, **pad)
        self._log = scrolledtext.ScrolledText(lf2, state="disabled", height=12, wrap="word")
        self._log.pack(fill="both", expand=True)

    # ── Collections loading ────────────────────────────────────────────────

    def _load_collections(self):
        self._log_append("Loading collections from website…")

        def _fetch():
            try:
                cols = _fetch_collections_from_api()
                self.after(0, lambda: self._populate_list(cols))
            except Exception as e:
                self._log_q.put(f"Failed to load collections: {e}")

        threading.Thread(target=_fetch, daemon=True).start()

    def _populate_list(self, cols: List[Tuple[str, str]]):
        self._collections = cols
        self._listbox.delete(0, tk.END)
        for name, alias in cols:
            self._listbox.insert(tk.END, f"{alias}  —  {name}")
        self._log_append(f"Loaded {len(cols)} collections.")

    # ── Browse dialogs ─────────────────────────────────────────────────────

    def _browse_images(self):
        path = filedialog.askdirectory(title="Select images folder")
        if path:
            self._images_var.set(path)

    def _browse_db(self):
        path = filedialog.asksaveasfilename(
            title="Database file",
            defaultextension=".db",
            filetypes=[("SQLite database", "*.db"), ("All files", "*.*")],
        )
        if path:
            self._db_var.set(path)

    # ── Crawl control ──────────────────────────────────────────────────────

    def _get_aliases(self) -> List[str]:
        aliases = []
        for i in self._listbox.curselection():
            _, alias = self._collections[i]
            aliases.append(alias)
        for a in self._manual_var.get().strip().upper().split():
            if a and a not in aliases:
                aliases.append(a)
        return aliases

    def _start(self):
        aliases = self._get_aliases()
        if not aliases:
            messagebox.showwarning("No collection", "Select or type at least one collection alias.")
            return

        self._stop_event.clear()
        self._start_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._progress_var.set(0)
        self._progress_label.config(text="Starting…")
        self._log_append("=" * 48)
        self._log_append(f"Crawling: {', '.join(aliases)}")

        self._crawl_thread = threading.Thread(
            target=self._run, args=(aliases,), daemon=True
        )
        self._crawl_thread.start()

    def _stop(self):
        self._stop_event.set()
        self._stop_btn.config(state="disabled")
        self._log_q.put("Stop requested — finishing current item…")

    def _run(self, aliases: List[str]):
        try:
            conn = db.init_db(self._db_var.get())
            session = requests.Session()
            session.headers["User-Agent"] = "vads-art-crawler/1.0"

            for alias in aliases:
                if self._stop_event.is_set():
                    break
                self._crawl_collection(session, conn, alias)

            conn.close()
        except Exception as e:
            self._log_q.put(f"[ERROR] {e}")
        finally:
            self.after(0, self._done)

    def _crawl_collection(self, session: requests.Session, conn, alias: str):
        alias = alias.upper()
        delay = self._delay_var.get()
        limit = self._limit_var.get()
        images_dir = self._images_var.get()
        log = self._log_q.put

        log(f"\n[{alias}] Fetching total item count…")
        _, total = scraper.search_collection(session, alias, page=1, delay=0)
        if total == 0:
            log(f"[{alias}] No items found. Check the collection alias.")
            return

        total_pages = math.ceil(total / 10)
        target = min(total, limit) if limit > 0 else total
        log(f"[{alias}] {total} items across {total_pages} pages, processing {target}.")

        processed = skipped = failed = 0

        for page_num in range(1, total_pages + 1):
            if self._stop_event.is_set():
                log(f"[{alias}] Stopped by user.")
                break

            items, _ = scraper.search_collection(session, alias, page=page_num, delay=delay)
            if not items:
                break

            for item in items:
                if self._stop_event.is_set():
                    break

                item_id = item.get("itemId") or item.get("pointer") or item.get("id")
                if item_id is None:
                    continue
                item_id = int(item_id)

                if db.item_exists(conn, alias, item_id):
                    skipped += 1
                    self._push_progress(processed + skipped, target, alias, failed)
                    continue

                try:
                    detail = scraper.fetch_item(session, alias, item_id, delay=delay)
                except Exception as e:
                    log(f"  [WARN] {alias}/{item_id}: {e}")
                    failed += 1
                    continue

                fields = detail.get("fields") or []
                metadata = {f["key"]: f.get("value") for f in fields}
                image_url = detail.get("imageUri")
                if image_url and image_url.startswith("/"):
                    image_url = "https://www.vads.ac.uk" + image_url

                image_path = downloader.download_image(
                    session, alias, item_id, images_dir, image_url
                )
                db.upsert_item(conn, alias, item_id, metadata, image_url, image_path)

                processed += 1
                title = (metadata.get("title") or f"item {item_id}").strip()
                log(f"  {processed + skipped}/{target}  {title}")
                self._push_progress(processed + skipped, target, alias, failed)

                if limit > 0 and processed >= limit:
                    break

            if limit > 0 and processed >= limit:
                break

        log(f"[{alias}] Done. processed={processed}, skipped={skipped}, failed={failed}")
        self._export_and_clear(conn, alias, log)

    def _push_progress(self, done: int, target: int, alias: str, failed: int):
        pct = min(100.0, done / target * 100) if target else 0
        self._progress_q.put((pct, f"[{alias}] {done}/{target}  (failed: {failed})"))

    @staticmethod
    def _export_and_clear(conn, alias: str, log):
        cursor = conn.execute(
            "SELECT * FROM items WHERE collection = ? ORDER BY item_id", (alias,)
        )
        columns = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        if not rows:
            log(f"[{alias}] No rows to export.")
            return
        csv_path = f"{alias}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(columns)
            csv.writer(f).writerows(rows)
        conn.execute("DELETE FROM items WHERE collection = ?", (alias,))
        conn.commit()
        log(f"[{alias}] Exported {len(rows)} rows → {csv_path}")

    # ── GUI helpers ────────────────────────────────────────────────────────

    def _done(self):
        self._start_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        self._progress_var.set(100)
        self._progress_label.config(text="Done.")
        self._log_append("\nCrawl complete.")

    def _poll_queues(self):
        while not self._log_q.empty():
            self._log_append(self._log_q.get_nowait())
        pct = label = None
        while not self._progress_q.empty():
            pct, label = self._progress_q.get_nowait()
        if pct is not None:
            self._progress_var.set(pct)
            self._progress_label.config(text=label)
        self.after(100, self._poll_queues)

    def _log_append(self, msg: str):
        self._log.configure(state="normal")
        self._log.insert(tk.END, msg + "\n")
        self._log.see(tk.END)
        self._log.configure(state="disabled")

    def _on_close(self):
        if self._crawl_thread and self._crawl_thread.is_alive():
            if messagebox.askyesno("Quit", "A crawl is running. Stop and quit?"):
                self._stop_event.set()
                self.destroy()
        else:
            self.destroy()


if __name__ == "__main__":
    CrawlerApp().mainloop()
