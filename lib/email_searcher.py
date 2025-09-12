"""
Унифицированный сервис для поиска писем.

Автоматически выбирает оптимальный метод поиска:
- Gmail API для Google аккаунтов  
- IMAP для остальных провайдеров
"""

import imaplib
import email
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from email.header import decode_header
from email.utils import parsedate_to_datetime
from logging_setup import get_logger
import config
from .email_provider import should_use_gmail_api_for_search, get_imap_settings, normalize_email
from .gmail_service import GmailService
from models.schemas import EmailInfo

logger = get_logger(__name__)


class UnifiedEmailSearcher:
    """Унифицированный поисковик писем."""
    
    def __init__(self, account_email: Optional[str] = None):
        """
        Инициализация поисковика.
        
        Args:
            account_email: Email аккаунта для поиска (по умолчанию из конфига)
        """
        self.account_email = normalize_email(account_email or config.SMTP_USER or "")
        if not self.account_email:
            raise ValueError("Email аккаунта не задан. Укажите SMTP_USER в конфигурации.")
        
        self.gmail_service = None
        self._init_gmail_service()
    
    def _init_gmail_service(self):
        """Инициализирует Gmail сервис если нужно."""
        # Используем новую функцию, специфичную для поиска
        if should_use_gmail_api_for_search(self.account_email):
            try:
                self.gmail_service = GmailService()
                logger.info("Gmail API сервис для поиска инициализирован")
            except Exception as e:
                logger.warning(f"Не удалось инициализировать Gmail API для поиска: {e}")
                self.gmail_service = None
    
    def search_emails_by_recipient(self, to_email: str, subject: str = "") -> List[EmailInfo]:
        """
        Ищет письма по получателю, выбирая оптимальный метод.
        
        Args:
            to_email: Email получателя
            subject: Тема для фильтрации (опционально)
            
        Returns:
            Список EmailInfo объектов
        """
        if not to_email.strip():
            return []
        
        to_email = normalize_email(to_email)
        
        # Пытаемся найти через Gmail API если возможно (только для поиска)
        # Используем новую функцию, специфичную для поиска
        if self.gmail_service and should_use_gmail_api_for_search(self.account_email):
            try:
                return self._search_via_gmail_api(to_email, subject)
            except Exception as e:
                logger.warning(f"Ошибка поиска через Gmail API: {e}, пробуем IMAP")
        
        # Fallback на IMAP
        return self._search_via_imap(to_email, subject)
    
    def _search_via_gmail_api(self, to_email: str, subject: str = "") -> List[EmailInfo]:
        """Поиск через Gmail API."""
        try:
            # Формируем поисковый запрос
            search_days = getattr(config, 'EMAIL_SEARCH_DAYS', 30)
            max_results = getattr(config, 'EMAIL_SEARCH_LIMIT', 50)
            
            # Базовый запрос: письма к указанному получателю
            query_parts = [f"to:{to_email}"]
            
            # Добавляем ограничение по дате
            if search_days > 0:
                since_date = datetime.now() - timedelta(days=search_days)
                date_str = since_date.strftime('%Y/%m/%d')
                query_parts.append(f"after:{date_str}")
            
            # Добавляем тему если указана
            if subject.strip():
                query_parts.append(f'subject:"{subject.strip()}"')
            
            query = " ".join(query_parts)
            logger.info(f"Gmail API поиск: {query}")
            
            # Выполняем поиск
            results = self.gmail_service.search_emails(query, max_results)
            
            # Конвертируем в EmailInfo объекты
            email_infos = []
            for email_data in results:
                # Парсим дату
                date_str = email_data.get('date', '')
                try:
                    if date_str:
                        # Gmail API возвращает дату в RFC 2822 формате
                        parsed_date = parsedate_to_datetime(date_str)
                        if parsed_date.tzinfo is None:
                            # Если нет таймзоны, предполагаем UTC
                            parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                    else:
                        parsed_date = datetime.now(timezone.utc)
                except Exception:
                    parsed_date = datetime.now(timezone.utc)
                
                # Извлекаем значение из квадратных скобок
                body = email_data.get('snippet', '')
                bracket_value = self.extract_bracket_value(body)
                
                email_info = EmailInfo(
                    message_id=email_data.get('id', ''),
                    subject=email_data.get('subject', ''),
                    date=parsed_date,
                    bracket_value=bracket_value,
                    sender=self.account_email,
                    references=(),  # Gmail API не возвращает references в поиске
                    reply_to=''
                )
                
                # Дополнительная фильтрация по теме если нужно
                if subject.strip() and subject.lower() not in email_info.subject.lower():
                    continue
                
                email_infos.append(email_info)
            
            logger.info(f"Gmail API найдено {len(email_infos)} писем")
            return email_infos
            
        except Exception as e:
            logger.error(f"Ошибка поиска через Gmail API: {e}")
            raise
    
    def _search_via_imap(self, to_email: str, subject: str = "") -> List[EmailInfo]:
        """Поиск через IMAP."""
        try:
            imap_settings = get_imap_settings(self.account_email)
            
            # Получаем данные аутентификации
            username = config.IMAP_USER or config.SMTP_USER
            password = config.IMAP_PASSWORD or config.SMTP_PASSWORD
            
            if not username or not password:
                raise ValueError("IMAP_USER и IMAP_PASSWORD должны быть заданы")
            
            # Подключаемся к IMAP
            imap = imaplib.IMAP4_SSL(imap_settings['server'], imap_settings['port'])
            imap.login(username, password)
            
            # Выбираем папку отправленных
            sent_folder = self._select_sent_folder(imap)
            
            # Формируем критерии поиска
            search_criteria = f'TO "{to_email}"'
            
            # Добавляем ограничение по дате
            search_days = getattr(config, 'EMAIL_SEARCH_DAYS', 30)
            if search_days > 0:
                since_date = datetime.now() - timedelta(days=search_days)
                since_str = since_date.strftime('%d-%b-%Y')
                search_criteria += f' SINCE "{since_str}"'
            
            logger.info(f"IMAP поиск в {sent_folder}: {search_criteria}")
            
            # Выполняем поиск
            status, messages = imap.search(None, search_criteria)
            
            if status != 'OK':
                logger.warning(f"IMAP поиск не удался: {status}")
                return []
            
            message_ids = messages[0].split()
            if not message_ids:
                logger.info("Письма не найдены через IMAP")
                return []
            
            # Ограничиваем количество результатов
            search_limit = getattr(config, 'EMAIL_SEARCH_LIMIT', 50)
            message_ids = message_ids[-search_limit:] if len(message_ids) > search_limit else message_ids
            
            # Обрабатываем письма
            email_infos = []
            for msg_id in message_ids:
                try:
                    email_info = self._parse_imap_message(imap, msg_id)
                    if email_info:
                        # Фильтруем по теме если указана
                        if subject.strip() and subject.lower() not in email_info.subject.lower():
                            continue
                        email_infos.append(email_info)
                except Exception as e:
                    logger.warning(f"Ошибка обработки письма {msg_id}: {e}")
                    continue
            
            imap.close()
            imap.logout()
            
            logger.info(f"IMAP найдено {len(email_infos)} писем")
            return email_infos
            
        except Exception as e:
            logger.error(f"Ошибка поиска через IMAP: {e}")
            return []
    
    def _select_sent_folder(self, imap: imaplib.IMAP4_SSL) -> str:
        """Выбирает папку отправленных писем."""
        # Пробуем различные названия папки отправленных
        sent_folders = [
            '[Gmail]/&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-',  # Gmail Отправленные (UTF-7)
            '[Gmail]/Sent Mail',  # Gmail английский
            'INBOX.Sent',
            'Sent',
            'INBOX'  # Fallback
        ]
        
        for folder in sent_folders:
            try:
                status, count = imap.select(folder)
                if status == 'OK':
                    logger.info(f"Выбрана папка: {folder}")
                    return folder
            except Exception:
                continue
        
        # Если ничего не сработало, используем INBOX
        imap.select('INBOX')
        return 'INBOX'
    
    def _parse_imap_message(self, imap: imaplib.IMAP4_SSL, msg_id: bytes) -> Optional[EmailInfo]:
        """Парсит сообщение IMAP."""
        try:
            status, msg_data = imap.fetch(msg_id, '(RFC822)')
            if status != 'OK':
                return None
            
            raw_email = msg_data[0][1]
            email_message = email.message_from_bytes(raw_email)
            
            # Извлекаем заголовки
            message_id = email_message.get('Message-ID', '')
            subject = self._decode_mime_header(email_message.get('Subject', ''))
            date_header = email_message.get('Date', '')
            
            # Парсим дату
            try:
                if date_header:
                    parsed_date = parsedate_to_datetime(date_header)
                    if parsed_date.tzinfo is None:
                        # Если нет таймзоны, предполагаем UTC
                        parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                else:
                    parsed_date = datetime.now(timezone.utc)
            except Exception:
                parsed_date = datetime.now(timezone.utc)
            
            # Извлекаем тело письма
            body = self._extract_email_body(email_message)
            
            # Извлекаем значение из квадратных скобок
            bracket_value = self.extract_bracket_value(body)
            
            # Извлекаем References
            references_header = email_message.get('References', '')
            references = tuple(references_header.split()) if references_header else ()
            
            return EmailInfo(
                message_id=message_id,
                subject=subject,
                date=parsed_date,
                bracket_value=bracket_value,
                sender=self.account_email,
                references=references,
                reply_to=email_message.get('Reply-To', '')
            )
            
        except Exception as e:
            logger.warning(f"Ошибка парсинга сообщения: {e}")
            return None
    
    def _decode_mime_header(self, header: str) -> str:
        """Декодирует MIME-заголовок."""
        try:
            decoded_fragments = decode_header(header)
            result = ''
            for fragment, encoding in decoded_fragments:
                if isinstance(fragment, bytes):
                    if encoding:
                        result += fragment.decode(encoding)
                    else:
                        result += fragment.decode('utf-8', errors='ignore')
                else:
                    result += str(fragment)
            return result
        except Exception:
            return header
    
    def _extract_email_body(self, email_message) -> str:
        """Извлекает тело письма."""
        try:
            if email_message.is_multipart():
                for part in email_message.walk():
                    if part.get_content_type() == "text/plain":
                        charset = part.get_content_charset() or 'utf-8'
                        return part.get_payload(decode=True).decode(charset, errors='ignore')
            else:
                charset = email_message.get_content_charset() or 'utf-8'
                return email_message.get_payload(decode=True).decode(charset, errors='ignore')
        except Exception:
            pass
        return ""
    
    def extract_bracket_value(self, email_body: str) -> str:
        """Извлекает значение из квадратных скобок в тексте письма."""
        if not email_body:
            return ""
        
        pattern = r'\[([^\]]+)\]'
        matches = re.findall(pattern, email_body)
        return matches[0] if matches else ""