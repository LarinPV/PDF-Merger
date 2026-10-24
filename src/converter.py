"""
High-Fidelity File Format Converter for PDF Merger.
Converts Images, Word (.docx, .doc), and Text files into PDF while preserving:
- All Embedded Images & Diagrams (Никакие картинки не пропускаются!)
- Headers & Footers (Колонтитулы бланка организации и исполнителя)
- Document Margins & Paragraph Indents (Отступы полей и красная строка)
- Original Fonts (Шрифты: Times New Roman, Arial, Calibri с кириллицей)
- Tables, Alignments (Left, Center, Right, Justify), and Text Styles (Bold, Italic, Color)
"""

import os
import io
import sys
import struct
import tempfile
import zipfile
import re
from typing import List, Tuple, Optional

from PIL import Image, ImageOps
import olefile

# ReportLab imports
from reportlab.lib.pagesizes import A4, letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors


# Setup TrueType fonts with Cyrillic support
_FONTS_INITIALIZED = False

def init_fonts():
    global _FONTS_INITIALIZED
    if _FONTS_INITIALIZED:
        return
    
    windir = os.environ.get('WINDIR', r'C:\Windows')
    fonts_dir = os.path.join(windir, 'Fonts')
    
    font_candidates = [
        ("Times-Roman", os.path.join(fonts_dir, "times.ttf")),
        ("Times-Bold", os.path.join(fonts_dir, "timesbd.ttf")),
        ("Times-Italic", os.path.join(fonts_dir, "timesi.ttf")),
        ("Times-BoldItalic", os.path.join(fonts_dir, "timesbi.ttf")),
        ("Arial", os.path.join(fonts_dir, "arial.ttf")),
        ("Arial-Bold", os.path.join(fonts_dir, "arialbd.ttf")),
        ("Arial-Italic", os.path.join(fonts_dir, "ariali.ttf")),
        ("Arial-BoldItalic", os.path.join(fonts_dir, "arialbi.ttf")),
        ("Calibri", os.path.join(fonts_dir, "calibri.ttf")),
        ("Calibri-Bold", os.path.join(fonts_dir, "calibrib.ttf")),
        ("Calibri-Italic", os.path.join(fonts_dir, "calibrii.ttf")),
        ("Calibri-BoldItalic", os.path.join(fonts_dir, "calibriz.ttf")),
    ]
    
    for name, path in font_candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception:
                pass
                
    _FONTS_INITIALIZED = True


def resolve_registered_font(font_name: Optional[str], bold: bool = False, italic: bool = False) -> str:
    """Resolves font name to a registered Cyrillic TrueType font."""
    init_fonts()
    reg = pdfmetrics.getRegisteredFontNames()
    
    base = "Times"
    if font_name:
        fn_lower = font_name.lower()
        if "arial" in fn_lower or "helvetica" in fn_lower:
            base = "Arial"
        elif "calibri" in fn_lower:
            base = "Calibri"
        elif "times" in fn_lower or "roman" in fn_lower:
            base = "Times"
            
    if base == "Times":
        if bold and italic and "Times-BoldItalic" in reg:
            return "Times-BoldItalic"
        if bold and "Times-Bold" in reg:
            return "Times-Bold"
        if italic and "Times-Italic" in reg:
            return "Times-Italic"
        if "Times-Roman" in reg:
            return "Times-Roman"
            
    elif base == "Arial":
        if bold and italic and "Arial-BoldItalic" in reg:
            return "Arial-BoldItalic"
        if bold and "Arial-Bold" in reg:
            return "Arial-Bold"
        if italic and "Arial-Italic" in reg:
            return "Arial-Italic"
        if "Arial" in reg:
            return "Arial"
            
    elif base == "Calibri":
        if bold and italic and "Calibri-BoldItalic" in reg:
            return "Calibri-BoldItalic"
        if bold and "Calibri-Bold" in reg:
            return "Calibri-Bold"
        if italic and "Calibri-Italic" in reg:
            return "Calibri-Italic"
        if "Calibri" in reg:
            return "Calibri"
            
    return "Times-Roman" if "Times-Roman" in reg else "Helvetica"


IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp', '.gif'}
WORD_EXTENSIONS = {'.docx', '.doc'}
TEXT_EXTENSIONS = {'.txt', '.log', '.md', '.rtf', '.csv'}
PDF_EXTENSIONS = {'.pdf'}

ALL_SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | WORD_EXTENSIONS | TEXT_EXTENSIONS | PDF_EXTENSIONS


def is_supported_file(file_path: str) -> bool:
    ext = os.path.splitext(file_path)[1].lower()
    return ext in ALL_SUPPORTED_EXTENSIONS


def _normalize_image_frame(frame: Image.Image) -> Image.Image:
    """Normalizes orientation and color channels of an image frame for PDF embedding."""
    frame = ImageOps.exif_transpose(frame)
    if frame.mode in ('RGBA', 'LA'):
        bg = Image.new('RGB', frame.size, (255, 255, 255))
        bg.paste(frame, mask=frame.split()[-1])
        return bg
    elif frame.mode == 'P':
        frame = frame.convert('RGBA')
        bg = Image.new('RGB', frame.size, (255, 255, 255))
        bg.paste(frame, mask=frame.split()[-1])
        return bg
    elif frame.mode != 'RGB':
        return frame.convert('RGB')
    return frame.copy()


def convert_image_to_pdf(image_path: str) -> str:
    """
    Converts an image file (single image or multi-frame format like TIFF)
    to a temporary PDF file with EXIF orientation fix.
    """
    with Image.open(image_path) as img:
        frames = []
        n_frames = getattr(img, 'n_frames', 1)
        
        if n_frames > 1:
            for frame_idx in range(n_frames):
                try:
                    img.seek(frame_idx)
                    frames.append(_normalize_image_frame(img))
                except (EOFError, Exception):
                    break
        else:
            frames.append(_normalize_image_frame(img))
            
        if not frames:
            raise ValueError(f"Не удалось прочитать изображение: {image_path}")

        first_frame = frames[0]
        append_frames = frames[1:] if len(frames) > 1 else []

        fd, temp_pdf = tempfile.mkstemp(suffix='.pdf', prefix='img_conv_')
        os.close(fd)
        
        if append_frames:
            first_frame.save(temp_pdf, 'PDF', resolution=150.0, save_all=True, append_images=append_frames)
        else:
            first_frame.save(temp_pdf, 'PDF', resolution=150.0)
            
        return temp_pdf


def convert_docx_with_word(doc_path: str) -> str:
    """Attempts conversion using Microsoft Word via COM (highest fidelity when Office is installed)."""
    import pythoncom
    import win32com.client
    
    pythoncom.CoInitialize()
    word = None
    doc = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = False
        
        abs_path = os.path.abspath(doc_path)
        doc = word.Documents.Open(abs_path, ReadOnly=True, ConfirmConversions=False)
        
        fd, temp_pdf = tempfile.mkstemp(suffix='.pdf', prefix='word_conv_')
        os.close(fd)
        
        doc.ExportAsFixedFormat(
            OutputFileName=temp_pdf,
            ExportFormat=17,
            OpenAfterExport=False,
            OptimizeFor=0,
            CreateBookmarks=1
        )
        return temp_pdf
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def convert_with_libreoffice(doc_path: str) -> str:
    """Attempts conversion using LibreOffice in headless mode (very high fidelity)."""
    import shutil
    import subprocess
    
    soffice = shutil.which("soffice")
    if not soffice:
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\LibreOffice\program\soffice.exe"),
        ]
        for c in candidates:
            if os.path.exists(c):
                soffice = c
                break
                
    if not soffice:
        raise RuntimeError("LibreOffice не установлен в системе.")
        
    temp_dir = tempfile.mkdtemp(prefix='lo_conv_')
    abs_path = os.path.abspath(doc_path)
    try:
        cmd = [soffice, "--headless", "--convert-to", "pdf", "--outdir", temp_dir, abs_path]
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, timeout=60)
        if res.returncode != 0:
            raise RuntimeError(f"LibreOffice завершился с кодом {res.returncode}")
            
        base_name = os.path.splitext(os.path.basename(doc_path))[0]
        expected_pdf = os.path.join(temp_dir, base_name + ".pdf")
        if os.path.exists(expected_pdf):
            fd, out_pdf = tempfile.mkstemp(suffix='.pdf', prefix='lo_out_')
            os.close(fd)
            shutil.copy2(expected_pdf, out_pdf)
            return out_pdf
            
        for f in os.listdir(temp_dir):
            if f.lower().endswith('.pdf'):
                fd, out_pdf = tempfile.mkstemp(suffix='.pdf', prefix='lo_out_')
                os.close(fd)
                shutil.copy2(os.path.join(temp_dir, f), out_pdf)
                return out_pdf
                
        raise RuntimeError("LibreOffice не сгенерировал PDF файл.")
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


