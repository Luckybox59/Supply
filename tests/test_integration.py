"""Интеграционные тесты для новой архитектуры Parser."""

import pytest
import os
import tempfile
import json
from unittest.mock import patch, MagicMock
from services.pipeline import run_processing, ProcessingPipeline
from core import parse_project_folder


class TestIntegration:
    """Интеграционные тесты для полного пайплайна обработки."""
    
    def setup_method(self):
        """Настройка перед каждым тестом."""
        self.test_dir = tempfile.mkdtemp()
        self.pipeline = ProcessingPipeline()
    
    def teardown_method(self):
        """Очистка после каждого теста."""
        import shutil
        try:
            shutil.rmtree(self.test_dir)
        except OSError:
            pass
    
    def create_test_pdf(self, filename: str, content: str = "Test PDF content"):
        """Создает тестовый PDF файл."""
        filepath = os.path.join(self.test_dir, filename)
        # Создаем простой текстовый файл вместо PDF для тестов
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return filepath
    
    def create_test_excel(self, filename: str, content: str = "Test Excel content"):
        """Создает тестовый Excel файл."""
        filepath = os.path.join(self.test_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return filepath
    
    @patch('parsers.PDFParser.parse_pdf')
    @patch('parsers.ExcelParser.parse_excel')
    @patch('llm.LLMClient.query')
    @patch('llm.LLMClient.extract_json_from_response')
    def test_full_pipeline_processing(self, mock_extract_json, mock_llm_query, 
                                    mock_excel_parse, mock_pdf_parse):
        """Тест полного пайплайна обработки."""
        # Настройка моков
        mock_pdf_parse.return_value = "Parsed PDF content"
        mock_excel_parse.return_value = "Parsed Excel content"
        mock_llm_query.return_value = "LLM response"
        mock_extract_json.return_value = [
            {
                "поставщик": "ООО Тест",
                "номер_счета": "123",
                "дата": "2024-01-01",
                "сумма": "1000.00"
            }
        ]
        
        # Создаем тестовые файлы
        pdf_file = self.create_test_pdf("test_invoice.pdf")
        excel_file = self.create_test_excel("test_invoice.xlsx")
        
        # Создаем тестовую директорию проекта
        project_dir = os.path.join(self.test_dir, "(37)Петрова(Ленина, 10)(Кухня)")
        os.makedirs(project_dir, exist_ok=True)
        
        # Перемещаем файлы в проектную директорию
        import shutil
        pdf_path = os.path.join(project_dir, "test_invoice.pdf")
        excel_path = os.path.join(project_dir, "test_invoice.xlsx")
        shutil.move(pdf_file, pdf_path)
        shutil.move(excel_file, excel_path)
        
        # Запускаем обработку
        results, elapsed_time, report_content, json_file, report_file, card_file = run_processing(
            cwd=project_dir,
            app_fname_selected=None,
            invoice_filenames_selected=["test_invoice.pdf", "test_invoice.xlsx"],
            model="test-model",
            use_template_for_report=False
        )
        
        # Проверяем результаты
        assert len(results) > 0
        assert elapsed_time > 0
        assert json_file is not None
        
        # Проверяем, что файлы созданы
        if json_file:
            json_path = os.path.join(project_dir, json_file)
            assert os.path.exists(json_path)
        
        # Проверяем содержимое результатов
        result = results[0]
        assert result["поставщик"] == "ООО Тест"
        assert result["номер_счета"] == "123"
        assert "номер" in result  # Должна быть добавлена информация о проекте
        assert "заказчик" in result
    
    def test_project_folder_parsing(self):
        """Тест парсинга информации из имени папки проекта."""
        test_cases = [
            ("(37)Петрова(Ленина, 10)(Кухня)", {
                "номер": "37",
                "заказчик": "Петрова",
                "адрес": "Ленина, 10",
                "изделие": "Кухня"
            }),
            ("(42)Иванов(Мира, 5-10)(Шкаф)", {
                "номер": "42",
                "заказчик": "Иванов",
                "адрес": "Мира, 5-10",
                "изделие": "Шкаф"
            })
        ]
        
        for folder_name, expected in test_cases:
            project_dir = os.path.join(self.test_dir, folder_name)
            os.makedirs(project_dir, exist_ok=True)
            
            result = parse_project_folder(project_dir)
            
            assert result["номер"] == expected["номер"]
            assert result["заказчик"] == expected["заказчик"]
            assert result["адрес"] == expected["адрес"]
            assert result["изделие"] == expected["изделие"]
    
    @patch('parsers.PDFParser.parse_pdf')
    def test_pipeline_single_file_processing(self, mock_pdf_parse):
        """Тест обработки одного файла через пайплайн."""
        mock_pdf_parse.return_value = "Test PDF content"
        
        pdf_file = self.create_test_pdf("test.pdf")
        
        result = self.pipeline.process_single_file(pdf_file)
        
        assert result is not None
        mock_pdf_parse.assert_called_once_with(pdf_file)
    
    @patch('parsers.PDFParser.parse_pdf')
    @patch('parsers.ExcelParser.parse_excel')
    def test_pipeline_parallel_processing(self, mock_excel_parse, mock_pdf_parse):
        """Тест параллельной обработки файлов."""
        mock_pdf_parse.return_value = "PDF content"
        mock_excel_parse.return_value = "Excel content"
        
        pdf_file = self.create_test_pdf("test.pdf")
        excel_file = self.create_test_excel("test.xlsx")
        
        results = self.pipeline.process_files_parallel([pdf_file, excel_file])
        
        assert len(results) == 2
        assert "PDF content" in results or "Excel content" in results
    
    @patch('llm.LLMClient.query')
    @patch('llm.LLMClient.extract_json_from_response')
    def test_pipeline_llm_batch_processing(self, mock_extract_json, mock_llm_query):
        """Тест обработки батча через LLM."""
        mock_llm_query.return_value = "LLM response"
        mock_extract_json.return_value = [
            {"поставщик": "Тест", "сумма": "1000"}
        ]
        
        contents = ["Content 1", "Content 2"]
        
        results = self.pipeline.process_with_llm_batch(contents)
        
        assert len(results) == 1
        mock_llm_query.assert_called_once()
        mock_extract_json.assert_called_once()
    
    @patch('parsers.PDFParser.parse_pdf')
    @patch('llm.LLMClient.query')
    @patch('llm.LLMClient.extract_json_from_response')
    def test_pipeline_multi_llm_processing(self, mock_extract_json, mock_llm_query, 
                                         mock_pdf_parse):
        """Тест обработки нескольких файлов одним запросом к LLM."""
        
        # Настройка моков
        mock_llm_query.return_value = "LLM response"
        mock_extract_json.return_value = [{"поставщик": "Тест"}]
        
        file_contents = [("test.pdf", "Test content")]
        
        results = self.pipeline.process_with_llm_multi(file_contents)
        
        assert len(results) == 1
        mock_llm_query.assert_called_once()
        mock_extract_json.assert_called_once()
    
    def test_error_handling_in_pipeline(self):
        """Тест обработки ошибок в пайплайне."""
        # Тест с несуществующим файлом
        result = self.pipeline.process_single_file("nonexistent.pdf")
        assert result is None
        
        # Тест с неподдерживаемым типом файла
        txt_file = os.path.join(self.test_dir, "test.txt")
        with open(txt_file, 'w') as f:
            f.write("test")
        
        result = self.pipeline.process_single_file(txt_file)
        assert result is None
    
    @patch('email_service.EmailSender.send_email')
    def test_email_integration(self, mock_send_email):
        """Тест интеграции с системой отправки email."""
        mock_send_email.return_value = True
        
        from parser import send_email_with_attachments
        
        result = send_email_with_attachments(
            to_emails=["test@example.com"],
            subject="Test Subject",
            body="Test Body",
            attachment_paths=[]
        )
        
        assert result is True
        mock_send_email.assert_called_once()
    
    def test_artifacts_management(self):
        """Тест управления артефактами."""
        from services import artifacts
        
        # Очищаем артефакты
        artifacts.clear()
        
        # Создаем тестовый файл
        test_file = os.path.join(self.test_dir, "test_artifact.txt")
        with open(test_file, 'w') as f:
            f.write("test")
        
        # Регистрируем артефакт
        artifacts.register(test_file)
        
        # Проверяем, что артефакт зарегистрирован
        artifact_list = artifacts.list_all()
        assert any(test_file in path for path in artifact_list)
        
        # Очищаем артефакты
        stats = artifacts.cleanup()
        
        # Проверяем статистику очистки
        assert len(stats.get("deleted", [])) > 0 or len(stats.get("not_found", [])) > 0


class TestPerformanceMetrics:
    """Тесты для системы метрик производительности."""
    
    def test_performance_logging(self):
        """Тест логирования метрик производительности."""
        from logging_setup import get_performance_logger
        
        perf_logger = get_performance_logger("test")
        
        # Тестируем таймер
        perf_logger.start_timer("test_operation")
        import time
        time.sleep(0.01)  # Небольшая задержка
        elapsed = perf_logger.end_timer("test_operation", test_param="value")
        
        assert elapsed > 0
        assert elapsed < 1.0  # Должно быть меньше секунды
    
    def test_memory_usage_tracking(self):
        """Тест отслеживания использования памяти."""
        from logging_setup import get_performance_logger
        
        perf_logger = get_performance_logger("test")
        
        # Создаем большой объект для увеличения памяти
        large_data = ['x' * 1000 for _ in range(1000)]
        
        perf_logger.log_memory_usage("after_large_allocation")
        
        # Удаляем объект
        del large_data
        
        perf_logger.log_memory_usage("after_cleanup")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
