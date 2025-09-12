"""
Упрощенный процессор данных для Parser.

Консолидирует всю логику обработки документов в простые функции
следуя принципу KISS.
"""

import os
import time
import json
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from jinja2 import Template

from lib.file_parser import parse_file
from lib.text_processor import clean_text
from lib.llm_client import extract_multiple_documents, generate_comparison_report
from lib.utils import (
    parse_project_folder, replace_supplier_name, compare_items, 
    to_str, ParserError, simple_retry
)
from logging_setup import get_logger
import config

logger = get_logger(__name__)


def process_files(file_paths: List[str]) -> List[str]:
    """
    Обрабатывает список файлов.
    
    Args:
        file_paths: Список путей к файлам
        
    Returns:
        Список извлеченного текста из файлов
    """
    results = []
    
    for file_path in file_paths:
        try:
            # Парсим файл
            content = parse_file(file_path)
            if content:
                # Очищаем текст
                cleaned = clean_text(content)
                results.append(cleaned)
                logger.debug(f"Обработан файл: {os.path.basename(file_path)}")
            else:
                logger.warning(f"Пустой контент для файла: {file_path}")
                results.append("")
        except Exception as e:
            logger.error(f"Ошибка обработки файла {file_path}: {e}")
            results.append("")
    
    logger.info(f"Обработано {len(file_paths)} файлов, успешных: {sum(1 for r in results if r)}")
    return results


