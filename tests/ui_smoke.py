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
print("UI SMOKE TEST OK" if ok and result["tiles"] == 2 else "UI SMOKE TEST FAILED")
sys.exit(0 if ok and result["tiles"] == 2 else 1)
