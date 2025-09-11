"""Обновленный основной модуль parser.py с новой архитектурой."""

import os
import sys
from typing import List, Optional, Tuple

# Импорты новой архитектуры
from services.pipeline import run_processing
from email_service import EmailSender
from core.exceptions import ParserError
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
        
        # Запускаем обработку
        results, elapsed_time, report, json_file, report_file, card_file = run_processing(
            cwd=cwd,
            app_fname_selected=None,  # Пока не определяем заявку автоматически
            invoice_filenames_selected=all_files,
            model=None  # Используем модель по умолчанию
        )
        
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
        email_sender = EmailSender()
        
        for to_email in to_emails:
            # Используем корректный метод отправки с вложениями
            email_sender.send_email_with_attachments(
                subject=subject,
                body=body,
                to_email=to_email,
                attachment_paths=attachment_paths,
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
    
    return run_processing(
        cwd=directory,
        app_fname_selected=app_filename,
        invoice_filenames_selected=invoice_filenames,
        model=model,
    )


# Обратная совместимость - экспортируем основные функции из старого API
def parse_project_folder(folder_path: str):
    """Обратная совместимость для парсинга информации о проекте."""
    from core import parse_project_folder as core_parse_project_folder
    return core_parse_project_folder(folder_path)


def replace_supplier_name(supplier_name: str) -> str:
    """Обратная совместимость для нормализации имен поставщиков."""
    from core import replace_supplier_name as core_replace_supplier_name
    return core_replace_supplier_name(supplier_name)


def query_openrouter(prompt: str, model: Optional[str] = None) -> str:
    """Обратная совместимость для запросов к LLM."""
    from llm import LLMClient
    client = LLMClient()
    return client.query(prompt, model)


def extract_json_from_llm_response(response: str) -> str:
    """Обратная совместимость для извлечения JSON из ответа LLM."""
    from llm import LLMClient
    client = LLMClient()
    json_data = client.extract_json_from_response(response)
    import json
    return json.dumps(json_data, ensure_ascii=False)


if __name__ == "__main__":
    main()