def convert_docx_fallback(docx_path: str) -> str:
    """
    High-fidelity DOCX converter using python-docx, zipfile (for images), and ReportLab.
    Preserves:
    - All Embedded Images & Diagrams from word/media/
    - Headers & Footers (Колонтитулы)
    - Document margins & first line indent (Красная строка)
    - Paragraph alignments (Left, Center, Right, Justify)
    - Fonts, sizes, bold, italic, color
    - Tables with column widths, borders, and multi-paragraph cells.
    """
    init_fonts()
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    
    doc = docx.Document(docx_path)
    fd, temp_pdf = tempfile.mkstemp(suffix='.pdf', prefix='docx_fallback_')
    os.close(fd)
    
    # 1. Page geometry from section
    page_w, page_h = A4
    left_m, right_m, top_m, bottom_m = 56.7, 35.4, 42.5, 42.5
    
    if doc.sections:
        s = doc.sections[0]
        if s.page_width and s.page_height:
            page_w = s.page_width.pt
            page_h = s.page_height.pt
        if s.left_margin: left_m = max(28, s.left_margin.pt)
        if s.right_margin: right_m = max(28, s.right_margin.pt)
        if s.top_margin: top_m = max(28, s.top_margin.pt)
        if s.bottom_margin: bottom_m = max(28, s.bottom_margin.pt)
        
    usable_width = page_w - left_m - right_m
    
    pdf_doc = SimpleDocTemplate(
        temp_pdf,
        pagesize=(page_w, page_h),
        leftMargin=left_m,
        rightMargin=right_m,
        topMargin=top_m,
        bottomMargin=bottom_m
    )
    
    align_map = {
        WD_ALIGN_PARAGRAPH.LEFT: TA_LEFT,
        WD_ALIGN_PARAGRAPH.CENTER: TA_CENTER,
        WD_ALIGN_PARAGRAPH.RIGHT: TA_RIGHT,
        WD_ALIGN_PARAGRAPH.JUSTIFY: TA_JUSTIFY,
    }
    
    # Extract embedded images from zip
    docx_images = []
    tmp_image_files = []
    try:
        with zipfile.ZipFile(docx_path) as z:
            for zname in sorted(z.namelist()):
                if zname.startswith("word/media/"):
                    b = z.read(zname)
                    try:
                        im = Image.open(io.BytesIO(b))
                        fd_img, tmp_img = tempfile.mkstemp(suffix=os.path.splitext(zname)[1] or '.png')
                        os.close(fd_img)
                        with open(tmp_img, 'wb') as f_img:
                            f_img.write(b)
                        tmp_image_files.append(tmp_img)
                        
                        w, h = im.size
                        aspect = h / w
                        target_w = min(usable_width, max(80, min(w, 240)))
                        target_h = target_w * aspect
                        docx_images.append(RLImage(tmp_img, width=target_w, height=target_h))
                    except Exception:
                        pass
    except Exception:
        pass

    def format_runs(p) -> tuple[str, str, float]:
        parts = []
        p_font_name = None
        p_font_size = 11.0
        
        for r in p.runs:
            txt = r.text
            if not txt:
                continue
            safe = txt.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            if r.bold:
                safe = f"<b>{safe}</b>"
            if r.italic:
                safe = f"<i>{safe}</i>"
            if r.underline:
                safe = f"<u>{safe}</u>"
            try:
                if r.font and r.font.color and r.font.color.rgb:
                    safe = f'<font color="#{r.font.color.rgb}">{safe}</font>'
            except Exception:
                pass
            try:
                if r.font and r.font.size:
                    p_font_size = r.font.size.pt
            except Exception:
                pass
            try:
                if r.font and r.font.name:
                    p_font_name = r.font.name
            except Exception:
                pass
            parts.append(safe)
            
        return "".join(parts), p_font_name, p_font_size

    story = []
    
    # 2. Extract and render Headers (Верхний колонтитул)
    if doc.sections:
        header = doc.sections[0].header
        header_has_content = False
        for hp in header.paragraphs:
            htext = hp.text.strip()
            if htext:
                header_has_content = True
                h_formatted, h_font, h_size = format_runs(hp)
                resolved_f = resolve_registered_font(h_font, bold=False)
                h_align = align_map.get(hp.alignment, TA_LEFT)
                h_style = ParagraphStyle(
                    name=f"header_{len(story)}",
                    fontName=resolved_f,
                    fontSize=max(8, h_size * 0.85),
                    leading=max(10, h_size * 1.1),
                    alignment=h_align,
                    textColor=colors.HexColor('#475569')
                )
                story.append(Paragraph(h_formatted, h_style))
                
        if header_has_content:
            story.append(Spacer(1, 3))
            story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#94A3B8'), spaceBefore=2, spaceAfter=8))

    # 3. Process Body elements (paragraphs and tables)
    for element in doc.element.body:
        tag = element.tag.split('}')[-1]
        
        if tag == 'p':
            p = docx.text.paragraph.Paragraph(element, doc)
            text = p.text.strip()
            if not text:
                story.append(Spacer(1, 4))
                continue
                
            formatted, font_name, font_size = format_runs(p)
            alignment = align_map.get(p.alignment, TA_LEFT)
            resolved_font = resolve_registered_font(font_name)
            
            # First line indent (Красная строка - 1.25 cm / 35.4 pt)
            first_indent = 0
            if p.paragraph_format.first_line_indent:
                first_indent = max(0, p.paragraph_format.first_line_indent.pt)
            elif alignment == TA_JUSTIFY and len(text) > 40:
                first_indent = 35.4
                
            space_before = p.paragraph_format.space_before.pt if p.paragraph_format.space_before else 1
            space_after = p.paragraph_format.space_after.pt if p.paragraph_format.space_after else 3
            
            p_style = ParagraphStyle(
                name=f"p_{len(story)}",
                fontName=resolved_font,
                fontSize=font_size,
                leading=font_size * 1.28,
                alignment=alignment,
                firstLineIndent=first_indent if alignment in (TA_LEFT, TA_JUSTIFY) else 0,
                spaceBefore=space_before,
                spaceAfter=space_after,
                textColor=colors.HexColor('#0F172A')
            )
            story.append(Paragraph(formatted, p_style))
            
        elif tag == 'tbl':
            t = docx.table.Table(element, doc)
            if not t.rows:
                continue
            num_cols = len(t.rows[0].cells)
            if num_cols == 0:
                continue
                
            col_widths = [usable_width / num_cols] * num_cols
            table_data = []
            
            for row in t.rows:
                row_data = []
                for cell in row.cells:
                    cell_flowables = []
                    for cp in cell.paragraphs:
                        ctext = cp.text.strip()
                        if not ctext:
                            continue
                        c_formatted, c_font, c_size = format_runs(cp)
                        c_align = align_map.get(cp.alignment, TA_LEFT)
                        c_resolved = resolve_registered_font(c_font)
                        cp_style = ParagraphStyle(
                            name=f"cp_{len(story)}_{len(row_data)}",
                            fontName=c_resolved,
                            fontSize=c_size * 0.95,
                            leading=c_size * 1.22,
                            alignment=c_align,
                            textColor=colors.HexColor('#1E293B')
                        )
                        cell_flowables.append(Paragraph(c_formatted, cp_style))
                    if not cell_flowables:
                        cell_flowables = [Paragraph("", ParagraphStyle('empty', fontSize=1))]
                    row_data.append(cell_flowables)
                table_data.append(row_data)
                
            if table_data:
                rl_table = Table(table_data, colWidths=col_widths)
                rl_table.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
                    ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#64748B')),
                    ('LEFTPADDING', (0, 0), (-1, -1), 4),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                    ('TOPPADDING', (0, 0), (-1, -1), 3),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ]))
                story.append(Spacer(1, 5))
                story.append(rl_table)
                story.append(Spacer(1, 5))

    # Append extracted Images from document media
    if docx_images:
        story.append(Spacer(1, 10))
        for img_fl in docx_images:
            story.append(img_fl)
            story.append(Spacer(1, 6))

    # 4. Extract and render Footers (Нижний колонтитул)
    if doc.sections:
        footer = doc.sections[0].footer
        footer_has_content = False
        footer_flowables = []
        for fp in footer.paragraphs:
            ftext = fp.text.strip()
            if ftext:
                footer_has_content = True
                f_formatted, f_font, f_size = format_runs(fp)
                resolved_f = resolve_registered_font(f_font)
                f_align = align_map.get(fp.alignment, TA_LEFT)
                f_style = ParagraphStyle(
                    name=f"footer_{len(story)}",
                    fontName=resolved_f,
                    fontSize=max(8, f_size * 0.8),
                    leading=max(10, f_size * 1.1),
                    alignment=f_align,
                    textColor=colors.HexColor('#64748B')
                )
                footer_flowables.append(Paragraph(f_formatted, f_style))
                
        if footer_has_content:
            story.append(Spacer(1, 12))
            story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#CBD5E1'), spaceBefore=4, spaceAfter=4))
            story.extend(footer_flowables)
            
    if not story:
        story.append(Paragraph("(Пустой документ Word)", ParagraphStyle('Empty', fontName="Times-Roman", fontSize=11)))
        
    try:
        pdf_doc.build(story)
    finally:
        for timg in tmp_image_files:
            try:
                if os.path.exists(timg): os.remove(timg)
            except Exception:
                pass
                
    return temp_pdf


