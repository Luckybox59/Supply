"""Тесты для модулей парсинга документов."""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

from parsers.text_cleaner import TextCleaner
from parsers.pdf_parser import PDFParser
from parsers.excel_parser import ExcelParser


class TestTextCleaner:
    """Тесты для TextCleaner."""
    
    def test_clean_text_basic(self):
        """Тест базовой очистки текста."""
        dirty_text = "  Строка 1  \n\n  \n  Строка 2\t\t\tСтрока 3  \n  "
        expected = "Строка 1\nСтрока 2 | Строка 3"
        result = TextCleaner.clean_text(dirty_text)
        assert result == expected
    
    def test_clean_text_nan_removal(self):
        """Тест удаления значений 'nan'."""
        text_with_nan = "Поставщик: ООО Тест\nИНН: nan\nКПП: 123456789"
        result = TextCleaner.clean_text(text_with_nan)
        assert "nan" not in result
        assert "ООО Тест" in result
    
    def test_clean_text_empty_input(self):
        """Тест обработки пустого ввода."""
        assert TextCleaner.clean_text("") == ""
        assert TextCleaner.clean_text(None) == ""
    
    def test_ocr_fixes_applied(self):
        """Тест применения OCR исправлений."""
        text = "Тест с множественными  пробелами"
        result = TextCleaner.clean_text(text)
        assert "  " not in result  # Множественные пробелы должны быть заменены
    
    def test_add_ocr_fix(self):
        """Тест добавления нового правила OCR."""
        original_count = len(TextCleaner.OCR_FIXES)
        TextCleaner.add_ocr_fix(r'тест', 'ТЕСТ')
        assert len(TextCleaner.OCR_FIXES) == original_count + 1
        
        # Проверяем применение нового правила
        result = TextCleaner.clean_text("это тест")
        assert "ТЕСТ" in result


class TestPDFParser:
    """Тесты для PDFParser."""
    
    @patch('parsers.pdf_parser.pdfplumber')
    def test_parse_pdf_with_pdfplumber_success(self, mock_pdfplumber):
        """Тест успешного парсинга PDF через pdfplumber."""
        # Настраиваем мок
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Тестовый текст из PDF"
        mock_pdf.pages = [mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf
        
        result = PDFParser.parse_pdf("test.pdf")
        assert result == "Тестовый текст из PDF"
        mock_pdfplumber.open.assert_called_once_with("test.pdf")
    
    @patch('parsers.pdf_parser.convert_from_path')
    @patch('parsers.pdf_parser.pdfplumber')
    def test_parse_pdf_fallback_to_ocr(self, mock_pdfplumber, mock_convert):
        """Тест fallback на OCR при неудаче pdfplumber."""
        # pdfplumber возвращает пустой текст
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""
        mock_pdf.pages = [mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf
        
        # Настраиваем OCR мок
        mock_image = MagicMock()
        mock_convert.return_value = [mock_image]
        
        with patch.object(PDFParser, 'get_easyocr_reader') as mock_reader:
            mock_reader.return_value.readtext.return_value = ["OCR текст"]
            result = PDFParser.parse_pdf("test.pdf")
            assert result == "OCR текст"
    
    def test_get_easyocr_reader_singleton(self):
        """Тест singleton поведения OCR reader."""
        # Очищаем кэш
        PDFParser.clear_ocr_cache()
        
        with patch('parsers.pdf_parser.easyocr.Reader') as mock_reader_class:
            mock_reader = MagicMock()
            mock_reader_class.return_value = mock_reader
            
            # Первый вызов должен создать reader
            reader1 = PDFParser.get_easyocr_reader()
            # Второй вызов должен вернуть тот же объект
            reader2 = PDFParser.get_easyocr_reader()
            
            assert reader1 is reader2
            mock_reader_class.assert_called_once_with(['ru', 'en'])


class TestExcelParser:
    """Тесты для ExcelParser."""
    
    @patch('parsers.excel_parser.xlrd')
    def test_parse_xls_file(self, mock_xlrd):
        """Тест парсинга .xls файла."""
        # Настраиваем мок xlrd
        mock_book = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.name = "Лист1"
        mock_sheet.nrows = 2
        mock_sheet.ncols = 2
        mock_sheet.cell_value.side_effect = [
            "Заголовок1", "Заголовок2",
            "Значение1", 123.0
        ]
        mock_book.sheets.return_value = [mock_sheet]
        mock_xlrd.open_workbook.return_value = mock_book
        
        result = ExcelParser.parse_xlsx("test.xls")
        
        assert "Лист1" in result
        assert "Заголовок1" in result
        assert "123" in result  # float должен стать int строкой
        mock_xlrd.open_workbook.assert_called_once_with("test.xls", encoding_override='cp1251')
    
    @patch('parsers.excel_parser.pd.ExcelFile')
    def test_parse_xlsx_file(self, mock_excel_file):
        """Тест парсинга .xlsx файла."""
        # Настраиваем мок pandas
        mock_df = MagicMock()
        mock_df.fillna.return_value.values = [
            ["Заголовок1", "Заголовок2"],
            ["Значение1", 456.0]
        ]
        
        mock_file = MagicMock()
        mock_file.sheet_names = ["Лист1"]
        mock_file.parse.return_value = mock_df
        mock_excel_file.return_value.__enter__.return_value = mock_file
        
        result = ExcelParser.parse_xlsx("test.xlsx")
        
        assert "Лист1" in result
        assert "Заголовок1" in result
        assert "456" in result
    
    def test_parse_xlsx_file_extension_detection(self):
        """Тест определения типа файла по расширению."""
        with patch.object(ExcelParser, '_parse_xls') as mock_xls:
            mock_xls.return_value = "xls result"
            result = ExcelParser.parse_xlsx("test.xls")
            assert result == "xls result"
            mock_xls.assert_called_once_with("test.xls")
        
        with patch.object(ExcelParser, '_parse_xlsx_modern') as mock_xlsx:
            mock_xlsx.return_value = "xlsx result"
            result = ExcelParser.parse_xlsx("test.xlsx")
            assert result == "xlsx result"
            mock_xlsx.assert_called_once_with("test.xlsx")


# Фикстуры для интеграционных тестов
@pytest.fixture
def temp_pdf_file():
    """Создает временный PDF файл для тестов."""
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        # Здесь можно создать простой PDF для тестов
        yield f.name
    os.unlink(f.name)


@pytest.fixture
def temp_excel_file():
    """Создает временный Excel файл для тестов."""
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        yield f.name
    os.unlink(f.name)
