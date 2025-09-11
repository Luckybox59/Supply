"""Тесты для модуля email."""

import pytest
import tempfile
import os
from unittest.mock import patch, MagicMock

from email_service.sender import EmailSender


class TestEmailSender:
    """Тесты для EmailSender."""
    
    def test_init_with_all_params(self):
        """Тест инициализации со всеми параметрами."""
        sender = EmailSender(
            smtp_server="smtp.test.com",
            smtp_port=587,
            smtp_user="test@test.com",
            smtp_password="password",
            from_email="from@test.com"
        )
        
        assert sender.smtp_server == "smtp.test.com"
        assert sender.smtp_port == 587
        assert sender.smtp_user == "test@test.com"
        assert sender.from_email == "from@test.com"
    
    def test_init_missing_params_raises_error(self):
        """Тест ошибки при отсутствии обязательных параметров."""
        with pytest.raises(ValueError, match="Не заданы параметры SMTP"):
            EmailSender(smtp_server="smtp.test.com")  # Отсутствуют другие параметры
    
    def test_init_with_config_fallback(self):
        """Тест использования значений из config по умолчанию."""
        with patch('email_service.sender.config') as mock_config:
            mock_config.SMTP_SERVER = "smtp.config.com"
            mock_config.SMTP_PORT = 465
            mock_config.SMTP_USER = "config@test.com"
            mock_config.SMTP_PASSWORD = "config_pass"
            mock_config.FROM_EMAIL = "from_config@test.com"
            
            sender = EmailSender()
            assert sender.smtp_server == "smtp.config.com"
            assert sender.smtp_port == 465
    
    @patch('email_service.sender.smtplib.SMTP_SSL')
    def test_send_email_success(self, mock_smtp_ssl):
        """Тест успешной отправки email."""
        # Создаем временный файл для вложения
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Тестовое содержимое")
            temp_file = f.name
        
        try:
            mock_smtp = MagicMock()
            mock_smtp_ssl.return_value.__enter__.return_value = mock_smtp
            
            sender = EmailSender(
                smtp_server="smtp.test.com",
                smtp_port=465,
                smtp_user="test@test.com",
                smtp_password="password",
                from_email="from@test.com"
            )
            
            sender.send_email_with_attachments(
                subject="Тест",
                body="Тестовое письмо",
                to_email="to@test.com",
                attachment_paths=[temp_file]
            )
            
            mock_smtp.login.assert_called_once_with("test@test.com", "password")
            mock_smtp.send_message.assert_called_once()
        finally:
            os.unlink(temp_file)
    
    def test_send_email_empty_subject_raises_error(self):
        """Тест ошибки при пустой теме."""
        sender = EmailSender(
            smtp_server="smtp.test.com",
            smtp_port=465,
            smtp_user="test@test.com",
            smtp_password="password",
            from_email="from@test.com"
        )
        
        with pytest.raises(ValueError, match="Тема письма не может быть пустой"):
            sender.send_email_with_attachments("", "body", "to@test.com", [])
    
    def test_send_email_missing_file_raises_error(self):
        """Тест ошибки при отсутствии файла вложения."""
        sender = EmailSender(
            smtp_server="smtp.test.com",
            smtp_port=465,
            smtp_user="test@test.com",
            smtp_password="password",
            from_email="from@test.com"
        )
        
        with pytest.raises(FileNotFoundError, match="Файлы для вложения не найдены"):
            sender.send_email_with_attachments(
                "Тест", "body", "to@test.com", ["nonexistent.txt"]
            )
    
    @patch('email_service.sender.smtplib.SMTP_SSL')
    def test_test_connection_success(self, mock_smtp_ssl):
        """Тест успешной проверки подключения."""
        mock_smtp = MagicMock()
        mock_smtp_ssl.return_value.__enter__.return_value = mock_smtp
        
        sender = EmailSender(
            smtp_server="smtp.test.com",
            smtp_port=465,
            smtp_user="test@test.com",
            smtp_password="password",
            from_email="from@test.com"
        )
        
        result = sender.test_connection()
        assert result is True
        mock_smtp.login.assert_called_once()
    
    @patch('email_service.sender.smtplib.SMTP_SSL')
    def test_test_connection_failure(self, mock_smtp_ssl):
        """Тест неудачной проверки подключения."""
        mock_smtp_ssl.side_effect = Exception("Connection failed")
        
        sender = EmailSender(
            smtp_server="smtp.test.com",
            smtp_port=465,
            smtp_user="test@test.com",
            smtp_password="password",
            from_email="from@test.com"
        )
        
        result = sender.test_connection()
        assert result is False
