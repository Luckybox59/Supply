"""Механизм повторных попыток с экспоненциальным backoff."""

import time
import random
from typing import Callable, TypeVar, Any, Optional, Type, Tuple
from functools import wraps
from logging_setup import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Декоратор для повторных попыток с экспоненциальным backoff.
    
    Args:
        max_attempts: Максимальное количество попыток
        base_delay: Базовая задержка в секундах
        max_delay: Максимальная задержка в секундах
        backoff_factor: Коэффициент увеличения задержки
        jitter: Добавлять случайность к задержке
        exceptions: Типы исключений для повтора
        
    Returns:
        Декорированная функция
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_attempts - 1:
                        # Последняя попытка - пробрасываем исключение
                        logger.error(f"Функция {func.__name__} не выполнена после {max_attempts} попыток: {e}")
                        raise
                    
                    # Вычисляем задержку
                    delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                    
                    if jitter:
                        # Добавляем случайность ±25%
                        jitter_range = delay * 0.25
                        delay += random.uniform(-jitter_range, jitter_range)
                    
                    logger.warning(f"Попытка {attempt + 1}/{max_attempts} функции {func.__name__} неудачна: {e}. "
                                 f"Повтор через {delay:.2f}с")
                    
                    time.sleep(delay)
            
            # Этот код никогда не должен выполниться, но для безопасности типов
            raise last_exception or Exception("Неожиданная ошибка в retry_with_backoff")
        
        return wrapper
    return decorator


class RetryableOperation:
    """Класс для выполнения операций с повторными попытками."""
    
    def __init__(self, 
                 max_attempts: int = 3,
                 base_delay: float = 1.0,
                 max_delay: float = 60.0,
                 backoff_factor: float = 2.0,
                 jitter: bool = True):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.jitter = jitter
    
    def execute(self, 
                operation: Callable[[], T],
                exceptions: Tuple[Type[Exception], ...] = (Exception,),
                operation_name: str = "operation") -> T:
        """
        Выполняет операцию с повторными попытками.
        
        Args:
            operation: Функция для выполнения
            exceptions: Типы исключений для повтора
            operation_name: Имя операции для логирования
            
        Returns:
            Результат операции
        """
        last_exception = None
        
        for attempt in range(self.max_attempts):
            try:
                return operation()
            except exceptions as e:
                last_exception = e
                
                if attempt == self.max_attempts - 1:
                    logger.error(f"Операция {operation_name} не выполнена после {self.max_attempts} попыток: {e}")
                    raise
                
                # Вычисляем задержку
                delay = min(self.base_delay * (self.backoff_factor ** attempt), self.max_delay)
                
                if self.jitter:
                    jitter_range = delay * 0.25
                    delay += random.uniform(-jitter_range, jitter_range)
                
                logger.warning(f"Попытка {attempt + 1}/{self.max_attempts} операции {operation_name} неудачна: {e}. "
                             f"Повтор через {delay:.2f}с")
                
                time.sleep(delay)
        
        raise last_exception or Exception(f"Неожиданная ошибка в операции {operation_name}")


# Предустановленные декораторы для частых случаев
network_retry = retry_with_backoff(
    max_attempts=3,
    base_delay=1.0,
    exceptions=(ConnectionError, TimeoutError)
)

llm_retry = retry_with_backoff(
    max_attempts=2,
    base_delay=2.0,
    max_delay=10.0
)

file_operation_retry = retry_with_backoff(
    max_attempts=3,
    base_delay=0.5,
    exceptions=(OSError, IOError, PermissionError)
)
