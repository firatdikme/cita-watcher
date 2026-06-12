"""Cita previa watcher for Extranjeria Barcelona (icpplustieb).

Walks the booking flow for POLICIA-CARTA DE INVITACION and posts to ntfy.sh
when a slot opens. Designed to run on a ~12-min schedule via Windows Task
Scheduler (run.bat + register_task.ps1).

NOTE: this site (icp.administracionelectronica.gob.es) blocks datacenter IPs,
so GitHub Actions cannot reach it — the watcher must run from a residential
connection. It also fronts an F5/TSPD JavaScript challenge, which the real
Chrome channel passes (the bundled Playwright Chromium does not).
"""

import os
import random
import re
import sys
import time
import urllib.request
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ============================ CONFIG (non-sensitive) ========================
START_URL  = os.environ.get(
    "CITA_START_URL",
    "https://icp.administracionelectronica.gob.es/icpplustieb/citar?p=8&locale=es",
)                                                            # Barcelona extranjeria
SEDE_ID    = os.environ.get("CITA_SEDE_ID", "99")            # 99 = Cualquier oficina
TRAMITE_ID = os.environ.get("CITA_TRAMITE_ID", "4037")       # POLICIA-CARTA DE INVITACION
DOC_TYPE   = os.environ.get("CITA_DOC_TYPE", "N.I.E.")       # N.I.E. | D.N.I. | PASAPORTE

# ============================ CONFIG (sensitive — env only) =================
DOC_NUMBER = os.environ.get("CITA_DOC_NUMBER")
FULL_NAME  = os.environ.get("CITA_FULL_NAME")
NTFY_TOPIC = os.environ.get("CITA_NTFY_TOPIC")

# ============================ Behaviour =====================================
HEADLESS     = os.environ.get("CITA_HEADLESS", "1") == "1"
CHANNEL      = os.environ.get("CITA_BROWSER_CHANNEL", "chrome")  # real Chrome passes TSPD
TIMEOUT_MS   = int(os.environ.get("CITA_TIMEOUT_MS", "60000"))
JITTER_MAX_S = int(os.environ.get("CITA_JITTER_MAX_S", "90"))

NO_SLOTS_MARKER = "no hay citas disponibles"
# ============================================================================


def notify(title: str, message: str, priority: str = "default", tags: str = "") -> None:
    if not NTFY_TOPIC:
        print("[warn] CITA_NTFY_TOPIC not set; skipping push", file=sys.stderr)
        return
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={"Title": title, "Priority": priority, "Tags": tags},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print(f"[warn] ntfy push failed: {e}", file=sys.stderr)


