import os
import json
from pathlib import Path

# Базовые пути и загрузка секретов
def _load_secrets() -> dict:
    try:
        p = Path(__file__).with_name('secrets.json')
        if p.exists():
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}

# Загруженные настройки приложения из secrets.json (секретные)
_SECRETS = _load_secrets()

# Базовые пути и загрузка настроек
def _load_settings() -> dict:
    try:
        p = Path(__file__).with_name('settings.json')
        if p.exists():
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


# Загруженные настройки приложения из settings.json (не секретные)
_SETTINGS = _load_settings()


# Вспомогательная функция получения значения: сначала secrets.json, затем переменные окружения, затем значение по умолчанию
def _get(name: str, default=None):
    if name in _SECRETS and _SECRETS.get(name) not in (None, ""):
        return _SECRETS.get(name)
    return os.getenv(name, default)


# Общие настройки OpenRouter (LLM)
API_KEY: str | None = _get("OPENROUTER_API_KEY")  # Ключ API для OpenRouter
API_BASE_URL: str = _get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")  # Базовый URL для OpenRouter
DEFAULT_MODEL: str = _get("OPENROUTER_MODEL", "qwen/qwen-2.5-72b-instruct:free")  # Модель LLM по умолчанию

# External tools
POPPLER_PATH: str = _get("POPPLER_PATH", r"D:/Program files/poppler-24.08.0/Library/bin")  # Путь к Poppler

# SMTP / Email
SMTP_SERVER: str = _get("SMTP_SERVER", "smtp.gmail.com")  # Сервер SMTP
SMTP_PORT: int = int(_get("SMTP_PORT", 465))  # Порт SMTP
SMTP_USER: str | None = _get("SMTP_USER")  # Пользователь SMTP
SMTP_PASSWORD: str | None = _get("SMTP_PASSWORD")  # Пароль SMTP
FROM_EMAIL: str | None = _get("FROM_EMAIL", SMTP_USER if SMTP_USER else None)  # Адрес отправителя

# Метаданные приложения для OpenRouter (идентификация клиента)
APP_REFERRER: str = _get("OPENROUTER_REFERRER", "https://local.parser.app")  # URL приложения/реферера
APP_TITLE: str = _get("OPENROUTER_APP_TITLE", "ParserGUI")  # Название приложения

# Параллельная обработка файлов (включить = 1/true)
PARSER_PARALLEL: bool = str(_get("PARSER_PARALLEL", "0")).strip() in ("1", "true", "True")  # Включить параллельную обработку

# Путь к шаблону отчёта (Jinja2). Можно переопределить через secrets.json или ENV.
REPORT_TEMPLATE_PATH: str = _get(
    "REPORT_TEMPLATE_PATH",
    str(Path(__file__).with_name('Шаблон отчета для Parser.md.j2')),
)

# Настройки OCR (управляют качеством и скоростью распознавания)
OCR_DPI: int = int(_get("OCR_DPI", 500))  # DPI при конвертации PDF в изображения
OCR_POOL_WORKERS: int = int(_get("OCR_POOL_WORKERS", 2))  # Число воркеров в пуле OCR
OCR_USE_PREPROCESSING: bool = str(_get("OCR_USE_PREPROCESSING", "1")).strip() in ("1", "true", "True")  # Включить предобработку изображений
OCR_MAX_WIDTH: int = int(_get("OCR_MAX_WIDTH", 2000))  # Максимальная ширина изображения для ресайза
OCR_MAX_HEIGHT: int = int(_get("OCR_MAX_HEIGHT", 2000))  # Максимальная высота изображения для ресайза
OCR_CONTRAST: float = float(_get("OCR_CONTRAST", 1.0))  # Коэффициент контрастности (1.0 = без изменений)
OCR_BRIGHTNESS: float = float(_get("OCR_BRIGHTNESS", 1.0))  # Коэффициент яркости
OCR_SHARPNESS: float = float(_get("OCR_SHARPNESS", 1.0))  # Коэффициент резкости
OCR_DENOISE: bool = str(_get("OCR_DENOISE", "0")).strip() in ("0", "false", "False")  # Шумоподавление (медианный фильтр)
OCR_LANGS: str = str(_get("OCR_LANGS", "ru,en")).strip() # Языки EasyOCR в виде строки через запятую (например, "ru,en")
OCR_DETAIL: int = int(_get("OCR_DETAIL", 0))  # Параметр detail для easyocr.readtext (0 = только текст)
OCR_PARAGRAPH: bool = str(_get("OCR_PARAGRAPH", "1")).strip() in ("1", "true", "True")  # Склеивать строки в абзацы

# Параметры приложения (не секретные), берутся из settings.json с дефолтами
TO_EMAIL_DEFAULT: str = str(_SETTINGS.get("to_email_default", "")).strip()  # Адрес получателя по умолчанию
SUBJECT_SUFFIX_PEREDELKA: str = str(_SETTINGS.get("subject_suffix_peredelka", "(#ПЕР)")).strip()  # Суффикс темы для переделки
FOLDER_PAID_LABEL: str = str(_SETTINGS.get("folder_paid_label", "Оплата")).strip()  # Метка оплаты для имени папки

# IMAP настройки для поиска писем
IMAP_SERVER: str = _get("IMAP_SERVER", "imap.gmail.com")  # IMAP сервер
IMAP_PORT: int = int(_get("IMAP_PORT", 993))  # Порт IMAP сервера
IMAP_USE_SSL: bool = str(_get("IMAP_USE_SSL", "1")).strip() in ("1", "true", "True")  # Использовать SSL
IMAP_USER: str | None = _get("IMAP_USER", SMTP_USER)  # Пользователь IMAP (по умолчанию как SMTP_USER)
IMAP_PASSWORD: str | None = _get("IMAP_PASSWORD", SMTP_PASSWORD)  # Пароль IMAP (по умолчанию как SMTP_PASSWORD)

# Настройки поиска писем
EMAIL_SEARCH_LIMIT: int = int(_get("EMAIL_SEARCH_LIMIT", 50))  # Максимум писем в результатах
EMAIL_SEARCH_DAYS: int = int(_get("EMAIL_SEARCH_DAYS", 30))  # Поиск за последние N дней
