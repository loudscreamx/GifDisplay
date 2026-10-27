"""Прокручиваемая область: содержимое кладётся в .inner. Колесо мыши листает, когда курсор над областью."""
import tkinter as tk
from tkinter import ttk


class ScrollFrame(ttk.Frame):
    def __init__(self, parent, bg):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=bg)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.bar.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.bind_all("<MouseWheel>", self._wheel, add="+")

    def set_bg(self, color):
        self.canvas.configure(bg=color)

    def _on_scroll(self, lo, hi):
        self.bar.set(lo, hi)
        if float(lo) <= 0 and float(hi) >= 1:  # всё помещается: полоса не нужна, но место под неё остаётся
            self.bar.state(["disabled"])
        else:
            self.bar.state(["!disabled"])

    def _inside(self, widget):
        while widget is not None:
            if widget is self:
                return True
            widget = widget.master
        return False

    def _wheel(self, event):
        if not self.winfo_viewable():
            return
        w = self.winfo_containing(event.x_root, event.y_root)
        if w is None or not self._inside(w):
            return
        if w.winfo_class() in ("Treeview", "Listbox", "Text"):  # у списков своя прокрутка
            return
        lo, hi = self.canvas.yview()
        if lo <= 0 and hi >= 1:
            return
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def scroll_to_top(self):
        self.canvas.yview_moveto(0)
