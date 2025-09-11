"""Тесты для модулей LLM."""

import pytest
import json
from unittest.mock import patch, MagicMock
import requests

from llm.client import LLMClient
from llm.prompt_builder import PromptBuilder


class TestLLMClient:
    """Тесты для LLMClient."""
    
    def test_init_with_config(self):
        """Тест инициализации с параметрами из config."""
        with patch('llm.client.config') as mock_config:
            mock_config.API_KEY = "test_key"
            mock_config.API_BASE_URL = "https://test.api"
            mock_config.DEFAULT_MODEL = "test_model"
            
            client = LLMClient()
            assert client.api_key == "test_key"
            assert client.base_url == "https://test.api"
            assert client.default_model == "test_model"
    
    def test_init_without_api_key_raises_error(self):
        """Тест ошибки при отсутствии API ключа."""
        with patch('llm.client.config') as mock_config:
            mock_config.API_KEY = None
            
            with pytest.raises(ValueError, match="API ключ не задан"):
                LLMClient()
    
    @patch('llm.client.requests.post')
    def test_query_success(self, mock_post):
        """Тест успешного запроса к LLM."""
        # Настраиваем мок ответа
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Тестовый ответ"}}]
        }
        mock_post.return_value = mock_response
        
        client = LLMClient(api_key="test_key", base_url="https://test.api")
        result = client.query("Тестовый промпт")
        
        assert result == "Тестовый ответ"
        mock_post.assert_called_once()
    
    @patch('llm.client.requests.post')
    def test_query_network_error(self, mock_post):
        """Тест обработки сетевой ошибки."""
        mock_post.side_effect = requests.RequestException("Network error")
        
        client = LLMClient(api_key="test_key", base_url="https://test.api")
        
        with pytest.raises(RuntimeError, match="Сетевой сбой"):
            client.query("Тестовый промпт")
    
    @patch('llm.client.requests.post')
    def test_query_http_error(self, mock_post):
        """Тест обработки HTTP ошибки."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_post.return_value = mock_response
        
        client = LLMClient(api_key="test_key", base_url="https://test.api")
        
        with pytest.raises(RuntimeError, match="Ошибка ответа OpenRouter"):
            client.query("Тестовый промпт")
    
    @patch('llm.client.requests.get')
    def test_get_available_models(self, mock_get):
        """Тест получения списка моделей."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "data": [
                {"id": "model1"},
                {"id": "model2:free"},
                {"id": "model3"}
            ]
        }
        mock_get.return_value = mock_response
        
        client = LLMClient(api_key="test_key", base_url="https://test.api")
        models = client.get_available_models()
        
        assert models == ["model1", "model2:free", "model3"]
    
    def test_extract_json_from_response(self):
        """Тест извлечения JSON из ответа LLM."""
        client = LLMClient(api_key="test_key")
        
        # Тест с markdown обёрткой
        response_with_markdown = "```json\n{\"key\": \"value\"}\n```"
        result = client.extract_json_from_response(response_with_markdown)
        assert result == "{\"key\": \"value\"}"
        
        # Тест без обёртки
        response_plain = "{\"key\": \"value\"}"
        result = client.extract_json_from_response(response_plain)
        assert result == "{\"key\": \"value\"}"


class TestPromptBuilder:
    """Тесты для PromptBuilder."""
    
    def test_build_single_invoice_prompt(self):
        """Тест построения промпта для одного счета."""
        prompt = PromptBuilder.build_single_invoice_prompt("test.pdf", "Тестовый текст")
        
        assert "test.pdf" in prompt
        assert "Тестовый текст" in prompt
        assert "JSON" in prompt
        assert "supplier" in prompt
        assert "items" in prompt
    
    def test_build_multi_invoice_prompt(self):
        """Тест построения промпта для нескольких счетов."""
        invoices = [
            {"filename": "invoice1.pdf", "text": "Текст счета 1"},
            {"filename": "invoice2.pdf", "text": "Текст счета 2"}
        ]
        
        prompt = PromptBuilder.build_multi_invoice_prompt(invoices)
        
        assert "invoice1.pdf" in prompt
        assert "invoice2.pdf" in prompt
        assert "Текст счета 1" in prompt
        assert "Текст счета 2" in prompt
        assert "[ { ... }, { ... }, ... ]" in prompt
    
    def test_build_multi_invoice_prompt_empty_list(self):
        """Тест ошибки при пустом списке счетов."""
        with pytest.raises(ValueError, match="Список счетов не может быть пустым"):
            PromptBuilder.build_multi_invoice_prompt([])
    
    def test_build_comparison_report_prompt(self):
        """Тест построения промпта для отчета сравнения."""
        template = "Шаблон: {{ application.number }} vs {{ invoice.number }}"
        app_json = {"number": "APP-001", "items": []}
        inv_json = {"number": "INV-001", "items": []}
        
        prompt = PromptBuilder.build_comparison_report_prompt(template, app_json, inv_json)
        
        assert "Jinja2-шаблон" in prompt
        assert template in prompt
        assert "APP-001" in prompt
        assert "INV-001" in prompt
        assert "опечаткой" in prompt  # Проверяем инструкции по опечаткам
