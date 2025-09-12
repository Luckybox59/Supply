"""
Упрощенный модуль для парсинга файлов PDF и Excel.

Следует принципу KISS - простая функциональность без избыточных абстракций.
"""

import pandas as pd
import xlrd
import pdfplumber
import numpy as np
from pathlib import Path
from typing import Optional
from pdf2image import convert_from_path
import config
from logging_setup import get_logger

logger = get_logger(__name__)


def parse_file(file_path: str) -> str:
    """
    Универсальная функция парсинга файла.
    
    Args:
        file_path: Путь к файлу (.pdf, .xls, .xlsx)
        
    Returns:
        Извлеченный текст
        
    Raises:
        ValueError: При неподдерживаемом формате файла
        RuntimeError: При ошибке парсинга
    """
    if not Path(file_path).exists():
        raise RuntimeError(f"Файл не найден: {file_path}")
    
    ext = Path(file_path).suffix.lower()
    
    if ext == '.pdf':
        return parse_pdf(file_path)
    elif ext in ['.xls', '.xlsx']:
        return parse_excel(file_path)
    else:
        raise ValueError(f"Неподдерживаемый формат файла: {ext}")


def parse_pdf(file_path: str) -> str:
    """
    Парсит PDF файл с fallback на OCR.
    
    Args:
        file_path: Путь к PDF файлу
        
    Returns:
        Извлеченный текст
        
    Raises:
        RuntimeError: При ошибке парсинга
    """
    try:
        # 1) Попытка через pdfplumber (текстовый PDF)
        text = _extract_text_with_pdfplumber(file_path)
        if text and len(text.strip()) > 10:
            logger.debug(f"PDF {file_path} успешно обработан через pdfplumber")
            return text
            
        # 2) Fallback: OCR
        logger.info(f"Переход к OCR для файла {file_path}")
        return _extract_text_with_ocr(file_path)
        
    except Exception as e:
        logger.error(f"Ошибка парсинга PDF {file_path}: {e}")
        raise RuntimeError(f"Не удалось обработать PDF файл {file_path}: {e}")


def parse_excel(file_path: str) -> str:
    """
    Парсит Excel файл (.xls или .xlsx).
    
    Args:
        file_path: Путь к Excel файлу
        
    Returns:
        Текстовое представление содержимого
        
    Raises:
        RuntimeError: При ошибке парсинга
    """
    ext = Path(file_path).suffix.lower()
    
    try:
        if ext == '.xls':
            return _parse_xls(file_path)
        else:  # .xlsx
            return _parse_xlsx(file_path)
    except Exception as e:
        logger.error(f"Ошибка парсинга Excel {file_path}: {e}")
        raise RuntimeError(f"Не удалось обработать Excel файл {file_path}: {e}")


def _extract_text_with_pdfplumber(file_path: str) -> str:
    """Извлекает текст из PDF через pdfplumber."""
    try:
        extracted_pages = []
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                try:
                    text = page.extract_text(x_tolerance=1.5, y_tolerance=1.5) or ''
                    if text:
                        extracted_pages.append(text)
                        logger.debug(f"Извлечен текст со страницы {i+1}")
                except Exception as e:
                    logger.warning(f"Ошибка извлечения текста со страницы {i+1}: {e}")
                    continue
        
        result = '\n'.join(extracted_pages).strip()
        logger.debug(f"pdfplumber извлек {len(result)} символов из {len(extracted_pages)} страниц")
        return result
    except Exception as e:
        logger.debug(f"pdfplumber не смог обработать файл: {e}")
        return ""


