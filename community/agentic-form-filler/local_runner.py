import sys
import asyncio
import json
import base64
import os
import subprocess
from playwright.async_api import async_playwright


async def main():
    if len(sys.argv) < 2:
        return

    command = sys.argv[1]

    # --- MODE 1: Write Data ---
    if command == "write_data":
        encoded = sys.argv[2]
        decoded = base64.b64decode(encoded).decode('utf-8')
        with open("data.json", "w") as f:
            f.write(decoded)
        return

    # --- MODE 2: Background Launcher ---
    if command == "start":
        target_form = sys.argv[2] if len(sys.argv) > 2 else "form.html"
        # Detach the background browser process. creationflags is Windows-only
        # (raises ValueError on POSIX); start_new_session is the POSIX equivalent.
        popen_kwargs = (
            {"creationflags": 0x00000008}
            if sys.platform == "win32"
            else {"start_new_session": True}
        )
        subprocess.Popen([sys.executable, "local_runner.py", "start_bg", target_form], **popen_kwargs)
        print(f"Launched Playwright in background for {target_form}.")
        return

    # --- MODE 3: Background Browser Loop ---
    if command == "start_bg":
        target_form = sys.argv[2] if len(sys.argv) > 2 else "form.html"

        if os.path.exists("data.json"):
            os.remove("data.json")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()

            form_path = os.path.abspath(target_form)
            await page.goto(f"file:///{form_path}")

            while True:
                if os.path.exists("data.json"):
                    with open("data.json", "r") as f:
                        try:
                            data = json.load(f)
                        except (json.JSONDecodeError, OSError):
                            data = {}

                    inputs = await page.query_selector_all("input, textarea")
                    for input_el in inputs:
                        id_attr = await input_el.get_attribute("id") or ""
                        name_attr = await input_el.get_attribute("name") or ""
                        placeholder = await input_el.get_attribute("placeholder") or ""

                        target_str = (id_attr + " " + name_attr + " " + placeholder).lower()

                        for key, value in data.items():
                            if key.lower() in target_str:
                                await input_el.fill(str(value))
                                break

                    buttons = await page.query_selector_all("button, input[type='submit'], div[role='button']")
                    for btn in buttons:
                        text = await btn.inner_text() or await btn.get_attribute("value") or ""
                        id_attr = await btn.get_attribute("id") or ""
                        combined = (text + " " + id_attr).lower()

                        if "submit" in combined or "next" in combined or "search" in combined:
                            await btn.click()
                            break

                    os.remove("data.json")
                    break

                await asyncio.sleep(0.1)

            await asyncio.sleep(5)
            await browser.close()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
