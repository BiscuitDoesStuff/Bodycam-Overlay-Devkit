"""Setup logic for getting ClaudeBridge running in Bodycam.

Deploys the bundled ue4ss_bundle/ (if UE4SS isn't already installed) and
mod/ClaudeBridge/ into the game's Binaries/Win64, registering the mod in
mods.txt. Design rationale for what gets bundled/deployed and why: see
docs/DOCUMENTATION.md section 5.4.

Callable standalone (`python src/install_bridge.py`) or imported by overlay_app.py
to run automatically on startup.
"""
import os
import re
import shutil
import sys
import webbrowser

try:
    import winreg
except ImportError:  # not running on Windows (e.g. this file imported for a syntax check)
    winreg = None

# PyInstaller onefile builds extract bundled data (see build.bat's --add-data)
# to a temp dir exposed as sys._MEIPASS; plain `python src/install_bridge.py` runs
# use this file's own directory instead. Same pattern as game_api.py's _HERE.
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
BUNDLED_MOD = os.path.join(HERE, "mod", "ClaudeBridge")
UE4SS_BUNDLE = os.path.join(HERE, "ue4ss_bundle")
UE4SS_RELEASES_URL = "https://github.com/UE4SS-RE/RE-UE4SS/releases"

# Fallback only -- find_game_root() checks every registered Steam library
# first (see _steam_library_paths), so this short guess-list is just a safety
# net for a non-Steam copy or if that lookup fails for some reason.
CANDIDATE_ROOTS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Bodycam\Bodycam",
    r"C:\Program Files\Steam\steamapps\common\Bodycam\Bodycam",
    r"D:\SteamLibrary\steamapps\common\Bodycam\Bodycam",
    r"D:\Steam\steamapps\common\Bodycam\Bodycam",
]


def _steam_install_path():
    """Finds the Steam client's own install directory (registry first, since
    Steam itself can be installed anywhere -- falling back to the common
    default) so its library folders can be read from libraryfolders.vdf."""
    if winreg is not None:
        for hive, subkey, value_name in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    path, _ = winreg.QueryValueEx(key, value_name)
                    path = os.path.normpath(path)
                    if os.path.isdir(path):
                        return path
            except OSError:
                continue
    for guess in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        if os.path.isdir(guess):
            return guess
    return None


def _steam_library_paths():
    """Every Steam library folder (the base install plus any added under
    Steam's own Storage settings -- these can be on any drive/path), parsed
    from libraryfolders.vdf. This is what lets find_game_root() locate
    Bodycam wherever the user actually put it instead of only the handful of
    default paths in CANDIDATE_ROOTS."""
    steam = _steam_install_path()
    if steam is None:
        return []
    vdf_path = os.path.join(steam, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return [steam]
    # Only the "path" value of each library entry is needed here, so a regex
    # over quoted "path" lines is enough -- no need for a full VDF parser.
    paths = [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s*"([^"]+)"', text)]
    return list(dict.fromkeys(paths + [steam]))  # de-dup, keep order, base install always included


def find_game_root():
    for library in _steam_library_paths():
        win64 = os.path.join(library, "steamapps", "common", "Bodycam", "Bodycam", "Binaries", "Win64")
        if os.path.isdir(win64):
            return win64
    for root in CANDIDATE_ROOTS:
        win64 = os.path.join(root, "Binaries", "Win64")
        if os.path.isdir(win64):
            return win64
    return None


def has_ue4ss(win64):
    """True only for a UE4SS install that will actually work -- also checks
    for the shared UEHelpers Lua library mods require(), not just the ue4ss/
    folder's existence. See docs/DOCUMENTATION.md section 5.4 for why that
    distinction matters."""
    ue4ss_dir = os.path.join(win64, "ue4ss")
    if not os.path.isdir(ue4ss_dir):
        return False
    return os.path.isfile(os.path.join(ue4ss_dir, "Mods", "shared", "UEHelpers", "UEHelpers.lua"))


def has_claude_bridge(win64):
    return os.path.isdir(os.path.join(win64, "ue4ss", "Mods", "ClaudeBridge"))


