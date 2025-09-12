"""
Gmail API сервис для отправки и поиска писем.

Использует OAuth2 аутентификацию для безопасного доступа к Gmail.
"""

import base64
import json
import pickle
import os
from typing import Optional, List, Dict, Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

from logging_setup import get_logger
import config

logger = get_logger(__name__)

# Gmail API imports - with graceful handling if not installed
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GMAIL_API_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Gmail API библиотеки не установлены: {e}")
    GMAIL_API_AVAILABLE = False


class GmailService:
    """Gmail API клиент для отправки и поиска писем."""
    
    # Области доступа Gmail API
    SCOPES = [
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/gmail.readonly'
    ]
    
    def __init__(self, credentials_path: Optional[str] = None, token_path: Optional[str] = None):
        """
        Инициализация Gmail сервиса.
        
        Args:
            credentials_path: Путь к файлу OAuth2 credentials
            token_path: Путь к файлу токена доступа
        """
        if not GMAIL_API_AVAILABLE:
            raise RuntimeError("Gmail API библиотеки не установлены. Установите: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")
        
        # Получаем пути из конфигурации или используем переданные
        creds_path = credentials_path or getattr(config, 'GMAIL_CREDENTIALS_PATH', 'gmail_credentials.json')
        token_path_config = token_path or getattr(config, 'GMAIL_TOKEN_PATH', 'gmail_token.json')
        
        # Преобразуем в абсолютные пути относительно корня проекта
        project_root = Path(__file__).parent.parent
        self.credentials_path = str(project_root / creds_path) if not os.path.isabs(creds_path) else creds_path
        self.token_path = str(project_root / token_path_config) if not os.path.isabs(token_path_config) else token_path_config
        
        self.service = None
        self.credentials = None
    
    def authenticate(self) -> bool:
        """
        OAuth2 аутентификация с Gmail API.
        
        Returns:
            True если аутентификация успешна
        """
        creds = None
        
        # Загружаем существующий токен
        if os.path.exists(self.token_path):
            try:
                with open(self.token_path, 'rb') as token_file:
                    creds = pickle.load(token_file)
            except Exception as e:
                logger.warning(f"Не удалось загрузить токен: {e}")
        
        # Если нет валидного токена, проводим аутентификацию
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    logger.warning(f"Не удалось обновить токен: {e}")
                    creds = None
            
            if not creds:
                if not os.path.exists(self.credentials_path):
                    logger.error(f"Файл credentials не найден: {self.credentials_path}")
                    return False
                
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_path, self.SCOPES)
                    creds = flow.run_local_server(port=0)
                except Exception as e:
                    logger.error(f"Ошибка OAuth2 аутентификации: {e}")
                    return False
            
            # Сохраняем токен
            try:
                with open(self.token_path, 'wb') as token_file:
                    pickle.dump(creds, token_file)
            except Exception as e:
                logger.warning(f"Не удалось сохранить токен: {e}")
        
        try:
            self.service = build('gmail', 'v1', credentials=creds)
            self.credentials = creds
            logger.info("Gmail API аутентификация успешна")
            return True
        except Exception as e:
            logger.error(f"Ошибка создания Gmail API сервиса: {e}")
            return False
    
    def send_email(self, to_email: str, subject: str, body: str, 
                   attachments: Optional[List[str]] = None,
                   reply_to_message_id: Optional[str] = None,
                   from_name: Optional[str] = None) -> Optional[str]:
        """
        Отправка письма через Gmail API.
        
        Args:
            to_email: Адрес получателя
            subject: Тема письма
            body: Текст письма
            attachments: Список путей к файлам вложений
            reply_to_message_id: ID сообщения для ответа
            from_name: Отображаемое имя отправителя
            
        Returns:
            ID отправленного сообщения или None при ошибке
        """
        if not self.service:
            if not self.authenticate():
                return None
        
        try:
            message = self._create_message(to_email, subject, body, attachments, reply_to_message_id, from_name)
            
            result = self.service.users().messages().send(
                userId='me', body=message).execute()
            
            message_id = result['id']
            logger.info(f"Письмо отправлено через Gmail API: {message_id}")
            return message_id
            
        except HttpError as e:
            logger.error(f"Gmail API ошибка отправки: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка отправки письма: {e}")
            return None
    
    def search_emails(self, query: str, max_results: int = 50) -> List[Dict[str, Any]]:
        """
        Поиск писем через Gmail API.
        
        Args:
            query: Поисковый запрос Gmail
            max_results: Максимальное количество результатов
            
        Returns:
            Список словарей с информацией о письмах
        """
        if not self.service:
            if not self.authenticate():
                return []
        
        try:
            # Выполняем поиск
            results = self.service.users().messages().list(
                userId='me', q=query, maxResults=max_results).execute()
            
            messages = results.get('messages', [])
            
            # Получаем детали для каждого письма
            email_list = []
            for msg in messages:
                try:
                    msg_detail = self.service.users().messages().get(
                        userId='me', id=msg['id'], format='metadata',
                        metadataHeaders=['From', 'To', 'Subject', 'Date']).execute()
                    
                    email_info = self._parse_message_metadata(msg_detail)
                    email_list.append(email_info)
                    
                except Exception as e:
                    logger.warning(f"Ошибка получения деталей письма {msg['id']}: {e}")
                    continue
            
            logger.info(f"Gmail API поиск: найдено {len(email_list)} писем")
            return email_list
            
        except HttpError as e:
            logger.error(f"Gmail API ошибка поиска: {e}")
            return []
        except Exception as e:
            logger.error(f"Ошибка поиска писем: {e}")
            return []
    
    def send_reply(self, original_message_id: str, reply_subject: str, 
                   reply_body: str, to_email: str,
                   attachments: Optional[List[str]] = None,
                   from_name: Optional[str] = None) -> Optional[str]:
        """
        Отправка ответа на существующее письмо.
        
        Args:
            original_message_id: ID исходного сообщения
            reply_subject: Тема ответа
            reply_body: Текст ответа
            to_email: Адрес получателя
            attachments: Список вложений
            from_name: Отображаемое имя отправителя
            
        Returns:
            ID отправленного ответа или None при ошибке
        """
        try:
            # Получаем исходное сообщение для threadId
            original_msg = self.service.users().messages().get(
                userId='me', id=original_message_id, format='metadata').execute()
            
            thread_id = original_msg['threadId']
            
            # Создаем ответ
            reply_message = self._create_message(
                to_email, reply_subject, reply_body, attachments, original_message_id, from_name)
            reply_message['threadId'] = thread_id
            
            result = self.service.users().messages().send(
                userId='me', body=reply_message).execute()
            
            reply_id = result['id']
            logger.info(f"Ответ отправлен через Gmail API: {reply_id}")
            return reply_id
            
        except Exception as e:
            logger.error(f"Ошибка отправки ответа: {e}")
            return None
    
    def _create_message(self, to_email: str, subject: str, body: str,
                       attachments: Optional[List[str]] = None,
                       reply_to_message_id: Optional[str] = None,
                       from_name: Optional[str] = None) -> Dict[str, Any]:
        """Создает сообщение для Gmail API."""
        # Получаем отображаемое имя отправителя
        display_name = from_name or getattr(config, 'FROM_NAME', 'Игорь Бяков')
        from_email = getattr(config, 'FROM_EMAIL') or getattr(config, 'SMTP_USER', '')
        
        if attachments:
            message = MIMEMultipart()
        else:
            message = MIMEText(body, 'plain', 'utf-8')
            message['to'] = to_email
            message['subject'] = subject
            message['from'] = f'"{display_name}" <{from_email}>'
            
            if reply_to_message_id:
                message['In-Reply-To'] = reply_to_message_id
                message['References'] = reply_to_message_id
            
            return {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
        
        # Создаем сообщение с вложениями
        message['to'] = to_email
        message['subject'] = subject
        message['from'] = f'"{display_name}" <{from_email}>'
        
        if reply_to_message_id:
            message['In-Reply-To'] = reply_to_message_id
            message['References'] = reply_to_message_id
        
        # Добавляем тело письма
        message.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # Добавляем вложения
        for file_path in attachments or []:
            if os.path.exists(file_path):
                with open(file_path, 'rb') as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())
                
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {os.path.basename(file_path)}'
                )
                message.attach(part)
        
        return {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
    
    def _parse_message_metadata(self, msg_detail: Dict[str, Any]) -> Dict[str, Any]:
        """Парсит метаданные сообщения Gmail."""
        headers = {h['name']: h['value'] for h in msg_detail['payload']['headers']}
        
        return {
            'id': msg_detail['id'],
            'thread_id': msg_detail['threadId'],
            'subject': headers.get('Subject', ''),
            'from': headers.get('From', ''),
            'to': headers.get('To', ''),
            'date': headers.get('Date', ''),
            'snippet': msg_detail.get('snippet', '')
        }