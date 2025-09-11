"""Модуль для отправки email через SMTP."""

import os
import smtplib
import time
from email.message import EmailMessage
from typing import List, Optional
from logging_setup import get_logger
import config

logger = get_logger(__name__)


class EmailSender:
    """Класс для отправки email с вложениями через SMTP."""
    
    def __init__(self,
                 smtp_server: Optional[str] = None,
                 smtp_port: Optional[int] = None,
                 smtp_user: Optional[str] = None,
                 smtp_password: Optional[str] = None,
                 from_email: Optional[str] = None):
        """
        Инициализация email отправителя.
        
        Args:
            smtp_server: SMTP сервер
            smtp_port: Порт SMTP сервера
            smtp_user: Пользователь для аутентификации
            smtp_password: Пароль для аутентификации
            from_email: Email отправителя
        """
        self.smtp_server = smtp_server or config.SMTP_SERVER
        self.smtp_port = smtp_port or config.SMTP_PORT
        self.smtp_user = smtp_user or config.SMTP_USER
        self.smtp_password = smtp_password or config.SMTP_PASSWORD
        self.from_email = from_email or config.FROM_EMAIL or self.smtp_user
        
        # Валидация обязательных параметров
        if not all([self.smtp_server, self.smtp_port, self.smtp_user, self.smtp_password, self.from_email]):
            missing = []
            if not self.smtp_server: missing.append("SMTP_SERVER")
            if not self.smtp_port: missing.append("SMTP_PORT")
            if not self.smtp_user: missing.append("SMTP_USER")
            if not self.smtp_password: missing.append("SMTP_PASSWORD")
            if not self.from_email: missing.append("FROM_EMAIL")
            
            raise ValueError(f"Не заданы параметры SMTP: {', '.join(missing)}. "
                           "Укажите их в переменных окружения или config.")
    
    def send_email_with_attachments(self,
                                  subject: str,
                                  body: str,
                                  to_email: str,
                                  attachment_paths: List[str],
                                  from_name: str = "Игорь Бяков") -> None:
        """
        Отправляет email с вложениями.
        
        Args:
            subject: Тема письма
            body: Текст письма
            to_email: Email получателя
            attachment_paths: Список путей к файлам для вложения
            from_name: Имя отправителя
            
        Raises:
            RuntimeError: При ошибке отправки
        """
        if not subject.strip():
            raise ValueError("Тема письма не может быть пустой")
        if not body.strip():
            raise ValueError("Текст письма не может быть пустым")
        if not to_email.strip():
            raise ValueError("Email получателя не может быть пустым")
        
        # Проверяем существование файлов
        missing_files = []
        for path in attachment_paths:
            if not os.path.exists(path):
                missing_files.append(path)
        
        if missing_files:
            raise FileNotFoundError(f"Файлы для вложения не найдены: {', '.join(missing_files)}")
        
        # Создаем сообщение
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = f'{from_name} <{self.from_email}>'
        msg['To'] = to_email
        msg.set_content(body)
        
        # Добавляем вложения
        for attachment_path in attachment_paths:
            try:
                with open(attachment_path, 'rb') as f:
                    file_data = f.read()
                    file_name = os.path.basename(attachment_path)
                msg.add_attachment(file_data, maintype='application', subtype='octet-stream', filename=file_name)
                logger.debug(f"Добавлено вложение: {file_name}")
            except Exception as e:
                logger.error(f"Ошибка добавления вложения {attachment_path}: {e}")
                raise RuntimeError(f"Не удалось добавить вложение {attachment_path}: {e}")
        
        # Отправляем письмо
        t_send_start = time.perf_counter()
        try:
            with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port) as smtp:
                smtp.login(self.smtp_user, self.smtp_password)
                smtp.send_message(msg)
        except Exception as e:
            logger.error(f"Ошибка отправки email: {e}")
            raise RuntimeError(f"Не удалось отправить письмо: {e}")
        
        t_send_end = time.perf_counter()
        file_names = [os.path.basename(p) for p in attachment_paths]
        logger.info(f"Письмо с файлами {', '.join(file_names)} отправлено на {to_email} за {t_send_end - t_send_start:.2f} с")
    
    def test_connection(self) -> bool:
        """
        Тестирует подключение к SMTP серверу.
        
        Returns:
            True если подключение успешно, False иначе
        """
        try:
            with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port) as smtp:
                smtp.login(self.smtp_user, self.smtp_password)
            logger.info("SMTP подключение успешно протестировано")
            return True
        except Exception as e:
            logger.error(f"Ошибка тестирования SMTP подключения: {e}")
            return False
    
    def send_reply_email(self,
                        subject: str,
                        body: str,
                        to_email: str,
                        attachment_paths: List[str],
                        reply_to_message_id: Optional[str] = None,
                        references: Optional[List[str]] = None,
                        from_name: str = "Игорь Бяков") -> None:
        """
        Отправляет email как ответ на существующее письмо.
        
        Args:
            subject: Тема письма
            body: Текст письма
            to_email: Email получателя
            attachment_paths: Список путей к файлам для вложения
            reply_to_message_id: Message-ID письма, на которое отвечаем
            references: Список References для цепочки писем
            from_name: Имя отправителя
            
        Raises:
            RuntimeError: При ошибке отправки
        """
        if not subject.strip():
            raise ValueError("Тема письма не может быть пустой")
        if not body.strip():
            raise ValueError("Текст письма не может быть пустым")
        if not to_email.strip():
            raise ValueError("Email получателя не может быть пустым")
        
        # Проверяем существование файлов
        missing_files = []
        for path in attachment_paths:
            if not os.path.exists(path):
                missing_files.append(path)
        
        if missing_files:
            raise FileNotFoundError(f"Файлы для вложения не найдены: {', '.join(missing_files)}")
        
        # Создаем сообщение
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = f'{from_name} <{self.from_email}>'
        msg['To'] = to_email
        
        # Добавляем заголовки для ответа, если указаны
        if reply_to_message_id:
            msg['In-Reply-To'] = reply_to_message_id
            
            # Формируем References
            if references:
                all_references = references + [reply_to_message_id]
            else:
                all_references = [reply_to_message_id]
            
            msg['References'] = ' '.join(all_references)
            
            logger.info(f"Отправка ответа на письмо: {reply_to_message_id}")
        
        msg.set_content(body)
        
        # Добавляем вложения
        for attachment_path in attachment_paths:
            try:
                with open(attachment_path, 'rb') as f:
                    file_data = f.read()
                    file_name = os.path.basename(attachment_path)
                msg.add_attachment(file_data, maintype='application', subtype='octet-stream', filename=file_name)
                logger.debug(f"Добавлено вложение: {file_name}")
            except Exception as e:
                logger.error(f"Ошибка добавления вложения {attachment_path}: {e}")
                raise RuntimeError(f"Не удалось добавить вложение {attachment_path}: {e}")
        
        # Отправляем письмо
        t_send_start = time.perf_counter()
        try:
            with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port) as smtp:
                smtp.login(self.smtp_user, self.smtp_password)
                smtp.send_message(msg)
        except Exception as e:
            logger.error(f"Ошибка отправки email: {e}")
            raise RuntimeError(f"Не удалось отправить письмо: {e}")
        
        t_send_end = time.perf_counter()
        file_names = [os.path.basename(p) for p in attachment_paths]
        logger.info(f"Письмо-ответ с файлами {', '.join(file_names)} отправлено на {to_email} за {t_send_end - t_send_start:.2f} с")