def extract_document_data(file_contents: List[Tuple[str, str]], model: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Извлекает структурированные данные из содержимого документов через LLM.
    
    Args:
        file_contents: Список кортежей (имя_файла, содержимое)
        model: Модель LLM для использования
        
    Returns:
        Список словарей с извлеченными данными
    """
    if not file_contents:
        return []
    
    try:
        # Подготавливаем документы для LLM
        documents = [{'filename': filename, 'text': content} 
                    for filename, content in file_contents]
        
        # Используем retry для устойчивости
        def llm_extraction():
            return extract_multiple_documents(documents)
        
        results = simple_retry(llm_extraction, max_attempts=3, delay=2.0)
        
        logger.info(f"LLM извлек данные из {len(file_contents)} документов")
        return results or []
        
    except Exception as e:
        logger.error(f"Ошибка извлечения данных через LLM: {e}")
        return []


def enrich_with_project_info(data_list: List[Dict[str, Any]], project_dir: str) -> List[Dict[str, Any]]:
    """
    Обогащает данные информацией о проекте.
    
    Args:
        data_list: Список данных документов
        project_dir: Директория проекта
        
    Returns:
        Обогащенные данные
    """
    project_info = parse_project_folder(project_dir)
    enriched_results = []
    
    for data in data_list:
        if not data:
            continue
            
        # Создаем копию для изменения
        enriched = data.copy()
        
        # Адаптируем ключи LLM к русским (для совместимости)
        enriched = adapt_llm_keys(enriched)
        
        # Добавляем информацию о проекте
        proj_number = project_info.get('номер') or project_info.get('номер_договора')
        enriched.update({
            'номер': proj_number,
            'номер_договора': project_info.get('номер_договора') or proj_number,
            'заказчик': project_info.get('заказчик'),
            'адрес': project_info.get('адрес'),
            'изделие': project_info.get('изделие')
        })
        
        # Нормализуем имя поставщика
        if 'поставщик' in enriched:
            original_supplier = enriched['поставщик']
            normalized_supplier = replace_supplier_name(original_supplier)
            if normalized_supplier != original_supplier:
                enriched['поставщик'] = normalized_supplier
                logger.debug(f"Нормализовано имя поставщика: '{original_supplier}' -> '{normalized_supplier}'")
        
        enriched_results.append(enriched)
    
    return enriched_results


def adapt_llm_keys(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Адаптирует ключи из схемы LLM к русским ключам.
    
    Args:
        data: Данные с английскими ключами
        
    Returns:
        Данные с русскими ключами
    """
    try:
        adapted = dict(data) if isinstance(data, dict) else {}
        
        # Номер счета
        if 'number' in data and not adapted.get('номер_счета'):
            adapted['номер_счета'] = data['number']
        
        # Поставщик
        if 'supplier' in data and not adapted.get('поставщик'):
            supplier = data['supplier']
            if isinstance(supplier, dict):
                adapted['поставщик'] = supplier.get('name', '')
            elif isinstance(supplier, str):
                adapted['поставщик'] = supplier
        
        # Сумма
        if 'total' in data and not adapted.get('сумма'):
            total = data['total']
            if isinstance(total, dict):
                adapted['сумма'] = total.get('amount')
            else:
                adapted['сумма'] = total
        
        return adapted
    except Exception:
        return data


def generate_report(app_data: Optional[Dict[str, Any]], 
                   invoice_data: Optional[Dict[str, Any]], 
                   app_filename: str = "", 
                   invoice_filename: str = "",
                   use_llm: bool = False) -> str:
    """
    Генерирует отчет сравнения.
    
    Args:
        app_data: Данные заявки
        invoice_data: Данные счета
        app_filename: Имя файла заявки
        invoice_filename: Имя файла счета
        use_llm: Использовать LLM для генерации отчета
        
    Returns:
        Содержимое отчета или сообщение об ошибке
    """
    if not app_data or not invoice_data:
        return "Недостаточно данных для сравнения"
    
    try:
        if use_llm:
            # Генерируем отчет через LLM
            try:
                template_path = config.get_template_path()
                with open(template_path, 'r', encoding='utf-8') as f:
                    template_text = f.read()
                
                context = {
                    'app_name': app_filename or 'Заявка',
                    'inv_name': invoice_filename or 'Счет',
                    'application': app_data,
                    'invoice': invoice_data,
                }
                
                return generate_comparison_report(template_text, context)
            
            except FileNotFoundError as e:
                logger.error(f"Ошибка генерации отчета: {e}")
                return f"Отчет не может быть сгенерирован: {e}"
        else:
            # Локальная генерация отчета
            comparison = compare_items(app_data, invoice_data)
            return generate_local_report(
                app_filename or 'Заявка',
                invoice_filename or 'Счет',
                comparison.get('matches', []),
                comparison.get('only_in_app', []),
                comparison.get('only_in_inv', [])
            )
            
    except Exception as e:
        logger.error(f"Ошибка генерации отчета: {e}")
        return f"Ошибка генерации отчета: {e}"


def generate_local_report(app_name: str, inv_name: str, 
                         matches: List[Dict], only_in_app: List[Dict], 
                         only_in_inv: List[Dict]) -> str:
    """
    Генерирует отчет локально через Jinja2.
    
    Args:
        app_name: Имя файла заявки
        inv_name: Имя файла счета
        matches: Совпадающие позиции
        only_in_app: Позиции только в заявке
        only_in_inv: Позиции только в счете
        
    Returns:
        Содержимое отчета или сообщение об ошибке
    """
    try:
        template_path = config.get_template_path()
        with open(template_path, 'r', encoding='utf-8') as f:
            template_text = f.read()
        
        context = {
            'app_name': app_name,
            'inv_name': inv_name,
            'matches': matches,
            'only_in_app': only_in_app,
            'only_in_inv': only_in_inv,
        }
        
        template = Template(template_text)
        return template.render(**context)
    
    except FileNotFoundError as e:
        logger.error(f"Ошибка локального рендеринга отчета: {e}")
        return f"Отчет не может быть сгенерирован: {e}"
    except Exception as e:
        logger.error(f"Ошибка локального рендеринга отчета: {e}")
        return f"Ошибка генерации отчета: {e}"


def generate_product_card(results: List[Dict[str, Any]]) -> str:
    """
    Генерирует карточку изделия.
    
    Args:
        results: Результаты обработки счетов
        
    Returns:
        Содержимое карточки
    """
    if not results:
        return ""
    
    lines = ["КАРТОЧКА ИЗДЕЛИЯ\n", "=" * 50, ""]
    
    # Информация о проекте из первого счета
    first_result = results[0]
    if 'номер' in first_result:
        lines.append(f"Номер проекта: {first_result['номер']}")
    if 'заказчик' in first_result:
        lines.append(f"Заказчик: {first_result['заказчик']}")
    if 'адрес' in first_result:
        lines.append(f"Адрес: {first_result['адрес']}")
    if 'изделие' in first_result:
        lines.append(f"Изделие: {first_result['изделие']}")
    
    lines.append("")
    lines.append("СЧЕТА:")
    lines.append("-" * 30)
    
    total_sum = 0
    for i, result in enumerate(results, 1):
        lines.append(f"\n{i}. Счет от {result.get('поставщик', 'Неизвестно')}")
        if 'номер_счета' in result:
            lines.append(f"   Номер: {result['номер_счета']}")
        if 'дата' in result:
            lines.append(f"   Дата: {result['дата']}")
        if 'сумма' in result:
            try:
                amount_str = to_str(result['сумма']).replace(',', '.').replace(' ', '')
                amount = float(amount_str)
                total_sum += amount
                lines.append(f"   Сумма: {amount:,.2f} руб.")
            except (ValueError, TypeError):
                lines.append(f"   Сумма: {result['сумма']}")
    
    if total_sum > 0:
        lines.append(f"\nОБЩАЯ СУММА: {total_sum:,.2f} руб.")
    
    lines.append(f"\nДата формирования: {time.strftime('%d.%m.%Y %H:%M')}")
    
    return "\n".join(lines)


def save_results(output_dir: str, results: List[Dict[str, Any]], 
                report_content: str, file_names: List[str] = None) -> Dict[str, str]:
    """
    Сохраняет результаты в файлы.
    
    Args:
        output_dir: Директория для сохранения
        results: Результаты обработки
        report_content: Содержимое отчета
        file_names: Имена исходных файлов
        
    Returns:
        Словарь с путями к созданным файлам
    """
    output_files = {}
    
    try:
        # Сохраняем JSON результаты
        if results:
            if file_names and len(file_names) == len(results):
                # Отдельный файл для каждого документа
                json_files = []
                for result, file_name in zip(results, file_names):
                    base_name = os.path.splitext(file_name)[0]
                    json_filename = f"{base_name}_extracted.json"
                    json_path = os.path.join(output_dir, json_filename)
                    
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    
                    json_files.append(json_filename)
                    logger.debug(f"Сохранен JSON: {json_filename}")
                
                output_files['json_files'] = json_files
                output_files['json_file'] = json_files[0] if json_files else ""
            else:
                # Один файл для всех результатов
                json_filename = "extracted_results.json"
                json_path = os.path.join(output_dir, json_filename)
                
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)
                
                output_files['json_file'] = json_filename
                logger.info(f"Сохранен JSON: {json_filename}")
        
        # Сохраняем отчет
        if report_content:
            report_filename = "comparison_report.md"
            report_path = os.path.join(output_dir, report_filename)
            
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report_content)
            
            output_files['report_file'] = report_filename
            logger.debug(f"Сохранен отчет: {report_filename}")
        
        # Генерируем и сохраняем карточку изделия
        if results:
            card_content = generate_product_card(results)
            if card_content:
                card_filename = "Карточка изделия.txt"
                card_path = os.path.join(output_dir, card_filename)
                
                with open(card_path, 'w', encoding='utf-8') as f:
                    f.write(card_content)
                
                output_files['card_file'] = card_filename
                logger.debug(f"Сохранена карточка: {card_filename}")
    
    except Exception as e:
        logger.error(f"Ошибка сохранения результатов: {e}")
    
    return output_files


