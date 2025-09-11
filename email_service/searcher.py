"""Модуль для поиска писем через IMAP."""

import imaplib
import email
import re
from datetime import datetime, timedelta
from typing import List, Optional
from email.header import decode_header
import config
from logging_setup import get_logger
from models.schemas import EmailInfo

logger = get_logger(__name__)


class EmailSearcher:
    """Класс для поиска писем через IMAP."""
    
    def __init__(self,
                 imap_server: Optional[str] = None,
                 imap_port: Optional[int] = None,
                 username: Optional[str] = None,
                 password: Optional[str] = None):
        """
        Инициализация IMAP клиента.
        
        Args:
            imap_server: IMAP сервер
            imap_port: Порт IMAP сервера
            username: Пользователь для аутентификации
            password: Пароль для аутентификации
        """
        self.imap_server = imap_server or getattr(config, 'IMAP_SERVER', 'imap.gmail.com')
        self.imap_port = imap_port or getattr(config, 'IMAP_PORT', 993)
        self.username = username or getattr(config, 'IMAP_USER', None) or getattr(config, 'SMTP_USER', None)
        self.password = password or getattr(config, 'IMAP_PASSWORD', None) or getattr(config, 'SMTP_PASSWORD', None)
        
        if not all([self.imap_server, self.username, self.password]):
            missing = []
            if not self.imap_server: missing.append("IMAP_SERVER")
            if not self.username: missing.append("IMAP_USER")
            if not self.password: missing.append("IMAP_PASSWORD")
            
            raise ValueError(f"Не заданы параметры IMAP: {', '.join(missing)}. "
                           "Укажите их в переменных окружения или config.")
    
    def connect_imap(self) -> imaplib.IMAP4_SSL:
        """Подключается к IMAP серверу."""
        try:
            imap = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            imap.login(self.username, self.password)
            return imap
        except Exception as e:
            logger.error(f"Ошибка подключения к IMAP: {e}")
            raise RuntimeError(f"Не удалось подключиться к IMAP серверу: {e}")
    
    def extract_bracket_value(self, email_body: str) -> str:
        """Извлекает значение из квадратных скобок в тексте письма."""
        if not email_body:
            return ""
        
        # Ищем все значения в квадратных скобках
        pattern = r'\[([^\]]+)\]'
        matches = re.findall(pattern, email_body)
        
        # Возвращаем первое найденное значение или пустую строку
        return matches[0] if matches else ""
    
    def decode_mime_words(self, s: str) -> str:
        """Декодирует MIME-закодированные слова в заголовках."""
        try:
            decoded_fragments = decode_header(s)
            decoded_string = ''
            for fragment, encoding in decoded_fragments:
                if isinstance(fragment, bytes):
                    if encoding:
                        decoded_string += fragment.decode(encoding)
                    else:
                        decoded_string += fragment.decode('utf-8', errors='ignore')
                else:
                    decoded_string += str(fragment)
            return decoded_string
        except Exception:
            return s
    
    def parse_email_date(self, date_str: str) -> datetime:
        """Парсит дату из заголовка письма."""
        try:
            # Парсим стандартный формат RFC 2822
            return email.utils.parsedate_to_datetime(date_str)
        except Exception:
            # Если не удалось распарсить, возвращаем текущую дату
            return datetime.now()
    
    def search_emails_by_recipient(self, to_email: str, subject: str = "") -> List[EmailInfo]:
        """
        Ищет письма по получателю за указанный период, 
        затем фильтрует по теме локально.
        
        Args:
            to_email: Email получателя
            subject: Тема письма для локальной фильтрации (опционально)
            
        Returns:
            Список EmailInfo объектов
        """
        if not to_email.strip():
            return []
        
        email_infos = []
        imap = None
        
        try:
            imap = self.connect_imap()
            
            # Выбираем папку отправленных (Gmail)
            # Используем общее название папки отправленных для Gmail
            sent_folder = '[Gmail]/&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-'  # Отправленные (закодировано в UTF-7)
            
            try:
                status, count = imap.select(sent_folder)
                if status != 'OK':
                    # Пробуем альтернативные названия папки отправленных
                    for folder in ['[Gmail]/Sent Mail', 'INBOX.Sent', 'Sent']:
                        try:
                            status, count = imap.select(folder)
                            if status == 'OK':
                                sent_folder = folder
                                break
                        except Exception:
                            continue
                    
                    if status != 'OK':
                        logger.warning(f"Не удалось выбрать папку отправленных. Переключаемся на INBOX")
                        imap.select('INBOX')
                        sent_folder = 'INBOX'
                else:
                    logger.info(f"Выбрана папка отправленных: {sent_folder}")
            except Exception as e:
                logger.warning(f"Ошибка выбора папки отправленных: {e}. Используем INBOX")
                imap.select('INBOX')
                sent_folder = 'INBOX'
            
            # Ограничиваем поиск последними N днями
            search_limit = getattr(config, 'EMAIL_SEARCH_LIMIT', 50)
            search_days = getattr(config, 'EMAIL_SEARCH_DAYS', 30)
            
            # Простой поиск: только по получателю и дате
            search_criteria = f'TO "{to_email}"'
            
            # Добавляем ограничение по дате (последние N дней)
            if search_days > 0:
                since_date = datetime.now() - timedelta(days=search_days)
                # IMAP формат даты: DD-Mon-YYYY
                since_str = since_date.strftime('%d-%b-%Y')
                search_criteria += f' SINCE "{since_str}"'
            
            logger.info(f"Поиск писем по получателю в {sent_folder}: {search_criteria}")
            
            # Выполняем простой поиск
            status, messages = imap.search(None, search_criteria)
            
            if status != 'OK':
                logger.warning(f"Поиск писем не удался: {status}")
                return []
            
            # Получаем ID сообщений
            message_ids = messages[0].split()
            
            if not message_ids:
                logger.info("Письма не найдены")
                return []
            
            # Ограничиваем количество результатов
            message_ids = message_ids[-search_limit:] if len(message_ids) > search_limit else message_ids
            
            logger.info(f"Найдено писем: {len(message_ids)}")
            
            # Обрабатываем каждое письмо
            for msg_id in message_ids:
                try:
                    # Получаем заголовки и тело письма
                    status, msg_data = imap.fetch(msg_id, '(RFC822)')
                    
                    if status != 'OK':
                        continue
                    
                    # Парсим письмо
                    raw_email = msg_data[0][1]
                    email_message = email.message_from_bytes(raw_email)
                    
                    # Извлекаем заголовки
                    message_id = email_message.get('Message-ID', '')
                    subject_header = email_message.get('Subject', '')
                    date_header = email_message.get('Date', '')
                    from_header = email_message.get('From', '')
                    references_header = email_message.get('References', '')
                    reply_to_header = email_message.get('Reply-To', from_header)
                    
                    # Декодируем заголовки
                    decoded_subject = self.decode_mime_words(subject_header)
                    decoded_from = self.decode_mime_words(from_header)
                    decoded_reply_to = self.decode_mime_words(reply_to_header)
                    
                    # Парсим дату
                    parsed_date = self.parse_email_date(date_header)
                    
                    # Извлекаем тело письма
                    body = self.extract_email_body(email_message)
                    
                    # Извлекаем значение из квадратных скобок
                    bracket_value = self.extract_bracket_value(body)
                    
                    # Парсим References (конвертируем в tuple для hashable EmailInfo)
                    references = tuple(ref.strip() for ref in references_header.split()) if references_header else ()
                    
                    # Создаем EmailInfo
                    email_info = EmailInfo(
                        message_id=message_id,
                        subject=decoded_subject,
                        date=parsed_date,
                        bracket_value=bracket_value,
                        sender=decoded_from,
                        references=references,
                        reply_to=decoded_reply_to
                    )
                    
                    email_infos.append(email_info)
                    
                except Exception as e:
                    logger.warning(f"Ошибка обработки письма {msg_id}: {e}")
                    continue
            
            # Сортируем по дате (новые сначала)
            email_infos.sort(key=lambda x: x.date, reverse=True)
            
            # Локальная фильтрация по теме, если указана
            if subject.strip():
                subject_lower = subject.strip().lower()
                filtered_emails = []
                for email_info in email_infos:
                    if subject_lower in email_info.subject.lower():
                        filtered_emails.append(email_info)
                email_infos = filtered_emails
                logger.info(f"После локальной фильтрации по теме '{subject}' осталось: {len(email_infos)} писем")
            
        except Exception as e:
            logger.error(f"Ошибка поиска писем: {e}")
            raise
        
        finally:
            if imap:
                try:
                    imap.close()
                    imap.logout()
                except Exception:
                    pass
        
        return email_infos
    
    def extract_email_body(self, email_message) -> str:
        """Извлекает текстовое тело письма."""
        body = ""
        
        try:
            if email_message.is_multipart():
                # Если письмо многочастное, ищем текстовые части
                for part in email_message.walk():
                    content_type = part.get_content_type()
                    if content_type == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            # Определяем кодировку
                            charset = part.get_content_charset() or 'utf-8'
                            try:
                                body += payload.decode(charset, errors='ignore')
                            except Exception:
                                body += payload.decode('utf-8', errors='ignore')
                        break
            else:
                # Простое письмо
                payload = email_message.get_payload(decode=True)
                if payload:
                    charset = email_message.get_content_charset() or 'utf-8'
                    try:
                        body = payload.decode(charset, errors='ignore')
                    except Exception:
                        body = payload.decode('utf-8', errors='ignore')
        
        except Exception as e:
            logger.warning(f"Ошибка извлечения тела письма: {e}")
        
        return body
    
    def test_connection(self) -> bool:
        """Тестирует подключение к IMAP серверу."""
        try:
            imap = self.connect_imap()
            # Просто закрываем соединение без вызова close()
            imap.logout()
            logger.info("IMAP подключение успешно протестировано")
            return True
        except Exception as e:
            logger.error(f"Ошибка тестирования IMAP подключения: {e}")
            return False