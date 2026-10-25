import json
import logging
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable

from src.client.http_client import HttpClient
from src.http.response import Response
from src.http.url import ParseError, HttpError
from .widgets import (
    BG_INPUT,
    BG_INPUT_DISABLED,
    HeaderTable,
    create_dark_text,
    highlight_syntax,
    show_error,
    status_color,
)

logger = logging.getLogger("http_gui")
HISTORY_FILE = Path("history.json")


class ClientTab(ttk.Frame):
    """Вкладка HTTP-клиента в стиле Telegram."""

    def __init__(self, parent, get_timeout_ms: Callable[[], int]):
        super().__init__(parent, padding=12)
        self.get_timeout_ms = get_timeout_ms
        self.result_queue: queue.Queue = queue.Queue()
        self._build_ui()
        self._poll_queue()

    def _build_ui(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(top, text="Метод:").pack(side=tk.LEFT)
        self.method_var = tk.StringVar(value="GET")
        self.method_combo = ttk.Combobox(
            top, textvariable=self.method_var, values=["GET", "POST"], width=8, state="readonly"
        )
        self.method_combo.pack(side=tk.LEFT, padx=6)
        self.method_combo.bind("<<ComboboxSelected>>", self._on_method_change)

        ttk.Label(top, text="URL:").pack(side=tk.LEFT)
        self.url_var = tk.StringVar(value="http://localhost:8080/")
        self.url_entry = ttk.Entry(top, textvariable=self.url_var)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        # Enter в поле URL отправляет запрос
        self.url_entry.bind("<Return>", lambda _e: self.send_request())

        self.send_btn = ttk.Button(top, text="Отправить", command=self.send_request)
        self.send_btn.pack(side=tk.LEFT, padx=4)

        self.clear_btn = ttk.Button(top, text="Очистить", command=self.clear_all)
        self.clear_btn.pack(side=tk.LEFT, padx=4)

        self.spinner_var = tk.StringVar(value="Готов")
        self.spinner_lbl = ttk.Label(top, textvariable=self.spinner_var, width=18, anchor="e", foreground="#769fc0")
        self.spinner_lbl.pack(side=tk.RIGHT, padx=6)

        # Заголовки запроса
        hdr_box = ttk.LabelFrame(self, text=" Заголовки запроса ", padding=8)
        hdr_box.pack(fill=tk.X, pady=6)
        self.header_table = HeaderTable(hdr_box)
        self.header_table.pack(fill=tk.X)

        # Тело запроса
        body_box = ttk.LabelFrame(self, text=" Тело запроса (только для POST) ", padding=8)
        body_box.pack(fill=tk.X, pady=6)
        req_frame, self.req_body_text = create_dark_text(body_box, height=4, font=("Consolas", 10))
        req_frame.pack(fill=tk.X)
        # Ctrl+Enter в теле запроса тоже отправляет запрос
        self.req_body_text.bind("<Control-Return>", lambda _e: (self.send_request(), "break")[1])
        self._on_method_change()

        # Ответ сервера
        resp_box = ttk.LabelFrame(self, text=" Ответ сервера ", padding=8)
        resp_box.pack(fill=tk.BOTH, expand=True, pady=6)

        status_bar = ttk.Frame(resp_box)
        status_bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(status_bar, text="Статус:").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="—")
        self.status_lbl = ttk.Label(
            status_bar, textvariable=self.status_var, font=("Segoe UI", 10, "bold"), foreground="#8c9fad"
        )
        self.status_lbl.pack(side=tk.LEFT, padx=8)

        paned = ttk.PanedWindow(resp_box, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        hdr_resp_frame = ttk.Frame(paned)
        ttk.Label(hdr_resp_frame, text="Заголовки ответа:").pack(anchor="w")
        hdr_text_frame, self.resp_headers_text = create_dark_text(hdr_resp_frame, height=4, font=("Consolas", 9))
        hdr_text_frame.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        paned.add(hdr_resp_frame, weight=1)

        body_resp_frame = ttk.Frame(paned)
        ttk.Label(body_resp_frame, text="Тело ответа (JSON / HTML / Текст):").pack(anchor="w")
        body_text_frame, self.resp_body_text = create_dark_text(body_resp_frame, height=8, font=("Consolas", 10))
        body_text_frame.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        paned.add(body_resp_frame, weight=3)

    def _on_method_change(self, _event=None) -> None:
        if self.method_var.get() == "POST":
            self.req_body_text.configure(state=tk.NORMAL, bg=BG_INPUT)
        else:
            self.req_body_text.configure(state=tk.DISABLED, bg=BG_INPUT_DISABLED)

    def _set_status(self, text: str, color: str) -> None:
        self.status_var.set(text)
        self.status_lbl.configure(foreground=color)

    def clear_all(self) -> None:
        self.url_var.set("")
        self.header_table.clear()
        self.req_body_text.configure(state=tk.NORMAL)
        self.req_body_text.delete("1.0", tk.END)
        self._on_method_change()
        self._set_status("—", "#8c9fad")
        self.resp_headers_text.delete("1.0", tk.END)
        self.resp_body_text.delete("1.0", tk.END)
        self.spinner_var.set("Готов")

    def send_request(self) -> None:
        # Защита от повторной отправки (Enter / Ctrl+Enter при уже идущем запросе)
        if str(self.send_btn.cget("state")) == "disabled":
            return

        url = self.url_var.get().strip()
        method = self.method_var.get().upper()
        headers = self.header_table.get_headers()
        body = ""
        if method == "POST":
            body = self.req_body_text.get("1.0", tk.END).rstrip("\n")

        self.send_btn.configure(state=tk.DISABLED)
        self.spinner_var.set("⏳ Отправка...")
        self._set_status("Ожидание...", "#769fc0")

        timeout_ms = self.get_timeout_ms()
        thread = threading.Thread(
            target=self._worker_request,
            args=(method, url, headers, body, timeout_ms),
            daemon=True,
        )
        thread.start()

    def _worker_request(
        self, method: str, url: str, headers: dict, body: str, timeout_ms: int
    ) -> None:
        start_t = time.perf_counter()
        try:
            client = HttpClient(timeout_ms=timeout_ms)
            if method == "GET":
                resp = client.get(url, headers=headers)
            else:
                ct = headers.get("Content-Type", "text/plain; charset=utf-8")
                resp = client.post(url, body=body.encode("utf-8"), content_type=ct, headers=headers)
            elapsed = round((time.perf_counter() - start_t) * 1000, 2)
            self._save_history(method, url, resp.status, elapsed)
            self.result_queue.put(("ok", resp, elapsed))
        except (ParseError, ConnectionError, TimeoutError, HttpError, ValueError) as exc:
            logger.warning("Ошибка клиентского запроса (%s %s): %s", method, url, exc)
            self.result_queue.put(("error", f"{type(exc).__name__}: {exc}", 0.0))
        except Exception as exc:
            logger.exception("Непредвиденная ошибка клиента")
            self.result_queue.put(("error", f"Ошибка: {exc}", 0.0))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload, elapsed = self.result_queue.get_nowait()
                self.send_btn.configure(state=tk.NORMAL)
                if kind == "ok":
                    resp: Response = payload
                    self.spinner_var.set(f"Готово ({elapsed} мс)")
                    self._set_status(f"{resp.status} {resp.reason}", status_color(resp.status))
                    hdr_lines = "\n".join(f"{k}: {v}" for k, v in resp.headers.items())
                    self.resp_headers_text.delete("1.0", tk.END)
                    self.resp_headers_text.insert("1.0", hdr_lines)

                    ct = ""
                    for k, v in resp.headers.items():
                        if k.lower() == "content-type":
                            ct = v
                            break
                    body_text = resp.body.decode("utf-8", errors="replace")
                    highlight_syntax(self.resp_body_text, body_text, ct)
                else:
                    self.spinner_var.set("Ошибка")
                    self._set_status("ОШИБКА", status_color(500))
                    self.resp_headers_text.delete("1.0", tk.END)
                    show_error(self.resp_body_text, str(payload))
        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll_queue)

    @staticmethod
    def _save_history(method: str, url: str, status: int, elapsed_ms: float) -> None:
        try:
            items = []
            if HISTORY_FILE.exists():
                items = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            items.append(
                {
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "method": method,
                    "url": url,
                    "status": status,
                    "elapsed_ms": elapsed_ms,
                }
            )
            HISTORY_FILE.write_text(json.dumps(items[-100:], indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
