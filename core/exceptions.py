"""Пользовательские исключения для системы парсинга."""

from typing import Optional, Any


class ParserError(Exception):
    """Базовое исключение для всех ошибок парсера."""
    
    def __init__(self, message: str, details: Optional[dict] = None, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.original_error = original_error
    
    def __str__(self) -> str:
        result = self.message
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            result += f" (детали: {details_str})"
        if self.original_error:
            result += f" (исходная ошибка: {self.original_error})"
        return result


class PDFParsingError(ParserError):
    """Ошибка парсинга PDF документа."""
    
    def __init__(self, file_path: str, message: str = "Ошибка парсинга PDF", **kwargs):
        super().__init__(message, details={"file_path": file_path}, **kwargs)
        self.file_path = file_path


class ExcelParsingError(ParserError):
    """Ошибка парсинга Excel документа."""
    
    def __init__(self, file_path: str, message: str = "Ошибка парсинга Excel", **kwargs):
        super().__init__(message, details={"file_path": file_path}, **kwargs)
        self.file_path = file_path


class LLMError(ParserError):
    """Ошибка взаимодействия с LLM."""
    
    def __init__(self, message: str = "Ошибка LLM", model: Optional[str] = None, 
                 status_code: Optional[int] = None, **kwargs):
        details = {}
        if model:
            details["model"] = model
        if status_code:
            details["status_code"] = status_code
        super().__init__(message, details=details, **kwargs)
        self.model = model
        self.status_code = status_code


class EmailError(ParserError):
    """Ошибка отправки email."""
    
    def __init__(self, message: str = "Ошибка отправки email", 
                 to_email: Optional[str] = None, smtp_server: Optional[str] = None, **kwargs):
        details = {}
        if to_email:
            details["to_email"] = to_email
        if smtp_server:
            details["smtp_server"] = smtp_server
        super().__init__(message, details=details, **kwargs)
        self.to_email = to_email
        self.smtp_server = smtp_server


class ValidationError(ParserError):
    """Ошибка валидации данных."""
    
    def __init__(self, message: str = "Ошибка валидации", 
                 field: Optional[str] = None, value: Optional[Any] = None, **kwargs):
        details = {}
        if field:
            details["field"] = field
        if value is not None:
            details["value"] = str(value)
        super().__init__(message, details=details, **kwargs)
        self.field = field
        self.value = value


class ConfigurationError(ParserError):
    """Ошибка конфигурации."""
    
    def __init__(self, message: str = "Ошибка конфигурации", 
                 config_key: Optional[str] = None, **kwargs):
        details = {}
        if config_key:
            details["config_key"] = config_key
        super().__init__(message, details=details, **kwargs)
        self.config_key = config_key