def deploy_ue4ss_bundle(win64):
    """Copies dwmapi.dll + the ue4ss/ folder (UE4SS.dll, settings, enabler mods)
    from ue4ss_bundle/ into the game's Binaries/Win64. These are the exact files
    already installed and running on this machine, just redeployed -- nothing
    fetched fresh. Returns True if deployed, False if the bundle isn't present
    (source-only checkout that skipped the bundling step)."""
    if not os.path.isdir(UE4SS_BUNDLE):
        return False
    shutil.copy2(os.path.join(UE4SS_BUNDLE, "dwmapi.dll"), os.path.join(win64, "dwmapi.dll"))
    dest_ue4ss = os.path.join(win64, "ue4ss")
    if os.path.isdir(dest_ue4ss):
        shutil.rmtree(dest_ue4ss)
    shutil.copytree(os.path.join(UE4SS_BUNDLE, "ue4ss"), dest_ue4ss)
    return True


def install_claude_bridge(win64):
    """Copies the bundled ClaudeBridge mod in and registers it in mods.txt.
    Assumes ue4ss/ already exists -- check has_ue4ss() first."""
    mods_dir = os.path.join(win64, "ue4ss", "Mods")
    dest = os.path.join(mods_dir, "ClaudeBridge")
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(BUNDLED_MOD, dest)

    mods_txt = os.path.join(mods_dir, "mods.txt")
    line_needed = "ClaudeBridge : 1"
    content = ""
    if os.path.exists(mods_txt):
        with open(mods_txt, encoding="utf-8", errors="replace") as f:
            content = f.read()
    if "ClaudeBridge" not in content:
        with open(mods_txt, "a", encoding="utf-8") as f:
            if content and not content.endswith("\n"):
                f.write("\n")
            f.write(line_needed + "\n")
    return dest


def ensure_setup(prompt_for_path=None, on_status=None):
    """Full check used by overlay_app.py at startup. `prompt_for_path`, if given,
    is called (path = prompt_for_path()) when auto-detection fails, so a GUI can
    show its own dialog instead of blocking on input(). `on_status(msg)` is
    called with human-readable progress messages.

    Returns a dict: {ok: bool, win64: str|None, reason: str}
    reason is one of: 'ready', 'needs_ue4ss', 'not_found', 'installed_bridge'
    """
    def status(msg):
        if on_status:
            on_status(msg)

    win64 = find_game_root()
    if win64 is None and prompt_for_path:
        candidate = prompt_for_path()
        if candidate and os.path.isdir(candidate):
            win64 = candidate

    if win64 is None:
        return {"ok": False, "win64": None, "reason": "not_found"}

    if not has_ue4ss(win64):
        status(f"UE4SS not found at {win64}\\ue4ss.")
        if deploy_ue4ss_bundle(win64):
            status("Deployed the bundled UE4SS (your own previously-installed copy).")
            install_claude_bridge(win64)
            return {"ok": True, "win64": win64, "reason": "installed_ue4ss_and_bridge"}
        status("No bundled UE4SS available -- opening the official release page.")
        try:
            webbrowser.open(UE4SS_RELEASES_URL)
        except Exception:
            pass
        return {"ok": False, "win64": win64, "reason": "needs_ue4ss"}

    if not has_claude_bridge(win64):
        status("UE4SS found. Installing the ClaudeBridge mod...")
        install_claude_bridge(win64)
        return {"ok": True, "win64": win64, "reason": "installed_bridge"}

    status("ClaudeBridge already installed.")
    return {"ok": True, "win64": win64, "reason": "ready"}


def _prompt_for_path():
    print("Couldn't auto-find your Bodycam install. Checked every registered "
          "Steam library plus these common locations:")
    for r in CANDIDATE_ROOTS:
        print("  ", r)
    path = input("Paste the full path to Bodycam's Binaries\\Win64 folder: ").strip('"')
    return path if os.path.isdir(path) else None


def main():
    result = ensure_setup(prompt_for_path=_prompt_for_path, on_status=print)
    print()
    if result["reason"] == "not_found":
        print("Couldn't find or confirm your Bodycam install. Aborting.")
        sys.exit(1)
    elif result["reason"] == "needs_ue4ss":
        print("UE4SS still needs to be installed manually -- see the page that just opened.")
        print("Re-run this script once it's in place.")
        sys.exit(1)
    else:
        print("Done. Fully restart Bodycam (a new mod FOLDER needs a real restart,")
        print("Ctrl+R hot-reload only picks up changes to mods already loaded).")
        print(f"Game root used: {result['win64']}")


if __name__ == "__main__":
    main()
