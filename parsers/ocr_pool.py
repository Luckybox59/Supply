"""Пул воркеров для OCR обработки с предварительной обработкой изображений."""

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple, Union, Any
import threading
from logging_setup import get_logger, get_performance_logger
import config
from core.exceptions import PDFParsingError
from core.retry import retry_with_backoff
import easyocr

logger = get_logger(__name__)
perf_logger = get_performance_logger(__name__)


class ImagePreprocessor:
    """Класс для предварительной обработки изображений перед OCR."""
    
    @staticmethod
    def enhance_image(image: Image.Image, 
                     contrast: float = 1.2,
                     brightness: float = 1.1,
                     sharpness: float = 1.1) -> Image.Image:
        """
        Улучшает качество изображения для лучшего OCR.
        
        Args:
            image: Исходное изображение
            contrast: Коэффициент контрастности (1.0 = без изменений)
            brightness: Коэффициент яркости
            sharpness: Коэффициент резкости
            
        Returns:
            Обработанное изображение
        """
        # Конвертируем в RGB если нужно
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Применяем улучшения
        if contrast != 1.0:
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(contrast)
        
        if brightness != 1.0:
            enhancer = ImageEnhance.Brightness(image)
            image = enhancer.enhance(brightness)
        
        if sharpness != 1.0:
            enhancer = ImageEnhance.Sharpness(image)
            image = enhancer.enhance(sharpness)
        
        return image
    
    @staticmethod
    def resize_if_needed(image: Image.Image, 
                        max_width: int = 2000,
                        max_height: int = 2000) -> Image.Image:
        """
        Изменяет размер изображения если оно слишком большое.
        
        Args:
            image: Исходное изображение
            max_width: Максимальная ширина
            max_height: Максимальная высота
            
        Returns:
            Изображение с подходящим размером
        """
        width, height = image.size
        
        if width <= max_width and height <= max_height:
            return image
        
        # Вычисляем коэффициент масштабирования
        scale_w = max_width / width
        scale_h = max_height / height
        scale = min(scale_w, scale_h)
        
        new_width = int(width * scale)
        new_height = int(height * scale)
        
        logger.debug(f"Изменение размера изображения: {width}x{height} -> {new_width}x{new_height}")
        return image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    @staticmethod
    def apply_filters(image: Image.Image, denoise: bool = True) -> Image.Image:
        """
        Применяет фильтры для улучшения качества текста.
        
        Args:
            image: Исходное изображение
            denoise: Применять ли шумоподавление
            
        Returns:
            Отфильтрованное изображение
        """
        if denoise:
            # Легкое размытие для удаления шума
            image = image.filter(ImageFilter.MedianFilter(size=3))
        
        return image
    
    @classmethod
    def preprocess_for_ocr(cls, image: Image.Image) -> Image.Image:
        """
        Полная предварительная обработка изображения для OCR.
        
        Args:
            image: Исходное изображение
            
        Returns:
            Обработанное изображение
        """
        # Изменяем размер если нужно
        image = cls.resize_if_needed(
            image,
            max_width=getattr(config, 'OCR_MAX_WIDTH', 2000),
            max_height=getattr(config, 'OCR_MAX_HEIGHT', 2000)
        )
        
        # Улучшаем качество
        image = cls.enhance_image(
            image,
            contrast=getattr(config, 'OCR_CONTRAST', 1.2),
            brightness=getattr(config, 'OCR_BRIGHTNESS', 1.1),
            sharpness=getattr(config, 'OCR_SHARPNESS', 1.1)
        )
        
        # Применяем фильтры
        image = cls.apply_filters(image, denoise=getattr(config, 'OCR_DENOISE', True))
        
        return image


class OCRWorker:
    """Воркер для выполнения OCR в отдельном потоке."""
    
    def __init__(self, worker_id: int):
        self.worker_id = worker_id
        self._reader: Optional[easyocr.Reader] = None
        self.processed_count = 0
    
    def get_reader(self) -> easyocr.Reader:
        """Ленивая инициализация OCR reader для воркера."""
        if self._reader is None:
            logger.info(f"Инициализация EasyOCR Reader для воркера {self.worker_id}")
            langs = [s.strip() for s in getattr(config, 'OCR_LANGS', 'ru,en').split(',') if s.strip()]
            self._reader = easyocr.Reader(langs)
        return self._reader
    
    @retry_with_backoff(max_attempts=2, base_delay=1.0)
    def process_image(self, image: Union[Image.Image, np.ndarray], 
                     preprocess: bool = True) -> List[str]:
        """
        Обрабатывает изображение через OCR.
        
        Args:
            image: Изображение для обработки
            preprocess: Применять ли предварительную обработку
            
        Returns:
            Список распознанных текстовых блоков
        """
        perf_logger.start_timer(f"ocr_worker_{self.worker_id}")
        
        try:
            # Предварительная обработка если нужна
            if preprocess and isinstance(image, Image.Image):
                image = ImagePreprocessor.preprocess_for_ocr(image)
            
            # Конвертируем в numpy array если нужно
            if isinstance(image, Image.Image):
                image_array = np.array(image)
            else:
                image_array = image
            
            # Выполняем OCR
            reader = self.get_reader()
            result = reader.readtext(
                image_array,
                detail=getattr(config, 'OCR_DETAIL', 0),
                paragraph=getattr(config, 'OCR_PARAGRAPH', True)
            )
            
            self.processed_count += 1
            logger.debug(f"Воркер {self.worker_id} обработал изображение, найдено {len(result)} блоков текста")
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка OCR в воркере {self.worker_id}: {e}")
            raise PDFParsingError("", f"Ошибка OCR обработки: {e}", original_error=e)
        finally:
            perf_logger.end_timer(f"ocr_worker_{self.worker_id}")


