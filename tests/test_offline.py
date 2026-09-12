"""Offline regression net for the bridge protocol + a few pure-Python parsers.
Runs with no game, no tkinter, no network -- just the local filesystem.

    python tests/test_offline.py

Plain asserts, no framework. Never imports overlay_app (tkinter + a global
hotkey) -- only bridge_client and game_api, which are pure Python.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import bridge_client as bc
import game_api as api

SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")

_FAILURES = []


def check(name, fn):
    try:
        fn()
    except Exception as e:
        _FAILURES.append(f"{name}: {e}")
        print(f"FAIL {name}: {e}")
    else:
        print(f"ok   {name}")


def _with_temp_bridge_dir():
    """Points bc's module-level paths at a throwaway directory for the
    duration of the caller's block, restoring them afterward."""
    d = tempfile.mkdtemp()
    orig = (bc._DIR, bc._REQ, bc._RESP, bc._TMP)
    bc._DIR = d
    bc._REQ = os.path.join(d, "req.txt")
    bc._RESP = os.path.join(d, "resp.txt")
    bc._TMP = os.path.join(d, "req.tmp")
    return d, orig


def _restore_bridge_dir(orig, d):
    bc._DIR, bc._REQ, bc._RESP, bc._TMP = orig
    shutil.rmtree(d, ignore_errors=True)


def test_extract_return_value():
    assert bc._extract_return_value("hi\n-- return: 42") == "42"
    assert bc._extract_return_value("just print output, no return") == "just print output, no return"
    assert bc._extract_return_value("line1\nline2\n-- return: {a=1}") == "{a=1}"


def test_fake_round_trip():
    d, orig = _with_temp_bridge_dir()
    try:
        result = {}

        def worker():
            try:
                result["body"] = bc._send("return 1", 3)
            except Exception as e:
                result["err"] = e

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        deadline = time.time() + 2
        while not os.path.exists(bc._REQ) and time.time() < deadline:
            time.sleep(0.02)
        assert os.path.exists(bc._REQ), "req.txt was never written"

        with open(bc._REQ, encoding="utf-8") as f:
            lines = f.read().split("\n", 1)
        rid = int(lines[0])
        assert rid > 10**12, f"id {rid} should be a millisecond timestamp, not a small counter"
        assert lines[1] == "return 1"

        with open(bc._TMP, "w", encoding="utf-8") as f:
            f.write(f"{rid}\nOK\nhi\n-- return: 42")
        os.replace(bc._TMP, bc._RESP)

        t.join(timeout=3)
        assert "err" not in result, f"_send raised: {result.get('err')}"
        assert bc._extract_return_value(result["body"]) == "42"
    finally:
        _restore_bridge_dir(orig, d)


def test_timeout_cleans_up_req():
    d, orig = _with_temp_bridge_dir()
    try:
        raised = False
        try:
            bc._send("x", 0.3)
        except bc.BridgeError:
            raised = True
        assert raised, "expected a BridgeError on timeout"
        assert not os.path.exists(bc._REQ), "req.txt must not survive a timeout"
    finally:
        _restore_bridge_dir(orig, d)


def test_normalize_widgets():
    legacy = {"Do Thing": "print('hi')", "Other": "return 1"}
    out = api._normalize_widgets(legacy)
    assert {w["label"] for w in out} == {"Do Thing", "Other"}
    assert all(w["widget"] == "button" and w["mode"] == "run_once" for w in out)

    current = {"widgets": [{"widget": "button", "label": "X", "code": "1", "mode": "run_once"}]}
    assert api._normalize_widgets(current) == current["widgets"]

    assert api._normalize_widgets("garbage") == []
    assert api._normalize_widgets(None) == []


def test_bundled_json_schema():
    with open(os.path.join(SRC_DIR, "maps.json"), encoding="utf-8") as f:
        maps = json.load(f)
    for name, info in maps.items():
        if name.startswith("_"):
            continue
        assert info["status"] in ("confirmed", "unconfirmed"), f"maps.json[{name}] has an unknown status"

    with open(os.path.join(SRC_DIR, "gamemodes.json"), encoding="utf-8") as f:
        gamemodes = json.load(f)
    for name, info in gamemodes.items():
        if name.startswith("_"):
            continue
        assert info["status"] in ("working", "untested", "no_content", "broken"), \
            f"gamemodes.json[{name}] has an unknown status"

    with open(os.path.join(SRC_DIR, "item_catalog.json"), encoding="utf-8") as f:
        catalog = json.load(f)
    categories = catalog["categories"]
    assert categories, "item_catalog.json has no categories"
    for cat_name, ids in categories.items():
        assert isinstance(ids, list) and all(isinstance(i, int) for i in ids), \
            f"item_catalog.json[{cat_name}] should be a list of int ids"


def test_get_live_state_nomatch():
    orig_run_lua = bc.run_lua
    bc.run_lua = lambda src, timeout=15.0: "NOMATCH"
    try:
        state = api.get_live_state()
        assert state == {"connected": True, "in_match": False}
    finally:
        bc.run_lua = orig_run_lua


def test_gvas2_round_trip():
    fixture = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "Loadout.sav")
    if not os.path.exists(fixture):
        print("skip test_gvas2_round_trip (no tests/fixtures/Loadout.sav)")
        return
    import gvas2
    d, regs, rows, L = gvas2.slots(fixture)
    assert len(L) > 0


if __name__ == "__main__":
    check("extract_return_value", test_extract_return_value)
    check("fake_round_trip", test_fake_round_trip)
    check("timeout_cleans_up_req", test_timeout_cleans_up_req)
    check("normalize_widgets", test_normalize_widgets)
    check("bundled_json_schema", test_bundled_json_schema)
    check("get_live_state_nomatch", test_get_live_state_nomatch)
    check("gvas2_round_trip", test_gvas2_round_trip)

    if _FAILURES:
        print(f"\n{len(_FAILURES)} failure(s)")
        sys.exit(1)
    print("\nall green")