def process_documents(work_dir: str, 
                     application_file: Optional[str] = None,
                     invoice_files: List[str] = None,
                     model: Optional[str] = None,
                     use_llm_report: bool = False) -> Tuple[List[Dict], float, str, Dict[str, str]]:
    """
    Основная функция обработки документов.
    
    Args:
        work_dir: Рабочая директория
        application_file: Имя файла заявки (опционально)
        invoice_files: Список имен файлов счетов
        model: Модель LLM
        use_llm_report: Использовать LLM для отчета
        
    Returns:
        Кортеж: (результаты, время_выполнения, отчет, файлы_вывода)
    """
    start_time = time.time()
    logger.info(f"Начинаем обработку документов в {work_dir}")
    
    try:
        # Определяем файлы для обработки
        files_to_process = []
        file_names = []
        
        if application_file:
            app_path = os.path.join(work_dir, application_file)
            files_to_process.append(app_path)
            file_names.append(application_file)
        
        if invoice_files:
            for inv_file in invoice_files:
                inv_path = os.path.join(work_dir, inv_file)
                files_to_process.append(inv_path)
                file_names.append(inv_file)
        
        if not files_to_process:
            raise ValueError("Не указаны файлы для обработки")
        
        # Обрабатываем файлы
        logger.info(f"Обработка {len(files_to_process)} файлов")
        file_contents_list = process_files(files_to_process)
        
        # Подготавливаем данные для LLM
        file_contents = [(name, content) for name, content in zip(file_names, file_contents_list) if content]
        
        if not file_contents:
            raise RuntimeError("Не удалось извлечь содержимое из файлов")
        
        # Извлекаем данные через LLM
        logger.info("Отправка данных в LLM для извлечения")
        extracted_data = extract_document_data(file_contents, model)
        
        if not extracted_data:
            raise RuntimeError("LLM не вернул данных")
        
        # Обогащаем данные информацией о проекте
        enriched_data = enrich_with_project_info(extracted_data, work_dir)
        
        # Генерируем отчет (только для сценария заявка + счет)
        report_content = ""
        if application_file and invoice_files and len(invoice_files) == 1 and len(enriched_data) >= 2:
            app_data = enriched_data[0]  # Первый документ - заявка
            inv_data = enriched_data[1]  # Второй документ - счет
            
            report_content = generate_report(
                app_data, inv_data, application_file, invoice_files[0], use_llm_report)
        
        # Сохраняем результаты
        output_files = save_results(work_dir, enriched_data, report_content, file_names)
        
        elapsed_time = time.time() - start_time
        logger.info(f"Обработка завершена за {elapsed_time:.2f} секунд")
        
        return enriched_data, elapsed_time, report_content, output_files
        
    except Exception as e:
        logger.error(f"Ошибка обработки документов: {e}")
        elapsed_time = time.time() - start_time
        error_msg = f"Ошибка: {e}"
        return [], elapsed_time, error_msg, {}