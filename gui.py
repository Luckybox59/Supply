import os
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from pathlib import Path
import json
import requests
import config
from tkinter import filedialog
import logging
from logging_setup import TkTextHandler, get_logger
from typing import Optional, List

# Прямое использование новой архитектуры lib/
import parser as core
from lib.data_processor import process_documents

# Новые импорты для поиска веток в почте
from lib.email_searcher import UnifiedEmailSearcher as EmailSearcher
from models.schemas import EmailInfo
from gui.components.email_branch_widget import EmailBranchWidget

class ParserGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Парсер счетов — GUI")
        self.geometry("1100x800")  # Увеличиваем высоту для лучшей демонстрации изменений

        self.cwd = os.getcwd()
        self.files = [f for f in os.listdir(self.cwd) if f.lower().endswith((".pdf", ".xls", ".xlsx"))]
        self.files.sort()

        self.app_var_map = {}   # для одиночного выбора заявки (чекбоксы, но разрешаем только одну галку)
        self.inv_var_map = {}   # для выбора счетов

        # Настройки модели OpenRouter
        self.selected_model = self._load_saved_model() or config.DEFAULT_MODEL or ''
        self.model_values = [self.selected_model] if self.selected_model else []
        
        # Инициализируем базовый логгер сразу (до _build_ui)
        self._logger = get_logger("parser.gui")
        
        # Новые переменные для поиска веток в почте (инициализируются в _build_ui)
        self.email_searcher = None  # Инициализируем по требованию в _init_email_searcher
        self.email_branch_widget = None  # Будет создан в _build_ui
        self.selected_reply_email = None  # Выбранное письмо для ответа

        self._build_ui()
        self._wire_events()

        # Данные результата
        self.app_selected = None
        self.invoices_selected = []
        self.report_md = None
        self.attachments = []  # абсолютные пути вложений для письма

        # Логирование в окно лога (добавляем text handler после создания log_text)
        try:
            handler = TkTextHandler(self.log_text)
            handler.setLevel(logging.INFO)
            # Вешаем хендлер на корневой логгер, чтобы видеть сообщения всех модулей
            logging.getLogger().addHandler(handler)
            self._logger.info("GUI инициализирован. Логи подключены к окну.")
            
            # После инициализации UI проверяем статус компонентов
            if self.email_branch_widget is not None:
                self._logger.info("✅ EmailBranchWidget доступен для использования")
            else:
                self._logger.warning("⚠️ EmailBranchWidget не инициализирован")
                
        except Exception:
            pass

    def _cleanup_generated_files(self, directory: str) -> int:
        """Удаляет сгенерированные файлы.
        Возвращает количество удалённых файлов.
        """
        count = 0
        try:
            import os
            import glob
            from pathlib import Path
            
            # Паттерны файлов для удаления
            patterns = [
                "*_extracted.json",
                "comparison_report.md", 
                "Карточка изделия.txt",
                "*_analysis.json"
            ]
            
            dir_path = Path(directory)
            for pattern in patterns:
                for file_path in dir_path.glob(pattern):
                    try:
                        file_path.unlink()
                        count += 1
                    except Exception:
                        pass
                        
        except Exception:
            pass
        return count

    def _build_ui(self):
        # Главный вертикальный панельный контейнер: сверху контент, снизу лог
        main_paned = ttk.Panedwindow(self, orient=tk.VERTICAL)
        main_paned.pack(fill=tk.BOTH, expand=True)

        # Верхний горизонтальный панельный контейнер: слева выбор/кнопка/почта, справа отчет
        top_paned = ttk.Panedwindow(main_paned, orient=tk.HORIZONTAL)
        main_paned.add(top_paned, weight=4)  # Вес 4 для пропорции 4:1 (80%:20%)

        # Левая вертикальная панель: файлы (заявки+счета горизонтально), кнопка, почта (в этом порядке)
        left_paned = ttk.Panedwindow(top_paned, orient=tk.VERTICAL)
        top_paned.add(left_paned, weight=2)  # Увеличиваем вес левой панели для большего пространства

        # 1) Горизонтальная панель для заявок и счетов
        files_paned = ttk.Panedwindow(left_paned, orient=tk.HORIZONTAL)
        left_paned.add(files_paned, weight=2)  # Увеличиваем вес для большей высоты

        # 1a) Заявка - левая часть горизонтальной панели
        app_frame = ttk.LabelFrame(files_paned, text="Заявка (необязательно, выбрать максимум 1)")
        files_paned.add(app_frame, weight=1)
        app_canvas = tk.Canvas(app_frame, height=140)
        app_scroll = ttk.Scrollbar(app_frame, orient="vertical", command=app_canvas.yview)
        self.app_list_frame = ttk.Frame(app_canvas)
        self.app_list_frame.bind(
            "<Configure>", lambda e: app_canvas.configure(scrollregion=app_canvas.bbox("all"))
        )
        app_canvas.create_window((0, 0), window=self.app_list_frame, anchor="nw")
        app_canvas.configure(yscrollcommand=app_scroll.set)
        app_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        app_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        for f in self.files:
            var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(self.app_list_frame, text=f, variable=var, command=lambda fname=f: self._on_app_checkbox_changed(fname))
            cb.pack(anchor="w")
            self.app_var_map[f] = var

        # 1b) Счета - правая часть горизонтальной панели
        inv_frame = ttk.LabelFrame(files_paned, text="Счета (выберите один или несколько)")
        files_paned.add(inv_frame, weight=1)
        inv_canvas = tk.Canvas(inv_frame, height=140)
        inv_scroll = ttk.Scrollbar(inv_frame, orient="vertical", command=inv_canvas.yview)
        self.inv_list_frame = ttk.Frame(inv_canvas)
        self.inv_list_frame.bind(
            "<Configure>", lambda e: inv_canvas.configure(scrollregion=inv_canvas.bbox("all"))
        )
        inv_canvas.create_window((0, 0), window=self.inv_list_frame, anchor="nw")
        inv_canvas.configure(yscrollcommand=inv_scroll.set)
        inv_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inv_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        for f in self.files:
            var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(self.inv_list_frame, text=f, variable=var, command=self._validate_run_button)
            cb.pack(anchor="w")
            self.inv_var_map[f] = var

        # 2) Кнопка запуска + выбор модели OpenRouter
        btn_frame = ttk.Frame(left_paned)
        left_paned.add(btn_frame, weight=0)
        self.run_btn = ttk.Button(btn_frame, text="Запустить обработку (LLM)", command=self._run_processing, state=tk.DISABLED)
        self.run_btn.pack(side=tk.LEFT, padx=8, pady=8)
        # Чекбокс: использовать LLM для генерации отчета по шаблону (иначе локально)
        self.use_llm_report_var = tk.BooleanVar(value=False)
        self.use_llm_report_cb = ttk.Checkbutton(btn_frame, text="Отчет через LLM", variable=self.use_llm_report_var)
        self.use_llm_report_cb.pack(side=tk.LEFT, padx=(12, 8))
        # Комбобокс с моделями справа от кнопки
        ttk.Label(btn_frame, text="Модель:").pack(side=tk.LEFT, padx=(12, 4))
        self.model_var = tk.StringVar(value=self.selected_model)
        self.model_combo = ttk.Combobox(btn_frame, textvariable=self.model_var, state="readonly", width=55, values=self.model_values)
        self.model_combo.pack(side=tk.LEFT, padx=(0, 8), pady=8)
        self.model_combo.bind('<<ComboboxSelected>>', lambda e: self._on_model_selected())
        # Загрузка списка моделей в фоне
        threading.Thread(target=self._fetch_models_thread, daemon=True).start()
        
        # 2.5) Email ветки - новый блок
        branch_frame = ttk.LabelFrame(left_paned, text="Поиск веток в почте")
        left_paned.add(branch_frame, weight=3)  # Увеличиваем вес с 2 до 3 для большей высоты
        
        # Кнопка поиска
        branch_btn_frame = ttk.Frame(branch_frame)
        branch_btn_frame.pack(fill=tk.X, padx=4, pady=4)
        
        self.find_branch_btn = ttk.Button(
            branch_btn_frame,
            text="Найти ветку в почте",
            command=self._on_find_email_branch,
            state=tk.DISABLED
        )
        self.find_branch_btn.pack(side=tk.LEFT, padx=(0, 8))
        
        # Статус поиска
        self.branch_status_label = ttk.Label(branch_btn_frame, text="Заполните поля почты для поиска")
        self.branch_status_label.pack(side=tk.LEFT, padx=(8, 0))
        
        # Виджет списка писем
        try:
            self.email_branch_widget = EmailBranchWidget(
                branch_frame,
                on_selection_changed=self._on_email_selected
            )
            # Логирование с проверкой наличия логгера
            if hasattr(self, '_logger') and self._logger:
                self._logger.info("EmailBranchWidget успешно инициализирован")
        except Exception as e:
            # Логирование с проверкой наличия логгера
            if hasattr(self, '_logger') and self._logger:
                self._logger.error(f"Ошибка инициализации EmailBranchWidget: {e}")
            else:
                print(f"Error initializing EmailBranchWidget: {e}")  # Fallback к print
            self.email_branch_widget = None

        # 3) Почта
        mail_frame = ttk.LabelFrame(left_paned, text="Отправка письма")
        left_paned.add(mail_frame, weight=2)  # Увеличиваем вес для большей высоты
        ttk.Label(mail_frame, text="Кому").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        ttk.Label(mail_frame, text="Тема").grid(row=1, column=0, sticky="e", padx=4, pady=4)
        ttk.Label(mail_frame, text="Текст").grid(row=2, column=0, sticky="ne", padx=4, pady=4)
        self.to_entry = ttk.Entry(mail_frame, width=60)
        self.subj_entry = ttk.Entry(mail_frame, width=60)
        self.body_text = ScrolledText(mail_frame, width=60, height=6, wrap=tk.WORD)
        self.to_entry.grid(row=0, column=1, sticky="we", padx=4, pady=4)
        self.subj_entry.grid(row=1, column=1, sticky="we", padx=4, pady=4)
        self.body_text.grid(row=2, column=1, sticky="we", padx=4, pady=4)
        
        # Добавляем обработчики для полей почты
        self.to_entry.bind('<KeyRelease>', lambda e: self._validate_email_search_fields())
        self.subj_entry.bind('<KeyRelease>', lambda e: (self._sync_peredelka_from_subject(), self._validate_email_search_fields()))
        # Вложения: список под полем текста (скроллируемые строки с крестиком удаления)
        ttk.Label(mail_frame, text="Вложения").grid(row=3, column=0, sticky="ne", padx=4, pady=(0,4))
        attach_frame = ttk.Frame(mail_frame)
        attach_frame.grid(row=3, column=1, sticky="nsew", padx=4, pady=(0,4))
        mail_frame.rowconfigure(3, weight=1)
        mail_frame.columnconfigure(1, weight=1)
        self.attach_canvas = tk.Canvas(attach_frame, height=110)
        self.attach_scroll = ttk.Scrollbar(attach_frame, orient="vertical", command=self.attach_canvas.yview)
        self.attach_list_frame = ttk.Frame(self.attach_canvas)
        self.attach_list_frame.bind("<Configure>", lambda e: self.attach_canvas.configure(scrollregion=self.attach_canvas.bbox("all")))
        self.attach_canvas.create_window((0,0), window=self.attach_list_frame, anchor="nw")
        self.attach_canvas.configure(yscrollcommand=self.attach_scroll.set)
        self.attach_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.attach_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        # Кнопки управления вложениями под списком
        attach_btns = ttk.Frame(mail_frame)
        attach_btns.grid(row=4, column=1, sticky="w", padx=4, pady=(0,8))
        self.add_attach_btn = ttk.Button(attach_btns, text="Прикрепить...", command=self._on_attach_files)
        self.add_attach_btn.pack(side=tk.LEFT)
        # Правая колонка почтового блока: чекбокс Переделка над кнопкой Отправить
        right_mail_col = ttk.Frame(mail_frame)
        right_mail_col.grid(row=0, column=2, rowspan=5, sticky="ns", padx=8, pady=4)
        self.peredelka_var = tk.BooleanVar(value=False)
        self.peredelka_cb = ttk.Checkbutton(right_mail_col, text="Переделка", variable=self.peredelka_var, command=self._on_peredelka_toggle)
        self.peredelka_cb.pack(anchor="n", pady=(0, 6))
        
        # Переносим кнопку отправки ниже
        self.send_btn = ttk.Button(right_mail_col, text="Отправить письмо", command=self._send_mail, state=tk.DISABLED)
        self.send_btn.pack(anchor="n")
        mail_frame.columnconfigure(1, weight=1)

        # Правая часть — Отчет
        report_frame = ttk.LabelFrame(top_paned, text="Отчет сравнения (Markdown)")
        top_paned.add(report_frame, weight=2)
        self.report_text = ScrolledText(report_frame, wrap=tk.WORD)
        self.report_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Нижняя часть — Лог (20% от высоты окна)
        log_frame = ttk.LabelFrame(main_paned, text="Лог выполнения")
        main_paned.add(log_frame, weight=1)  # Вес 1 для пропорции 4:1 (20% высоты)
        self.log_text = ScrolledText(log_frame, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        

        # Инициализируем доступность чекбокса 'Переделка' по текущей теме (обычно пусто)
        self.after(0, self._sync_peredelka_from_subject)

    def _wire_events(self):
        pass

    # ---- Настройки модели (persist) ----
    def _settings_path(self) -> Path:
        return Path(__file__).with_name('settings.json')

    def _load_saved_model(self):
        try:
            p = self._settings_path()
            if p.exists():
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data.get('openrouter_model')
        except Exception:
            return None

    def _save_selected_model(self):
        try:
            p = self._settings_path()
            data = { 'openrouter_model': self.model_var.get() }
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


    def _on_model_selected(self):
        self.selected_model = self.model_var.get().strip()
        if self.selected_model:
            # Сохраним и выставим переменную окружения для процесса
            os.environ['OPENROUTER_MODEL'] = self.selected_model
            self._save_selected_model()

    def _fetch_models_thread(self):
        # Получим список бесплатных моделей через OpenRouter API
        try:
            url = f"{getattr(config, 'API_BASE_URL', 'https://openrouter.ai/api/v1')}/models"
            headers = { 'Authorization': f"Bearer {getattr(config, 'API_KEY', '') or ''}" }
            r = requests.get(url, headers=headers, timeout=30)
            if r.ok:
                data = r.json().get('data', [])
                ids = [x.get('id', '') for x in data if isinstance(x, dict)]
                free = [i for i in ids if ':free' in i]
                # Предпочитаем instruct-роуты сначала
                instruct = [i for i in free if 'instruct' in i.lower()]
                others = [i for i in free if i not in instruct]
                values = instruct + others
                # Гарантируем наличие выбранной модели в списке
                if self.selected_model and self.selected_model not in values:
                    values.insert(0, self.selected_model)
                if not values and self.selected_model:
                    values = [self.selected_model]
                self.after(0, lambda v=values: self._apply_model_values(v))
        except Exception:
            # Тихо игнорируем ошибки сети, оставляем текущее значение
            pass

    def _apply_model_values(self, values):
        try:
            self.model_values = values
            self.model_combo.configure(values=values)
            if not self.model_var.get() and values:
                self.model_var.set(values[0])
                self._on_model_selected()
        except Exception:
            pass

    def _on_app_checkbox_changed(self, selected_name: str):
        # Заявка опциональна: если кликнутый чекбокс стал True — снимаем остальные;
        # если стал False — ничего не трогаем (разрешаем 0 выбранных)
        selected_now = self.app_var_map[selected_name].get()
        if selected_now:
            for name, var in self.app_var_map.items():
                if name != selected_name and var.get():
                    var.set(False)
        self._validate_run_button()

    def _validate_run_button(self):
        inv_checked = [name for name, var in self.inv_var_map.items() if var.get()]
        # Кнопка обработки активна, если выбран хотя бы один счет
        self.run_btn.configure(state=(tk.NORMAL if len(inv_checked) > 0 else tk.DISABLED))

    def _on_peredelka_toggle(self):
        # Добавляем/убираем суффикс (из настроек) в теме по состоянию чекбокса
        subject = self.subj_entry.get().strip()
        token = getattr(config, 'SUBJECT_SUFFIX_PEREDELKA', '(#ПЕР)') or '(#ПЕР)'
        if self.peredelka_var.get():
            if token not in subject:
                # Без лишнего пробела перед суффиксом
                subject = (subject + token).strip()
        else:
            if token in subject:
                subject = subject.replace(token, "").replace("  ", " ").strip()
        self.subj_entry.delete(0, tk.END)
        self.subj_entry.insert(0, subject)

    def _sync_peredelka_from_subject(self):
        # Если пользователь правит тему руками — отражаем это на чекбоксе и его доступности
        subj = self.subj_entry.get()
        token = getattr(config, 'SUBJECT_SUFFIX_PEREDELKA', '(#ПЕР)') or '(#ПЕР)'
        has = token in subj
        is_empty = len(subj.strip()) == 0
        # Синхронизация состояния
        if self.peredelka_var.get() != has:
            self.peredelka_var.set(has)
        # Доступность чекбокса
        if is_empty:
            self.peredelka_cb.configure(state=tk.DISABLED)
            # При пустой теме не держим чекбокс включенным
            if self.peredelka_var.get():
                self.peredelka_var.set(False)
        else:
            self.peredelka_cb.configure(state=tk.NORMAL)

    def _set_mail_defaults(self, results, elapsed_time, json_file, report_file, card_file):
        # Значения по умолчанию с новой архитектурой
        to_email_default = (getattr(config, 'TO_EMAIL_DEFAULT', '') or '').strip()
        
        # Извлекаем данные из результатов
        if results:
            first_result = results[0]
            _postav = (first_result.get('поставщик') or '').strip()
            _num = (first_result.get('номер') or '').strip()
            _zakaz = (first_result.get('заказчик') or 'не найдено').strip()
            _izdelie = (first_result.get('изделие') or '').strip()

            # Подсчитываем общую сумму без разделителей разрядов, с точкой как десятичным разделителем
            total_sum = 0.0
            for result in results:
                if 'сумма' in result:
                    try:
                        amount = float(str(result['сумма']).replace(',', '.').replace(' ', ''))
                        total_sum += amount
                    except (ValueError, TypeError):
                        pass

            # Формируем строковое представление суммы без лишних нулей
            sum_str = ("{0:.10f}".format(total_sum)).rstrip('0').rstrip('.') if isinstance(total_sum, float) else str(total_sum)

            # Тема: гарантированно включаем номер проекта, если он есть
            if _num:
                subject_default = f"{_postav}({_num}){_zakaz}".strip()
            else:
                subject_default = f"{_postav} { _zakaz }".strip()

            # Тело: строго в виде [Изделие: сумма]
            body_default = f"[{_izdelie}: {sum_str}]"
        else:
            subject_default = "Обработка завершена"
            body_default = f"Обработка завершена за {elapsed_time:.2f} сек."
        self.to_entry.delete(0, tk.END)
        self.subj_entry.delete(0, tk.END)
        self.body_text.delete("1.0", tk.END)
        self.to_entry.insert(0, to_email_default)
        self.subj_entry.insert(0, subject_default)
        # Синхронизируем чекбокс '(#ПЕР)' с темой по умолчанию
        if hasattr(self, 'peredelka_var'):
            self._sync_peredelka_from_subject()
        self.body_text.insert("1.0", body_default)
        # Инициализируем вложения: по умолчанию ТОЛЬКО исходные файлы счетов
        try:
            self.attachments = []
            # Добавляем исходные файлы счетов
            for f in self.invoices_selected:
                self.attachments.append(os.path.join(self.cwd, f))
            self._refresh_attachments_view()
        except Exception:
            self.attachments = []
            self._refresh_attachments_view()
        # Активируем кнопку отправки
        self.send_btn.configure(state=tk.NORMAL)
        # Проверяем активацию кнопки поиска веток после программного заполнения полей
        self._validate_email_search_fields()

    def _run_processing(self):
        # Собираем выбор
        self.app_selected = next((name for name, var in self.app_var_map.items() if var.get()), None)
        self.invoices_selected = [name for name, var in self.inv_var_map.items() if var.get()]

        # Предварительная проверка: API ключ
        api_key = getattr(config, 'API_KEY', '') or ''
        if not api_key.strip():
            messagebox.showwarning("Проверка", "Не задан OPENROUTER_API_KEY (config/secrets). Укажите ключ перед запуском.")
            return

        # Блокируем кнопку чтобы не нажимали повторно
        self.run_btn.configure(state=tk.DISABLED)
        self.send_btn.configure(state=tk.DISABLED)
        self.report_text.delete("1.0", tk.END)

        # Запускаем в отдельном потоке, чтобы не подвесить GUI
        threading.Thread(target=self._process_thread, daemon=True).start()

    def _process_thread(self):
        try:
            self._process_core()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка обработки: {e}")
        finally:
            # Повторная валидация кнопок
            self._validate_run_button()

    def _process_core(self):
        # Используем новую архитектуру lib/
        results, elapsed_time, report_content, output_files = process_documents(
            work_dir=self.cwd,
            application_file=self.app_selected,
            invoice_files=self.invoices_selected,
            model=(self.selected_model or config.DEFAULT_MODEL),
            use_llm_report=bool(self.use_llm_report_var.get())
        )
        
        # Преобразуем output_files для совместимости
        json_file = output_files.get('json', '')
        report_file = output_files.get('report', '')
        card_file = output_files.get('card')

        if not results:
            self._logger.warning('Нет успешно обработанных счетов.')
            return

        # Заполнение полей письма и показ отчета (если был)
        self._set_mail_defaults(results, elapsed_time, json_file, report_file, card_file)
        if report_content:
            self.report_text.insert("1.0", report_content)

        messagebox.showinfo("Готово", "Обработка завершена. Проверьте отчет (если был) и поля письма.")

    # ---- Работа с вложениями ----
    def _refresh_attachments_view(self):
        # Пересобираем список строк вложений с кнопками удаления
        for child in list(self.attach_list_frame.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass
        for p in self.attachments:
            row = ttk.Frame(self.attach_list_frame)
            row.pack(fill=tk.X, padx=0, pady=0)
            name_lbl = ttk.Label(row, text=os.path.basename(p), anchor="w")
            name_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4,0))
            btn = ttk.Button(row, text="✕", width=3, command=lambda _p=p: self._detach_one(_p))
            btn.pack(side=tk.RIGHT, padx=(4,4))

    def _on_attach_files(self):
        try:
            # Разрешаем выбирать только в текущей папке и поддерживаемые расширения
            paths = filedialog.askopenfilenames(
                title="Выберите файлы для вложения",
                initialdir=self.cwd,
                filetypes=[
                    ("Документы", "*.pdf *.xls *.xlsx"),
                    ("PDF", "*.pdf"),
                    ("Excel", "*.xls *.xlsx")
                ]
            )
            if not paths:
                return
            # Фильтруем: только файлы из текущей папки (с нормализацией путей)
            from pathlib import Path as _P
            cwd_res = _P(self.cwd).resolve()
            allowed = {'.pdf', '.xls', '.xlsx'}
            new_paths = []
            for p in paths:
                try:
                    pres = _P(p).resolve()
                    if pres.parent == cwd_res and pres.suffix.lower() in allowed:
                        new_paths.append(str(pres))
                except Exception:
                    continue
            # Добавляем без дубликатов
            s = set(self.attachments)
            for p in new_paths:
                if p not in s:
                    self.attachments.append(p)
            self._refresh_attachments_view()
        except Exception:
            pass

    def _detach_one(self, path: str):
        try:
            self.attachments = [p for p in self.attachments if p != path]
            self._refresh_attachments_view()
        except Exception:
            pass

    def _send_mail(self):
        to_email = self.to_entry.get().strip()
        subject = self.subj_entry.get().strip()
        body = self.body_text.get("1.0", tk.END).strip()
        if not to_email or not subject or not body:
            messagebox.showwarning("Проверка", "Заполните поля 'Кому', 'Тема' и 'Текст'.")
            return
        attachments = list(self.attachments)
        if not attachments:
            messagebox.showwarning("Проверка", "Нет выбранных счетов для отправки.")
            return

        # Отправка в отдельном потоке
        def _send():
            try:
                smtp_server = getattr(config, 'SMTP_SERVER', 'smtp.gmail.com')
                smtp_port = int(getattr(config, 'SMTP_PORT', 465))
                smtp_user = getattr(config, 'SMTP_USER', None)
                smtp_password = getattr(config, 'SMTP_PASSWORD', None)
                from_email = getattr(config, 'FROM_EMAIL', smtp_user)
                if not (smtp_user and smtp_password and from_email):
                    raise RuntimeError("Не заданы параметры SMTP (SMTP_USER/SMTP_PASSWORD/FROM_EMAIL). Укажите их в переменных окружения или config.")
                # Используем новую архитектуру lib/ для отправки email
                from lib.email_sender import UnifiedEmailSender
                email_sender = UnifiedEmailSender(from_email)
                
                # Проверяем, есть ли выбранное письмо для ответа
                if self.selected_reply_email:
                    # Отправляем ответ
                    email_sender.send_reply(
                        to_email=to_email,
                        subject=subject,
                        body=body,
                        attachments=attachments,
                        original_message_id=self.selected_reply_email.message_id,
                        references=self.selected_reply_email.references
                    )
                    try:
                        self._logger.info(f"Отправлен ответ на письмо: {self.selected_reply_email.message_id}")
                    except Exception:
                        pass
                else:
                    # Обычная отправка
                    email_sender.send_email(
                        to_email=to_email,
                        subject=subject,
                        body=body,
                        attachments=attachments
                    )
                    try:
                        self._logger.info("Отправлено новое письмо")
                    except Exception:
                        pass
                # Переименование папки заказа: добавить метку "Оплата"
                try:
                    self._mark_folder_as_paid()
                except Exception as _e:
                    # Тихо залогируем, но не считаем ошибкой отправки
                    try:
                        self._logger.warning(f"Не удалось пометить папку как 'Оплата': {_e}")
                    except Exception:
                        pass
                # Сбросить все сформированные данные в окне (кроме лога)
                try:
                    self.after(0, self._reset_after_send)
                except Exception:
                    pass
                messagebox.showinfo("Почта", "Письмо отправлено успешно.")
            except Exception as e:
                messagebox.showerror("Почта", f"Ошибка при отправке письма: {e}")

        threading.Thread(target=_send, daemon=True).start()

    def _mark_folder_as_paid(self):
        """Добавляет слово 'Оплата' в имя текущей папки (self.cwd).
        Правило: вставить метку оплаты прямо перед последней закрывающей скобкой ')'.
        Если ')' нет — добавить метку в конец имени без дополнительных пробелов/скобок.
        Если уже содержит 'Оплата' — ничего не делаем.
        Обновляем self.cwd и заголовок окна.
        """
        try:
            t0 = time.perf_counter()
            cur = Path(self.cwd)
            name = cur.name
            paid = getattr(config, 'FOLDER_PAID_LABEL', 'Оплата') or 'Оплата'
            # Всегда сначала удаляем сгенерированные приложением файлы,
            # даже если метка оплаты уже присутствует в имени папки
            try:
                removed = self._cleanup_generated_files(directory=str(cur))
                try:
                    self._logger.info(f"Удалено файлов приложения перед переименованием/пометкой: {removed}")
                except Exception:
                    pass
            except Exception:
                pass
            # Если метка уже в имени — переименование не требуется
            if paid in name:
                return
            idx = name.rfind(')')
            if idx != -1:
                # Вставляем метку как есть (без добавления ведущего пробела)
                new_name = name[:idx] + f'{paid}' + name[idx:]
            else:
                # Добавляем метку в конец без доп. пробелов/скобок
                new_name = name + f'{paid}'
            new_path = cur.with_name(new_name)
            if new_path.exists():
                # Не перезаписываем существующую папку
                return
            # На Windows нельзя переименовать текущую рабочую директорию процесса.
            # Временно сменим CWD на родительскую, выполним rename, затем перейдем в новую папку.
            import os as _os
            orig_proc_cwd = _os.getcwd()
            try:
                _os.chdir(str(cur.parent))
                cur.rename(new_path)
                # Перейдем в новую директорию (не обязательно, но удобно для относительных путей)
                _os.chdir(str(new_path))
            except Exception:
                # Откатим рабочую директорию процесса
                try:
                    _os.chdir(orig_proc_cwd)
                except Exception:
                    pass
                raise
            # Обновим cwd и заголовок окна в главном потоке
            self.cwd = str(new_path)
            self.after(0, lambda: self.title(f"Парсер счетов — GUI — {new_name}"))
            # Перечитаем файлы и перерисуем списки
            self.after(0, self._reload_files_and_lists)
            t1 = time.perf_counter()
            try:
                self._logger.info(f"Очистка файлов и переименование папки заняли: {t1 - t0:.3f} с")
            except Exception:
                pass
        except Exception as e:
            raise

    def _reload_files_and_lists(self):
        """Перечитывает список файлов из self.cwd и перерисовывает чекбоксы заявок/счетов."""
        try:
            # Обновим список файлов
            self.files = [f for f in os.listdir(self.cwd) if f.lower().endswith((".pdf", ".xls", ".xlsx"))]
            self.files.sort()
            # Сбросим отображение
            for child in list(self.app_list_frame.winfo_children()):
                try:
                    child.destroy()
                except Exception:
                    pass
            for child in list(self.inv_list_frame.winfo_children()):
                try:
                    child.destroy()
                except Exception:
                    pass
            # Пересоберем карты состояний
            self.app_var_map.clear()
            self.inv_var_map.clear()
            for f in self.files:
                var = tk.BooleanVar(value=False)
                cb = ttk.Checkbutton(self.app_list_frame, text=f, variable=var, command=lambda fname=f: self._on_app_checkbox_changed(fname))
                cb.pack(anchor="w")
                self.app_var_map[f] = var
            for f in self.files:
                var = tk.BooleanVar(value=False)
                cb = ttk.Checkbutton(self.inv_list_frame, text=f, variable=var, command=self._validate_run_button)
                cb.pack(anchor="w")
                self.inv_var_map[f] = var
            # Провалидируем кнопки
            self._validate_run_button()
        except Exception:
            pass

    def _reset_after_send(self):
        """Сбрасывает все данные UI, сформированные после запуска LLM, кроме лога."""
        try:
            t0 = time.perf_counter()
            # Очистим отчет
            try:
                self.report_text.delete("1.0", tk.END)
            except Exception:
                pass
            # Очистим поля письма
            try:
                self.to_entry.delete(0, tk.END)
                self.subj_entry.delete(0, tk.END)
                self.body_text.delete("1.0", tk.END)
                # Синхронизируем чекбокс переделки и отключим его при пустой теме
                self._sync_peredelka_from_subject()
                # Проверяем активацию кнопки поиска веток после очистки полей
                self._validate_email_search_fields()
            except Exception:
                pass
            # Очистим вложения
            try:
                self.attachments = []
                self._refresh_attachments_view()
            except Exception:
                pass
            # Очищаем выбор письма для ответа
            try:
                self.selected_reply_email = None
                if self.email_branch_widget:
                    self.email_branch_widget.clear_selection()
                # Возвращаем обычный текст кнопки
                self.send_btn.configure(text="Отправить письмо")
            except Exception:
                pass
            # Снимем выборы файлов
            try:
                for var in self.app_var_map.values():
                    var.set(False)
                for var in self.inv_var_map.values():
                    var.set(False)
            except Exception:
                pass
            # Внутренние переменные
            self.app_selected = None
            self.invoices_selected = []
            self.report_md = None
            # Кнопки
            try:
                self._validate_run_button()  # выключит run_btn
                self.send_btn.configure(state=tk.DISABLED)
            except Exception:
                pass
            t1 = time.perf_counter()
            try:
                self._logger.info(f"Сброс данных UI после отправки занял: {t1 - t0:.3f} с")
            except Exception:
                pass
        except Exception:
            pass
    
    # ---- Новые методы для поиска веток в почте ----
    
    def _init_email_searcher(self):
        """Инициализирует EmailSearcher при первом использовании."""
        if self.email_searcher is None:
            try:
                self.email_searcher = EmailSearcher()
                self._logger.info("EmailSearcher инициализирован")
            except Exception as e:
                self._logger.error(f"Ошибка инициализации EmailSearcher: {e}")
                messagebox.showerror("Ошибка", f"Не удалось инициализировать поиск по почте: {e}")
                return False
        return True

    def _validate_email_search_fields(self) -> bool:
        """Проверяет, что поля почты заполнены для поиска."""
        try:
            to_email = self.to_entry.get().strip() if hasattr(self, 'to_entry') and self.to_entry else ""
            subject = self.subj_entry.get().strip() if hasattr(self, 'subj_entry') and self.subj_entry else ""
            
            has_fields = bool(to_email and subject)
            
            # Обновляем состояние кнопок
            state = tk.NORMAL if has_fields else tk.DISABLED
            try:
                if hasattr(self, 'find_branch_btn') and self.find_branch_btn:
                    self.find_branch_btn.configure(state=state)
            except Exception:
                pass
            
            # Обновляем статус
            try:
                if hasattr(self, 'branch_status_label') and self.branch_status_label:
                    if has_fields:
                        self.branch_status_label.configure(text="Готов к поиску")
                    else:
                        self.branch_status_label.configure(text="Заполните поля почты для поиска")
            except Exception:
                pass
            
            return has_fields
        except Exception:
            return False

    def _on_find_email_branch(self):
        """Обработчик кнопки поиска ветки в почте."""
        if not self._validate_email_search_fields():
            messagebox.showwarning("Проверка", "Заполните поля 'Кому' и 'Тема' для поиска.")
            return
        
        if not self._init_email_searcher():
            return
        
        # Получаем данные для поиска
        to_email = self.to_entry.get().strip()
        subject = self.subj_entry.get().strip()
        
        self._logger.info(f"Инициирован поиск веток в почте для получателя: {to_email}")
        
        # Блокируем кнопки на время поиска
        try:
            self.find_branch_btn.configure(state=tk.DISABLED)
            self.branch_status_label.configure(text="Поиск...")
        except Exception:
            pass
        
        # Запускаем поиск в отдельном потоке
        threading.Thread(
            target=self._search_email_branch_thread,
            args=(to_email, subject),
            daemon=True
        ).start()

    def _search_email_branch_thread(self, to_email: str, subject: str = ""):
        """Поиск писем в отдельном потоке."""
        import time
        start_time = time.perf_counter()
        
        try:
            self._logger.info(f"Начат поиск веток в почте: получатель='{to_email}', тема='{subject}'")
            
            emails = self.email_searcher.search_emails_by_recipient(to_email, subject)
            
            elapsed_time = time.perf_counter() - start_time
            self._logger.info(f"Поиск веток завершен за {elapsed_time:.2f} с. Найдено писем: {len(emails)}")
            
            # Обновляем UI в основном потоке
            self.after(0, lambda: self._update_email_search_results(emails, elapsed_time))
            
        except Exception as e:
            elapsed_time = time.perf_counter() - start_time
            self._logger.error(f"Ошибка поиска писем за {elapsed_time:.2f} с: {e}")
            self.after(0, lambda: self._update_email_search_error(str(e)))

    def _update_email_search_results(self, emails: List[EmailInfo], elapsed_time: float = 0):
        """Обновляет результаты поиска в UI."""
        try:
            # Обновляем список писем (с проверкой на None)
            if self.email_branch_widget is not None and hasattr(self.email_branch_widget, 'set_emails'):
                self.email_branch_widget.set_emails(emails)
                self._logger.info(f"Передано {len(emails)} писем в EmailBranchWidget")
            else:
                if self.email_branch_widget is None:
                    self._logger.warning("EmailBranchWidget равен None")
                else:
                    self._logger.warning(f"EmailBranchWidget не имеет метод set_emails. Тип: {type(self.email_branch_widget)}")
            
            # Обновляем статус (с указанием времени поиска)
            if hasattr(self, 'branch_status_label') and self.branch_status_label:
                if emails:
                    if elapsed_time > 0:
                        self.branch_status_label.configure(text=f"Найдено писем: {len(emails)} за {elapsed_time:.1f}с")
                    else:
                        self.branch_status_label.configure(text=f"Найдено писем: {len(emails)}")
                else:
                    if elapsed_time > 0:
                        self.branch_status_label.configure(text=f"Письма не найдены (поиск {elapsed_time:.1f}с)")
                    else:
                        self.branch_status_label.configure(text="Письма не найдены")
            
            # Восстанавливаем кнопки
            if self._validate_email_search_fields():
                if hasattr(self, 'find_branch_btn') and self.find_branch_btn:
                    self.find_branch_btn.configure(state=tk.NORMAL)
            
            if elapsed_time > 0:
                self._logger.info(f"Обновление UI завершено. Общее время операции: {elapsed_time:.2f} с")
            
        except Exception as e:
            self._logger.error(f"Ошибка обновления UI: {e}")

    def _update_email_search_error(self, error_msg: str):
        """Обновляет UI при ошибке поиска."""
        try:
            # Обновляем статус
            if hasattr(self, 'branch_status_label') and self.branch_status_label:
                self.branch_status_label.configure(text="Ошибка поиска")
            
            # Восстанавливаем кнопки
            if self._validate_email_search_fields():
                if hasattr(self, 'find_branch_btn') and self.find_branch_btn:
                    self.find_branch_btn.configure(state=tk.NORMAL)
            
            messagebox.showerror("Ошибка поиска", f"Не удалось найти письма:\n{error_msg}")
            
        except Exception as e:
            self._logger.error(f"Ошибка обновления UI при ошибке: {e}")

    def _on_email_selected(self, email_info: Optional[EmailInfo]):
        """Обработчик выбора письма из списка."""
        self.selected_reply_email = email_info
        
        if email_info:
            self._logger.info(f"Выбрано письмо для ответа: {email_info.subject}")
            
            # Обновляем текст кнопки отправки
            try:
                self.send_btn.configure(text="Ответить на письмо")
            except Exception:
                pass
        else:
            self._logger.info("Отменен выбор письма для ответа")
            
            # Возвращаем обычный текст кнопки
            try:
                self.send_btn.configure(text="Отправить письмо")
            except Exception:
                pass


if __name__ == "__main__":
    app = ParserGUI()
    app.mainloop()
