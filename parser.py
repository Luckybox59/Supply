"""Обновленный основной модуль parser.py с новой архитектурой."""

import os
import sys
from typing import List, Optional, Tuple

# Прямое использование новой архитектуры lib/
from lib.data_processor import process_documents
from lib.email_sender import UnifiedEmailSender
from lib.utils import ParserError
from logging_setup import get_logger
import config

logger = get_logger(__name__)


def main():
    """Основная функция для запуска из командной строки или GUI."""
    try:
        # Получаем текущую директорию
        cwd = os.getcwd()
        logger.info(f"Запуск парсера в директории: {cwd}")
        
        # Ищем файлы для обработки
        pdf_files = []
        excel_files = []
        
        for file in os.listdir(cwd):
            if file.lower().endswith('.pdf'):
                pdf_files.append(file)
            elif file.lower().endswith(('.xls', '.xlsx')):
                excel_files.append(file)
        
        if not pdf_files and not excel_files:
            logger.warning("Не найдено файлов для обработки (PDF, XLS, XLSX)")
            return
        
        all_files = pdf_files + excel_files
        logger.info(f"Найдено файлов для обработки: {len(all_files)}")
        
        # Используем новую функцию process_documents
        results, elapsed_time, report, output_files = process_documents(
            work_dir=cwd,
            application_file=None,  # Пока не определяем заявку автоматически
            invoice_files=all_files,
            model=None  # Используем модель по умолчанию
        )
        
        # Преобразуем output_files для логирования
        json_file = output_files.get('json', '')
        report_file = output_files.get('report', '')
        card_file = output_files.get('card', '')
        
        logger.info(f"Обработка завершена за {elapsed_time:.2f} секунд")
        logger.info(f"Обработано файлов: {len(results)}")
        
        if json_file:
            logger.info(f"Создан JSON файл: {json_file}")
        if report_file:
            logger.info(f"Создан отчет: {report_file}")
        if card_file:
            logger.info(f"Создана карточка изделия: {card_file}")
        
        print(f"Обработка завершена успешно за {elapsed_time:.2f} секунд")
        print(f"Результаты сохранены в файлы: {json_file}, {report_file}, {card_file}")
        
    except Exception as e:
        logger.error(f"Ошибка при выполнении: {e}")
        print(f"Ошибка: {e}")
        sys.exit(1)


def send_email_with_attachments(to_emails: List[str], 
                               subject: str,
                               body: str,
                               attachment_paths: List[str]) -> bool:
    """
    Отправляет email с вложениями.
    
    Args:
        to_emails: Список адресов получателей
        subject: Тема письма
        body: Текст письма
        attachment_paths: Список путей к файлам-вложениям
        
    Returns:
        True если отправка успешна, False иначе
    """
    try:
        email_sender = UnifiedEmailSender()
        
        for to_email in to_emails:
            # Используем новый метод отправки
            email_sender.send_email(
                to_email=to_email,
                subject=subject,
                body=body,
                attachments=attachment_paths
            )
        
        logger.info(f"Письма успешно отправлены на {len(to_emails)} адресов")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка отправки email: {e}")
        return False


def process_files_in_directory(directory: str,
                              app_filename: Optional[str] = None,
                              invoice_filenames: Optional[List[str]] = None,
                              model: Optional[str] = None) -> Tuple[List, float, str, str, str, Optional[str]]:
    """
    Обрабатывает файлы в указанной директории.
    
    Args:
        directory: Путь к директории
        app_filename: Имя файла заявки
        invoice_filenames: Список имен файлов счетов
        model: Модель LLM для использования
        
    Returns:
        Результаты обработки
    """
    if not os.path.exists(directory):
        raise ParserError(f"Директория не существует: {directory}")
    
    if not invoice_filenames:
        # Автоматически находим файлы счетов
        invoice_filenames = []
        for file in os.listdir(directory):
            if file.lower().endswith(('.pdf', '.xls', '.xlsx')):
                invoice_filenames.append(file)
    
    return process_documents(
        work_dir=directory,
        application_file=app_filename,
        invoice_files=invoice_filenames,
        model=model,
    )


# Обратная совместимость - экспортируем основные функции из lib/
def parse_project_folder(folder_path: str):
    """Обратная совместимость для парсинга информации о проекте."""
    from lib.utils import parse_project_folder as lib_parse_project_folder
    return lib_parse_project_folder(folder_path)


def replace_supplier_name(supplier_name: str) -> str:
    """Обратная совместимость для нормализации имен поставщиков."""
    from lib.utils import replace_supplier_name as lib_replace_supplier_name
    return lib_replace_supplier_name(supplier_name)


def query_openrouter(prompt: str, model: Optional[str] = None) -> str:
    """Обратная совместимость для запросов к LLM."""
    from lib.llm_client import LLMClient
    client = LLMClient()
    return client.query(prompt, model)


def extract_json_from_llm_response(response: str) -> str:
    """Обратная совместимость для извлечения JSON из ответа LLM."""
    from lib.llm_client import LLMClient
    client = LLMClient()
    json_data = client.extract_json_from_response(response)
    import json
    return json.dumps(json_data, ensure_ascii=False)


if __name__ == "__main__":
    main()
