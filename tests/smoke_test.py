"""Headless smoke test: core logic without showing the window."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="savedeck-test-")
os.environ["SAVEDECK_HOME"] = TMP  # isolate: never touch the real config

from savedeck import detect, launch, art, library as lib          # noqa: E402
from savedeck.engine.config import Config                                # noqa: E402
from savedeck.engine.engine import BackupEngine                          # noqa: E402
from savedeck.engine.models import Game                                  # noqa: E402

failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== library store ==")
entry = lib.new_entry("Test Game", source="steam", launchTarget="steam://rungameid/1")
lib2 = {"games": [entry], "lastScan": None}
lib.save_library(lib2)
loaded = lib.load_library()
check("save/load roundtrip", loaded["games"][0]["name"] == "Test Game")
check("home is redirected", lib.data_dir() == os.path.normpath(TMP))

print("== vdf parser ==")
vdf = '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"C:\\\\Steam"\n\t\t"apps"\n\t\t{\n\t\t\t"1245620"\t\t"12345"\n\t\t}\n\t}\n}'
data = detect.parse_vdf(vdf)
check("parse libraryfolders", data.get("libraryfolders", {}).get("0", {}).get("path") == "C:\\Steam")
acf = detect.parse_vdf('"AppState"{ "appid" "1245620" "name" "ELDEN RING" "StateFlags" "4" "installdir" "ELDEN RING" }').get("AppState") or {}
check("parse appmanifest", acf.get("name") == "ELDEN RING" and acf.get("StateFlags") == "4")

print("== launch targets ==")
try:
    launch.launch({"name": "x", "launchTarget": ""})
    check("empty target rejected", False)
except launch.LaunchError:
    check("empty target rejected", True)
check("steam url passes through", "steam://rungameid/1" in
      launch.launch_target({"launchTarget": "steam://rungameid/1"}))

print("== art ==")
p = art.placeholder_png(os.path.join(TMP, "ph.png"), (100, 150), "Half-Life")
check("placeholder generated", bool(p) and os.path.isfile(p))
from PIL import Image
img = Image.open(p)
check("placeholder size", img.size == (100, 150))

print("== engine + config ==")
config = Config()
engine = BackupEngine(config)
g = Game(name="Smoke Game", paths=[TMP], repo="", interval_minutes=60)
config.add_game(g)
check("config add/get", config.get_game(g.id) is g)
entries = [lib.new_entry("Smoke Game", **{"sp_id": g.id})]
linked = next((gg for gg in entries if config.get_game(gg.get("sp_id"))), None)
check("library<->engine link", linked is not None)
engine.stop()

print("== detector (live machine) ==")
steam = detect.detect_steam_games()
print(f"  steam games found: {len(steam)}")
if steam:
    g0 = steam[0]
    check("steam entry shape", all(k in g0 for k in ("name", "source", "launchTarget")))
gog = detect.detect_gog_games()
print(f"  gog games found: {len(gog)}")
epic = detect.detect_epic_games()
print(f"  epic games found: {len(epic)}")

print("== hidden password ==")
lib.set_hidden_password("hunter2")
check("password set", lib.hidden_password_set())
check("wrong password rejected", not lib.verify_hidden_password("wrongpw"))
check("right password accepted", lib.verify_hidden_password("hunter2"))
lib.set_hidden_password("")
check("password cleared", not lib.hidden_password_set())

print()
if failures:
    print(f"SMOKE TEST FAILED: {failures}")
    sys.exit(1)
print("SMOKE TEST OK")
