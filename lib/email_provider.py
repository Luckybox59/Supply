"""
Модуль для определения почтового провайдера.

Автоматически определяет, является ли email аккаунт Google аккаунтом
для выбора оптимального метода работы с почтой.
"""

import re
from typing import Optional, List
from logging_setup import get_logger
import config

logger = get_logger(__name__)


def detect_email_provider(email: str) -> str:
    """
    Определяет провайдера по email адресу.
    
    Args:
        email: Email адрес
        
    Returns:
        Тип провайдера: 'google', 'outlook', 'yandex', 'other'
    """
    if not email or '@' not in email:
        return 'other'
    
    domain = email.split('@')[1].lower()
    
    # Google домены
    google_domains = ['gmail.com', 'googlemail.com']
    if hasattr(config, 'GOOGLE_DOMAINS') and config.GOOGLE_DOMAINS:
        google_domains.extend(config.GOOGLE_DOMAINS)
    
    if domain in google_domains:
        return 'google'
    
    # G Suite / Google Workspace (могут иметь кастомные домены)
    # Это сложнее определить автоматически, но можно добавить известные домены
    
    # Outlook / Hotmail
    outlook_domains = ['outlook.com', 'hotmail.com', 'live.com', 'msn.com']
    if domain in outlook_domains:
        return 'outlook'
    
    # Yandex
    yandex_domains = ['yandex.ru', 'yandex.com', 'ya.ru']
    if domain in yandex_domains:
        return 'yandex'
    
    return 'other'


def is_google_account(email: str) -> bool:
    """
    Проверяет, является ли аккаунт Google аккаунтом.
    
    Args:
        email: Email адрес
        
    Returns:
        True если это Google аккаунт
    """
    return detect_email_provider(email) == 'google'


def should_use_gmail_api(email: str) -> bool:
    """
    Определяет, следует ли использовать Gmail API для данного email.
    
    Args:
        email: Email адрес
        
    Returns:
        True если следует использовать Gmail API
    """
    # Проверяем настройки
    use_gmail_api = getattr(config, 'USE_GMAIL_API', True)
    if not use_gmail_api:
        return False
    
    # Проверяем, что это Google аккаунт
    return is_google_account(email)


def get_smtp_settings(email: str) -> dict:
    """
    Возвращает настройки SMTP для провайдера.
    
    Args:
        email: Email адрес
        
    Returns:
        Словарь с настройками SMTP
    """
    provider = detect_email_provider(email)
    
    if provider == 'google':
        return {
            'server': 'smtp.gmail.com',
            'port': 587,
            'use_tls': True,
            'use_ssl': False
        }
    elif provider == 'outlook':
        return {
            'server': 'smtp-mail.outlook.com',
            'port': 587,
            'use_tls': True,
            'use_ssl': False
        }
    elif provider == 'yandex':
        return {
            'server': 'smtp.yandex.ru',
            'port': 587,
            'use_tls': True,
            'use_ssl': False
        }
    else:
        # Возвращаем настройки по умолчанию из конфига
        return {
            'server': getattr(config, 'SMTP_SERVER', 'smtp.gmail.com'),
            'port': getattr(config, 'SMTP_PORT', 587),
            'use_tls': True,
            'use_ssl': False
        }


def get_imap_settings(email: str) -> dict:
    """
    Возвращает настройки IMAP для провайдера.
    
    Args:
        email: Email адрес
        
    Returns:
        Словарь с настройками IMAP
    """
    provider = detect_email_provider(email)
    
    if provider == 'google':
        return {
            'server': 'imap.gmail.com',
            'port': 993,
            'use_ssl': True
        }
    elif provider == 'outlook':
        return {
            'server': 'outlook.office365.com',
            'port': 993,
            'use_ssl': True
        }
    elif provider == 'yandex':
        return {
            'server': 'imap.yandex.ru',
            'port': 993,
            'use_ssl': True
        }
    else:
        # Возвращаем настройки по умолчанию из конфига
        return {
            'server': getattr(config, 'IMAP_SERVER', 'imap.gmail.com'),
            'port': getattr(config, 'IMAP_PORT', 993),
            'use_ssl': getattr(config, 'IMAP_USE_SSL', True)
        }


def validate_email_format(email: str) -> bool:
    """
    Проверяет корректность формата email адреса.
    
    Args:
        email: Email адрес для проверки
        
    Returns:
        True если формат корректный
    """
    if not email:
        return False
    
    # Простая проверка формата email
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def normalize_email(email: str) -> str:
    """
    Нормализует email адрес.
    
    Args:
        email: Исходный email адрес
        
    Returns:
        Нормализованный email адрес
    """
    if not email:
        return ""
    
    # Убираем лишние пробелы и приводим к нижнему регистру
    normalized = email.strip().lower()
    
    return normalized