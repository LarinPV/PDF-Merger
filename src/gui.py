"""
Modern Graphical User Interface for PDF Merger.
Supports:
- Drag-and-drop row reordering for single AND multiple selected files
- Drag-and-drop files directly from Windows Explorer
- High-DPI scaling awareness on Windows
- Keyboard shortcuts
"""

import os
import sys
import datetime
import subprocess
import threading
import webbrowser
from typing import List, Optional

# Enable High DPI awareness on Windows before importing tkinter
if sys.platform == 'win32':
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import windnd
except ImportError:
    windnd = None

from src.merger import merge_files, MergeError
from src.converter import ALL_SUPPORTED_EXTENSIONS, is_supported_file
from src.registry import is_context_menu_installed, install_context_menu, uninstall_context_menu


def format_size(bytes_size: int) -> str:
    if bytes_size < 1024:
        return f"{bytes_size} Б"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} КБ"
    else:
        return f"{bytes_size / (1024 * 1024):.1f} МБ"


def get_file_type_label(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.pdf':
        return "PDF Документ"
    elif ext in ('.docx', '.doc'):
        return "Word Документ"
    elif ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp', '.gif'):
        return "Изображение"
    elif ext in ('.txt', '.log', '.md', '.rtf', '.csv'):
        return "Текстовый файл"
    return "Файл"


class PDFMergerApp(tk.Tk):
    def __init__(self, initial_files: Optional[List[str]] = None):
        super().__init__()
        
        self.title("Объединение в PDF")
        self.geometry("780x540")
        self.minsize(560, 360)
        
        # Center window
        self._center_window()
        
        # Icon
        self._set_app_icon()
        
        # State
        self.file_items: List[str] = []
        self.is_merging = False
        
        # Multi-row drag state
        self._drag_selected_indices: List[int] = []
        self._drag_anchor_index: Optional[int] = None
        self._drag_pending: bool = False
        self._is_dragging: bool = False
        
        self._setup_styles()
        self._create_widgets()
        self._bind_shortcuts()
        self._setup_dnd()
        
        # Load initial files if provided
        if initial_files:
            self.add_files(initial_files)

    def _center_window(self):
        self.update_idletasks()
        w = 780
        h = 540
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _set_app_icon(self):
        if getattr(sys, 'frozen', False):
            base_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
        ico_path = os.path.join(base_dir, "assets", "app_icon.ico")
        if os.path.exists(ico_path):
            try:
                self.iconbitmap(ico_path)
            except Exception:
                pass

    def _setup_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use('vista')
        except Exception:
            pass
            
        style.configure('TButton', font=('Segoe UI', 9), padding=(6, 3))
        style.configure('Primary.TButton', font=('Segoe UI', 10, 'bold'), padding=(12, 6))
        style.configure('Header.TLabel', font=('Segoe UI', 12, 'bold'), foreground='#1E293B')
        style.configure('Subheader.TLabel', font=('Segoe UI', 9), foreground='#64748B')
        style.configure('Status.TLabel', font=('Segoe UI', 9), foreground='#334155')
        style.configure('Link.TLabel', font=('Segoe UI', 9), foreground='#2563EB')

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding="14 10 14 10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. Top bar: File counter on left, Context menu button and GitHub link on right
        top_bar = ttk.Frame(main_frame)
        top_bar.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))

        self.count_label = ttk.Label(top_bar, text="Файлы (0)", font=('Segoe UI', 10, 'bold'))
        self.count_label.pack(side=tk.LEFT, anchor=tk.W)

        self.integration_btn = ttk.Button(
            top_bar, 
            command=self._toggle_context_menu
        )
        self.integration_btn.pack(side=tk.RIGHT, anchor=tk.E)
        self._update_integration_button_text()

        # GitHub author link
        self.github_link = ttk.Label(
            top_bar,
            text="GitHub: @LarinPV",
            cursor="hand2",
            style='Link.TLabel'
        )
        self.github_link.pack(side=tk.RIGHT, padx=(0, 14), anchor=tk.E)
        self.github_link.bind("<Button-1>", lambda e: self._open_github())
        self.github_link.bind("<Enter>", lambda e: self.github_link.configure(font=('Segoe UI', 9, 'underline'), foreground='#1D4ED8'))
        self.github_link.bind("<Leave>", lambda e: self.github_link.configure(font=('Segoe UI', 9), foreground='#2563EB'))

        # 2. Toolbar: Action buttons (Add, Delete, Clear) & Ordering (Up, Down)
        toolbar = ttk.Frame(main_frame)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))

        left_tb = ttk.Frame(toolbar)
        left_tb.pack(side=tk.LEFT)

        ttk.Button(left_tb, text="➕ Добавить файлы", command=self._add_files_dialog).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(left_tb, text="📂 Добавить папку", command=self._add_folder_dialog).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(left_tb, text="🗑️ Удалить", command=self._remove_selected).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(left_tb, text="Очистить", command=self._clear_all).pack(side=tk.LEFT, padx=(0, 4))

        right_tb = ttk.Frame(toolbar)
        right_tb.pack(side=tk.RIGHT)

        ttk.Button(right_tb, text="▼ Вниз", command=self._move_down).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(right_tb, text="▲ Вверх", command=self._move_up).pack(side=tk.RIGHT)

        # 3. Bottom controls (Packed BOTTOM-FIRST so they NEVER get cut off on window resize)
        # 3a. Bottom Status & Merge Button
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))

        self.merge_btn = ttk.Button(
            bottom_frame, 
            text="📑 Объединить в один PDF", 
            style='Primary.TButton',
            command=self._start_merge
        )
        self.merge_btn.pack(side=tk.RIGHT, padx=(10, 0), ipady=4, ipadx=10)

        status_box = ttk.Frame(bottom_frame)
        status_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.status_label = ttk.Label(status_box, text="Файлы не выбраны", style='Status.TLabel')
        self.status_label.pack(anchor=tk.W, pady=(0, 2))

        self.progress_bar = ttk.Progressbar(status_box, mode='determinate')
        self.progress_bar.pack(fill=tk.X)

        # 3b. Save Destination
        out_frame = ttk.Frame(main_frame)
        out_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 6))

        ttk.Button(out_frame, text="Обзор...", width=10, command=self._browse_output).pack(side=tk.RIGHT)
        ttk.Label(out_frame, text="Сохранить в:").pack(side=tk.LEFT, padx=(0, 6))

        self.output_entry = ttk.Entry(out_frame)
        self.output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        # 3c. Compact Options Row
        options_frame = ttk.Frame(main_frame)
        options_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 6))

        self.var_keep_bookmarks = tk.BooleanVar(value=True)
        self.var_add_file_bookmarks = tk.BooleanVar(value=True)
        self.var_open_after = tk.BooleanVar(value=True)

        cb1 = ttk.Checkbutton(
            options_frame, 
            text="Сохранять закладки PDF", 
            variable=self.var_keep_bookmarks
        )
        cb1.pack(side=tk.LEFT, padx=(0, 16))

        cb2 = ttk.Checkbutton(
            options_frame, 
            text="Закладки по именам файлов", 
            variable=self.var_add_file_bookmarks
        )
        cb2.pack(side=tk.LEFT, padx=(0, 16))

        cb3 = ttk.Checkbutton(
            options_frame, 
            text="Открыть после объединения", 
            variable=self.var_open_after
        )
        cb3.pack(side=tk.LEFT)

        # 4. Central Table (expands and fills all remaining middle space)
        table_frame = ttk.Frame(main_frame)
        table_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 6))

        columns = ("order", "name", "type", "size", "path")
        self.tree = ttk.Treeview(table_frame, columns=columns, show='headings', selectmode='extended', height=5)
        self.tree.heading("order", text="№")
        self.tree.heading("name", text="Имя файла")
        self.tree.heading("type", text="Тип")
        self.tree.heading("size", text="Размер")
        self.tree.heading("path", text="Путь")

        self.tree.column("order", width=38, anchor=tk.CENTER, stretch=False)
        self.tree.column("name", width=260, stretch=True)
        self.tree.column("type", width=110, stretch=False)
        self.tree.column("size", width=80, anchor=tk.E, stretch=False)
        self.tree.column("path", width=220, stretch=True)

        v_scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        h_scrollbar = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        self.tree.grid(row=0, column=0, sticky='nsew')
        v_scrollbar.grid(row=0, column=1, sticky='ns')
        h_scrollbar.grid(row=1, column=0, sticky='ew')

        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # Bind Drag-and-Drop events for single and multi-selection
        self.tree.bind("<ButtonPress-1>", self._on_tree_button_press)
        self.tree.bind("<B1-Motion>", self._on_tree_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_button_release)

    def _setup_dnd(self):
        """Hook external file drag-and-drop from Windows Explorer."""
        if windnd is not None:
            try:
                windnd.hook_dropfiles(self, func=self._on_drop_files)
            except Exception:
                pass

    def _on_drop_files(self, raw_files):
        decoded = []
        for f in raw_files:
            if isinstance(f, bytes):
                try:
                    f = f.decode('utf-8')
                except Exception:
                    f = f.decode('cp1251', errors='ignore')
            decoded.append(f)
        if decoded:
            self.add_files(decoded)

    # ==================== Multi-Row Drag & Drop Logic ====================
    def _move_multiple_items(self, items: List[str], selected_indices: List[int], target_index: int) -> tuple[List[str], List[int]]:
        """Moves selected indices to target_index as a contiguous block."""
        selected_indices = sorted(selected_indices)
        if not selected_indices:
            return items, []
        if target_index in selected_indices:
            return items, selected_indices
            
        target_item = items[target_index]
        selected_items = [items[i] for i in selected_indices]
        remaining = [item for i, item in enumerate(items) if i not in selected_indices]
        
        new_target_pos = remaining.index(target_item)
        if target_index > selected_indices[-1]:
            insert_pos = new_target_pos + 1
        else:
            insert_pos = new_target_pos
            
        new_items = remaining[:insert_pos] + selected_items + remaining[insert_pos:]
        new_selected = list(range(insert_pos, insert_pos + len(selected_items)))
        return new_items, new_selected

    def _on_tree_button_press(self, event):
        clicked_id = self.tree.identify_row(event.y)
        if not clicked_id:
            self._drag_selected_indices = []
            self._drag_anchor_index = None
            self._drag_pending = False
            return
            
        try:
            clicked_idx = int(clicked_id)
        except ValueError:
            return

        current_selection = [int(i) for i in self.tree.selection()]

        # If user clicked on an item that is ALREADY part of multi-selection:
        # keep the whole multi-selection intact and prepare for dragging!
        if clicked_idx in current_selection and len(current_selection) > 1:
            self._drag_selected_indices = sorted(current_selection)
            self._drag_anchor_index = clicked_idx
            self._drag_pending = True
            self._is_dragging = False
            # Prevent default Tkinter Treeview from clearing the multi-selection
            return "break"
        else:
            # Single item or normal selection
            self._drag_selected_indices = [clicked_idx]
            self._drag_anchor_index = clicked_idx
            self._drag_pending = False
            self._is_dragging = False

    def _on_tree_motion(self, event):
        if not self._drag_selected_indices:
            return

        target_id = self.tree.identify_row(event.y)
        if not target_id:
            if event.y < 20 and min(self._drag_selected_indices) > 0:
                target_idx = 0
            elif event.y > self.tree.winfo_height() - 20 and max(self._drag_selected_indices) < len(self.file_items) - 1:
                target_idx = len(self.file_items) - 1
            else:
                return
        else:
            try:
                target_idx = int(target_id)
            except ValueError:
                return

        if target_idx not in self._drag_selected_indices and 0 <= target_idx < len(self.file_items):
            self._is_dragging = True
            self.config(cursor="fleur")

            new_items, new_selected = self._move_multiple_items(
                self.file_items, self._drag_selected_indices, target_idx
            )
            self.file_items = new_items
            self._drag_selected_indices = new_selected
            self._refresh_tree()
            
            for idx in new_selected:
                self.tree.selection_add(str(idx))
            self.tree.see(str(target_idx))

    def _on_tree_button_release(self, event):
        self.config(cursor="")
        if self._is_dragging:
            self._suggest_output_path()
        else:
            # If user simply clicked on an already-selected row without moving mouse,
            # select just that single clicked row (standard Windows click behavior)
            if self._drag_pending and self._drag_anchor_index is not None:
                # Check if Ctrl or Shift is not held
                if not (event.state & 4 or event.state & 1):
                    self.tree.selection_set(str(self._drag_anchor_index))
                    
        self._is_dragging = False
        self._drag_pending = False
        self._drag_selected_indices = []
        self._drag_anchor_index = None

    # ==================== Keyboard Shortcuts ====================
    def _bind_shortcuts(self):
        self.bind("<Delete>", lambda e: self._remove_selected())
        self.bind("<Control-a>", lambda e: self._select_all())
        self.bind("<Alt-Up>", lambda e: self._move_up())
        self.bind("<Alt-Down>", lambda e: self._move_down())

    def _select_all(self):
        for item in self.tree.get_children():
            self.tree.selection_add(item)

    def bring_to_front(self):
        self.deiconify()
        self.lift()
        self.attributes('-topmost', True)
        self.after(150, lambda: self.attributes('-topmost', False))
        self.focus_force()

    def _update_integration_button_text(self):
        installed = is_context_menu_installed()
        if installed:
            self.integration_btn.configure(text="✓ В контекстном меню")
        else:
            self.integration_btn.configure(text="+ В контекстное меню")

    def _open_github(self):
        try:
            webbrowser.open_new_tab("https://github.com/LarinPV")
        except Exception:
            pass

    def _toggle_context_menu(self):
        if is_context_menu_installed():
            if messagebox.askyesno("Контекстное меню", "Удалить пункт из контекстного меню Проводника?"):
                uninstall_context_menu()
                messagebox.showinfo("Успешно", "Пункт удален из контекстного меню.")
        else:
            install_context_menu()
            messagebox.showinfo("Успешно", "Пункт успешно добавлен в контекстное меню Проводника.")
        self._update_integration_button_text()

    def add_files(self, files: List[str]):
        added_any = False
        for f in files:
            abs_p = os.path.abspath(f)
            if os.path.isdir(abs_p):
                for entry in sorted(os.listdir(abs_p)):
                    sub_p = os.path.join(abs_p, entry)
                    if os.path.isfile(sub_p) and is_supported_file(sub_p):
                        if sub_p not in self.file_items:
                            self.file_items.append(sub_p)
                            added_any = True
            elif os.path.isfile(abs_p) and is_supported_file(abs_p):
                if abs_p not in self.file_items:
                    self.file_items.append(abs_p)
                    added_any = True
                    
        if added_any:
            self._refresh_tree()
            self._suggest_output_path()
            self.bring_to_front()

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for idx, file_path in enumerate(self.file_items):
            fname = os.path.basename(file_path)
            ftype = get_file_type_label(file_path)
            fsize = format_size(os.path.getsize(file_path)) if os.path.exists(file_path) else "0 Б"
            self.tree.insert("", tk.END, iid=str(idx), values=(idx + 1, fname, ftype, fsize, file_path))
            
        self.count_label.config(text=f"Файлы ({len(self.file_items)})")
        if self.file_items:
            self.status_label.config(text=f"Выбрано файлов: {len(self.file_items)}")
        else:
            self.status_label.config(text="Файлы не выбраны")

    def _suggest_output_path(self):
        if not self.output_entry.get().strip() and self.file_items:
            first_dir = os.path.dirname(self.file_items[0])
            now_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
            default_name = f"Объединенный_{now_str}.pdf"
            self.output_entry.insert(0, os.path.join(first_dir, default_name))

    def _move_up(self):
        selected = self.tree.selection()
        if not selected:
            return
        indices = sorted([int(i) for i in selected])
        if indices[0] == 0:
            return
        for i in indices:
            self.file_items[i - 1], self.file_items[i] = self.file_items[i], self.file_items[i - 1]
        self._refresh_tree()
        for i in indices:
            self.tree.selection_add(str(i - 1))
        self.tree.see(str(indices[0] - 1))

    def _move_down(self):
        selected = self.tree.selection()
        if not selected:
            return
        indices = sorted([int(i) for i in selected], reverse=True)
        if indices[0] == len(self.file_items) - 1:
            return
        for i in indices:
            self.file_items[i + 1], self.file_items[i] = self.file_items[i], self.file_items[i + 1]
        self._refresh_tree()
        for i in indices:
            self.tree.selection_add(str(i + 1))
        self.tree.see(str(indices[0] + 1))

    def _remove_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        indices = sorted([int(i) for i in selected], reverse=True)
        for i in indices:
            del self.file_items[i]
        self._refresh_tree()

    def _clear_all(self):
        self.file_items.clear()
        self._refresh_tree()

    def _add_files_dialog(self):
        types = [
            ("Все поддерживаемые файлы", "*.pdf;*.docx;*.doc;*.jpg;*.jpeg;*.png;*.bmp;*.tiff;*.tif;*.webp;*.txt;*.md"),
            ("PDF Документы (*.pdf)", "*.pdf"),
            ("Word Документы (*.docx;*.doc)", "*.docx;*.doc"),
            ("Изображения (*.jpg;*.png;...)", "*.jpg;*.jpeg;*.png;*.bmp;*.tiff;*.tif;*.webp;*.gif"),
            ("Текстовые файлы (*.txt;*.md)", "*.txt;*.log;*.md;*.rtf;*.csv"),
            ("Все файлы (*.*)", "*.*")
        ]
        files = filedialog.askopenfilenames(title="Выберите файлы для объединения", filetypes=types)
        if files:
            self.add_files(list(files))

    def _add_folder_dialog(self):
        folder = filedialog.askdirectory(title="Выберите папку с файлами для объединения")
        if folder:
            self.add_files([folder])

    def _browse_output(self):
        current = self.output_entry.get().strip()
        init_dir = os.path.dirname(current) if current else (os.path.dirname(self.file_items[0]) if self.file_items else "")
        target = filedialog.asksaveasfilename(
            title="Сохранить итоговый PDF как",
            initialdir=init_dir,
            defaultextension=".pdf",
            filetypes=[("PDF Документ (*.pdf)", "*.pdf")]
        )
        if target:
            self.output_entry.delete(0, tk.END)
            self.output_entry.insert(0, target)

    def _start_merge(self):
        if self.is_merging:
            return
            
        if not self.file_items:
            messagebox.showwarning("Внимание", "Список файлов пуст. Добавьте файлы для объединения.")
            return
            
        output_file = self.output_entry.get().strip()
        if not output_file:
            self._suggest_output_path()
            output_file = self.output_entry.get().strip()
            if not output_file:
                messagebox.showwarning("Внимание", "Укажите путь для сохранения итогового PDF файла.")
                return
                
        if not output_file.lower().endswith('.pdf'):
            output_file += '.pdf'
            self.output_entry.delete(0, tk.END)
            self.output_entry.insert(0, output_file)

        self.is_merging = True
        self.merge_btn.config(state=tk.DISABLED, text="⏳ Объединение...")
        self.progress_bar['maximum'] = len(self.file_items)
        self.progress_bar['value'] = 0
        
        thread = threading.Thread(
            target=self._run_merge_worker,
            args=(list(self.file_items), output_file),
            daemon=True
        )
        thread.start()

    def _run_merge_worker(self, files: List[str], output_path: str):
        def progress(idx, total, fname, msg):
            self.after(0, self._update_progress, idx, total, msg)

        try:
            result = merge_files(
                file_list=files,
                output_path=output_path,
                preserve_bookmarks=self.var_keep_bookmarks.get(),
                add_file_bookmarks=self.var_add_file_bookmarks.get(),
                progress_callback=progress
            )
            self.after(0, self._on_merge_complete, result)
        except Exception as e:
            self.after(0, self._on_merge_error, str(e))

    def _update_progress(self, idx: int, total: int, msg: str):
        self.progress_bar['maximum'] = total
        self.progress_bar['value'] = idx
        self.status_label.config(text=msg)

    def _on_merge_complete(self, result: dict):
        self.is_merging = False
        self.progress_bar['value'] = self.progress_bar['maximum']
        
        pages = result.get('total_pages', 0)
        size_str = format_size(result.get('file_size_bytes', 0))
        out_path = result.get('output_path', '')
        
        # Check if we should open the file
        if self.var_open_after.get() and os.path.exists(out_path):
            try:
                os.startfile(out_path)
            except Exception:
                pass
                
        msg = f"Файлы успешно объединены в один PDF!\n\nСтраниц: {pages}\nРазмер: {size_str}\nФайл: {out_path}"
        if result.get('errors'):
            msg += "\n\nПредупреждения:\n" + "\n".join(result['errors'])
            
        # Hide the main window so only the popup dialog remains, then close the application
        self.withdraw()
        messagebox.showinfo("Объединение завершено", msg)
        self.destroy()

    def _on_merge_error(self, err_msg: str):
        self.is_merging = False
        self.merge_btn.config(state=tk.NORMAL, text="📑 Объединить в один PDF")
        self.status_label.config(text="Ошибка объединения")
        messagebox.showerror("Ошибка объединения", f"Не удалось объединить файлы:\n\n{err_msg}")
