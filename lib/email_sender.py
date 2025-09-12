"""
Унифицированный сервис для отправки писем.

Всегда использует SMTP для отправки писем, независимо от провайдера.
"""

import os
import smtplib
import time
from email.message import EmailMessage
from typing import List, Optional, Dict, Any
from logging_setup import get_logger
import config
from .email_provider import get_smtp_settings, normalize_email

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
        
        # Gmail API больше не используется для отправки
        self.gmail_service = None
    
    def send_email(self, 
                   to_email: str,
                   subject: str,
                   body: str,
                   attachments: Optional[List[str]] = None,
                   from_name: Optional[str] = None) -> bool:
        """
        Отправляет письмо через SMTP.
        
        Args:
            to_email: Email получателя
            subject: Тема письма
            body: Текст письма
            attachments: Список путей к вложениям
            from_name: Имя отправителя
            
        Returns:
            True если письмо отправлено успешно
            
        Raises:
            RuntimeError: Если возникла ошибка при отправке письма
        """
        if not subject.strip():
            raise ValueError("Тема письма не может быть пустой")
        if not body.strip():
            raise ValueError("Текст письма не может быть пустым")
        if not to_email.strip():
            raise ValueError("Email получателя не может быть пустым")
        
        to_email = normalize_email(to_email)
        display_name = from_name or getattr(config, 'FROM_NAME', 'Игорь Бяков')
        
        # Проверяем существование файлов вложений
        if attachments:
            self._validate_attachments(attachments)
        
        start_time = time.perf_counter()
        
        # Всегда используем SMTP для отправки
        try:
            result = self._send_via_smtp(to_email, subject, body, attachments, display_name)
            
            if result:
                elapsed = time.perf_counter() - start_time
                logger.info(f"Письмо отправлено через SMTP за {elapsed:.2f}с")
            else:
                raise RuntimeError(f"Не удалось отправить письмо через SMTP на {to_email}")
                
            return result
        except Exception as e:
            logger.error(f"Ошибка отправки письма: {e}")
            raise RuntimeError(f"Не удалось отправить письмо: {e}") from e
    
    def send_reply(self,
                   to_email: str,
                   subject: str,
                   body: str,
                   original_message_id: Optional[str] = None,
                   references: Optional[List[str]] = None,
                   attachments: Optional[List[str]] = None,
                   from_name: Optional[str] = None) -> bool:
        """
        Отправляет ответ на письмо через SMTP.
        
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
            
        Raises:
            RuntimeError: Если возникла ошибка при отправке ответа
        """
        to_email = normalize_email(to_email)
        display_name = from_name or getattr(config, 'FROM_NAME', 'Игорь Бяков')
        
        # Проверяем вложения
        if attachments:
            self._validate_attachments(attachments)
        
        start_time = time.perf_counter()
        
        # Всегда используем SMTP для отправки ответа
        try:
            result = self._send_reply_via_smtp(
                to_email, subject, body, original_message_id, references, attachments, display_name)
            
            if result:
                elapsed = time.perf_counter() - start_time
                logger.info(f"Ответ отправлен через SMTP за {elapsed:.2f}с")
            else:
                raise RuntimeError(f"Не удалось отправить ответ через SMTP на {to_email}")
                
            return result
        except Exception as e:
            logger.error(f"Ошибка отправки ответа: {e}")
            raise RuntimeError(f"Не удалось отправить ответ: {e}") from e
    
    def _send_via_smtp(self,
                       to_email: str,
                       subject: str,
                       body: str,
                       attachments: Optional[List[str]] = None,
                       from_name: Optional[str] = None) -> bool:
        """Отправляет письмо через SMTP."""
        try:
            smtp_settings = get_smtp_settings(self.from_email)
            display_name = from_name or getattr(config, 'FROM_NAME', 'Игорь Бяков')
            
            # Получаем данные аутентификации
            smtp_user = config.SMTP_USER
            smtp_password = config.SMTP_PASSWORD
            
            if not smtp_user or not smtp_password:
                raise ValueError("SMTP_USER и SMTP_PASSWORD должны быть заданы для SMTP отправки")
            
            # Создаем сообщение
            msg = EmailMessage()
            msg['Subject'] = subject
            msg['From'] = f'{display_name} <{self.from_email}>'
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
            raise
    
    def _send_reply_via_smtp(self,
                            to_email: str,
                            subject: str,
                            body: str,
                            original_message_id: Optional[str] = None,
                            references: Optional[List[str]] = None,
                            attachments: Optional[List[str]] = None,
                            from_name: Optional[str] = None) -> bool:
        """Отправляет ответ через SMTP."""
        try:
            smtp_settings = get_smtp_settings(self.from_email)
            display_name = from_name or getattr(config, 'FROM_NAME', 'Игорь Бяков')
            
            # Получаем данные аутентификации
            smtp_user = config.SMTP_USER
            smtp_password = config.SMTP_PASSWORD
            
            if not smtp_user or not smtp_password:
                raise ValueError("SMTP_USER и SMTP_PASSWORD должны быть заданы")
            
            # Создаем сообщение
            msg = EmailMessage()
            msg['Subject'] = subject
            msg['From'] = f'{display_name} <{self.from_email}>'
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
            raise
    
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
        Тестирует подключение к почтовому сервису через SMTP.
        
        Returns:
            True если подключение успешно
            
        Raises:
            RuntimeError: Если возникла ошибка при тестировании подключения
        """
        # Всегда тестируем только SMTP
        try:
            smtp_settings = get_smtp_settings(self.from_email)
            smtp_user = config.SMTP_USER
            smtp_password = config.SMTP_PASSWORD
            
            if not smtp_user or not smtp_password:
                logger.warning("SMTP credentials не заданы")
                raise RuntimeError("SMTP credentials не заданы")
            
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
            raise RuntimeError(f"Не удалось протестировать SMTP подключение: {e}") from e