"""Модуль для парсинга PDF документов."""

import numpy as np
from pathlib import Path
from typing import Optional, List
import pdfplumber
from pdf2image import convert_from_path
import config
from logging_setup import get_logger, get_performance_logger
from core.exceptions import PDFParsingError
from core.retry import file_operation_retry
from .ocr_pool import get_global_ocr_pool

logger = get_logger(__name__)
perf_logger = get_performance_logger(__name__)


class PDFParser:
    """Класс для парсинга PDF документов с поддержкой OCR и пула воркеров."""
    
    @classmethod
    @file_operation_retry
    def parse_pdf(cls, file_path: str, use_ocr_pool: bool = True) -> str:
        """
        Парсит PDF файл, сначала пытается извлечь текст напрямую,
        при неудаче использует OCR с пулом воркеров.
        
        Args:
            file_path: Путь к PDF файлу
            use_ocr_pool: Использовать пул воркеров для OCR
            
        Returns:
            Извлеченный текст
            
        Raises:
            PDFParsingError: При ошибке парсинга файла
        """
        if not Path(file_path).exists():
            raise PDFParsingError(file_path, "Файл не найден")
        
        perf_logger.start_timer(f"pdf_parse_{Path(file_path).name}")
        
        try:
            # 1) Попытка через pdfplumber (текстовый PDF)
            text_plumber = cls._extract_text_with_pdfplumber(file_path)
            if text_plumber and len(text_plumber) > 10:
                logger.debug(f"PDF {file_path} успешно обработан через pdfplumber")
                return text_plumber
                
            # 2) Fallback: OCR
            logger.info(f"Переход к OCR для файла {file_path}")
            if use_ocr_pool:
                return cls._extract_text_with_ocr_pool(file_path)
            else:
                return cls._extract_text_with_ocr_legacy(file_path)
            
        except Exception as e:
            logger.error(f"Ошибка парсинга PDF {file_path}: {e}")
            raise PDFParsingError(file_path, f"Не удалось обработать PDF файл", original_error=e)
        finally:
            perf_logger.end_timer(f"pdf_parse_{Path(file_path).name}", file_path=file_path)
    
    @classmethod
    def _extract_text_with_pdfplumber(cls, file_path: str) -> str:
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
    
    @classmethod
    def _extract_text_with_ocr_pool(cls, file_path: str) -> str:
        """Извлекает текст из PDF через OCR с использованием пула воркеров."""
        try:
            # Конвертируем PDF в изображения
            poppler_path = getattr(config, 'POPPLER_PATH', None)
            images = convert_from_path(file_path, poppler_path=poppler_path, dpi=getattr(config, 'OCR_DPI', 200))
            
            if not images:
                raise PDFParsingError(file_path, "Не удалось конвертировать PDF в изображения")
            
            logger.info(f"Конвертировано {len(images)} страниц PDF в изображения")
            
            # Используем пул воркеров для OCR
            ocr_pool = get_global_ocr_pool(
                max_workers=getattr(config, 'OCR_POOL_WORKERS', 2),
                use_preprocessing=getattr(config, 'OCR_USE_PREPROCESSING', True)
            )
            all_texts = ocr_pool.process_images(images)
            
            result = '\n'.join(all_texts)
            logger.info(f"OCR пул обработал {len(images)} страниц, извлечено {len(result)} символов")
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка OCR пула для {file_path}: {e}")
            raise PDFParsingError(file_path, f"Ошибка OCR обработки", original_error=e)
    
    @classmethod
    def _extract_text_with_ocr_legacy(cls, file_path: str) -> str:
        """Извлекает текст из PDF через OCR (legacy метод без пула)."""
        try:
            import easyocr
            
            poppler_path = getattr(config, 'POPPLER_PATH', None)
            images = convert_from_path(
                file_path,
                poppler_path=poppler_path,
                dpi=getattr(config, 'OCR_DPI', 200)
            )
            
            # Создаем reader для этой операции
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
                    all_text.extend(result)
                    logger.debug(f"OCR обработана страница {i+1}/{len(images)}")
                except Exception as e:
                    logger.warning(f"Ошибка OCR на странице {i+1}: {e}")
                    continue
                    
            return '\n'.join(all_text)
            
        except Exception as e:
            logger.error(f"Ошибка legacy OCR для {file_path}: {e}")
            raise PDFParsingError(file_path, f"Ошибка legacy OCR обработки", original_error=e)
    
    @classmethod
    def parse_multiple_pdfs(cls, file_paths: List[str], use_ocr_pool: bool = True) -> List[str]:
        """
        Парсит несколько PDF файлов параллельно.
        
        Args:
            file_paths: Список путей к PDF файлам
            use_ocr_pool: Использовать пул воркеров
            
        Returns:
            Список извлеченных текстов
        """
        if not file_paths:
            return []
        
        perf_logger.start_timer("pdf_batch_parse")
        
        results = []
        for file_path in file_paths:
            try:
                text = cls.parse_pdf(file_path, use_ocr_pool)
                results.append(text)
            except Exception as e:
                logger.error(f"Ошибка парсинга {file_path}: {e}")
                results.append("")  # Добавляем пустую строку для сохранения порядка
        
        perf_logger.end_timer("pdf_batch_parse", 
                            files_count=len(file_paths),
                            successful_count=sum(1 for r in results if r))
        
        return results
