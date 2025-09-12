"""
Упрощенный модуль для обработки и очистки текста.

Содержит простые функции для очистки текста без избыточных абстракций.
"""

import re
from typing import Optional
from logging_setup import get_logger

logger = get_logger(__name__)


def clean_text(text: str) -> str:
    """
    Очищает и нормализует текст.
    
    Args:
        text: Исходный текст для очистки
        
    Returns:
        Очищенный и нормализованный текст
    """
    if not text:
        return ""
    
    # Преобразуем в строку, если это не строка
    if not isinstance(text, str):
        text = str(text)
        
    # Удаляем лишние пробелы и пустые строки
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    text = '\n'.join(lines)
    
    # Удаляем значения 'nan' (в любом регистре)
    text = re.sub(r'\bnan\b', '', text, flags=re.IGNORECASE)
    
    # Заменяем множественные табуляции на одну
    text = re.sub(r'\t+', '\t', text)
    
    # Заменяем табуляции на ' | '
    text = text.replace('\t', ' | ')
    
    # Удаляем лишние пробелы вокруг разделителей
    text = re.sub(r' *\| *', ' | ', text)
    
    # Применяем базовые исправления
    text = apply_basic_fixes(text)
    
    return text.strip()


def apply_basic_fixes(text: str) -> str:
    """
    Применяет базовые исправления текста после OCR.
    
    Args:
        text: Исходный текст
        
    Returns:
        Исправленный текст
    """
    if not text:
        return ""
    
    # Частые OCR-замены
    fixes = [
        (r'—', '-'),      # длинное тире на дефис
        (r'…', '...'),    # многоточие
        (r' +', ' '),     # множественные пробелы
        (r'\n +', '\n'),  # пробелы в начале строк
        (r' +\n', '\n'),  # пробелы в конце строк
    ]
    
    for pattern, replacement in fixes:
        text = re.sub(pattern, replacement, text)
    
    return text


def normalize_whitespace(text: str) -> str:
    """
    Нормализует пробельные символы в тексте.
    
    Args:
        text: Исходный текст
        
    Returns:
        Нормализованный текст
    """
    if not text:
        return ""
    
    # Заменяем различные пробельные символы на обычные пробелы
    text = re.sub(r'[\u00A0\u2000-\u200B\u2028\u2029]', ' ', text)
    
    # Удаляем множественные пробелы
    text = re.sub(r' +', ' ', text)
    
    # Удаляем пробелы в начале и конце строк
    lines = [line.strip() for line in text.split('\n')]
    
    return '\n'.join(lines).strip()


def extract_key_value_pairs(text: str) -> dict:
    """
    Извлекает пары ключ-значение из текста.
    
    Ищет строки вида "Ключ: Значение" или "Ключ | Значение".
    
    Args:
        text: Исходный текст
        
    Returns:
        Словарь с извлеченными парами
    """
    pairs = {}
    
    if not text:
        return pairs
    
    # Паттерны для поиска пар ключ-значение
    patterns = [
        r'([^:\n]+):\s*([^\n]+)',      # "Ключ: Значение"
        r'([^|\n]+)\|\s*([^\n]+)',     # "Ключ | Значение"
        r'([^=\n]+)=\s*([^\n]+)',      # "Ключ = Значение"
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for key, value in matches:
            key = key.strip()
            value = value.strip()
            if key and value:
                pairs[key] = value
    
    return pairs


def remove_supplier_replacements(text: str, replacements: Optional[dict] = None) -> str:
    """
    Применяет замены поставщиков к тексту.
    
    Args:
        text: Исходный текст
        replacements: Словарь замен (ключ -> значение)
        
    Returns:
        Текст с примененными заменами
    """
    if not text or not replacements:
        return text
    
    result = text
    
    for old_value, new_value in replacements.items():
        if old_value and new_value:
            # Заменяем точные совпадения (учитывая границы слов)
            pattern = r'\b' + re.escape(old_value) + r'\b'
            result = re.sub(pattern, new_value, result, flags=re.IGNORECASE)
    
    return result


def extract_numbers(text: str) -> list:
    """
    Извлекает все числа из текста.
    
    Args:
        text: Исходный текст
        
    Returns:
        Список найденных чисел (как строк)
    """
    if not text:
        return []
    
    # Паттерн для поиска чисел (включая дробные)
    pattern = r'\b\d+(?:[.,]\d+)?\b'
    numbers = re.findall(pattern, text)
    
    return numbers


def extract_dates(text: str) -> list:
    """
    Извлекает даты из текста в различных форматах.
    
    Args:
        text: Исходный текст
        
    Returns:
        Список найденных дат (как строк)
    """
    if not text:
        return []
    
    # Паттерны для различных форматов дат
    patterns = [
        r'\b\d{1,2}[./]\d{1,2}[./]\d{4}\b',      # DD.MM.YYYY или DD/MM/YYYY
        r'\b\d{4}[.-]\d{1,2}[.-]\d{1,2}\b',      # YYYY-MM-DD
        r'\b\d{1,2}\s+[а-яё]+\s+\d{4}\b',       # DD месяц YYYY (русский)
    ]
    
    dates = []
    for pattern in patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        dates.extend(matches)
    
    return dates