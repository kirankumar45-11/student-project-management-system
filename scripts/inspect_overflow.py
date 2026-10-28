import sys
import time
import threading
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import uvicorn
from playwright.sync_api import sync_playwright

def main():
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=8000, log_level="warning")
    srv = uvicorn.Server(config)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    time.sleep(2)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={'width': 360, 'height': 740})
        page = context.new_page()
        page.goto('http://127.0.0.1:8000/auth/login')
        page.fill('#username', 'E2E_COORD_P5')
        page.fill('#password', 'Password123!')
        page.click("form[action='/auth/login'] button[type=submit]")
        page.wait_for_url('http://127.0.0.1:8000/dashboard')

        leaves = page.evaluate('''() => {
            const all = Array.from(document.querySelectorAll('*'));
            return all
                .filter(el => {
                    const rect = el.getBoundingClientRect();
                    const overflows = (rect.right > 361 || el.scrollWidth > 361);
                    if (!overflows) return false;
                    const childOverflows = Array.from(el.children).some(c => {
                        const cr = c.getBoundingClientRect();
                        return cr.right > 361 || c.scrollWidth > 361;
                    });
                    return !childOverflows;
                })
                .map(el => ({
                    tag: el.tagName,
                    id: el.id,
                    className: el.className,
                    rectRight: el.getBoundingClientRect().right,
                    scrollWidth: el.scrollWidth,
                    outer: el.outerHTML.substring(0, 120)
                }));
        }''')
        print(f"Leaf overflowing elements on Coordinator dashboard ({len(leaves)}):")
        for x in leaves[:15]:
            print(x)

        browser.close()

    srv.should_exit = True
    time.sleep(1)

if __name__ == "__main__":
    main()
