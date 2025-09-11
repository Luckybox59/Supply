"""Модуль для парсинга Excel документов (.xls и .xlsx)."""

import pandas as pd
import xlrd
from pathlib import Path
from typing import List
from logging_setup import get_logger

logger = get_logger(__name__)


class ExcelParser:
    """Класс для парсинга Excel документов с поддержкой старых и новых форматов."""
    
    @classmethod
    def parse_excel(cls, file_path: str) -> str:
        """
        Универсальный парсер Excel для .xls и .xlsx файлов.
        Алиас для parse_xlsx для обратной совместимости.
        
        Args:
            file_path: Путь к Excel файлу
            
        Returns:
            Текстовое представление содержимого файла
        """
        return cls.parse_xlsx(file_path)
    
    @classmethod
    def parse_xlsx(cls, file_path: str) -> str:
        """
        Универсальный парсер Excel для .xls и .xlsx файлов.
        
        Args:
            file_path: Путь к Excel файлу
            
        Returns:
            Текстовое представление содержимого файла
            
        Raises:
            RuntimeError: При ошибке парсинга файла
        """
        ext = Path(file_path).suffix.lower()
        
        try:
            if ext == '.xls':
                return cls._parse_xls(file_path)
            else:  # .xlsx и другие форматы
                return cls._parse_xlsx_modern(file_path)
        except Exception as e:
            logger.error(f"Ошибка парсинга Excel {file_path}: {e}")
            raise RuntimeError(f"Не удалось обработать Excel файл {file_path}: {e}")
    
    @classmethod
    def _parse_xls(cls, file_path: str) -> str:
        """Парсит старые .xls файлы через xlrd с правильной кодировкой."""
        try:
            book = xlrd.open_workbook(file_path, encoding_override='cp1251')
        except Exception as e:
            raise RuntimeError(f"Ошибка открытия XLS через xlrd: {e}. Убедитесь, что установлен пакет 'xlrd'.")

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
    
    @classmethod
    def _parse_xlsx_modern(cls, file_path: str) -> str:
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
            raise RuntimeError(f"Ошибка открытия/чтения XLSX через pandas/openpyxl: {e}. Убедитесь, что установлен 'openpyxl'.")

        return '\n'.join(all_text)
