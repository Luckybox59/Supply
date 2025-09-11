"""Модуль для очистки и нормализации текста."""

import re
from typing import List, Tuple


class TextCleaner:
    """Класс для очистки и нормализации текста после парсинга документов."""
    
    # Частые OCR-замены (можно расширять)
    OCR_FIXES: List[Tuple[str, str]] = [
        (r'О', 'О'),  # латинская O на кириллицу
        (r'0', '0'),  # латинский 0 на цифру 0
        (r'1', '1'),  # латинская l на 1
        (r'—', '-'),  # длинное тире на дефис
        (r'…', '...'),
        (r' +', ' '),  # множественные пробелы
    ]
    
    @classmethod
    def clean_text(cls, text: str) -> str:
        """
        Очищает текст от лишних символов и нормализует форматирование.
        
        Args:
            text: Исходный текст для очистки
            
        Returns:
            Очищенный и нормализованный текст
        """
        if not text or text is None:
            return ""
        
        # Преобразуем в строку, если это не строка
        if not isinstance(text, str):
            text = str(text)
            
        # Удаляем лишние пробелы и пустые строки
        lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
        text = '\n'.join(lines)
        
        # Удаляем или заменяем значения 'nan' (в любом регистре)
        text = re.sub(r'\bnan\b', '', text, flags=re.IGNORECASE)
        
        # Заменяем несколько подряд идущих табуляций на одну
        text = re.sub(r'\t+', '\t', text)
        
        # Заменяем табуляции на ' | '
        text = text.replace('\t', ' | ')
        
        # Удаляем лишние пробелы вокруг разделителей
        text = re.sub(r' *\| *', ' | ', text)
        
        # Применяем частые OCR-замены
        for pattern, repl in cls.OCR_FIXES:
            text = re.sub(pattern, repl, text)
            
        return text
    
    @classmethod
    def add_ocr_fix(cls, pattern: str, replacement: str) -> None:
        """
        Добавляет новое правило для исправления OCR ошибок.
        
        Args:
            pattern: Регулярное выражение для поиска
            replacement: Строка замены
        """
        cls.OCR_FIXES.append((pattern, replacement))
