"""
Унифицированный сервис для отправки писем.

Автоматически выбирает оптимальный метод отправки:
- Gmail API для Google аккаунтов
- SMTP для остальных провайдеров
"""

import os
import smtplib
import time
from email.message import EmailMessage
from typing import List, Optional, Dict, Any
from logging_setup import get_logger
import config
from .email_provider import should_use_gmail_api, get_smtp_settings, normalize_email
from .gmail_service import GmailService

logger = get_logger(__name__)


class UnifiedEmailSender:
    """Унифицированный отправитель писем."""
    
    def __init__(self, from_email: Optional[str] = None):
        """
        Инициализация отправителя.
        
        Args:
            from_email: Email отправителя (по умолчанию из конфига)
        """
        self.from_email = normalize_email(from_email or config.FROM_EMAIL or config.SMTP_USER or "")
        if not self.from_email:
            raise ValueError("Email отправителя не задан. Укажите FROM_EMAIL в конфигурации.")
        
        self.gmail_service = None
        self._init_gmail_service()
    
    def _init_gmail_service(self):
        """Инициализирует Gmail сервис если нужно."""
        if should_use_gmail_api(self.from_email):
            try:
                self.gmail_service = GmailService()
                logger.info("Gmail API сервис инициализирован")
            except Exception as e:
                logger.warning(f"Не удалось инициализировать Gmail API: {e}")
                self.gmail_service = None
    
    def send_email(self, 
                   to_email: str,
                   subject: str,
                   body: str,
                   attachments: Optional[List[str]] = None,
                   from_name: str = "Игорь Бяков") -> bool:
        """
        Отправляет письмо, выбирая оптимальный метод.
        
        Args:
            to_email: Email получателя
            subject: Тема письма
            body: Текст письма
            attachments: Список путей к вложениям
            from_name: Имя отправителя
            
        Returns:
            True если письмо отправлено успешно
        """
        if not subject.strip():
            raise ValueError("Тема письма не может быть пустой")
        if not body.strip():
            raise ValueError("Текст письма не может быть пустым")
        if not to_email.strip():
            raise ValueError("Email получателя не может быть пустым")
        
        to_email = normalize_email(to_email)
        
        # Проверяем существование файлов вложений
        if attachments:
            self._validate_attachments(attachments)
        
        start_time = time.perf_counter()
        
        # Пытаемся отправить через Gmail API если возможно
        if self.gmail_service and should_use_gmail_api(self.from_email):
            try:
                message_id = self.gmail_service.send_email(
                    to_email=to_email,
                    subject=subject,
                    body=body,
                    attachments=attachments
                )
                
                if message_id:
                    elapsed = time.perf_counter() - start_time
                    logger.info(f"Письмо отправлено через Gmail API за {elapsed:.2f}с")
                    return True
                else:
                    logger.warning("Gmail API не вернул ID сообщения, пробуем SMTP")
            except Exception as e:
                logger.warning(f"Ошибка отправки через Gmail API: {e}, пробуем SMTP")
        
        # Fallback на SMTP
        return self._send_via_smtp(to_email, subject, body, attachments, from_name)
    
    def send_reply(self,
                   to_email: str,
                   subject: str,
                   body: str,
                   original_message_id: Optional[str] = None,
                   references: Optional[List[str]] = None,
                   attachments: Optional[List[str]] = None,
                   from_name: str = "Игорь Бяков") -> bool:
        """
        Отправляет ответ на письмо.
        
        Args:
            to_email: Email получателя
            subject: Тема ответа
            body: Текст ответа
            original_message_id: ID исходного сообщения
            references: Список References для цепочки
            attachments: Список вложений
            from_name: Имя отправителя
            
        Returns:
            True если ответ отправлен успешно
        """
        to_email = normalize_email(to_email)
        
        # Проверяем вложения
        if attachments:
            self._validate_attachments(attachments)
        
        start_time = time.perf_counter()
        
        # Пытаемся отправить ответ через Gmail API
        if self.gmail_service and should_use_gmail_api(self.from_email) and original_message_id:
            try:
                reply_id = self.gmail_service.send_reply(
                    original_message_id=original_message_id,
                    reply_subject=subject,
                    reply_body=body,
                    to_email=to_email,
                    attachments=attachments
                )
                
                if reply_id:
                    elapsed = time.perf_counter() - start_time
                    logger.info(f"Ответ отправлен через Gmail API за {elapsed:.2f}с")
                    return True
                else:
                    logger.warning("Gmail API не вернул ID ответа, пробуем SMTP")
            except Exception as e:
                logger.warning(f"Ошибка отправки ответа через Gmail API: {e}, пробуем SMTP")
        
        # Fallback на SMTP
        return self._send_reply_via_smtp(
            to_email, subject, body, original_message_id, references, attachments, from_name)
    
    def _send_via_smtp(self,
                       to_email: str,
                       subject: str,
                       body: str,
                       attachments: Optional[List[str]] = None,
                       from_name: str = "Игорь Бяков") -> bool:
        """Отправляет письмо через SMTP."""
        try:
            smtp_settings = get_smtp_settings(self.from_email)
            
            # Получаем данные аутентификации
            smtp_user = config.SMTP_USER
            smtp_password = config.SMTP_PASSWORD
            
            if not smtp_user or not smtp_password:
                raise ValueError("SMTP_USER и SMTP_PASSWORD должны быть заданы для SMTP отправки")
            
            # Создаем сообщение
            msg = EmailMessage()
            msg['Subject'] = subject
            msg['From'] = f'{from_name} <{self.from_email}>'
            msg['To'] = to_email
            msg.set_content(body)
            
            # Добавляем вложения
            if attachments:
                self._add_attachments_to_message(msg, attachments)
            
            # Отправляем
            if smtp_settings.get('use_ssl', False):
                smtp_class = smtplib.SMTP_SSL
            else:
                smtp_class = smtplib.SMTP
            
            with smtp_class(smtp_settings['server'], smtp_settings['port']) as smtp:
                if smtp_settings.get('use_tls', False) and not smtp_settings.get('use_ssl', False):
                    smtp.starttls()
                
                smtp.login(smtp_user, smtp_password)
                smtp.send_message(msg)
            
            logger.info(f"Письмо отправлено через SMTP на {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка отправки через SMTP: {e}")
            return False
    
    def _send_reply_via_smtp(self,
                            to_email: str,
                            subject: str,
                            body: str,
                            original_message_id: Optional[str] = None,
                            references: Optional[List[str]] = None,
                            attachments: Optional[List[str]] = None,
                            from_name: str = "Игорь Бяков") -> bool:
        """Отправляет ответ через SMTP."""
        try:
            smtp_settings = get_smtp_settings(self.from_email)
            
            # Получаем данные аутентификации
            smtp_user = config.SMTP_USER
            smtp_password = config.SMTP_PASSWORD
            
            if not smtp_user or not smtp_password:
                raise ValueError("SMTP_USER и SMTP_PASSWORD должны быть заданы")
            
            # Создаем сообщение
            msg = EmailMessage()
            msg['Subject'] = subject
            msg['From'] = f'{from_name} <{self.from_email}>'
            msg['To'] = to_email
            
            # Добавляем заголовки для ответа
            if original_message_id:
                msg['In-Reply-To'] = original_message_id
                
                if references:
                    all_references = references + [original_message_id]
                else:
                    all_references = [original_message_id]
                
                msg['References'] = ' '.join(all_references)
            
            msg.set_content(body)
            
            # Добавляем вложения
            if attachments:
                self._add_attachments_to_message(msg, attachments)
            
            # Отправляем
            if smtp_settings.get('use_ssl', False):
                smtp_class = smtplib.SMTP_SSL
            else:
                smtp_class = smtplib.SMTP
            
            with smtp_class(smtp_settings['server'], smtp_settings['port']) as smtp:
                if smtp_settings.get('use_tls', False) and not smtp_settings.get('use_ssl', False):
                    smtp.starttls()
                
                smtp.login(smtp_user, smtp_password)
                smtp.send_message(msg)
            
            logger.info(f"Ответ отправлен через SMTP на {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка отправки ответа через SMTP: {e}")
            return False
    
    def _validate_attachments(self, attachments: List[str]):
        """Проверяет существование файлов вложений."""
        missing_files = []
        for path in attachments:
            if not os.path.exists(path):
                missing_files.append(path)
        
        if missing_files:
            raise FileNotFoundError(f"Файлы для вложения не найдены: {', '.join(missing_files)}")
    
    def _add_attachments_to_message(self, msg: EmailMessage, attachments: List[str]):
        """Добавляет вложения к сообщению."""
        for attachment_path in attachments:
            try:
                with open(attachment_path, 'rb') as f:
                    file_data = f.read()
                    file_name = os.path.basename(attachment_path)
                
                msg.add_attachment(file_data, maintype='application', 
                                 subtype='octet-stream', filename=file_name)
                logger.debug(f"Добавлено вложение: {file_name}")
            except Exception as e:
                logger.error(f"Ошибка добавления вложения {attachment_path}: {e}")
                raise RuntimeError(f"Не удалось добавить вложение {attachment_path}: {e}")
    
    def test_connection(self) -> bool:
        """
        Тестирует подключение к почтовому сервису.
        
        Returns:
            True если подключение успешно
        """
        # Тестируем Gmail API если возможно
        if self.gmail_service and should_use_gmail_api(self.from_email):
            try:
                if self.gmail_service.authenticate():
                    logger.info("Gmail API подключение успешно")
                    return True
            except Exception as e:
                logger.warning(f"Ошибка тестирования Gmail API: {e}")
        
        # Тестируем SMTP
        try:
            smtp_settings = get_smtp_settings(self.from_email)
            smtp_user = config.SMTP_USER
            smtp_password = config.SMTP_PASSWORD
            
            if not smtp_user or not smtp_password:
                logger.warning("SMTP credentials не заданы")
                return False
            
            if smtp_settings.get('use_ssl', False):
                smtp_class = smtplib.SMTP_SSL
            else:
                smtp_class = smtplib.SMTP
            
            with smtp_class(smtp_settings['server'], smtp_settings['port']) as smtp:
                if smtp_settings.get('use_tls', False) and not smtp_settings.get('use_ssl', False):
                    smtp.starttls()
                
                smtp.login(smtp_user, smtp_password)
            
            logger.info("SMTP подключение успешно")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка тестирования SMTP: {e}")
            return False