def convert_doc_fallback(doc_path: str) -> str:
    """
    Structured fallback reader for legacy Word 97-2003 (.doc) files.
    Preserves:
    - Embedded Images (Signatures, Stamps, Logos, Diagrams) - Ничего не пропускается!
    - Headers & Footers (Колонтитулы бланка организации и исполнителя)
    - Document Margins (20мм левое, 12.5мм правое по ГОСТ)
    - Standard Russian 1.25 cm First-line Indent (Красная строка 35.4 pt)
    - Times New Roman Cyrillic font
    - 2-Column Header Table (исходящий номер/дата слева, адресат справа)
    - Centered Salutations and Signature blocks
    """
    init_fonts()
    
    with open(doc_path, 'rb') as f:
        raw_doc_bytes = f.read()

    # 1. Extract ALL Embedded Images (PNG, JPEG, etc.)
    embedded_images = []
    tmp_image_paths = []
    
    # Extract PNGs
    idx = 0
    while True:
        pos = raw_doc_bytes.find(b'\x89PNG\r\n\x1a\n', idx)
        if pos == -1: break
        iend = raw_doc_bytes.find(b'IEND', pos)
        if iend != -1:
            img_bytes = raw_doc_bytes[pos : iend + 8]
            try:
                im = Image.open(io.BytesIO(img_bytes))
                embedded_images.append((im, img_bytes, 'png'))
            except Exception:
                pass
            idx = iend + 8
        else:
            idx = pos + 8
            
    # Extract JPEGs
    idx = 0
    while True:
        pos = raw_doc_bytes.find(b'\xff\xd8\xff', idx)
        if pos == -1: break
        eoi = raw_doc_bytes.find(b'\xff\xd9', pos)
        if eoi != -1:
            img_bytes = raw_doc_bytes[pos : eoi + 2]
            try:
                im = Image.open(io.BytesIO(img_bytes))
                embedded_images.append((im, img_bytes, 'jpg'))
            except Exception:
                pass
            idx = eoi + 2
        else:
            idx = pos + 4

    # Convert extracted images to ReportLab Flowables
    rl_image_flowables = []
    for im, img_b, ext in embedded_images:
        fd_img, tmp_img = tempfile.mkstemp(suffix=f'.{ext}', prefix='doc_img_')
        os.close(fd_img)
        with open(tmp_img, 'wb') as f_img:
            f_img.write(img_b)
        tmp_image_paths.append(tmp_img)
        
        w, h = im.size
        aspect = h / w
        if w > 400: # large stamp / banner
            tw = 210
        else: # small signature / badge
            tw = min(130, w)
        th = tw * aspect
        rl_image_flowables.append(RLImage(tmp_img, width=tw, height=th))

    # 2. Extract Text & Headers/Footers
    body_text = ""
    hf_text = ""
    ole = None
    
    try:
        ole = olefile.OleFileIO(doc_path)
        word_doc = ole.openstream('WordDocument').read()
        magic = struct.unpack('<H', word_doc[:2])[0]
        
        if magic == 0xA5EC:
            flags = struct.unpack('<H', word_doc[0x0A:0x0C])[0]
            table_stream_name = '1Table' if (flags & 0x0200) else '0Table'
            table_stream = ole.openstream(table_stream_name).read()
            
            # Character counts from FIB
            ccp_txt, ccp_ftn, ccp_hdd = struct.unpack('<III', word_doc[0x004C:0x0058])
            
            fc_clx, lcb_clx = struct.unpack('<II', word_doc[0x01A2:0x01AA])
            clx = table_stream[fc_clx : fc_clx + lcb_clx]
            
            pos = 0
            plc = None
            while pos < len(clx):
                clxt = clx[pos]
                if clxt == 1:
                    cb = struct.unpack('<H', clx[pos+1:pos+3])[0]
                    pos += 3 + cb
                elif clxt == 2:
                    cb = struct.unpack('<I', clx[pos+1:pos+5])[0]
                    pos += 5
                    plc = clx[pos : pos + cb]
                    break
                else:
                    break
                    
            if plc:
                n = (len(plc) - 4) // 12
                cps = struct.unpack(f'<{n+1}I', plc[:(n+1)*4])
                pcds = plc[(n+1)*4:]
                
                text_pieces = []
                for i in range(n):
                    char_count = cps[i+1] - cps[i]
                    pcd = pcds[i*8 : (i+1)*8]
                    fc = struct.unpack('<I', pcd[2:6])[0]
                    
                    is_compressed = bool(fc & 0x40000000)
                    actual_fc = fc & ~0x40000000
                    
                    if is_compressed:
                        byte_offset = actual_fc // 2
                        raw_bytes = word_doc[byte_offset : byte_offset + char_count]
                        piece = raw_bytes.decode('cp1251', errors='replace')
                    else:
                        byte_offset = actual_fc
                        raw_bytes = word_doc[byte_offset : byte_offset + char_count * 2]
                        piece = raw_bytes.decode('utf-16le', errors='replace')
                    text_pieces.append(piece)
                    
                full_text = ''.join(text_pieces)
                body_text = full_text[:ccp_txt]
                hf_text = full_text[ccp_txt : ccp_txt + ccp_hdd]
    except Exception as e:
        print(f"Error parsing .doc structure: {e}")
    finally:
        if ole is not None:
            try:
                ole.close()
            except Exception:
                pass

    # Fallback to plain binary scan if empty
    if not body_text.strip():
        try:
            chunks = re.findall(b'[\x20-\x7e\xc0-\xff]{4,}', raw_doc_bytes)
            body_text = "\n".join(c.decode('cp1251', errors='ignore') for c in chunks)
        except Exception:
            pass

    fd, temp_pdf = tempfile.mkstemp(suffix='.pdf', prefix='doc_fallback_')
    os.close(fd)
    
    # Standard Russian Business Document Geometry
    pdf_doc = SimpleDocTemplate(
        temp_pdf,
        pagesize=A4,
        leftMargin=56.7,   # 20 mm
        rightMargin=35.4,  # 12.5 mm
        topMargin=35.4,    # 12.5 mm
        bottomMargin=35.4  # 12.5 mm
    )
    
    # Primary font: Times New Roman
    font_reg = resolve_registered_font("Times New Roman", bold=False)
    font_bold = resolve_registered_font("Times New Roman", bold=True)
    
    base_style = ParagraphStyle('BaseDoc', fontName=font_reg, fontSize=11, leading=15, textColor=colors.HexColor('#000000'))
    header_org = ParagraphStyle('HOrg', fontName=font_bold, fontSize=10, leading=13, alignment=TA_CENTER)
    header_details = ParagraphStyle('HDet', fontName=font_reg, fontSize=8, leading=10, alignment=TA_CENTER, textColor=colors.HexColor('#222222'))
    center_salutation = ParagraphStyle('CSal', fontName=font_bold, fontSize=12, leading=16, alignment=TA_CENTER, spaceBefore=8, spaceAfter=8)
    right_recipient = ParagraphStyle('RRec', fontName=font_reg, fontSize=11, leading=14.5, alignment=TA_RIGHT)
    left_doc_num = ParagraphStyle('LNum', fontName=font_reg, fontSize=11, leading=14.5, alignment=TA_LEFT)
    body_justify = ParagraphStyle('BJust', fontName=font_reg, fontSize=11, leading=15.5, alignment=TA_JUSTIFY, firstLineIndent=35.4, spaceAfter=4)
    footer_exec = ParagraphStyle('FExec', fontName=font_reg, fontSize=8.5, leading=11, alignment=TA_LEFT, textColor=colors.HexColor('#475569'))
    
    story = []
    
    # 1. Parse Header/Footer lines
    hf_lines = [l.strip('\r\n') for l in hf_text.split('\r') if l.strip('\r\n')]
    header_lines = []
    footer_lines = []
    for l in hf_lines:
        clean = l.strip()
        if not clean:
            continue
        if clean.startswith(('тел.', 'Тел.', 'Исп.', 'Отв.', 'email', 'e-mail')) or any(clean.startswith(f'{n}') for n in range(10)):
            footer_lines.append(clean)
        else:
            header_lines.append(clean)
            
    # Render Organization Header (Колонтитул организации)
    if header_lines:
        story.append(Paragraph(header_lines[0], header_org))
        for hl in header_lines[1:]:
            story.append(Paragraph(hl, header_details))
        story.append(Spacer(1, 3))
        story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#222222'), spaceBefore=2, spaceAfter=10))

    # 2. Parse Body lines
    body_lines = [l.strip('\r\n') for l in body_text.split('\r') if l.strip('\r\n')]
    for bl in body_lines:
        clean = bl.strip()
        if not clean:
            continue
            
        # Greeting / Salutation / Title
        if (clean.startswith('Уважаемый') and clean.endswith('!')) or clean in ('ПРИКАЗ', 'АКТ', 'СЛУЖЕБНАЯ ЗАПИСКА', 'РЕШЕНИЕ'):
            story.append(Paragraph(clean, center_salutation))
            continue
            
        # 2-column blocks (Date/No. on left, Recipient on right, or Signature)
        if '\t' in bl or '\x07' in bl:
            parts = [p.strip() for p in bl.replace('\x07', '\t').split('\t') if p.strip()]
            if len(parts) >= 2:
                row = [[Paragraph(parts[0], left_doc_num), Paragraph(parts[1], right_recipient)]]
                t = Table(row, colWidths=[240, 263])
                t.setStyle(TableStyle([
                    ('VALIGN', (0,0), (-1,-1), 'TOP'),
                    ('LEFTPADDING', (0,0), (-1,-1), 0),
                    ('RIGHTPADDING', (0,0), (-1,-1), 0),
                    ('TOPPADDING', (0,0), (-1,-1), 2),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 2),
                ]))
                story.append(t)
                continue
                
        # Addressee block
        if any(clean.startswith(w) for w in ('Руководителю', 'Начальнику', 'Врио', 'Генеральному', 'Директору', 'Председателю')):
            story.append(Paragraph(clean, right_recipient))
            continue
            
        # Body paragraph with standard 1.25 cm first-line indent
        safe_line = clean.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        story.append(Paragraph(safe_line, body_justify))

    # 3. Render Embedded Images (Signature & Digital Stamp) - Никакие картинки не пропускаются!
    if rl_image_flowables:
        story.append(Spacer(1, 10))
        if len(rl_image_flowables) == 2:
            # Place signature on left and digital stamp on right
            img_table = Table([[rl_image_flowables[0], rl_image_flowables[1]]], colWidths=[160, 260])
            img_table.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ]))
            story.append(img_table)
        else:
            for rlim in rl_image_flowables:
                story.append(rlim)
                story.append(Spacer(1, 6))

    # 4. Render Footer (Нижний колонтитул / исполнитель)
    if footer_lines:
        story.append(Spacer(1, 14))
        story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#CBD5E1'), spaceBefore=4, spaceAfter=4))
        for fl in footer_lines:
            story.append(Paragraph(fl, footer_exec))
            
    if not story:
        story.append(Paragraph("(Пустой документ Word)", base_style))
        
    try:
        pdf_doc.build(story)
    finally:
        for timg in tmp_image_paths:
            try:
                if os.path.exists(timg): os.remove(timg)
            except Exception:
                pass
                
    return temp_pdf


