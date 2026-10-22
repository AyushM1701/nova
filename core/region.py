"""Drag a box on the screen to show Nova just that part ("turn this card into a Tailwind component")."""
import tkinter as tk


def select(root, on_done):
    """Dim the main screen and let the user drag a box. on_done((left, top, right, bottom)) in screen pixels,
    or on_done(None) for Esc or a click without a drag. Runs on the Tk thread. Returns a function that closes it
    unanswered (on_done(None)), for when the caller stops waiting."""
    # shortcut: main screen only; span every monitor (virtual screen size) if users with several ask for it
    w, h = root.winfo_screenwidth(), root.winfo_screenheight()
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.attributes("-alpha", 0.35)
    win.geometry(f"{w}x{h}+0+0")
    canvas = tk.Canvas(win, bg="black", highlightthickness=0, cursor="crosshair")
    canvas.pack(fill="both", expand=True)
    canvas.create_text(w // 2, 60, text="Drag around the part you mean.  Esc to cancel", fill="white",
                       font=("Segoe UI Semibold", 16))
    box, start = canvas.create_rectangle(0, 0, 0, 0, outline="#a9a1ff", width=3), [None]

    def finish(result):
        if win.winfo_exists():  # once only: Esc, a click or the caller's timeout, whichever comes first
            win.destroy()
            on_done(result)

    def press(e):
        start[0] = (e.x_root, e.y_root)

    def drag(e):
        if start[0]:
            canvas.coords(box, start[0][0], start[0][1], e.x_root, e.y_root)

    def release(e):
        if not start[0]:
            return finish(None)
        (x0, y0), (x1, y1) = start[0], (e.x_root, e.y_root)
        rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        finish(rect if rect[2] - rect[0] > 8 and rect[3] - rect[1] > 8 else None)

    canvas.bind("<ButtonPress-1>", press)
    canvas.bind("<B1-Motion>", drag)
    canvas.bind("<ButtonRelease-1>", release)
    win.bind("<Escape>", lambda _: finish(None))
    win.after(30, win.focus_force)  # Esc needs keyboard focus
    return lambda: finish(None)
