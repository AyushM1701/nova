"""Floating card, bottom-right: replies, approvals and Claude/Codex steps. Never takes focus (Windows)."""
import tkinter as tk

from core import system

BG, FG, DIM, ACCENT, TRACK = "#16161a", "#f2f2f2", "#a3a3ad", "#7c5cff", "#2a2a31"


class Card:
    def __init__(self, root, on_allow, on_deny):
        self.width = int(380 * root.winfo_fpixels("1i") / 96) if not system.IS_MAC else 380
        w = self.win = tk.Toplevel(root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-alpha", 0.96)
        w.configure(bg=BG)
        self.title = tk.Label(w, bg=BG, fg=FG, font=("Segoe UI Semibold", 12), anchor="w")
        self.body = tk.Label(w, bg=BG, fg=DIM, font=("Segoe UI", 10), anchor="w", justify="left",
                             wraplength=self.width - 32)
        self.buttons = tk.Frame(w, bg=BG)
        allow = "Allow  (shortcut)" if system.IS_MAC else "Allow  (hotkey)"
        for text, cmd, color in ((allow, on_allow, ACCENT), ("Deny  (Esc)", on_deny, TRACK)):
            tk.Button(self.buttons, text=text, command=cmd, bg=color, fg=FG, activebackground=color,
                      relief="flat", font=("Segoe UI", 10), padx=12, pady=4,
                      highlightbackground=BG).pack(side="left", padx=(0, 8))
        self.title.pack(fill="x", padx=16, pady=(12, 2))
        self.body.pack(fill="x", padx=16, pady=(0, 12))
        self._hide_job = None
        self.hwnd = system.no_activate(w)
        self.hide()

    def show(self, title, body="", buttons=False, hide_after=None):
        self.title.config(text=title)
        self.body.config(text=body if len(body) < 700 else body[:700] + "…")
        self.buttons.pack_forget()
        if buttons:
            self.buttons.pack(fill="x", padx=16, pady=(0, 14))
        self.win.update_idletasks()
        w, h = max(self.width, self.win.winfo_reqwidth()), self.win.winfo_reqheight()
        _, _, right, bottom = system.work_area()
        self.win.geometry(f"{w}x{h}+{int(right) - w - 24}+{int(bottom) - h - 24}")
        system.show(self.win, self.hwnd)
        self.hide_later(hide_after)

    def hide_later(self, seconds):
        if self._hide_job:
            self.win.after_cancel(self._hide_job)
            self._hide_job = None
        if seconds:
            self._hide_job = self.win.after(int(seconds * 1000), self.hide)

    def hide(self):
        system.hide(self.win, self.hwnd)
