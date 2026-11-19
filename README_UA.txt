SWEDCARS MONITOR — пакет для GitHub Actions

ЩО РОБИТЬ
- Перевіряє каталог https://swedcars.com/search/?condition=used за розкладом GitHub Actions.
- Розклад — кожні 5 хвилин (GitHub може затримувати запуски через навантаження).
- Надсилає нові оголошення в Telegram; якщо доступне фото — додає фото.
- Зберігає SQLite-базу, щоб не надсилати дублікати.
- Підтримує /start, /status та /help під час кожного запуску.

ВАЖЛИВО ПРО БЕЗПЕКУ
- Не додавайте .env і Telegram-токен до GitHub.
- Токен потрібно додати в GitHub → Settings → Secrets and variables → Actions → New repository secret.
  Name: TELEGRAM_BOT_TOKEN
  Secret: ваш НОВИЙ токен від BotFather.
  Додатково створіть Secret TELEGRAM_CHAT_ID зі своїм числовим chat_id.
- Старий токен, який потрапив на фото в листуванні, обов'язково відкличте через @BotFather (/revoke).
- У репозиторій завантажуйте лише цей пакет. У ньому немає .env та лог-файлу.

ПЕРЕНЕСЕННЯ НА GITHUB
1. Створіть репозиторій на https://github.com/new .
2. Для максимально безкоштовного використання GitHub-hosted runners зробіть репозиторій Public.
   Увага: код і база оголошень будуть видимі публічно. Токен залишиться секретом у GitHub Secrets.
3. Розпакуйте ZIP і завантажте ВСІ файли та папку .github у корінь репозиторію.
   Якщо сайт GitHub не показує приховану папку .github при виборі файлів, завантажте через GitHub Desktop або Git.
4. Відкрийте Settings → Secrets and variables → Actions → New repository secret.
5. Name: TELEGRAM_BOT_TOKEN. Secret: новий токен від BotFather. Натисніть Add secret.
6. Створіть ще один secret: TELEGRAM_CHAT_ID. Значення — ваш числовий Telegram chat_id (його можна взяти з рядка `Збережено Telegram chat_id` у локальному файлі логу/вікні CMD). Натисніть Add secret.
7. Відкрийте Actions. Якщо GitHub попросить — натисніть I understand my workflows, go ahead and enable them.
8. Виберіть workflow "SwedCars Monitor" → Run workflow для першого тесту.
9. Відкрийте запуск і перевірте, що крок "Scan SwedCars once" завершився зеленим статусом.
10. Після успішного тесту вимкніть локальну копію на ноутбуці (Ctrl+C), щоб два процеси не опитували Telegram одночасно.

БАЗА
У ZIP включено наявну SQLite-базу з 11 оголошеннями, які бот уже бачив. Chat ID не зберігається в публічній базі: для хмари він передається через GitHub Secret TELEGRAM_CHAT_ID.
Не видаляйте swedcars_seen.sqlite3 після першого завантаження: вона потрібна для захисту від повторів.
GitHub Actions комітить цю базу лише тоді, коли вона змінилася.

ОБМЕЖЕННЯ
- GitHub Actions — не повноцінний постійно ввімкнений сервер, а короткі запуски за розкладом.
- Найкоротший інтервал розкладу GitHub Actions — 5 хвилин, але фактичний запуск може запізнюватися.
- Парсер читає сторінки каталогу та посилання пагінації, які явно доступні в HTML. Якщо SwedCars змінить розмітку або приховає частину каталогу за JavaScript, парсер треба буде адаптувати.
- Фото й характеристики надсилаються лише тоді, коли вони присутні та коректно визначені на сторінці.
- Якщо GitHub-репозиторій Public не має активності 60 днів, GitHub може автоматично вимкнути scheduled workflow; періодично перевіряйте Actions.

ЛОКАЛЬНИЙ ЗАПУСК
Windows: встановіть залежності командою `python -m pip install -r requirements.txt`,
налаштуйте .env локально і запустіть `python main.py`.
Для одноразового тесту: `python main.py --once`.
