"""Виджет для отображения и выбора писем из найденной ветки."""

import tkinter as tk
from tkinter import ttk
from typing import List, Optional, Callable
from models.schemas import EmailInfo


class EmailBranchWidget:
    """Виджет для отображения списка найденных писем с возможностью выбора."""
    
    def __init__(self, parent_frame: ttk.Frame, on_selection_changed: Optional[Callable] = None):
        """
        Инициализация виджета.
        
        Args:
            parent_frame: Родительский фрейм
            on_selection_changed: Callback при изменении выбора
        """
        self.parent_frame = parent_frame
        self.on_selection_changed = on_selection_changed
        self.emails: List[EmailInfo] = []
        self.selected_email: Optional[EmailInfo] = None
        self.email_vars = {}  # {EmailInfo: BooleanVar}
        
        self._build_ui()
    
    def _build_ui(self):
        """Создает интерфейс виджета."""
        # Фрейм с прокруткой
        self.canvas = tk.Canvas(self.parent_frame, height=120)
        self.scrollbar = ttk.Scrollbar(self.parent_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # Добавляем поддержку прокрутки колесиком мыши
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.scrollable_frame.bind("<MouseWheel>", self._on_mousewheel)
        
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Сообщение когда список пуст
        self.empty_label = ttk.Label(self.scrollable_frame, text="Нажмите 'Найти ветку в почте' для поиска")
        self.empty_label.pack(pady=20)
    
    def _on_mousewheel(self, event):
        """Обработчик прокрутки колесиком мыши."""
        try:
            # На Windows event.delta дает значение кратное 120
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass
    
    def set_emails(self, emails: List[EmailInfo]):
        """Устанавливает список писем для отображения."""
        self.emails = emails
        self.selected_email = None
        self.email_vars.clear()
        
        # Очищаем текущий список
        for child in list(self.scrollable_frame.winfo_children()):
            child.destroy()
        
        if not emails:
            # Показываем сообщение о пустом списке
            self.empty_label = ttk.Label(self.scrollable_frame, text="Письма не найдены")
            self.empty_label.pack(pady=20)
        else:
            # Создаем чекбоксы для каждого письма
            for email_info in emails:
                var = tk.BooleanVar(value=False)
                self.email_vars[email_info] = var
                
                # Форматируем текст для отображения
                display_text = str(email_info)
                
                checkbox = ttk.Checkbutton(
                    self.scrollable_frame,
                    text=display_text,
                    variable=var,
                    command=lambda ei=email_info: self._on_email_checkbox_changed(ei)
                )
                checkbox.pack(anchor="w", padx=5, pady=2)
    
    def _on_email_checkbox_changed(self, selected_email: EmailInfo):
        """Обработчик изменения состояния чекбокса письма."""
        selected_now = self.email_vars[selected_email].get()
        
        if selected_now:
            # Если выбрали это письмо, снимаем выбор с остальных
            for email_info, var in self.email_vars.items():
                if email_info != selected_email and var.get():
                    var.set(False)
            
            self.selected_email = selected_email
        else:
            # Если сняли выбор с этого письма
            if self.selected_email == selected_email:
                self.selected_email = None
        
        # Вызываем callback
        if self.on_selection_changed:
            self.on_selection_changed(self.selected_email)
    
    def get_selected_email(self) -> Optional[EmailInfo]:
        """Возвращает выбранное письмо."""
        return self.selected_email
    
    def clear_selection(self):
        """Очищает выбор."""
        for var in self.email_vars.values():
            var.set(False)
        self.selected_email = None
        
        if self.on_selection_changed:
            self.on_selection_changed(None)