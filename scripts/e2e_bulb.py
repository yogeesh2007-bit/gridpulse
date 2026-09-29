"""End-to-end: operator UI <-> backend <-> bulb node. The node is a *firmware emulator* (same protocol and rules as
firmware/gridpulse_bulb_node), so this verifies the software layers, not the physical ESP32.

Needs the backend serving the built frontend on http://localhost:8000 (development mode: demo users).
    python scripts/e2e_bulb.py
"""
import re
import sys
import threading
import time

import httpx
from playwright.sync_api import expect, sync_playwright

BASE = "http://localhost:8000"
DEV = "bulb-e2e"
ok = True


def check(label, cond):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + label)


class Node:
    """Mirrors the firmware: relay OFF at boot, report boot/heartbeat, poll commands, button toggles locally."""

    def __init__(self):
        self.on, self.stop, self.c = False, False, httpx.Client(base_url=BASE, timeout=10)
        self.hold_until = 0.0
        self.post("boot")
        threading.Thread(target=self.loop, daemon=True).start()

    def post(self, source):
        self.c.post(f"/api/bulb/{DEV}/status", json={"bulb_on": self.on, "source": source, "rssi": -55, "firmware": "emulator"})

    def press(self):  # the physical button
        self.on = not self.on
        self.hold_until = time.time() + 2.5
        self.post("manual_button")

    def loop(self):
        beat = time.time()
        while not self.stop:
            time.sleep(1)  # (firmware polls every 3 s; faster here to keep the test short)
            if time.time() - beat >= 8:
                beat = time.time()
                self.post("heartbeat")
            want = self.c.get(f"/api/bulb/{DEV}/command").json()["bulb_on"]
            if time.time() > self.hold_until and want != self.on:
                self.on = want
                self.post("remote_command")


node = Node()
with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome", headless=True)
    p = b.new_page(viewport={"width": 1300, "height": 900})
    p.goto(f"{BASE}/signin")
    p.get_by_label("Email").fill("operator@gridpulse.local")
    p.get_by_label("Password", exact=True).fill("Operator123!")
    p.get_by_role("button", name="Sign in").click()
    p.wait_for_url("**/app/operator**")
    p.goto(f"{BASE}/app/operator?tab=hardware")
    card = p.locator(f'section:has-text("{DEV}")').locator("[data-testid=bulb-card]")
    expect(card).to_have_attribute("data-online", "true", timeout=20000)
    check("dashboard shows the node online", True)
    expect(card).to_have_attribute("data-state", "off")
    check("safe boot: bulb reported OFF", True)

    p.locator(f'section:has-text("{DEV}")').get_by_role("button", name="Turn ON").click()
    expect(card).to_have_attribute("data-state", "on", timeout=15000)
    check("remote ON from the dashboard reaches the device and is confirmed", node.on is True)
    expect(p.locator(f'section:has-text("{DEV}")').get_by_text("Remote command from the dashboard").first).to_be_visible(timeout=10000)
    check("UI labels the source as a remote command", True)

    node.press()  # someone presses the physical button
    expect(card).to_have_attribute("data-state", "off", timeout=15000)
    expect(p.locator(f'section:has-text("{DEV}")').get_by_text("Button press on the device").first).to_be_visible(timeout=10000)
    check("manual button press appears in the UI as a button press", True)
    time.sleep(4)
    check("backend did not revert the manual press", node.on is False and httpx.get(f"{BASE}/api/bulb/{DEV}/command").json()["bulb_on"] is False)

    node.stop = True  # the device goes silent
    p.screenshot(path="e2e-shots/bulb-panel.png", full_page=True)
    b.close()

print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
