"""UI smoke test: construct the full window, let it settle, auto-close."""
import faulthandler
import os
import sys
import tempfile
import tkinter as tk

faulthandler.dump_traceback_later(25, exit=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="savedeck-uitest-")
os.environ["SAVEDECK_HOME"] = TMP

from savedeck import library as lib            # noqa: E402
from savepoint.config import Config             # noqa: E402
from savepoint.engine import BackupEngine       # noqa: E402
from savedeck import theme                       # noqa: E402
from savedeck.ui.app import SaveDeckApp          # noqa: E402

lib.save_library({"games": [
    lib.new_entry("Alpha Game", source="steam",
                  launchTarget="steam://rungameid/1"),
    lib.new_entry("Beta Game", source="manual", favorite=True),
], "lastScan": None})

print("step: config+engine", flush=True)
config = Config()
engine = BackupEngine(config)
print("step: tk root", flush=True)
root = tk.Tk()
root.title("SaveDeck v1.0.0 - game library + save protection")
root.geometry("1220x800")
print("step: theme.apply", flush=True)
theme.apply(root)
theme.center_on_screen(root, 1220, 800)  # mirror main.py
print("step: SaveDeckApp", flush=True)
app = SaveDeckApp(root, config, engine)
print("step: app built", flush=True)

result = {"tiles": 0, "error": None}


def settle():
    try:
        root.update_idletasks()
        tiles = [w for w in app.inner.winfo_children()
                 if isinstance(w, tk.Frame)]
        result["tiles"] = len(tiles)
        # exercise filtering
        app.search_var.set("alpha")
        root.update_idletasks()
        filtered = len([w for w in app.inner.winfo_children()
                        if isinstance(w, tk.Frame)])
        result["filtered"] = filtered
        app.search_var.set("")
        root.update_idletasks()
        # hidden-games flow: hide a game, view it, unhide it
        app.toggle_hidden(app.lib["games"][0])
        root.update_idletasks()
        after_hide = len([w for w in app.inner.winfo_children()
                          if isinstance(w, tk.Frame)])
        app.open_hidden()  # no password set -> enters directly
        root.update_idletasks()
        hidden_view = len([w for w in app.inner.winfo_children()
                           if isinstance(w, tk.Frame)])
        pw_btn_visible = bool(app.pw_btn.winfo_manager())
        app._toggle_hidden_view()  # back to library
        root.update_idletasks()
        app.toggle_hidden(app.lib["games"][0])  # restore
        root.update_idletasks()
        result["hidden"] = (after_hide, hidden_view, pw_btn_visible)
        # window centering checks
        from savedeck.ui import dialogs
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        cx, cy = (sw - 1220) // 2, max(0, (sh - 800) // 2 - 20)
        result["main_centered"] = (abs(root.winfo_x() - cx) <= 2 and
                                   abs(root.winfo_y() - cy) <= 2)
        if os.environ.get("SD_DEBUG"):
            print(f"    debug: main x={root.winfo_x()} y={root.winfo_y()} "
                  f"w={root.winfo_width()} h={root.winfo_height()} "
                  f"screen={sw}x{sh} expected=({cx},{cy})", flush=True)
        dlg = dialogs.PasswordSetDialog(root)
        root.update()  # let the dialog map -> final size + re-center
        dw, dh = dlg.win.winfo_width(), dlg.win.winfo_height()
        # same basis center_over_parent uses: the parent's on-screen rect
        ex = root.winfo_rootx() + (root.winfo_width() - dw) // 2
        ey = root.winfo_rooty() + (root.winfo_height() - dh) // 3
        result["dlg_centered"] = (abs(dlg.win.winfo_x() - ex) <= 4 and
                                  abs(dlg.win.winfo_y() - ey) <= 4)
        if os.environ.get("SD_DEBUG"):
            print(f"    debug: dlg x={dlg.win.winfo_x()} y={dlg.win.winfo_y()} "
                  f"w={dw} h={dh} expected=({ex},{ey}) mapped="
                  f"{dlg.win.winfo_ismapped()}", flush=True)
        dlg.win.destroy()
        root.update()
        # game dialog: label/widget row alignment regression check
        gd = dialogs.GameDialog(root, app, lib.new_entry("Align Game"),
                                is_new=True)
        root.update()
        import tkinter.ttk as ttk
        aligned = True
        for f in [w for w in gd.win.winfo_children()
                  if isinstance(w, ttk.Labelframe)]:
            pos = {}
            for w in f.winfo_children():
                gi = w.grid_info()
                if gi:
                    pos[(gi["row"], gi["column"])] = w
            for (row, col) in pos:
                if col == 0 and (row, 1) not in pos:
                    aligned = False
        result["dlg_aligned"] = aligned
        gd.win.destroy()
        root.update()
    except Exception as e:
        result["error"] = str(e)
    finally:
        root.destroy()


root.after(2500, settle)
root.mainloop()
engine.stop()

ok = True
if result["error"]:
    print(f"  [FAIL] ui error: {result['error']}")
    ok = False
print(f"  [{'PASS' if result['tiles'] == 2 else 'FAIL'}] tile grid: "
      f"{result['tiles']} tiles")
print(f"  [{'PASS' if result.get('filtered') == 1 else 'FAIL'}] search filter: "
      f"{result.get('filtered')} tile(s)")
h = result.get("hidden") or (0, 0, False)
print(f"  [{'PASS' if h[0] == 1 else 'FAIL'}] hide game: {h[0]} tile(s) in library")
print(f"  [{'PASS' if h[1] == 1 else 'FAIL'}] hidden view: {h[1]} tile(s)")
print(f"  [{'PASS' if h[2] else 'FAIL'}] password button visible in hidden view")
ok = ok and h[0] == 1 and h[1] == 1 and h[2]
print(f"  [{'PASS' if result.get('main_centered') else 'FAIL'}] "
      f"main window centered on screen")
print(f"  [{'PASS' if result.get('dlg_centered') else 'FAIL'}] "
      f"dialog centered over parent")
print(f"  [{'PASS' if result.get('dlg_aligned') else 'FAIL'}] "
      f"game dialog labels aligned with widgets")
ok = (ok and result.get("main_centered") and result.get("dlg_centered")
      and result.get("dlg_aligned"))
print("UI SMOKE TEST OK" if ok and result["tiles"] == 2 else "UI SMOKE TEST FAILED")
sys.exit(0 if ok and result["tiles"] == 2 else 1)
