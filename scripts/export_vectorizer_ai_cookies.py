import json
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig", override=True)


def main() -> None:
    profile_dir = BASE_DIR / ".vectorizer-ai-profile"
    output_json = BASE_DIR / ".vectorizer-ai-cookies.json"
    output_env = BASE_DIR / ".vectorizer-ai-cookies.env"

    if not profile_dir.exists():
        raise RuntimeError(f"Perfil local nao encontrado: {profile_dir}")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            accept_downloads=True,
            viewport={"width": 1280, "height": 900},
            locale="pt-BR",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://pt.vectorizer.ai/", wait_until="domcontentloaded", timeout=60_000)
            cookies = [
                cookie
                for cookie in context.cookies(
                    ["https://vectorizer.ai/", "https://pt.vectorizer.ai/"]
                )
                if "vectorizer.ai" in cookie.get("domain", "")
            ]
        finally:
            context.close()

    if not cookies:
        raise RuntimeError("Nenhum cookie do Vectorizer.AI foi encontrado no perfil local.")

    payload = {"cookies": cookies}
    compact_payload = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_env.write_text(
        "VECTORIZER_AI_COOKIES_JSON=" + compact_payload + "\n",
        encoding="utf-8",
    )

    cookie_names = ", ".join(cookie["name"] for cookie in cookies)
    print(f"Cookies exportados: {cookie_names}")
    print(f"Arquivo JSON: {output_json}")
    print(f"Arquivo para colar na Discloud: {output_env}")


if __name__ == "__main__":
    main()
