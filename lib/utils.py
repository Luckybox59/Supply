"""
Упрощенные утилиты для проекта Parser.

Содержит базовые функции без избыточных абстракций.
"""

import re
import json
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
from logging_setup import get_logger

logger = get_logger(__name__)


# Основные исключения
class ParserError(Exception):
    """Базовое исключение для Parser."""
    
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.message = message
        self.original_error = original_error
    
    def __str__(self) -> str:
        result = self.message
        if self.original_error:
            result += f" (исходная ошибка: {self.original_error})"
        return result


class FileParsingError(ParserError):
    """Ошибка парсинга файла."""
    pass


class LLMError(ParserError):
    """Ошибка взаимодействия с LLM."""
    pass


class EmailError(ParserError):
    """Ошибка работы с email."""
    pass


# Утилиты для работы с проектами
def parse_project_folder(folder_path: str) -> Dict[str, str]:
    """
    Извлекает информацию о проекте из имени папки.
    
    Ожидаемый формат: (номер)Заказчик(адрес)(изделие)
    Пример: (37)Петухова(Окулова, 28-35)(Кухня)
    
    Args:
        folder_path: Путь к папке проекта
        
    Returns:
        Словарь с данными проекта
    """
    p = Path(folder_path).resolve()
    
    # Ищем проектную папку по шаблону в пути вверх от текущей
    for parent in [p] + list(p.parents):
        match = re.match(r'^\(([^)]+)\)([^()]+)\(([^)]+)\)\(([^)]+)\)$', parent.name)
        if match:
            num, zakazchik, address, izdelie = match.groups()
            logger.debug(f"Найдена проектная папка: {parent.name}")
            return {
                'номер_договора': num.strip(),
                'заказчик': zakazchik.strip(),
                'адрес': address.strip(),
                'изделие': izdelie.strip(),
                'project_dir': str(parent)
            }
    
    # Если не найдено — вернуть всё как 'не найдено'
    logger.warning(f"Проектная папка не найдена для пути: {folder_path}")
    return {
        'номер_договора': 'не найдено',
        'заказчик': 'не найдено',
        'адрес': 'не найдено',
        'изделие': 'не найдено',
        'project_dir': str(p)
    }


