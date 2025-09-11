import logging
import logging.handlers
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import os

_DEFAULT_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_configured = False


class JSONFormatter(logging.Formatter):
    """Форматтер для структурированного JSON логирования."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Форматирует запись лога в JSON."""
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Добавляем информацию об исключении, если есть
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Добавляем дополнительные поля, если есть
        if hasattr(record, 'extra_data'):
            log_entry.update(record.extra_data)
            
        return json.dumps(log_entry, ensure_ascii=False)


class PerformanceLogger:
    """Логгер для метрик производительности."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._start_times: Dict[str, float] = {}
    
    def start_timer(self, operation: str) -> None:
        """Запускает таймер для операции."""
        self._start_times[operation] = time.perf_counter()
    
    def end_timer(self, operation: str, **extra_data) -> float:
        """Завершает таймер и логирует время выполнения."""
        if operation not in self._start_times:
            self.logger.warning(f"Таймер для операции '{operation}' не был запущен")
            return 0.0
        
        elapsed = time.perf_counter() - self._start_times[operation]
        del self._start_times[operation]
        
        # Логируем с дополнительными данными
        extra = {
            'operation': operation,
            'duration_seconds': elapsed,
            'performance_metric': True,
            **extra_data
        }
        
        # Создаем LogRecord с дополнительными данными
        record = self.logger.makeRecord(
            self.logger.name, logging.INFO, __file__, 0,
            f"Операция '{operation}' выполнена за {elapsed:.3f}с",
            (), None
        )
        record.extra_data = extra
        self.logger.handle(record)
        
        return elapsed
    
    def log_metric(self, metric_name: str, value: Any, **extra_data) -> None:
        """Логирует произвольную метрику."""
        extra = {
            'metric_name': metric_name,
            'metric_value': value,
            'performance_metric': True,
            **extra_data
        }
        
        record = self.logger.makeRecord(
            self.logger.name, logging.INFO, __file__, 0,
            f"Метрика {metric_name}: {value}",
            (), None
        )
        record.extra_data = extra
        self.logger.handle(record)
    
    def log_system_info(self, operation: str, **kwargs):
        """Логирует информацию о системе."""
        import psutil
        
        system_info = {
            'cpu_percent': psutil.cpu_percent(),
            'memory_percent': psutil.virtual_memory().percent,
            'disk_usage': psutil.disk_usage('/').percent if os.name != 'nt' else psutil.disk_usage('C:').percent
        }
        
        self.log_metric(operation, system_info=system_info, **kwargs)
    
    def log_memory_usage(self, operation: str, **kwargs):
        """Логирует использование памяти."""
        import psutil
        
        memory_info = {
            'memory_mb': psutil.virtual_memory().used / 1024 / 1024,
            'memory_percent': psutil.virtual_memory().percent
        }
        
        self.log_metric(operation, memory_usage=memory_info, **kwargs)


def setup_advanced_logging(
    level: int = logging.INFO,
    log_dir: str = "logs",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    use_json: bool = True
) -> None:
    """
    Настраивает продвинутое логирование с ротацией и JSON форматом.
    
    Args:
        level: Уровень логирования
        log_dir: Директория для логов
        max_bytes: Максимальный размер файла лога
        backup_count: Количество backup файлов
        use_json: Использовать JSON формат
    """
    global _configured
    if _configured:
        return
    
    # Создаем директорию для логов
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)
    
    # Настраиваем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Очищаем существующие хендлеры
    root_logger.handlers.clear()
    
    # Консольный хендлер (обычный формат)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(_DEFAULT_FORMAT)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # Файловый хендлер с ротацией
    file_handler = logging.handlers.RotatingFileHandler(
        log_path / "parser.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    
    if use_json:
        file_formatter = JSONFormatter()
    else:
        file_formatter = logging.Formatter(_DEFAULT_FORMAT)
    
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)
    
    # Отдельный файл для ошибок
    error_handler = logging.handlers.RotatingFileHandler(
        log_path / "parser_errors.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)
    root_logger.addHandler(error_handler)
    
    # Отдельный файл для метрик производительности
    if use_json:
        perf_handler = logging.handlers.RotatingFileHandler(
            log_path / "parser_performance.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        perf_handler.setLevel(logging.INFO)
        perf_handler.setFormatter(JSONFormatter())
        
        # Фильтр только для метрик производительности
        class PerformanceFilter(logging.Filter):
            def filter(self, record):
                return hasattr(record, 'extra_data') and record.extra_data.get('performance_metric', False)
        
        perf_handler.addFilter(PerformanceFilter())
        root_logger.addHandler(perf_handler)
    
    _configured = True


def setup_basic_logging(level: int = logging.INFO) -> None:
    """Базовая настройка логирования (обратная совместимость)."""
    global _configured
    if _configured:
        return
    logging.basicConfig(level=level, format=_DEFAULT_FORMAT)
    _configured = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Получает логгер с настройкой по умолчанию."""
    setup_basic_logging()
    return logging.getLogger(name if name else "parser")


def get_performance_logger(name: Optional[str] = None) -> PerformanceLogger:
    """Получает логгер производительности."""
    logger = get_logger(name)
    return PerformanceLogger(logger)


class TkTextHandler(logging.Handler):
    """Logging handler to write records into a Tkinter Text/ScrolledText widget."""

    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.setFormatter(logging.Formatter(_DEFAULT_FORMAT))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record) + "\n"
            # Use Tk event loop to append text safely from any thread
            self.text_widget.after(0, self._append, msg)
        except Exception:
            self.handleError(record)

    def _append(self, msg: str):
        try:
            self.text_widget.configure(state="normal")
            self.text_widget.insert("end", msg)
            self.text_widget.see("end")
            self.text_widget.configure(state="disabled")
        except Exception:
            pass