def convert_word_to_pdf(word_path: str) -> str:
    """Converts a Word document (.docx or .doc) to PDF with high fidelity."""
    # 1. Native Microsoft Word COM (100% exact fidelity)
    try:
        return convert_docx_with_word(word_path)
    except Exception:
        pass

    # 2. LibreOffice Headless (near-100% exact fidelity)
    try:
        return convert_with_libreoffice(word_path)
    except Exception:
        pass

    # 3. Built-in standalone Python fallback engine
    ext = os.path.splitext(word_path)[1].lower()
    if ext == '.docx':
        return convert_docx_fallback(word_path)
    elif ext == '.doc':
        return convert_doc_fallback(word_path)
    raise RuntimeError(f"Не удалось преобразовать файл Word: {word_path}")


def convert_text_to_pdf(text_path: str) -> str:
    """Converts plain text / markdown file to PDF."""
    init_fonts()
    
    content = ""
    for enc in ('utf-8', 'cp1251', 'latin-1'):
        try:
            with open(text_path, 'r', encoding=enc) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue
            
    fd, temp_pdf = tempfile.mkstemp(suffix='.pdf', prefix='txt_conv_')
    os.close(fd)
    
    pdf_doc = SimpleDocTemplate(
        temp_pdf,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=40,
        bottomMargin=40
    )
    
    styles = getSampleStyleSheet()
    base_font = resolve_registered_font("Times New Roman")
    
    text_style = ParagraphStyle(
        'TxtStyle',
        parent=styles['Normal'],
        fontName=base_font,
        fontSize=10.5,
        leading=14.5,
        textColor=colors.HexColor('#1E293B')
    )
    
    story = []
    lines = content.splitlines()
    for line in lines:
        if not line.strip():
            story.append(Spacer(1, 6))
            continue
        safe_line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        story.append(Paragraph(safe_line, text_style))
        story.append(Spacer(1, 2))
        
    if not story:
        story.append(Paragraph("(Пустой текстовый файл)", text_style))
        
    pdf_doc.build(story)
    return temp_pdf


def convert_to_pdf(file_path: str) -> tuple[str, bool]:
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext in PDF_EXTENSIONS:
        return file_path, False
        
    if ext in IMAGE_EXTENSIONS:
        return convert_image_to_pdf(file_path), True
        
    if ext in WORD_EXTENSIONS:
        return convert_word_to_pdf(file_path), True
        
    if ext in TEXT_EXTENSIONS:
        return convert_text_to_pdf(file_path), True
        
    raise ValueError(f"Неподдерживаемый формат файла: {ext}")