# Работа со словарем поставщиков
def load_supplier_replacements() -> Dict[str, str]:
    """
    Загружает словарь замен поставщиков из JSON файла.
    
    Returns:
        Словарь замен или пустой словарь при ошибке
    """
    try:
        json_path = Path(__file__).parent.parent / 'supplier_replacements.json'
        if json_path.exists():
            with open(json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            logger.warning(f"Файл словаря поставщиков не найден: {json_path}")
            return {}
    except Exception as e:
        logger.error(f"Ошибка загрузки словаря поставщиков: {e}")
        return {}


def replace_supplier_name(supplier_name: str) -> str:
    """
    Заменяет имя поставщика согласно словарю замен.
    
    Args:
        supplier_name: Исходное имя поставщика
        
    Returns:
        Замененное имя или исходное, если замены нет
    """
    if not supplier_name:
        return supplier_name
    
    replacements = load_supplier_replacements()
    replacement = replacements.get(supplier_name, supplier_name)
    
    # Handle both old format (string) and new format (object with name and email)
    if isinstance(replacement, dict):
        normalized_name = replacement.get('name', supplier_name)
        if normalized_name != supplier_name:
            logger.debug(f"Заменено имя поставщика: '{supplier_name}' -> '{normalized_name}'")
        return normalized_name
    else:
        if replacement != supplier_name:
            logger.debug(f"Заменено имя поставщика: '{supplier_name}' -> '{replacement}'")
        return replacement


def get_supplier_email(supplier_name: str) -> str:
    """
    Получает email поставщика из словаря замен.
    
    Args:
        supplier_name: Имя поставщика
        
    Returns:
        Email поставщика или пустая строка, если не найден
    """
    if not supplier_name:
        return ""
    
    replacements = load_supplier_replacements()
    supplier_info = replacements.get(supplier_name, {})
    
    # Handle both old format (string) and new format (object with name and email)
    if isinstance(supplier_info, dict):
        email = supplier_info.get('email', '')
        if email:
            logger.debug(f"Найден email поставщика: '{supplier_name}' -> '{email}'")
        return email
    else:
        # Old format - no email available
        return ""


# Функции для сравнения данных
def to_str(value: Any) -> str:
    """Безопасное преобразование в строку."""
    try:
        return '' if value is None else str(value)
    except Exception:
        return ''


def normalize_article(article: str) -> str:
    """Нормализация артикула для сравнения."""
    article_str = to_str(article)
    return article_str.strip().lower()


def normalize_unit(unit: str) -> str:
    """Нормализация единицы измерения."""
    unit_str = to_str(unit)
    return unit_str.strip()


def parse_quantity(value: Any) -> Optional[float]:
    """Парсинг количества в float."""
    try:
        s = to_str(value).replace('\u00A0', '').replace(' ', '').replace(',', '.')
        if s in ('', '+', '-'):
            return None
        return float(s)
    except Exception:
        return None


def compare_items(app_json: Dict[str, Any], inv_json: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Сравнивает позиции по артикулу между заявкой и счетом.
    
    Args:
        app_json: JSON заявки
        inv_json: JSON счета
        
    Returns:
        Словарь с результатами сравнения:
        - matches: совпадающие артикулы
        - only_in_app: только в заявке
        - only_in_inv: только в счете
    """
    app_items = app_json.get('items') or []
    inv_items = inv_json.get('items') or []

    app_map = {}
    for item in app_items:
        art = normalize_article(item.get('article', ''))
        if not art:
            continue
        app_map[art] = {
            'article': to_str(item.get('article') or '').strip(),
            'qty': item.get('quantity'),
            'unit': item.get('unit'),
        }

    inv_map = {}
    for item in inv_items:
        art = normalize_article(item.get('article', ''))
        if not art:
            continue
        inv_map[art] = {
            'article': to_str(item.get('article') or '').strip(),
            'qty': item.get('quantity'),
            'unit': item.get('unit'),
        }

    matches = []
    only_in_app = []
    only_in_inv = []

    all_keys = set(app_map.keys()) | set(inv_map.keys())
    for key in sorted(all_keys):
        app_item = app_map.get(key)
        inv_item = inv_map.get(key)
        
        if app_item and inv_item:
            app_qty, inv_qty = parse_quantity(app_item['qty']), parse_quantity(inv_item['qty'])
            app_unit, inv_unit = normalize_unit(app_item['unit']), normalize_unit(inv_item['unit'])
            
            same_qty = (
                (app_qty is not None and inv_qty is not None and abs(app_qty - inv_qty) < 1e-9) or 
                (to_str(app_item['qty'] or '').strip() == to_str(inv_item['qty'] or '').strip())
            )
            same_unit = (app_unit == inv_unit)
            
            matches.append({
                'article': app_item['article'] or inv_item['article'],
                'app_qty': to_str(app_item['qty'] or '').strip(),
                'app_unit': app_unit,
                'inv_qty': to_str(inv_item['qty'] or '').strip(),
                'inv_unit': inv_unit,
                'same_qty': bool(same_qty),
                'same_unit': bool(same_unit),
            })
        elif app_item and not inv_item:
            only_in_app.append({
                'article': app_item['article'],
                'app_qty': to_str(app_item['qty'] or '').strip(),
                'app_unit': normalize_unit(app_item['unit']),
            })
        elif inv_item and not app_item:
            only_in_inv.append({
                'article': inv_item['article'],
                'inv_qty': to_str(inv_item['qty'] or '').strip(),
                'inv_unit': normalize_unit(inv_item['unit']),
            })

    logger.debug(f"Сравнение завершено: {len(matches)} совпадений, "
                f"{len(only_in_app)} только в заявке, {len(only_in_inv)} только в счете")

    return {
        'matches': matches,
        'only_in_app': only_in_app,
        'only_in_inv': only_in_inv,
    }


# Работа с файлами
def ensure_directory(file_path: str) -> None:
    """Создает директорию для файла если она не существует."""
    directory = os.path.dirname(file_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def get_file_extension(file_path: str) -> str:
    """Возвращает расширение файла в нижнем регистре."""
    return Path(file_path).suffix.lower()


def is_supported_file(file_path: str) -> bool:
    """Проверяет, поддерживается ли формат файла."""
    supported_extensions = {'.pdf', '.xls', '.xlsx'}
    return get_file_extension(file_path) in supported_extensions


def safe_filename(filename: str) -> str:
    """Создает безопасное имя файла, удаляя недопустимые символы."""
    # Удаляем недопустимые символы для имени файла
    safe_chars = re.sub(r'[<>:"/\\|?*]', '_', filename)
    return safe_chars.strip()


# Работа с JSON
def safe_json_loads(json_str: str) -> Any:
    """Безопасная загрузка JSON с обработкой ошибок."""
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка при парсинге JSON: {e}")
        return None


def safe_json_dumps(data: Any, ensure_ascii: bool = False, indent: int = 2) -> str:
    """Безопасная сериализация в JSON."""
    try:
        return json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
    except Exception as e:
        logger.error(f"Ошибка сериализации JSON: {e}")
        return "{}"


# Простой retry механизм
def simple_retry(func, max_attempts: int = 3, delay: float = 1.0):
    """
    Простой механизм повторных попыток.
    
    Args:
        func: Функция для выполнения
        max_attempts: Максимальное количество попыток
        delay: Задержка между попытками в секундах
        
    Returns:
        Результат выполнения функции
        
    Raises:
        Исключение от последней попытки
    """
    import time
    
    last_exception = None
    
    for attempt in range(max_attempts):
        try:
            return func()
        except Exception as e:
            last_exception = e
            if attempt < max_attempts - 1:  # Не последняя попытка
                logger.warning(f"Попытка {attempt + 1} не удалась: {e}. Повтор через {delay}с")
                time.sleep(delay)
            else:
                logger.error(f"Все {max_attempts} попыток не удались")
    
    if last_exception:
        raise last_exception
    else:
        raise RuntimeError("Функция не была выполнена")


# Валидация данных
def validate_email(email: str) -> bool:
    """Простая валидация email адреса."""
    if not email or '@' not in email:
        return False
    
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email.strip()) is not None


def validate_file_path(file_path: str) -> bool:
    """Проверяет существование файла."""
    return os.path.exists(file_path) and os.path.isfile(file_path)