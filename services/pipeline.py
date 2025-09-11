"""Обновленный пайплайн обработки документов с новой архитектурой."""

import os
import time
import concurrent.futures as futures
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

# New modular imports
from parsers import PDFParser, ExcelParser, TextCleaner
from llm import LLMClient, PromptBuilder
from core import parse_project_folder, replace_supplier_name, compare_items
from core.exceptions import ParserError, PDFParsingError, ExcelParsingError, LLMError
from core.retry import retry_with_backoff, llm_retry
from services import artifacts
from logging_setup import get_logger, get_performance_logger
import config
from models.schemas import Invoice, validate_invoices
from jinja2 import Template

logger = get_logger(__name__)
perf_logger = get_performance_logger(__name__)


class ProcessingPipeline:
    """Основной пайплайн обработки документов."""
    
    def __init__(self):
        """Инициализация пайплайна с новыми компонентами."""
        self.pdf_parser = PDFParser()
        self.excel_parser = ExcelParser()
        self.text_cleaner = TextCleaner()
        self.llm_client = LLMClient()
        self.prompt_builder = PromptBuilder()
        logger.debug("Инициализирован пайплайн обработки с новой архитектурой")
    
    def process_single_file(self, file_path: str) -> Optional[str]:
        """
        Обрабатывает один файл.
        
        Args:
            file_path: Путь к файлу
            
        Returns:
            Содержимое файла или None при ошибке
        """
        perf_logger.start_timer("single_file_processing")
        
        try:
            file_ext = Path(file_path).suffix.lower()
            
            if file_ext == '.pdf':
                content = self.pdf_parser.parse_pdf(file_path)
            elif file_ext in ['.xls', '.xlsx']:
                content = self.excel_parser.parse_excel(file_path)
            else:
                logger.warning(f"Неподдерживаемый тип файла: {file_ext}")
                return None
            
            if content:
                cleaned_content = self.text_cleaner.clean_text(content)
                elapsed = perf_logger.end_timer("single_file_processing", 
                                              file_path=file_path,
                                              file_type=file_ext)
                logger.debug(f"Файл {file_path} обработан за {elapsed:.3f}с")
                return cleaned_content
            
        except (PDFParsingError, ExcelParsingError) as e:
            logger.error(f"Ошибка парсинга файла {file_path}: {e}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при обработке {file_path}: {e}")
        
        perf_logger.end_timer("single_file_processing", success=False)
        return None
    
    def process_files_parallel(self, file_paths: List[str]) -> List[str]:
        """
        Параллельная обработка файлов.
        
        Args:
            file_paths: Список путей к файлам
            
        Returns:
            Список содержимого файлов
        """
        perf_logger.start_timer("parallel_processing")
        
        results = []
        max_workers = min(4, len(file_paths))  # Используем разумное значение по умолчанию
        
        with futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {
                executor.submit(self.process_single_file, path): path 
                for path in file_paths
            }
            
            for future in futures.as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                except Exception as e:
                    logger.error(f"Ошибка при обработке {path}: {e}")
        
        elapsed = perf_logger.end_timer("parallel_processing",
                                      files_count=len(file_paths),
                                      results_count=len(results))
        
        logger.info(f"Параллельная обработка {len(file_paths)} файлов завершена за {elapsed:.3f}с")
        return results
    
    @llm_retry
    def process_with_llm_batch(self, contents: List[str], model: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Обработка батча содержимого через LLM.
        
        Args:
            contents: Список содержимого файлов
            model: Модель для использования
            
        Returns:
            Список результатов от LLM
        """
        if not contents:
            return []
        
        perf_logger.start_timer("llm_batch_processing")
        
        try:
            # Создаем промпт для батча
            if len(contents) == 1:
                prompt = self.prompt_builder.build_single_invoice_prompt("batch_file", contents[0])
            else:
                # Создаем список файлов для multi-invoice промпта
                invoices = [{"filename": f"file_{i+1}", "text": content} 
                           for i, content in enumerate(contents)]
                prompt = self.prompt_builder.build_multi_invoice_prompt(invoices)
            
            # Отправляем запрос к LLM
            response = self.llm_client.query(prompt, model)
            
            # Извлекаем JSON из ответа
            json_results = self.llm_client.extract_json_from_response(response)
            
            # Валидируем результаты
            if json_results:
                valid_invoices = validate_invoices(json_results)
                elapsed = perf_logger.end_timer("llm_batch_processing",
                                              batch_size=len(contents),
                                              results_count=len(valid_invoices))
                logger.info(f"LLM обработал батч из {len(contents)} файлов за {elapsed:.3f}с")
                return valid_invoices
            
        except LLMError as e:
            logger.error(f"Ошибка LLM при обработке батча: {e}")
            raise
        except Exception as e:
            logger.error(f"Неожиданная ошибка при обработке LLM: {e}")
            raise LLMError(f"Ошибка обработки LLM: {e}")
        
        perf_logger.end_timer("llm_batch_processing", success=False)
        return []
    
    
    def process_with_llm_multi(self, file_contents: List[Tuple[str, str]], model: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Обрабатывает все файлы одним запросом к LLM, получая отдельные JSON на каждый файл.
        
        Args:
            file_contents: Список кортежей (filename, content)
            model: Модель LLM для использования
            
        Returns:
            Список результатов обработки (по одному JSON на файл)
        """
        if not file_contents:
            return []
        
        perf_logger.start_timer("multi_llm_processing")
        
        try:
            # Подготавливаем данные для промпта
            invoices = [{'filename': filename, 'text': content} for filename, content in file_contents]
            
            # Создаем промпт для всех файлов сразу
            prompt = self.prompt_builder.build_multi_invoice_prompt(invoices)
            
            # Отправляем запрос к LLM
            response = self.llm_client.query(prompt, model)
            
            # Извлекаем JSON из ответа
            json_results = self.llm_client.extract_json_from_response(response)
            
            # Валидируем результаты
            if json_results:
                valid_invoices = validate_invoices(json_results)
                elapsed = perf_logger.end_timer("multi_llm_processing",
                                              files_count=len(file_contents),
                                              results_count=len(valid_invoices))
                logger.info(f"LLM обработал {len(file_contents)} файлов одним запросом за {elapsed:.3f}с -> {len(valid_invoices)} результатов")
                return valid_invoices
            else:
                logger.warning("Пустой ответ от LLM")
                
        except LLMError as e:
            logger.error(f"Ошибка LLM при обработке файлов: {e}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при обработке LLM: {e}")
        
        perf_logger.end_timer("multi_llm_processing", success=False)
        return []
    


def enrich_invoice_data(invoice_data: Dict[str, Any], project_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Обогащает данные счета информацией о проекте.
    
    Args:
        invoice_data: Данные счета
        project_info: Информация о проекте
        
    Returns:
        Обогащенные данные счета
    """
    enriched = invoice_data.copy()
    
    # Добавляем информацию о проекте
    # Поддерживаем как ключ 'номер', так и 'номер_договора' из core.utils.parse_project_folder
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
            logger.debug("Нормализовано имя поставщика: '%s' -> '%s'", original_supplier, normalized_supplier)
    
    return enriched


def _adapt_llm_invoice_to_legacy(inv: Dict[str, Any]) -> Dict[str, Any]:
    """
    Приводит структуру счета из схемы LLM (number/supplier/total)
    к форме, ожидаемой downstream-логикой/GUI (русские ключи).

    Делает неглубокую копию и добавляет ключи:
    - 'номер_счета' из inv['number']
    - 'поставщик' из inv['supplier']['name']
    - 'сумма' из inv['total']['amount']
    Ничего не удаляет из оригинальной структуры.
    """
    try:
        adapted = dict(inv) if isinstance(inv, dict) else {}
        # Номер счета
        number = None
        try:
            number = inv.get('number')
        except Exception:
            number = None
        if number and not adapted.get('номер_счета'):
            adapted['номер_счета'] = number

        # Поставщик (строка) из supplier.name
        supplier_name = None
        try:
            supplier = inv.get('supplier') or {}
            if isinstance(supplier, dict):
                supplier_name = supplier.get('name')
            elif isinstance(supplier, str):
                supplier_name = supplier
        except Exception:
            supplier_name = None
        if supplier_name and not adapted.get('поставщик'):
            adapted['поставщик'] = supplier_name

        # Итоговая сумма из total.amount
        total_amount = None
        try:
            total = inv.get('total') or {}
            if isinstance(total, dict):
                total_amount = total.get('amount')
        except Exception:
            total_amount = None
        if total_amount is not None and not adapted.get('сумма'):
            adapted['сумма'] = total_amount

        return adapted
    except Exception:
        # В случае непредвиденной структуры — возвращаем как есть
        return inv


def generate_detailed_comparison_report(app_name: str, inv_name: str, 
                                     matches: list, only_in_app: list, only_in_inv: list,
                                     use_template_for_report: bool = False) -> str:
    """
    Генерирует детальный отчет сравнения заявки и счета.
    
    Args:
        app_name: Имя файла заявки
        inv_name: Имя файла счета
        matches: Совпадающие позиции
        only_in_app: Позиции только в заявке
        only_in_inv: Позиции только в счете
        
    Returns:
        Содержимое отчета
    """
    # Формируем отчет по одному и тому же Jinja2-шаблону:
    # локально или через LLM (по флагу use_template_for_report)
    template_path = getattr(config, 'REPORT_TEMPLATE_PATH', None) or os.path.join(os.path.dirname(os.path.dirname(__file__)), 'Шаблон отчета для Parser.md.j2')
    with open(template_path, 'r', encoding='utf-8') as f:
        template_text = f.read()

    context = {
        'app_name': app_name,
        'inv_name': inv_name,
        'matches': matches,
        'only_in_app': only_in_app,
        'only_in_inv': only_in_inv,
    }

    if use_template_for_report:
        # Рендерим через LLM по шаблону (одинаковый шаблон)
        try:
            llm_client = LLMClient()
            prompt_builder = PromptBuilder()
            prompt = prompt_builder.build_comparison_report_prompt(template_text, context)
            report = llm_client.query(prompt)
            logger.info("Отчет сравнения сгенерирован через LLM по Jinja2-шаблону")
            return report
        except Exception as e:
            logger.error(f"Ошибка генерации отчета через LLM: {e}")
            raise
    else:
        # Локальный рендер тем же шаблоном
        try:
            md = Template(template_text).render(**context)
            logger.info("Отчет сравнения сгенерирован локально по Jinja2-шаблону")
            return md
        except Exception as e:
            logger.error(f"Ошибка генерации отчета по шаблону: {e}")
            raise


def generate_llm_comparison_report_from_json(app_name: str,
                                             inv_name: str,
                                             app_json: Dict[str, Any],
                                             inv_json: Dict[str, Any]) -> str:
    """
    Генерирует отчет сравнения через LLM, передавая два готовых JSON (заявка и счет)
    и один и тот же Jinja2-шаблон. Возвращает финальный Markdown, сгенерированный LLM.
    """
    # Читаем текст шаблона (тот же файл)
    template_path = getattr(config, 'REPORT_TEMPLATE_PATH', None) or os.path.join(os.path.dirname(os.path.dirname(__file__)), 'Шаблон отчета для Parser.md.j2')
    with open(template_path, 'r', encoding='utf-8') as f:
        template_text = f.read()

    # Контекст, который получит LLM; он не обязан совпадать со структурой локального шаблон-рендера
    context = {
        'app_name': app_name,
        'inv_name': inv_name,
        'application': app_json,
        'invoice': inv_json,
    }

    llm_client = LLMClient()
    prompt_builder = PromptBuilder()
    prompt = prompt_builder.build_comparison_report_prompt(template_text, context)
    report_md = llm_client.query(prompt)
    logger.info("Отчет сравнения (LLM) сформирован на основе двух JSON и шаблона")
    return report_md


def generate_comparison_report(app_data: str, invoice_results: List[Dict[str, Any]], use_template_for_report: bool = False) -> str:
    """
    Генерирует отчет сравнения заявки и счетов.
    
    Args:
        app_data: Данные заявки
        invoice_results: Результаты обработки счетов
        
    Returns:
        Содержимое отчета
    """
    template_path = getattr(config, 'REPORT_TEMPLATE_PATH', None) or os.path.join(os.path.dirname(os.path.dirname(__file__)), 'Шаблон отчета для Parser.md.j2')
    with open(template_path, 'r', encoding='utf-8') as f:
        template_text = f.read()

    context = {
        'app_name': 'Заявка',
        'inv_name': 'Счета',
        'matches': [],
        'only_in_app': [],
        'only_in_inv': [],
        'raw': {
            'application': app_data,
            'invoices': invoice_results,
        }
    }

    if use_template_for_report:
        try:
            llm_client = LLMClient()
            prompt_builder = PromptBuilder()
            prompt = prompt_builder.build_comparison_report_prompt(template_text, context)
            report = llm_client.query(prompt)
            logger.info("Отчет сгенерирован через LLM по Jinja2-шаблону")
            return report
        except Exception as e:
            logger.error(f"Ошибка генерации отчета через LLM: {e}")
            raise
    else:
        try:
            md = Template(template_text).render(**context)
            logger.info("Отчет сгенерирован локально по Jinja2-шаблону")
            return md
        except Exception as e:
            logger.error(f"Ошибка генерации отчета по шаблону: {e}")
            raise


def save_results(cwd: str, results: List[Dict[str, Any]], report_content: str, 
                file_names: List[str] = None) -> Dict[str, str]:
    """
    Сохраняет результаты обработки в файлы.
    
    Args:
        cwd: Рабочая директория
        results: Результаты обработки
        report_content: Содержимое отчета
        
    Returns:
        Словарь с путями к созданным файлам
    """
    output_files = {}
    
    try:
        # Сохраняем JSON результаты - отдельный файл для каждого документа
        if results and file_names:
            import json
            json_files = []
            
            for i, (result, file_name) in enumerate(zip(results, file_names)):
                # Создаем имя JSON файла на основе исходного файла
                base_name = os.path.splitext(file_name)[0]
                json_filename = f"{base_name}_extracted.json"
                json_path = os.path.join(cwd, json_filename)
                
                # Сохраняем отдельный JSON для каждого файла
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                
                artifacts.register(json_path)
                json_files.append(json_filename)
                logger.debug(f"Сохранен JSON файл: {json_filename}")
            
            output_files['json_files'] = json_files
            output_files['json_file'] = json_files[0] if json_files else ""  # Для обратной совместимости
        elif results:
            # Fallback: сохраняем все в один файл если нет информации о файлах
            import json
            json_filename = "invoices_extracted.json"
            json_path = os.path.join(cwd, json_filename)
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            
            artifacts.register(json_path)
            output_files['json_file'] = json_filename
            logger.info(f"Сохранен JSON файл: {json_filename}")
        
        # Сохраняем отчет
        if report_content:
            report_filename = "comparison_report.md"
            report_path = os.path.join(cwd, report_filename)
            
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report_content)
            
            artifacts.register(report_path)
            output_files['report_file'] = report_filename
            logger.debug(f"Сохранен отчет: {report_filename}")
        
        # Генерируем карточку изделия
        if results:
            card_content = generate_product_card(results)
            if card_content:
                card_filename = "Карточка изделия.txt"
                card_path = os.path.join(cwd, card_filename)
                
                with open(card_path, 'w', encoding='utf-8') as f:
                    f.write(card_content)
                
                artifacts.register(card_path)
                output_files['card_file'] = card_filename
                logger.debug(f"Сохранена карточка изделия: {card_filename}")
    
    except Exception as e:
        logger.error(f"Ошибка сохранения результатов: {e}")
    
    return output_files


def generate_product_card(results: List[Dict[str, Any]]) -> str:
    """
    Генерирует карточку изделия на основе результатов.
    
    Args:
        results: Результаты обработки счетов
        
    Returns:
        Содержимое карточки изделия
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
                amount = float(str(result['сумма']).replace(',', '.').replace(' ', ''))
                total_sum += amount
                lines.append(f"   Сумма: {amount:,.2f} руб.")
            except (ValueError, TypeError):
                lines.append(f"   Сумма: {result['сумма']}")
    
    if total_sum > 0:
        lines.append(f"\nОБЩАЯ СУММА: {total_sum:,.2f} руб.")
    
    lines.append(f"\nДата формирования: {time.strftime('%d.%m.%Y %H:%M')}")
    
    return "\n".join(lines)


def run_processing(
    cwd: str,
    app_fname_selected: Optional[str],
    invoice_filenames_selected: List[str],
    model: Optional[str] = None,
    use_template_for_report: bool = False,
) -> Tuple[list, float, str, str, str, Optional[str]]:
    """
    Основная функция обработки файлов с новой архитектурой.
    
    Args:
        cwd: Рабочая директория
        app_fname_selected: Имя файла заявки
        invoice_filenames_selected: Список имен файлов счетов
        model: Модель LLM для использования
        
        
    Returns:
        Кортеж с результатами обработки
    """
    start_time = time.time()
    
    # Clear artifacts from previous runs
    artifacts.clear()
    
    # Уменьшаем шум: начальные параметры пишем в debug
    logger.debug(f"Начинаем обработку в директории: {cwd}")
    logger.debug(f"Файл заявки: {app_fname_selected}")
    logger.debug(f"Файлы счетов: {invoice_filenames_selected}")
    
    # Инициализируем пайплайн
    pipeline = ProcessingPipeline()
    
    try:
        # Parse project info from folder name
        project_info = parse_project_folder(cwd)
        logger.debug(f"Информация о проекте: {project_info}")
        
        # Определяем сценарий обработки
        app_data = None
        invoice_data_list = []
        llm_results = []
        processed_file_names = []  # Список имен обработанных файлов
        
        # Сценарий 1: Заявка + 1 счет (сравнение)
        if app_fname_selected and len(invoice_filenames_selected) == 1:
            logger.debug("Сценарий: сравнение заявки и счета")
            
            # Обрабатываем заявку
            app_path = os.path.join(cwd, app_fname_selected)
            app_data = pipeline.process_single_file(app_path)
            if app_data:
                logger.debug(f"Обработан файл заявки: {app_fname_selected}")
            
            # Обрабатываем счет
            invoice_path = os.path.join(cwd, invoice_filenames_selected[0])
            invoice_data = pipeline.process_single_file(invoice_path)
            if invoice_data:
                logger.debug(f"Обработан файл счета: {invoice_filenames_selected[0]}")
                
                # Отправляем заявку и счет одним запросом в LLM
                file_contents = [
                    (app_fname_selected, app_data),
                    (invoice_filenames_selected[0], invoice_data)
                ]
                processed_file_names = [app_fname_selected, invoice_filenames_selected[0]]
                # Логируем время предобработки до отправки в LLM
                preprocess_elapsed = time.time() - start_time
                logger.info(f"Обработка файлов перед отправкой в LLM заняла {preprocess_elapsed:.2f}с")
                llm_results = pipeline.process_with_llm_multi(file_contents, model)
                logger.debug(f"Получено {len(llm_results)} результатов от LLM для сравнения")
        
        # Сценарий 2: Только счета (без заявки)
        elif invoice_filenames_selected and not app_fname_selected:
            logger.debug("Сценарий: обработка только счетов")
            
            # Обрабатываем файлы счетов параллельно
            invoice_paths = [os.path.join(cwd, fname) for fname in invoice_filenames_selected]
            invoice_data_list = pipeline.process_files_parallel(invoice_paths)
            logger.debug(f"Обработано {len(invoice_data_list)} файлов счетов")
            
            # Подготавливаем данные для LLM
            if invoice_data_list:
                file_contents = [(invoice_filenames_selected[i], content) 
                               for i, content in enumerate(invoice_data_list) if content]
                processed_file_names = [invoice_filenames_selected[i] 
                                      for i, content in enumerate(invoice_data_list) if content]
                
                # Отправляем все счета одним запросом в LLM (перед этим — лог тайминга предобработки)
                preprocess_elapsed = time.time() - start_time
                logger.info(f"Обработка файлов перед отправкой в LLM заняла {preprocess_elapsed:.2f}с")
                llm_results = pipeline.process_with_llm_multi(file_contents, model)
                logger.debug(f"Получено {len(llm_results)} результатов от LLM")
        
        # Сценарий 3: Некорректный выбор
        else:
            logger.warning("Некорректный выбор файлов: нужна либо заявка+1 счет, либо только счета")
            return [], 0, "Ошибка: некорректный выбор файлов", "", "", None
        
        # Enrich with project info and normalize supplier names
        enriched_results = []
        for result in llm_results:
            if result:
                # Преобразуем ключи к ожидаемым русским, чтобы корректно заполнялись письмо и карточка
                adapted = _adapt_llm_invoice_to_legacy(result)
                enriched = enrich_invoice_data(adapted, project_info)
                enriched_results.append(enriched)
        
        # Generate comparison report
        report_content = ""
        if app_fname_selected and len(invoice_filenames_selected) == 1 and llm_results:
            # Для сценария сравнения: первый результат - заявка, второй - счет
            if len(llm_results) >= 2:
                app_result = llm_results[0]  # Результат обработки заявки
                invoice_result = llm_results[1]  # Результат обработки счета
                
                if use_template_for_report:
                    # Вариант 1: LLM строит отчет по двум JSON с использованием шаблона
                    try:
                        report_content = generate_llm_comparison_report_from_json(
                            app_fname_selected,
                            invoice_filenames_selected[0],
                            app_result,
                            invoice_result,
                        )
                    except Exception as e:
                        logger.error(f"Ошибка LLM-генерации отчета: {e}")
                        report_content = f"Ошибка генерации отчета: {str(e)}"
                else:
                    # Вариант 2: локальная генерация — сравнение и рендер по шаблону
                    try:
                        cmp = compare_items(app_result, invoice_result)
                        matches = cmp.get('matches', [])
                        only_in_app = cmp.get('only_in_app', [])
                        only_in_inv = cmp.get('only_in_inv', [])

                        report_content = generate_detailed_comparison_report(
                            app_fname_selected, invoice_filenames_selected[0],
                            matches, only_in_app, only_in_inv,
                            use_template_for_report=False
                        )
                    except Exception as e:
                        logger.error(f"Ошибка локального сравнения файлов: {e}")
                        report_content = f"Ошибка сравнения: {str(e)}"
            else:
                logger.warning("Недостаточно результатов от LLM для сравнения")
                report_content = "Ошибка: недостаточно данных для сравнения"
        
        # Save results
        output_files = save_results(cwd, enriched_results, report_content, processed_file_names)
        
        elapsed_time = time.time() - start_time
        logger.info(f"Обработка завершена за {elapsed_time:.2f} секунд")
        
        return (
            enriched_results,
            elapsed_time,
            report_content,
            output_files.get('json_file', ''),
            output_files.get('report_file', ''),
            output_files.get('card_file')
        )
        
    except Exception as e:
        logger.error(f"Ошибка при обработке: {e}")
        elapsed_time = time.time() - start_time
        return [], elapsed_time, f"Ошибка: {str(e)}", "", "", None
