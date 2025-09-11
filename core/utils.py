"""Утилиты для работы с проектными данными."""

import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from logging_setup import get_logger

logger = get_logger(__name__)


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


# Механизм подмены имени поставщика
def _load_supplier_replacements() -> Dict[str, str]:
    """
    Загружает словарь замен поставщиков из JSON файла.
    
    Returns:
        Словарь замен или пустой словарь при ошибке
    """
    try:
        import json
        from pathlib import Path
        
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
    
    replacements = _load_supplier_replacements()
    replacement = replacements.get(supplier_name, supplier_name)
    if replacement != supplier_name:
        logger.debug(f"Заменено имя поставщика: '{supplier_name}' -> '{replacement}'")
    
    return replacement


# Функции для сравнения данных заявки и счета
def _to_str(x: Any) -> str:
    """Безопасное преобразование в строку."""
    try:
        return '' if x is None else str(x)
    except Exception:
        return ''


def _norm_article(s: str) -> str:
    """Нормализация артикула для сравнения."""
    s_str = _to_str(s)
    if s_str is None:
        return ""
    return s_str.strip().lower()


def _norm_unit(s: str) -> str:
    """Нормализация единицы измерения."""
    s_str = _to_str(s)
    if s_str is None:
        return ""
    return s_str.strip()


def _parse_qty(val: Any) -> Optional[float]:
    """Парсинг количества в float."""
    try:
        s = _to_str(val).replace('\u00A0', '').replace(' ', '').replace(',', '.')
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
        art = _norm_article(item.get('article', ''))
        if not art:
            continue
        app_map[art] = {
            'article': _to_str(item.get('article') or '').strip(),
            'qty': item.get('quantity'),
            'unit': item.get('unit'),
        }

    inv_map = {}
    for item in inv_items:
        art = _norm_article(item.get('article', ''))
        if not art:
            continue
        inv_map[art] = {
            'article': _to_str(item.get('article') or '').strip(),
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
            app_qty, inv_qty = _parse_qty(app_item['qty']), _parse_qty(inv_item['qty'])
            app_unit, inv_unit = _norm_unit(app_item['unit']), _norm_unit(inv_item['unit'])
            
            same_qty = (
                (app_qty is not None and inv_qty is not None and abs(app_qty - inv_qty) < 1e-9) or 
                (_to_str(app_item['qty'] or '').strip() == _to_str(inv_item['qty'] or '').strip())
            )
            same_unit = (app_unit == inv_unit)
            
            matches.append({
                'article': app_item['article'] or inv_item['article'],
                'app_qty': _to_str(app_item['qty'] or '').strip(),
                'app_unit': app_unit,
                'inv_qty': _to_str(inv_item['qty'] or '').strip(),
                'inv_unit': inv_unit,
                'same_qty': bool(same_qty),
                'same_unit': bool(same_unit),
            })
        elif app_item and not inv_item:
            only_in_app.append({
                'article': app_item['article'],
                'app_qty': _to_str(app_item['qty'] or '').strip(),
                'app_unit': _norm_unit(app_item['unit']),
            })
        elif inv_item and not app_item:
            only_in_inv.append({
                'article': inv_item['article'],
                'inv_qty': _to_str(inv_item['qty'] or '').strip(),
                'inv_unit': _norm_unit(inv_item['unit']),
            })

    logger.debug(f"Сравнение завершено: {len(matches)} совпадений, "
                f"{len(only_in_app)} только в заявке, {len(only_in_inv)} только в счете")

    return {
        'matches': matches,
        'only_in_app': only_in_app,
        'only_in_inv': only_in_inv,
    }