def _extract_text_with_ocr(file_path: str) -> str:
    """Извлекает текст из PDF через OCR (упрощенная версия)."""
    try:
        import easyocr
        
        # Конвертируем PDF в изображения
        poppler_path = getattr(config, 'POPPLER_PATH', None)
        images = convert_from_path(
            file_path,
            poppler_path=poppler_path,
            dpi=getattr(config, 'OCR_DPI', 300)
        )
        
        if not images:
            raise RuntimeError("Не удалось конвертировать PDF в изображения")
        
        logger.info(f"Конвертировано {len(images)} страниц PDF в изображения")
        
        # Создаем OCR reader
        langs = [s.strip() for s in getattr(config, 'OCR_LANGS', 'ru,en').split(',') if s.strip()]
        reader = easyocr.Reader(langs)
        
        all_text = []
        for i, img in enumerate(images):
            try:
                result = reader.readtext(
                    np.array(img),
                    detail=getattr(config, 'OCR_DETAIL', 0),
                    paragraph=getattr(config, 'OCR_PARAGRAPH', True)
                )
                if isinstance(result, list):
                    # Если detail=0, result это список строк
                    page_text = '\n'.join(str(item) for item in result)
                else:
                    page_text = str(result)
                all_text.append(page_text)
                logger.debug(f"OCR обработана страница {i+1}/{len(images)}")
            except Exception as e:
                logger.warning(f"Ошибка OCR на странице {i+1}: {e}")
                continue
                
        result = '\n'.join(all_text)
        logger.info(f"OCR обработал {len(images)} страниц, извлечено {len(result)} символов")
        return result
        
    except Exception as e:
        logger.error(f"Ошибка OCR для {file_path}: {e}")
        raise RuntimeError(f"Ошибка OCR обработки: {e}")


def _parse_xls(file_path: str) -> str:
    """Парсит старые .xls файлы через xlrd."""
    try:
        book = xlrd.open_workbook(file_path, encoding_override='cp1251')
    except Exception as e:
        raise RuntimeError(f"Ошибка открытия XLS: {e}")

    all_text = []
    try:
        for sheet in book.sheets():
            rows_text = []
            try:
                nrows, ncols = sheet.nrows, sheet.ncols
            except Exception as e:
                all_text.append(f"--- Лист: {sheet.name} ---\n[Ошибка чтения размеров листа: {e}]")
                continue
                
            for r in range(nrows):
                row_vals = []
                for c in range(ncols):
                    try:
                        val = sheet.cell_value(r, c)
                    except Exception:
                        val = ''
                    
                    # Нормализуем значения к строкам
                    if isinstance(val, float):
                        # Избегаем '1.0' для целых
                        if val.is_integer():
                            val = str(int(val))
                        else:
                            val = str(val)
                    else:
                        val = str(val)
                    row_vals.append(val)
                rows_text.append('\t'.join(row_vals))
            all_text.append(f"--- Лист: {sheet.name} ---\n" + '\n'.join(rows_text))
    finally:
        try:
            book.release_resources()
        except Exception:
            pass

    return '\n'.join(all_text)


def _parse_xlsx(file_path: str) -> str:
    """Парсит современные .xlsx файлы через pandas."""
    all_text = []
    
    try:
        # Используем контекстный менеджер для гарантированного закрытия файла
        with pd.ExcelFile(file_path, engine='openpyxl') as xls:
            for sheet in xls.sheet_names:
                try:
                    df = xls.parse(sheet_name=sheet, header=None)
                except Exception as e:
                    all_text.append(f"--- Лист: {sheet} ---\n[Ошибка чтения листа: {e}]")
                    continue
                
                # Преобразуем значения в строки
                values = df.fillna('').values
                text_rows = [
                    '\t'.join(
                        str(int(x)) if isinstance(x, float) and x.is_integer() else str(x) 
                        for x in row
                    ) 
                    for row in values
                ]
                all_text.append(f'--- Лист: {sheet} ---\n' + '\n'.join(text_rows))
                
    except Exception as e:
        raise RuntimeError(f"Ошибка открытия/чтения XLSX: {e}")

    return '\n'.join(all_text)


def clean_text(text: str) -> str:
    """
    Очищает и нормализует текст.
    
    Args:
        text: Исходный текст
        
    Returns:
        Очищенный текст
    """
    if not text:
        return ""
    
    # Удаляем лишние пробелы и переносы строк
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    cleaned = '\n'.join(lines)
    
    # Заменяем множественные пробелы одинарными
    import re
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    return cleaned.strip()