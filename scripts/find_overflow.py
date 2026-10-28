import uvicorn
import threading
import time
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from playwright.sync_api import sync_playwright

def find_overflow():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={'width': 360, 'height': 740})
        page = context.new_page()
        page.goto('http://127.0.0.1:8000/auth/login')
        page.fill('#username', '1SP23CS001')
        page.fill('#password', 'Demo123456!')
        page.click("form[action='/auth/login'] button[type=submit]")
        page.wait_for_url('http://127.0.0.1:8000/dashboard')

        overflowing = page.evaluate('''() => {
            const elements = document.querySelectorAll('*');
            const results = [];
            for (const el of elements) {
                const rect = el.getBoundingClientRect();
                if (rect.right > 361 || el.scrollWidth > 361) {
                    results.push({
                        tag: el.tagName,
                        id: el.id,
                        className: el.className,
                        scrollWidth: el.scrollWidth,
                        right: rect.right,
                        snippet: el.outerHTML.substring(0, 80)
                    });
                }
            }
            return results;
        }''')
        print(f"Total overflowing elements: {len(overflowing)}")
        for x in overflowing[:10]:
            print(x)
        browser.close()

if __name__ == "__main__":
    import urllib.request
    server = None
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=1):
            pass
    except Exception:
        config = uvicorn.Config("app.main:app", host="127.0.0.1", port=8000, log_level="warning")
        server = uvicorn.Server(config)
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        time.sleep(2)
    try:
        find_overflow()
    finally:
        if server:
            server.should_exit = True
