"""
PDF Merging Engine with Outline / Bookmark preservation.
"""

import os
import shutil
import tempfile
import pypdf
from typing import List, Callable, Optional, Dict, Any
from src.converter import convert_to_pdf, is_supported_file


class MergeError(Exception):
    pass


def merge_files(
    file_list: List[str],
    output_path: str,
    preserve_bookmarks: bool = True,
    add_file_bookmarks: bool = True,
    progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None
) -> Dict[str, Any]:
    """
    Merges multiple files (PDF, Images, DOCX, Text) into a single PDF.
    
    Args:
        file_list: List of paths to input files.
        output_path: Target merged PDF file path.
        preserve_bookmarks: Whether to keep outlines/bookmarks from source PDFs.
        add_file_bookmarks: Whether to add a top-level bookmark for each input file.
        progress_callback: Callback(index, total, filename, message).
        cancel_check: Callable returning True if the operation was cancelled.
        
    Returns:
        Dict with merge results: total_pages, output_path, errors, file_count.
    """
    if not file_list:
        raise MergeError("Список файлов для объединения пуст.")
        
    total_files = len(file_list)
    temp_files_to_cleanup = []
    
    writer = pypdf.PdfWriter()
    processed_count = 0
    errors = []
    
    try:
        for idx, file_path in enumerate(file_list):
            if cancel_check and cancel_check():
                raise MergeError("Операция была отменена пользователем.")
                
            filename = os.path.basename(file_path)
            doc_title = os.path.splitext(filename)[0]
            
            if progress_callback:
                progress_callback(idx, total_files, filename, f"Конвертация и добавление: {filename}")
                
            if not os.path.exists(file_path):
                errors.append(f"Файл не найден: {file_path}")
                continue
                
            pdf_path = None
            is_temp = False
            
            try:
                pdf_path, is_temp = convert_to_pdf(file_path)
                if is_temp:
                    temp_files_to_cleanup.append(pdf_path)
            except Exception as conv_err:
                errors.append(f"Ошибка при обработке '{filename}': {conv_err}")
                continue
                
            try:
                reader = pypdf.PdfReader(pdf_path)
                
                # Check for password encryption
                if reader.is_encrypted:
                    try:
                        reader.decrypt('')
                    except Exception:
                        errors.append(f"Файл '{filename}' защищен паролем и не может быть объединен.")
                        continue
                        
                page_count = len(reader.pages)
                if page_count == 0:
                    continue
                    
                outline_title = doc_title if add_file_bookmarks else None
                
                # Append reader with bookmarks handling
                writer.append(
                    reader,
                    outline_item=outline_title,
                    import_outline=preserve_bookmarks
                )
                
                processed_count += 1
                
            except Exception as pdf_err:
                errors.append(f"Ошибка при чтении PDF '{filename}': {pdf_err}")
                continue
                
        if processed_count == 0:
            err_details = "; ".join(errors) if errors else "Не удалось обработать ни один файл."
            raise MergeError(f"Не удалось объединить файлы: {err_details}")
            
        if cancel_check and cancel_check():
            raise MergeError("Операция была отменена пользователем.")
            
        if progress_callback:
            progress_callback(total_files, total_files, "", "Сохранение и оптимизация PDF...")
            
        # Ensure output directory exists
        out_dir = os.path.dirname(os.path.abspath(output_path))
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
            
        # Write to temporary file first, then atomic rename
        temp_out = output_path + ".tmp"
        try:
            with open(temp_out, "wb") as f_out:
                writer.write(f_out)
                
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except PermissionError:
                    raise MergeError(
                        f"Не удалось сохранить '{os.path.basename(output_path)}': "
                        f"файл уже открыт в другой программе (например, Adobe Acrobat или браузере). "
                        f"Пожалуйста, закройте открытый файл и повторите попытку."
                    )
            try:
                os.rename(temp_out, output_path)
            except PermissionError:
                raise MergeError(
                    f"Не удалось перезаписать '{os.path.basename(output_path)}': "
                    f"доступ заблокирован другой программой. Пожалуйста, закройте открытый файл и повторите попытку."
                )
        except Exception:
            if os.path.exists(temp_out):
                try:
                    os.remove(temp_out)
                except Exception:
                    pass
            raise
        
        total_pages = len(writer.pages)
        file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        
        return {
            "success": True,
            "output_path": output_path,
            "processed_files": processed_count,
            "total_files": total_files,
            "total_pages": total_pages,
            "file_size_bytes": file_size,
            "errors": errors
        }
        
    finally:
        # Cleanup temporary converted files
        for tf in temp_files_to_cleanup:
            try:
                if os.path.exists(tf):
                    os.remove(tf)
            except Exception:
                pass
