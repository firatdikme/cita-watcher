"""Cita previa watcher for Registro Civil (icpplustiej).

Walks the booking flow and posts to ntfy.sh when a slot opens.
Designed to run on a ~12-min schedule (Windows Task Scheduler or GitHub Actions).
"""

import os
import random
import re
import sys
import time
import urllib.request
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ============================ CONFIG (non-sensitive) ========================
PROVINCIA_ID = os.environ.get("CITA_PROVINCIA_ID", "205")    # Barcelona
SEDE_ID      = os.environ.get("CITA_SEDE_ID", "2")           # RC Exclusivo Nº 2 Barcelona
TRAMITE_ID   = os.environ.get("CITA_TRAMITE_ID", "4142")     # Jura de nacionalidad española post 08/11/2015
DOC_TYPE     = os.environ.get("CITA_DOC_TYPE", "N.I.E.")     # N.I.E. | D.N.I. | PASAPORTE

# ============================ CONFIG (sensitive — env only) =================
DOC_NUMBER   = os.environ.get("CITA_DOC_NUMBER")
FULL_NAME    = os.environ.get("CITA_FULL_NAME")
NTFY_TOPIC   = os.environ.get("CITA_NTFY_TOPIC")

# ============================ Behaviour =====================================
HEADLESS     = os.environ.get("CITA_HEADLESS", "1") == "1"
TIMEOUT_MS   = int(os.environ.get("CITA_TIMEOUT_MS", "60000"))
JITTER_MAX_S = int(os.environ.get("CITA_JITTER_MAX_S", "90"))

START_URL       = "https://sede.administracionespublicas.gob.es/icpplustiej/citar?i=es&org=JUS-RC"
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
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            locale="es-ES",
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
            page.goto(START_URL, wait_until="networkidle", timeout=TIMEOUT_MS)

            if "429" in page.title() or "too many requests" in page.inner_text("body").lower():
                return "rate_limited"

            # Step 1 — provincia
            page.wait_for_selector("select[name=provincia]", state="visible", timeout=TIMEOUT_MS)
            page.select_option("select[name=provincia]", PROVINCIA_ID)
            page.wait_for_timeout(400)
            page.click("#btnAceptar")
            page.wait_for_url(re.compile(r"/(selectProvincia|selectSede)"), timeout=TIMEOUT_MS)

            # Step 2 — sede triggers AJAX populating tramiteGrupo[0]; pick trámite; click Aceptar
            page.wait_for_selector("select[name=sede]", state="visible", timeout=TIMEOUT_MS)
            page.select_option("select[name=sede]", SEDE_ID)
            page.wait_for_timeout(1500)
            page.select_option('select[name="tramiteGrupo[0]"]', TRAMITE_ID)
            page.wait_for_timeout(400)
            page.click("#btnAceptar")
            page.wait_for_url(re.compile(r"/acInfo"), timeout=TIMEOUT_MS)

            # Step 3 — info page; click "Presentación sin Cl@ve" (id=btnEntrar, NOT a button)
            page.click("#btnEntrar")
            page.wait_for_url(re.compile(r"/acEntrada"), timeout=TIMEOUT_MS)

            # Step 4 — identity
            radio_id = {
                "N.I.E.":    "#rdbTipoDocNie",
                "D.N.I.":    "#rdbTipoDocDni",
                "PASAPORTE": "#rdbTipoDocPas",
            }[DOC_TYPE]
            page.click(radio_id)
            page.fill("#txtIdCitado", DOC_NUMBER)
            page.fill("#txtDesCitado", FULL_NAME)
            page.locator(
                "#btnAceptar, input[type=button][value='Aceptar'], button:has-text('Aceptar')"
            ).first.click()
            page.wait_for_url(re.compile(r"/acValidarEntrada"), timeout=TIMEOUT_MS)

            # Step 5 — Solicitar Cita
            page.click("#btnEnviar")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(1500)

            # Step 6 — interpret result
            text = page.inner_text("body").lower()
            if "too many requests" in text or "429" in page.title():
                return "rate_limited"
            if page.locator("iframe[src*='recaptcha'], iframe[src*='hcaptcha']").count() > 0:
                return "captcha"
            if NO_SLOTS_MARKER in text:
                return "unavailable"
            return "available"

        except PWTimeout as e:
            return f"error:timeout:{str(e)[:140]}"
        except Exception as e:
            return f"error:{type(e).__name__}:{str(e)[:140]}"
        finally:
            browser.close()


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
            f"Trámite {TRAMITE_ID} at sede {SEDE_ID} (provincia {PROVINCIA_ID}).\n"
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