class OCRPool:
    """Пул воркеров для параллельной OCR обработки."""
    
    def __init__(self, max_workers: int = 2, use_preprocessing: bool = True):
        """
        Инициализация пула OCR воркеров.
        
        Args:
            max_workers: Максимальное количество воркеров
            use_preprocessing: Использовать предварительную обработку изображений
        """
        self.max_workers = max_workers
        self.use_preprocessing = use_preprocessing
        self._executor: Optional[ThreadPoolExecutor] = None
        self._workers: List[OCRWorker] = []
        self._lock = threading.Lock()
        
        logger.info(f"Инициализирован OCR пул с {max_workers} воркерами")
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
    
    def start(self) -> None:
        """Запускает пул воркеров."""
        with self._lock:
            if self._executor is not None:
                return
            
            self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
            self._workers = [OCRWorker(i) for i in range(self.max_workers)]
            logger.info(f"OCR пул запущен с {self.max_workers} воркерами")
    
    def shutdown(self) -> None:
        """Останавливает пул воркеров."""
        with self._lock:
            if self._executor is not None:
                self._executor.shutdown(wait=True)
                self._executor = None
                
                # Логируем статистику
                total_processed = sum(w.processed_count for w in self._workers)
                logger.info(f"OCR пул остановлен. Обработано изображений: {total_processed}")
                self._workers.clear()
    
    def process_images(self, images: List[Union[Image.Image, np.ndarray]]) -> List[str]:
        """
        Обрабатывает список изображений параллельно.
        
        Args:
            images: Список изображений для обработки
            
        Returns:
            Список объединенных текстов
        """
        if not images:
            return []
        
        if self._executor is None:
            raise RuntimeError("OCR пул не запущен. Используйте start() или контекстный менеджер.")
        
        perf_logger.start_timer("ocr_pool_batch")
        
        try:
            # Распределяем изображения по воркерам
            futures = []
            for i, image in enumerate(images):
                worker = self._workers[i % len(self._workers)]
                future = self._executor.submit(
                    worker.process_image, 
                    image, 
                    self.use_preprocessing
                )
                futures.append(future)
            
            # Собираем результаты
            all_texts = []
            for i, future in enumerate(as_completed(futures)):
                try:
                    texts = future.result()
                    all_texts.extend(texts)
                    logger.debug(f"Обработано изображение {i+1}/{len(images)}")
                except Exception as e:
                    logger.error(f"Ошибка обработки изображения {i+1}: {e}")
                    # Продолжаем обработку остальных изображений
            
            return all_texts
            
        finally:
            elapsed = perf_logger.end_timer("ocr_pool_batch", 
                                          images_count=len(images),
                                          texts_extracted=len(all_texts) if 'all_texts' in locals() else 0)
            logger.info(f"Пакетная OCR обработка завершена: {len(images)} изображений за {elapsed:.2f}с")
    
    def get_stats(self) -> dict:
        """Возвращает статистику работы пула."""
        with self._lock:
            if not self._workers:
                return {"active": False}
            
            return {
                "active": self._executor is not None,
                "max_workers": self.max_workers,
                "workers_count": len(self._workers),
                "total_processed": sum(w.processed_count for w in self._workers),
                "use_preprocessing": self.use_preprocessing
            }


# Глобальный пул для переиспользования
_global_ocr_pool: Optional[OCRPool] = None
_pool_lock = threading.Lock()


def get_global_ocr_pool(max_workers: int = 2, use_preprocessing: bool = True) -> OCRPool:
    """
    Получает глобальный пул OCR воркеров (singleton).
    
    Args:
        max_workers: Максимальное количество воркеров
        use_preprocessing: Использовать предварительную обработку
        
    Returns:
        Глобальный OCR пул
    """
    global _global_ocr_pool
    
    with _pool_lock:
        if _global_ocr_pool is None:
            _global_ocr_pool = OCRPool(max_workers, use_preprocessing)
            _global_ocr_pool.start()
        
        return _global_ocr_pool


def shutdown_global_ocr_pool() -> None:
    """Останавливает глобальный OCR пул."""
    global _global_ocr_pool
    
    with _pool_lock:
        if _global_ocr_pool is not None:
            _global_ocr_pool.shutdown()
            _global_ocr_pool = None
