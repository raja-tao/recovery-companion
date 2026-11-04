"""Browser smoke test: every role, every page — fails on console errors or error banners.

Run (stack up):  make ui-smoke   (uses the official Playwright container)
Screenshots are written to tests/e2e/screenshots/.
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("UI_BASE_URL", "http://frontend")
PW = os.environ.get("DEMO_PASSWORD", "Recovery#2026")
OUT = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(OUT, exist_ok=True)

ROUTES = {
    "patient@example.com": ["/patient", "/patient/checkin", "/patient/medications", "/patient/assistant?q=When%20can%20I%20drive%3F",
                            "/patient/plan", "/patient/appointments", "/patient/education", "/patient/messages",
                            "/patient/caregivers", "/patient/surveys"],
    "caregiver@example.com": ["/caregiver"],
    "nurse@example.com": ["/care-team", "/care-team/patients", "/care-team/transport", "/care-team/protocols", "/admin/analytics", "/admin/demo"],
    "doctor@example.com": ["/surgeon", "/surgeon/approvals", "/admin/documents"],
    "admin@example.com": ["/admin/analytics", "/admin/ai-agents", "/admin/integrations", "/admin/documents", "/admin/users",
                          "/admin/audit", "/admin/demo"],
}
failures = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    for email, routes in ROUTES.items():
        mobile = email.startswith("patient") or email.startswith("caregiver")
        ctx = browser.new_context(viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900})
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/login")
        page.fill("input[type=email]", email)
        page.fill("input[type=password]", PW)
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")
        role = email.split("@")[0]
        if role == "patient":  # mood question after sign-in
            dialog = page.get_by_role("dialog")
            dialog.wait_for(timeout=5000)
            page.wait_for_timeout(400)
            page.screenshot(path=os.path.join(OUT, "patient_mood_prompt.png"))
            dialog.get_by_role("button", name="Good").click()
            dialog.get_by_role("button", name="Tired").click()
            dialog.get_by_role("button", name="Share").click()
            dialog.get_by_text("Thank you for sharing").wait_for(timeout=5000)
            page.screenshot(path=os.path.join(OUT, "patient_mood_reply.png"))
            dialog.get_by_role("button", name="Continue").click()
            print("OK   patient mood prompt + personal reply")
        for r in routes:
            errors.clear()
            page.goto(BASE + r)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(600 if "assistant" not in r else 2500)
            name = f"{role}{r.split('?')[0].replace('/', '_')}.png"
            page.screenshot(path=os.path.join(OUT, name), full_page=True)
            banner = page.locator(".MuiAlert-standardError").count()
            h1 = page.locator("h1").count()
            status = "OK" if not errors and not banner and h1 else "FAIL"
            if status == "FAIL":
                failures.append((email, r, errors[:3], banner, h1))
            print(f"{status:4} {email:24} {r:40} h1={h1} errors={len(errors)} errorBanners={banner}")
        # Patient: open first worklist row etc.
        if role == "nurse":
            page.goto(BASE + "/care-team")
            page.wait_for_load_state("networkidle")
            page.locator("tbody tr").first.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(800)
            page.screenshot(path=os.path.join(OUT, "nurse_patient_detail.png"), full_page=True)
            print("OK   nurse patient detail h1=", page.locator("h1").inner_text())
            page.get_by_role("tab", name="Wellbeing").click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(600)
            page.screenshot(path=os.path.join(OUT, "nurse_patient_wellbeing.png"), full_page=True)
            print("OK   nurse patient wellbeing tab")
        ctx.close()
    browser.close()
if failures:
    print("FAILURES:", failures)
    sys.exit(1)
print("UI SMOKE PASSED")
