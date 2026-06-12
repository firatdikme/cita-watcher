"""One-off discovery for the extranjeria (icpplus) flow.

Walks: index.html (province picker) -> select Barcelona -> citar page,
then dumps every <select> (sede + tramite groups) with option values/labels.
Saves screenshots + HTML into ./debug-discover/ at each step.

Usage: python discover_tramites.py [--headful] [--province "Barcelona"]
"""

import os
import sys
from playwright.sync_api import sync_playwright

INDEX_URL = "https://icp.administracionelectronica.gob.es/icpplus/index.html"
HEADLESS = "--headful" not in sys.argv
PROVINCE = "Barcelona"
if "--province" in sys.argv:
    PROVINCE = sys.argv[sys.argv.index("--province") + 1]

OUT = "debug-discover"
os.makedirs(OUT, exist_ok=True)


def snap(page, tag):
    try:
        page.screenshot(path=f"{OUT}/{tag}.png", full_page=True, timeout=8000)
        open(f"{OUT}/{tag}.html", "w", encoding="utf-8").write(page.content())
    except Exception as e:
        print(f"[warn] snap {tag} failed: {e}", file=sys.stderr)


def dump_selects(page, label):
    print(f"\n========== SELECTS @ {label} (url={page.url}) ==========")
    selects = page.locator("select")
    n = selects.count()
    if n == 0:
        print("  (no selects found)")
        body = page.inner_text("body")
        print("  BODY (first 2000 chars):")
        print("  " + body[:2000].replace("\n", "\n  "))
        return
    for i in range(n):
        sel = selects.nth(i)
        name = sel.get_attribute("name") or sel.get_attribute("id") or f"select#{i}"
        print(f"\n--- SELECT name={name} ---")
        opts = sel.locator("option")
        for j in range(opts.count()):
            o = opts.nth(j)
            val = o.get_attribute("value")
            txt = (o.inner_text() or "").strip()
            print(f"  value={val!r}  {txt}")


with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=HEADLESS,
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx = browser.new_context(
        locale="es-ES",
        ignore_https_errors=True,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        ),
    )
    ctx.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    )
    page = ctx.new_page()
    page.set_default_timeout(60000)
    page.on("dialog", lambda d: d.accept())

    # Step 0 — province picker
    page.goto(INDEX_URL, wait_until="networkidle", timeout=60000)
    print(f"TITLE: {page.title()}")
    print(f"URL:   {page.url}")
    snap(page, "00-index")

    title = page.title().lower()
    body = page.inner_text("body").lower()
    if "403" in title or "forbidden" in body or "intrusion" in title:
        print("BLOCKED at index page. Body follows:")
        print(page.inner_text("body")[:1500])
        sys.exit(1)

    dump_selects(page, "index (province picker)")

    # Step 1 — pick province by label, submit
    prov_select = page.locator("select").first
    prov_select.select_option(label=PROVINCE)
    page.wait_for_timeout(400)
    page.locator(
        "#btnAceptar, input[type=submit], input[type=button][value*='ceptar'], button:has-text('Aceptar'), input[value*='Acceder']"
    ).first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    print(f"\nAFTER PROVINCE SUBMIT -> URL: {page.url}")
    print(f"TITLE: {page.title()}")
    snap(page, "01-citar")

    dump_selects(page, "citar (sede + tramites)")

    browser.close()
