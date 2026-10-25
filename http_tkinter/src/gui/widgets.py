import json
import re
import tkinter as tk
from tkinter import ttk, simpledialog
from typing import Dict, Tuple

# Палитра (должна совпадать с app.py)
BG_INPUT = "#1e2c3a"
BG_INPUT_DISABLED = "#131a22"
FG_TEXT = "#f5f5f5"
ACCENT = "#5288c1"


class HeaderTable(ttk.Frame):
    """Таблица заголовков запроса с кнопками добавления и удаления строк."""

    def __init__(self, parent):
        super().__init__(parent)
        cols = ("name", "value")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=4)
        self.tree.heading("name", text="Имя заголовка")
        self.tree.heading("value", text="Значение")
        self.tree.column("name", width=180, anchor="w")
        self.tree.column("value", width=320, anchor="w")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5)

        ttk.Button(btn_frame, text="+ Добавить", command=self.add_row).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="- Удалить", command=self.remove_selected).pack(fill=tk.X, pady=2)

        # Delete на выбранной строке тоже удаляет её
        self.tree.bind("<Delete>", lambda _e: self.remove_selected())

    def add_row(self, name: str = "", value: str = "") -> None:
        if not name:
            name = simpledialog.askstring("Заголовок", "Имя заголовка:", parent=self) or ""
        if not name.strip():
            return
        if not value:
            value = simpledialog.askstring("Заголовок", f"Значение для '{name}':", parent=self) or ""
        self.tree.insert("", tk.END, values=(name.strip(), value.strip()))

    def remove_selected(self) -> None:
        for item in self.tree.selection():
            self.tree.delete(item)

    def clear(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

    def get_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        for item in self.tree.get_children():
            k, v = self.tree.item(item, "values")
            if k:
                headers[str(k)] = str(v)
        return headers


class LogTable(ttk.Frame):
    """Таблица логов входящих запросов на вкладке Сервера."""

    def __init__(self, parent):
        super().__init__(parent)
        cols = ("time", "method", "path", "status", "duration")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=14)
        self.tree.heading("time", text="Время")
        self.tree.heading("method", text="Метод")
        self.tree.heading("path", text="Путь")
        self.tree.heading("status", text="Статус")
        self.tree.heading("duration", text="Время (мс)")

        self.tree.column("time", width=100, anchor="center")
        self.tree.column("method", width=80, anchor="center")
        self.tree.column("path", width=280, anchor="w")
        self.tree.column("status", width=80, anchor="center")
        self.tree.column("duration", width=100, anchor="e")

        # Цветовая маркировка строк по статусу
        self.tree.tag_configure("ok", foreground="#6fcf6f")
        self.tree.tag_configure("redirect", foreground="#e5c07b")
        self.tree.tag_configure("error", foreground="#e06c75")

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def add_log(self, timestamp: str, method: str, path: str, status: int, duration_ms: float) -> None:
        tag = status_tag(status)
        self.tree.insert(
            "", tk.END, values=(timestamp, method, path, status, f"{duration_ms:.2f}"), tags=(tag,)
        )
        children = self.tree.get_children()
        if children:
            self.tree.see(children[-1])

    def clear(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)


def status_tag(status: int) -> str:
    """Возвращает имя группы статуса: ok / redirect / error."""
    if 200 <= status < 300:
        return "ok"
    if 300 <= status < 400:
        return "redirect"
    return "error"


def status_color(status: int) -> str:
    """Цвет текста статуса ответа."""
    return {"ok": "#4bb543", "redirect": "#e5c07b", "error": "#e06c75"}[status_tag(status)]


def create_dark_text(parent, height: int = 4, font=("Consolas", 10)) -> Tuple[ttk.Frame, tk.Text]:
    """Создаёт тёмное текстовое поле с вертикальным скроллбаром.

    Возвращает (контейнер, сам Text): контейнер нужно pack()'ить, с Text работать как обычно.
    """
    container = ttk.Frame(parent)
    text = tk.Text(
        container,
        height=height,
        font=font,
        bg=BG_INPUT,
        fg=FG_TEXT,
        insertbackground="#ffffff",
        selectbackground=ACCENT,
        selectforeground="#ffffff",
        bd=0,
        highlightthickness=0,
        wrap=tk.WORD,
    )
    scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=text.yview)
    text.configure(yscrollcommand=scrollbar.set)
    text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    return container, text


def _configure_tags(text_widget: tk.Text) -> None:
    """Теги подсветки, читаемые на тёмном фоне."""
    text_widget.tag_configure("json_str", foreground="#ce9178")
    text_widget.tag_configure("json_num", foreground="#b5cea8")
    text_widget.tag_configure("json_key", foreground="#7ec7ff")  # настраивается позже -> приоритетнее json_str
    text_widget.tag_configure("html_tag", foreground="#e06c75")
    text_widget.tag_configure("error_text", foreground="#ff6b6b", font=("Consolas", 10, "bold"))


def show_error(text_widget: tk.Text, message: str) -> None:
    """Показывает сообщение об ошибке красным жирным шрифтом."""
    text_widget.configure(state=tk.NORMAL)
    text_widget.delete("1.0", tk.END)
    _configure_tags(text_widget)
    text_widget.insert("1.0", message, "error_text")


def highlight_syntax(text_widget: tk.Text, content: str, content_type: str = "") -> None:
    """Форматирует и подсвечивает JSON и HTML в текстовом поле ответа."""
    text_widget.configure(state=tk.NORMAL)
    text_widget.delete("1.0", tk.END)
    _configure_tags(text_widget)

    is_json = "json" in content_type.lower() or content.strip().startswith(("{", "["))
    if is_json:
        try:
            parsed = json.loads(content)
            content = json.dumps(parsed, indent=2, ensure_ascii=False)
        except Exception:
            pass

    text_widget.insert("1.0", content)

    if is_json:
        # Значения-строки
        for match in re.finditer(r'"(?:[^"\\]|\\.)*"', content):
            text_widget.tag_add("json_str", f"1.0+{match.start()}c", f"1.0+{match.end()}c")
        # Числа, true/false/null
        for match in re.finditer(r"(?<![\w\"])-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w\"])|\b(?:true|false|null)\b", content):
            text_widget.tag_add("json_num", f"1.0+{match.start()}c", f"1.0+{match.end()}c")
        # Ключи (перекрывают подсветку строк)
        for match in re.finditer(r'"((?:[^"\\]|\\.)*)"\s*:', content):
            text_widget.tag_add("json_key", f"1.0+{match.start()}c", f"1.0+{match.end() - 1}c")
    elif "html" in content_type.lower() or "<" in content:
        for match in re.finditer(r"</?[a-zA-Z0-9][^>]*>", content):
            text_widget.tag_add("html_tag", f"1.0+{match.start()}c", f"1.0+{match.end()}c")