def check_once() -> str:
    if not DOC_NUMBER or not FULL_NAME:
        return "error:config:CITA_DOC_NUMBER and CITA_FULL_NAME must be set"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            channel=CHANNEL or None,
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
        page.set_default_timeout(TIMEOUT_MS)
        page.on("dialog", lambda d: d.accept())

        try:
            # Step 1 — citar page (oficina + tramite). The first hit serves an
            # F5/TSPD JS challenge that reloads itself, so don't trust the
            # initial load: wait for the sede select to actually appear.
            page.goto(START_URL, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            try:
                page.wait_for_selector(
                    "select[name=sede]", state="attached", timeout=TIMEOUT_MS
                )
            except PWTimeout:
                text = page.inner_text("body").lower()
                if "429" in page.title() or "too many requests" in text:
                    return "rate_limited"
                if "intrusion" in page.title().lower():
                    return "error:blocked:fortigate"
                return "error:blocked:no-form (TSPD challenge not passed?)"

            # Dismiss the cookie banner once — its overlay can swallow clicks.
            try:
                cookie_btn = page.locator("a:has-text('Acepto'), #cookie_action_close_header")
                if cookie_btn.count() > 0:
                    cookie_btn.first.click(timeout=3000)
                    page.wait_for_timeout(300)
            except Exception:
                pass

            # The selection form appears twice: on /citar and again on
            # /selectSede (the platform's confirm step). Submit both.
            for _ in range(3):
                if not re.search(r"/(citar|selectSede)", page.url):
                    break
                page.wait_for_selector("select[name=sede]", state="attached", timeout=TIMEOUT_MS)
                page.select_option("select[name=sede]", SEDE_ID)
                page.wait_for_timeout(800)
                page.select_option('select[name="tramiteGrupo[0]"]', TRAMITE_ID)
                page.wait_for_timeout(400)
                page.click("#btnAceptar")
                page.wait_for_url(
                    re.compile(r"/(selectSede|acInfo|acEntrada)"), timeout=TIMEOUT_MS
                )
                page.wait_for_timeout(800)

            if re.search(r"/(citar|selectSede)", page.url):
                return "error:stuck-on-select (form did not advance)"

            # Step 2 — info page; "Entrar" (some tramites skip straight to acEntrada)
            if "/acInfo" in page.url:
                page.click("#btnEntrar")
                page.wait_for_url(re.compile(r"/acEntrada"), timeout=TIMEOUT_MS)

            # Step 3 — identity
            radio_id = {
                "N.I.E.":    "#rdbTipoDocNie",
                "D.N.I.":    "#rdbTipoDocDni",
                "PASAPORTE": "#rdbTipoDocPas",
            }[DOC_TYPE]
            if page.locator(radio_id).count() > 0:
                page.click(radio_id)
            page.fill("#txtIdCitado", DOC_NUMBER)
            page.fill("#txtDesCitado", FULL_NAME)
            page.locator(
                "#btnAceptar, input[type=button][value='Aceptar'], button:has-text('Aceptar')"
            ).first.click()
            page.wait_for_url(re.compile(r"/acValidarEntrada"), timeout=TIMEOUT_MS)
            page.wait_for_timeout(1500)

            # Step 4 — /acValidarEntrada is either "Opciones de la cita" (slots
            # may exist: click #btnEnviar = "Solicitar Cita") or already the
            # "no hay citas" page. Handle both.
            text = page.inner_text("body").lower()
            if NO_SLOTS_MARKER in text:
                return "unavailable"
            if page.locator("#btnEnviar").count() > 0:
                page.click("#btnEnviar")
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(1500)
                text = page.inner_text("body").lower()

            # Step 5 — interpret final result
            if "too many requests" in text or "429" in page.title():
                return "rate_limited"
            if page.locator("iframe[src*='recaptcha'], iframe[src*='hcaptcha']").count() > 0:
                return "captcha"
            if NO_SLOTS_MARKER in text:
                return "unavailable"
            return "available"

        except PWTimeout as e:
            _dump_debug(page, "timeout")
            return f"error:timeout:{str(e)[:140]}"
        except Exception as e:
            _dump_debug(page, "exception")
            return f"error:{type(e).__name__}:{str(e)[:140]}"
        finally:
            browser.close()


def _dump_debug(page, tag: str) -> None:
    """On error, save screenshot + HTML to ./debug/. Each step has its own
    try/except + tight timeout so a hung page can't stall the dump itself."""
    os.makedirs("debug", exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = f"debug/{stamp}-{tag}"
    for label, fn in [
        ("screenshot", lambda: page.screenshot(path=f"{base}.png", full_page=True, timeout=8000)),
        ("html",       lambda: open(f"{base}.html", "w", encoding="utf-8").write(page.content())),
        ("url",        lambda: open(f"{base}.url.txt", "w", encoding="utf-8").write(page.url)),
    ]:
        try:
            fn()
        except Exception as e:
            print(f"[warn] debug {label} failed: {e}", file=sys.stderr)


def main() -> None:
    if JITTER_MAX_S > 0:
        time.sleep(random.randint(0, JITTER_MAX_S))

    result = check_once()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {result}")

    if result == "available":
        notify(
            "Cita available!",
            f"Slot found for {DOC_TYPE} {DOC_NUMBER}.\n"
            f"Tramite {TRAMITE_ID} at sede {SEDE_ID} (Barcelona extranjeria).\n"
            f"Book NOW: {START_URL}",
            priority="urgent",
            tags="rotating_light,calendar",
        )
    elif result == "captcha":
        notify(
            "Cita watcher: CAPTCHA",
            "The site is asking for a CAPTCHA. Pause polling and re-check manually.",
            priority="high",
            tags="warning",
        )
    # 'unavailable', 'rate_limited' and 'error:*' are silent — only logged.


if __name__ == "__main__":
    main()
