import argparse
import logging
import os
import re
import sqlite3
import time
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

SITE_URL = "https://swedcars.com/search/?condition=used"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
CHECK_EVERY_SECONDS = 300
DB_PATH = os.getenv("DB_PATH", "swedcars_seen.sqlite3")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("swedcars")


def db_init():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS seen (
            url TEXT PRIMARY KEY,
            title TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")


def setting_get(key, default=None):
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def setting_set(key, value):
    with sqlite3.connect(DB_PATH) as db:
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))


def telegram_api(method, payload=None, timeout=20):
    if not BOT_TOKEN:
        raise RuntimeError("Не задано TELEGRAM_BOT_TOKEN у змінних середовища")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    response = requests.post(url, json=payload or {}, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API: {data}")
    return data["result"]


def send_message(chat_id, text):
    telegram_api("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False
    })


def get_chat_id():
    # Prefer GitHub Secret in cloud; local setup can keep chat_id in SQLite.
    return TELEGRAM_CHAT_ID or setting_get("chat_id")


def poll_telegram_updates():
    """Read pending /start and /status commands once per cloud run."""
    try:
        offset = int(setting_get("telegram_offset", "0"))
        updates = telegram_api("getUpdates", {
            "offset": offset,
            "timeout": 1,
            "allowed_updates": ["message"]
        }, timeout=5)
    except Exception as exc:
        log.warning("Не вдалося прочитати команди Telegram: %s", exc)
        return

    for update in updates:
        setting_set("telegram_offset", update["update_id"] + 1)
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        command = (message.get("text") or "").strip().split()[0] if message.get("text") else ""
        if not chat_id:
            continue

        if command == "/start":
            if not TELEGRAM_CHAT_ID:
                setting_set("chat_id", chat_id)
            send_message(
                chat_id,
                "✅ SwedCars Monitor підключено!\n"
                "Перевіряю каталог кожні 5 хвилин у хмарі.\n"
                "Повідомлятиму про нові оголошення."
            )
            log.info("Telegram-чат підключено.")
        elif command == "/status":
            send_message(chat_id, "🟢 SwedCars Monitor активний у хмарі. Перевірка запланована кожні 5 хвилин.")
        elif command == "/help":
            send_message(chat_id, "Команди:\n/start — підключити сповіщення\n/status — стан моніторингу\n/help — допомога")


def fetch_page(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def find_card_container(anchor):
    node = anchor
    best = anchor
    for _ in range(7):
        if node.parent is None:
            break
        node = node.parent
        txt = " ".join(node.stripped_strings)
        if "SEK" in txt and re.search(r"\b(?:19|20)\d{2}\b", txt) and (
            re.search(r"\b(?:mile|miles|km|mil)\b", txt, re.I)
            or re.search(r"\b(?:Automatic|Manual)\b", txt, re.I)
        ):
            return node
        best = node
    return best


def parse_listing_page(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    cars = {}
    ignored = {"Home", "Cars", "Contact", "WhatsApp", "Stockholm"}

    for a in soup.find_all("a", href=True):
        title = " ".join(a.stripped_strings).strip()
        href = a.get("href", "").strip()
        if not title or title in ignored or href.startswith("#") or href.lower().startswith(("mailto:", "javascript:")):
            continue

        car_url = urljoin(page_url, href).split("#")[0]
        parsed = urlparse(car_url)
        if parsed.netloc and not parsed.netloc.endswith("swedcars.com"):
            continue
        if car_url.rstrip("/") == SITE_URL.rstrip("/"):
            continue

        card = find_card_container(a)
        card_text = " | ".join(dict.fromkeys(x.strip() for x in card.stripped_strings if x.strip()))
        if "SEK" not in card_text or not re.search(r"\b(?:19|20)\d{2}\b", card_text):
            continue

        image_url = ""
        img = card.find("img")
        if img:
            image_url = (
                img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
            )
            if not image_url and img.get("srcset"):
                image_url = img["srcset"].split(",")[0].strip().split(" ")[0]
            if image_url:
                image_url = urljoin(page_url, image_url)

        price = re.search(r"[\d\s,.]+\s*SEK", card_text, re.I)
        year = re.search(r"\b(?:19|20)\d{2}\b", card_text)
        mileage = re.search(r"\b[\d\s,.]+\s*(?:miles|mile|km|mil)\b", card_text, re.I)
        gearbox = re.search(r"\b(Automatic|Manual)\b", card_text, re.I)
        fuel = re.search(r"\b(Diesel|Petrol|Gasoline|Electric|Hybrid|Plug-in hybrid)\b", card_text, re.I)

        details = [
            f"💰 Ціна: {price.group(0).strip()}" if price else "",
            f"📅 Рік: {year.group(0)}" if year else "",
            f"🛣 Пробіг: {mileage.group(0).strip()}" if mileage else "",
            f"⚙️ КПП: {gearbox.group(0)}" if gearbox else "",
            f"⛽ Паливо: {fuel.group(0)}" if fuel else "",
        ]
        cars[car_url] = {
            "url": car_url,
            "title": title,
            "image": image_url,
            "details": "\n".join(x for x in details if x),
            "raw": card_text[:1200],
        }
    return cars


def scrape_all():
    """Follow explicit next-page links; stop at repeated URLs or a safety limit."""
    first_html = fetch_page(SITE_URL)
    cars = {}
    queue = [(SITE_URL, first_html)]
    visited = set()

    while queue and len(visited) < 20:
        page_url, html = queue.pop(0)
        if page_url in visited:
            continue
        visited.add(page_url)
        cars.update(parse_listing_page(html, page_url))
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            label = " ".join(a.stripped_strings).lower()
            rel = " ".join(a.get("rel", [])).lower()
            href = a["href"].strip()
            is_next = "next" in rel or label in {"next", "»", "›", "наступна"}
            # Also accept pagination links explicitly marked with page query parameter.
            query = parse_qs(urlparse(href).query)
            is_page_link = "page" in query or "paged" in query
            if is_next or is_page_link:
                next_url = urljoin(page_url, href)
                if next_url not in visited and all(item[0] != next_url for item in queue):
                    try:
                        queue.append((next_url, fetch_page(next_url)))
                    except Exception as exc:
                        log.warning("Не вдалося завантажити сторінку %s: %s", next_url, exc)
    return cars


def known_urls():
    with sqlite3.connect(DB_PATH) as db:
        return {row[0] for row in db.execute("SELECT url FROM seen").fetchall()}


def save_car(car):
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            "INSERT OR IGNORE INTO seen(url,title) VALUES(?,?)",
            (car["url"], car["title"])
        )


def notify_new_car(chat_id, car):
    text = (
        "🚨 НОВИЙ АВТОМОБІЛЬ НА SWEDCARS!\n\n"
        f"🚘 {car['title']}\n"
        f"{car['details']}\n\n"
        f"🔗 {car['url']}"
    )
    if car["image"]:
        try:
            telegram_api("sendPhoto", {
                "chat_id": chat_id,
                "photo": car["image"],
                "caption": text[:1000]
            })
            return
        except Exception as exc:
            log.warning("Фото не надіслалося, надсилаю текст: %s", exc)
    send_message(chat_id, text)


def run_scan():
    if not BOT_TOKEN:
        raise SystemExit("Не задано TELEGRAM_BOT_TOKEN у GitHub Secrets або .env")

    db_init()
    poll_telegram_updates()
    chat_id = get_chat_id()

    cars = scrape_all()
    log.info("Знайдено оголошень: %s", len(cars))
    existing = known_urls()

    # The existing SQLite database is retained, so the known 11 listings remain a baseline.
    # On a genuinely empty database, save the current catalogue silently as the baseline.
    if not existing:
        for car in cars.values():
            save_car(car)
        log.info("Початковий список збережено без сповіщень.")
        if chat_id:
            send_message(chat_id, f"🔎 Початкове сканування завершено. Знайдено {len(cars)} оголошень. Стежу за новими.")
        return

    new_cars = [car for url, car in cars.items() if url not in existing]
    for car in new_cars:
        save_car(car)
        if chat_id:
            notify_new_car(chat_id, car)
        log.info("Нове оголошення: %s", car["title"])

    if not new_cars:
        log.info("Нових оголошень немає.")
    else:
        log.info("Надіслано сповіщень про нові авто: %s", len(new_cars))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Виконати одне сканування (для GitHub Actions)")
    args = parser.parse_args()

    if args.once:
        run_scan()
        return

    log.info("SwedCars Monitor запущено локально. Перевірка кожні 5 хвилин.")
    while True:
        try:
            run_scan()
        except Exception as exc:
            log.exception("Помилка перевірки SwedCars: %s", exc)
            chat_id = get_chat_id()
            if chat_id:
                try:
                    send_message(chat_id, f"⚠️ Не вдалося перевірити SwedCars: {exc}")
                except Exception:
                    pass
        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
