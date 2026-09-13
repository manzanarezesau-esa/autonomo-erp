# pdf_utils.py
import io
import base64
import re
import ssl
import urllib.request
import qrcode
from qrcode.image.pil import PilImage
import streamlit as st
from database import init_supabase
from verifactu_utils import generar_url_qr_verifactu, formatear_fecha_verifactu

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
)
from reportlab.lib.utils import ImageReader
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER


# -----------------------------------------------------------
# UTILIDADES DE IMAGEN Y TEXTO
# -----------------------------------------------------------
def _logo_sanitized(url):
    if not url:
        return ""
    return str(url).strip()


def _get_reportlab_logo(logo_input, max_w=180, max_h=80):
    if not logo_input:
        return None
    logo_input = str(logo_input).strip()
    if not logo_input:
        return None

    try:
        from PIL import Image as PILImage
        img_bytes = None

        if logo_input.startswith("data:image"):
            base64_data = logo_input.split(",", 1)[1]
            img_bytes = base64.b64decode(base64_data)
        elif logo_input.startswith("http://") or logo_input.startswith("https://"):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(logo_input, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=6, context=ctx) as resp:
                img_bytes = resp.read()
        elif len(logo_input) > 100 and not logo_input.startswith("/") and not logo_input.startswith("C:"):
            img_bytes = base64.b64decode(logo_input)
        else:
            with open(logo_input, "rb") as f:
                img_bytes = f.read()

        if img_bytes:
            pil_img = PILImage.open(io.BytesIO(img_bytes))
            w, h = pil_img.size
            if w > 0 and h > 0:
                ratio = min(max_w / w, max_h / h, 1.0)
                return RLImage(io.BytesIO(img_bytes), width=w * ratio, height=h * ratio)
    except Exception:
        return None
    return None


def get_qr_base64(invoice, client, company_config):
    """Genera QR Veri*Factu con formato oficial AEAT (sin hash)."""
    invoice_number = invoice.get('invoice_number', '')
    if not invoice_number:
        return ""

    numserie = invoice_number.replace("/", "-").strip()

    nif_emisor = company_config.get('company_tax_id', '')
    if not nif_emisor:
        return ""

    fecha_raw = invoice.get('date', '')
    if not fecha_raw:
        return ""

    try:
        fecha_verifactu = formatear_fecha_verifactu(str(fecha_raw))
    except Exception:
        fecha_verifactu = str(fecha_raw)

    importe_total = invoice.get('total', 0)

    try:
        qr_data = generar_url_qr_verifactu(
            nif_emisor=nif_emisor,
            num_serie_factura=numserie,
            fecha_expedicion=fecha_verifactu,
            importe_total=float(importe_total),
            produccion=True,
        )
    except Exception as e:
        st.error(f"Error generando URL QR Verifactu: {e}")
        return ""

    qr = qrcode.QRCode(box_size=4, border=1)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(image_factory=PilImage)
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()


def _get_qr_image(invoice, client, company_config, max_size=80):
    qr_base64 = get_qr_base64(invoice, client, company_config)
    if not qr_base64:
        return None
    try:
        qr_bytes = base64.b64decode(qr_base64)
        return RLImage(io.BytesIO(qr_bytes), width=max_size, height=max_size)
    except Exception:
        return None


def split_description_into_paragraphs(desc_text):
    if not desc_text:
        return [""]

    desc_text = str(desc_text).strip()
    desc_text = re.sub(r'[\u2580-\u25FF\uFFFD]', '', desc_text)

    raw_lines = desc_text.split('\n')
    paragraphs = []

    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        cleaned = re.sub(r'^[•\-\*\s\u200b\uFEFF]+', '', line).strip()
        if not cleaned:
            continue
        if len(cleaned) > 300:
            words = cleaned.split(' ')
            chunk = []
            chunk_len = 0
            for w in words:
                chunk.append(w)
                chunk_len += len(w) + 1
                if chunk_len >= 300:
                    paragraphs.append(" ".join(chunk))
                    chunk = []
                    chunk_len = 0
            if chunk:
                paragraphs.append(" ".join(chunk))
        else:
            paragraphs.append(cleaned)

    return paragraphs if paragraphs else [str(desc_text)]


def _fmt_money(valor):
    try:
        return f"{float(valor):,.2f} €"
    except (ValueError, TypeError):
        return "0.00 €"


# -----------------------------------------------------------
# FACTURA
# -----------------------------------------------------------
def make_invoice_pdf_from_template(invoice, client, company_config, lineas):
    styles = getSampleStyleSheet()

    company_style = ParagraphStyle(
        'CompanyStyle', parent=styles['Heading2'], fontSize=14, leading=16,
        textColor=colors.HexColor('#1E3A8A'), spaceAfter=2,
    )
    company_info_style = ParagraphStyle(
        'CompanyInfoStyle', parent=styles['Normal'], fontSize=9, leading=11,
        textColor=colors.HexColor('#4A5568'), spaceAfter=1,
    )
    title_style = ParagraphStyle(
        'TitleStyle', parent=styles['Title'], fontSize=18, leading=21,
        textColor=colors.HexColor('#1E3A8A'), spaceAfter=4, alignment=TA_CENTER,
    )
    meta_label_style = ParagraphStyle(
        'MetaLabelStyle', parent=styles['Normal'], fontSize=9, leading=11,
        textColor=colors.HexColor('#2D3748'), spaceAfter=1,
    )
    desc_style = ParagraphStyle(
        'DescStyle', parent=styles['Normal'], fontSize=9, leading=11,
        textColor=colors.HexColor('#2D3748'), spaceBefore=0, spaceAfter=0, alignment=TA_LEFT,
    )
    desc_header_style = ParagraphStyle(
        'DescHeaderStyle', parent=styles['Normal'], fontSize=9, leading=11,
        textColor=colors.white, fontName='Helvetica-Bold', spaceBefore=0, spaceAfter=0, alignment=TA_LEFT,
    )
    num_style = ParagraphStyle(
        'NumStyle', parent=styles['Normal'], fontSize=9, leading=11,
        textColor=colors.HexColor('#2D3748'), spaceBefore=0, spaceAfter=0, alignment=TA_RIGHT,
    )
    num_header_style = ParagraphStyle(
        'NumHeaderStyle', parent=styles['Normal'], fontSize=9, leading=11,
        textColor=colors.white, fontName='Helvetica-Bold', spaceBefore=0, spaceAfter=0, alignment=TA_RIGHT,
    )
    center_style = ParagraphStyle(
        'CenterStyle', parent=styles['Normal'], fontSize=9, leading=11,
        textColor=colors.HexColor('#2D3748'), spaceBefore=0, spaceAfter=0, alignment=TA_CENTER,
    )
    center_header_style = ParagraphStyle(
        'CenterHeaderStyle', parent=styles['Normal'], fontSize=9, leading=11,
        textColor=colors.white, fontName='Helvetica-Bold', spaceBefore=0, spaceAfter=0, alignment=TA_CENTER,
    )
    total_label_style = ParagraphStyle(
        'TotalLabelStyle', parent=styles['Normal'], fontSize=10, leading=12,
        textColor=colors.HexColor('#2D3748'), spaceBefore=0, spaceAfter=0, alignment=TA_LEFT,
    )
    total_value_style = ParagraphStyle(
        'TotalValueStyle', parent=styles['Normal'], fontSize=10, leading=12,
        textColor=colors.HexColor('#1E3A8A'), spaceBefore=0, spaceAfter=0,
        alignment=TA_RIGHT, fontName='Helvetica-Bold',
    )
    total_final_style = ParagraphStyle(
        'TotalFinalStyle', parent=styles['Normal'], fontSize=12, leading=14,
        textColor=colors.HexColor('#1E3A8A'), spaceBefore=0, spaceAfter=0,
        alignment=TA_RIGHT, fontName='Helvetica-Bold',
    )
    footer_style = ParagraphStyle(
        'FooterStyle', parent=styles['Normal'], fontSize=8, leading=10,
        textColor=colors.HexColor('#718096'), alignment=TA_CENTER,
    )

    PAGE_WIDTH, PAGE_HEIGHT = A4
    MARGIN_LEFT = 1.2 * cm
    MARGIN_RIGHT = 1.2 * cm
    MARGIN_TOP = 1.0 * cm
    MARGIN_BOTTOM = 1.0 * cm
    PRINTABLE_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

    company_name = company_config.get('company_name', '')
    company_tax_id = company_config.get('company_tax_id', '')
    company_address = company_config.get('company_address', '')
    company_iban = company_config.get('company_iban', '')
    company_phone = company_config.get('company_phone', '')
    company_email = company_config.get('company_email', '')

    client_name = client.get('name', '')
    client_tax_id = client.get('tax_id', '')
    client_address = client.get('address', '')

    invoice_number = invoice.get('invoice_number', '')
    invoice_date = invoice.get('date', '')
    invoice_month = invoice.get('month', '')
    invoice_status = invoice.get('status', 'Pendiente')
    es_rectificativa = company_config.get('es_rectificativa', False)
    factura_original = company_config.get('factura_original_num', '')

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=MARGIN_LEFT, rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
    )

    story = []

    logo_input = company_config.get('company_logo', '')
    logo_element = _get_reportlab_logo(logo_input, max_w=150, max_h=70)

    if logo_element:
        header_data = [
            [logo_element, Paragraph(f"<b>{company_name}</b>", company_style)],
            [Paragraph("", company_info_style), Paragraph(company_address, company_info_style)],
            [Paragraph("", company_info_style), Paragraph(f"NIF: {company_tax_id}", company_info_style)],
            [Paragraph("", company_info_style), Paragraph(f"Tel: {company_phone} | Email: {company_email}", company_info_style)],
        ]
        header_col_widths = [PRINTABLE_WIDTH * 0.35, PRINTABLE_WIDTH * 0.65]
    else:
        header_data = [
            [Paragraph(f"<b>{company_name}</b>", company_style), Paragraph("", company_info_style)],
            [Paragraph(company_address, company_info_style), Paragraph("", company_info_style)],
            [Paragraph(f"NIF: {company_tax_id}", company_info_style), Paragraph("", company_info_style)],
            [Paragraph(f"Tel: {company_phone} | Email: {company_email}", company_info_style), Paragraph("", company_info_style)],
        ]
        header_col_widths = [PRINTABLE_WIDTH, PRINTABLE_WIDTH]

    header_table = Table(header_data, colWidths=header_col_widths)
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LINEBELOW', (0, -1), (-1, -1), 1.5, colors.HexColor('#1E3A8A')),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10))

    if es_rectificativa:
        story.append(Paragraph("FACTURA RECTIFICATIVA", title_style))
        if factura_original:
            story.append(Paragraph(f"Rectifica a la factura: {factura_original}", meta_label_style))
    else:
        story.append(Paragraph("FACTURA", title_style))

    story.append(Paragraph(f"Nº {invoice_number}", meta_label_style))
    story.append(Spacer(1, 6))

    meta_data = [
        [Paragraph(f"<b>DATOS DEL CLIENTE</b>", meta_label_style), Paragraph(f"<b>Fecha:</b> {invoice_date}", meta_label_style)],
        [Paragraph(client_name, meta_label_style), Paragraph(f"<b>Periodo:</b> {invoice_month}", meta_label_style)],
        [Paragraph(f"NIF: {client_tax_id}", meta_label_style), Paragraph(f"<b>Estado:</b> {invoice_status}", meta_label_style)],
        [Paragraph(client_address, meta_label_style), Paragraph("", meta_label_style)],
    ]

    meta_table = Table(meta_data, colWidths=[PRINTABLE_WIDTH * 0.65, PRINTABLE_WIDTH * 0.35])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 8))

    col_desc_width = PRINTABLE_WIDTH * 0.40
    col_qty_width = PRINTABLE_WIDTH * 0.08
    col_price_width = PRINTABLE_WIDTH * 0.13
    col_base_width = PRINTABLE_WIDTH * 0.13
    col_vat_width = PRINTABLE_WIDTH * 0.10
    col_irpf_width = PRINTABLE_WIDTH * 0.08
    col_total_width = PRINTABLE_WIDTH * 0.08

    col_widths = [col_desc_width, col_qty_width, col_price_width, col_base_width, col_vat_width, col_irpf_width, col_total_width]

    vat_pct_display = invoice.get('vat_percentage', 21)
    irpf_pct_display = invoice.get('irpf_percentage', 0)

    headers = [
        Paragraph('<b>Concepto</b>', desc_header_style),
        Paragraph('<b>Cant.</b>', center_header_style),
        Paragraph('<b>Precio</b>', num_header_style),
        Paragraph('<b>Base</b>', num_header_style),
        Paragraph(f'<b>IVA ({vat_pct_display:.0f}%)</b>', num_header_style),
        Paragraph(f'<b>IRPF ({irpf_pct_display:.0f}%)</b>', num_header_style),
        Paragraph('<b>Total</b>', num_header_style),
    ]

    rows = [headers]

    for linea in lineas:
        desc = linea.get('description', '')
        qty = linea.get('quantity', 1)
        price = linea.get('unit_price', 0)
        base = linea.get('base_amount', 0)
        vat_amt = linea.get('vat_amount', 0)
        irpf_amt = linea.get('irpf_amount', 0)
        total_line = linea.get('total', base)

        rows.append([
            Paragraph(desc, desc_style),
            Paragraph(f"{float(qty):.0f}", center_style),
            Paragraph(_fmt_money(price), num_style),
            Paragraph(_fmt_money(base), num_style),
            Paragraph(_fmt_money(vat_amt), num_style),
            Paragraph(f"-{_fmt_money(irpf_amt)}", num_style),
            Paragraph(f"<b>{_fmt_money(total_line)}</b>", num_style),
        ])

    lines_table = Table(rows, colWidths=col_widths, repeatRows=1)
    lines_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#1E3A8A')),
        ('LINEBELOW', (0, 1), (-1, -1), 0.3, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
    ]))
    story.append(lines_table)
    story.append(Spacer(1, 8))

    totals_width = PRINTABLE_WIDTH * 0.35
    totals_left_offset = PRINTABLE_WIDTH - totals_width

    totals_data = [
        [Paragraph('Base imponible:', total_label_style), Paragraph(_fmt_money(invoice.get('base_amount', 0)), total_value_style)],
        [Paragraph(f'IVA ({vat_pct_display:.0f}%):', total_label_style), Paragraph(_fmt_money(invoice.get('vat_amount', 0)), total_value_style)],
        [Paragraph(f'IRPF ({irpf_pct_display:.0f}%):', total_label_style), Paragraph(f"-{_fmt_money(invoice.get('irpf_amount', 0))}", total_value_style)],
        [Paragraph('<b>TOTAL A PAGAR:</b>', total_final_style), Paragraph(f'<b>{_fmt_money(invoice.get("total", 0))}</b>', total_final_style)],
    ]

    totals_table = Table(totals_data, colWidths=[totals_width * 0.50, totals_width * 0.50])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.HexColor('#1E3A8A')),
    ]))

    totals_wrapper = Table([['', totals_table]], colWidths=[totals_left_offset, totals_width])
    totals_wrapper.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(totals_wrapper)
    story.append(Spacer(1, 8))

    story.append(Paragraph(f"<b>Forma de pago:</b> Transferencia bancaria", meta_label_style))
    story.append(Paragraph(f"<b>IBAN:</b> {company_iban}", meta_label_style))
    story.append(Spacer(1, 10))

    qr_img = _get_qr_image(invoice, client, company_config, max_size=70)
    if qr_img:
        qr_data = [
            [qr_img, Paragraph("Factura generada electrónicamente<br/>Gracias por su confianza", footer_style)],
        ]
        qr_table = Table(qr_data, colWidths=[80, PRINTABLE_WIDTH - 80])
        qr_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ]))
        story.append(qr_table)

    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Sistema de facturación verificable / VERI*FACTU - Factura verificable en la sede electrónica de la AEAT",
        footer_style
    ))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    return pdf_bytes


# -----------------------------------------------------------
# PRESUPUESTO
# -----------------------------------------------------------
def make_budget_pdf(company, client, lineas, base_total, vat_total, total, vat_pct, budget_number=None):
    styles = getSampleStyleSheet()

    company_style = ParagraphStyle(
        'CompanyStyle', parent=styles['Heading2'], fontSize=15, leading=18,
        textColor=colors.HexColor('#1E3A8A'), spaceAfter=3,
    )
    company_info_style = ParagraphStyle(
        'CompanyInfoStyle', parent=styles['Normal'], fontSize=10, leading=13,
        textColor=colors.HexColor('#4A5568'), spaceAfter=2,
    )
    title_style = ParagraphStyle(
        'TitleStyle', parent=styles['Title'], fontSize=18, leading=21,
        textColor=colors.HexColor('#1E3A8A'), spaceAfter=6, alignment=TA_CENTER,
    )
    client_info_style = ParagraphStyle(
        'ClientInfoStyle', parent=styles['Normal'], fontSize=10, leading=13,
        textColor=colors.HexColor('#2D3748'), spaceAfter=2, alignment=TA_CENTER,
    )
    desc_style = ParagraphStyle(
        'DescStyle', parent=styles['Normal'], fontSize=10, leading=14,
        textColor=colors.HexColor('#2D3748'), spaceBefore=0, spaceAfter=0, alignment=TA_LEFT,
    )
    desc_header_style = ParagraphStyle(
        'DescHeaderStyle', parent=styles['Normal'], fontSize=10, leading=12,
        textColor=colors.white, fontName='Helvetica-Bold', spaceBefore=0, spaceAfter=0, alignment=TA_LEFT,
    )
    num_style = ParagraphStyle(
        'NumStyle', parent=styles['Normal'], fontSize=10, leading=14,
        textColor=colors.HexColor('#2D3748'), spaceBefore=0, spaceAfter=0, alignment=TA_RIGHT,
    )
    num_header_style = ParagraphStyle(
        'NumHeaderStyle', parent=styles['Normal'], fontSize=10, leading=12,
        textColor=colors.white, fontName='Helvetica-Bold', spaceBefore=0, spaceAfter=0, alignment=TA_RIGHT,
    )
    center_style = ParagraphStyle(
        'CenterStyle', parent=styles['Normal'], fontSize=10, leading=14,
        textColor=colors.HexColor('#2D3748'), spaceBefore=0, spaceAfter=0, alignment=TA_CENTER,
    )
    center_header_style = ParagraphStyle(
        'CenterHeaderStyle', parent=styles['Normal'], fontSize=10, leading=12,
        textColor=colors.white, fontName='Helvetica-Bold', spaceBefore=0, spaceAfter=0, alignment=TA_CENTER,
    )
    total_label_style = ParagraphStyle(
        'TotalLabelStyle', parent=styles['Normal'], fontSize=10, leading=13,
        textColor=colors.HexColor('#2D3748'), spaceBefore=0, spaceAfter=0, alignment=TA_LEFT,
    )
    total_value_style = ParagraphStyle(
        'TotalValueStyle', parent=styles['Normal'], fontSize=10, leading=13,
        textColor=colors.HexColor('#1E3A8A'), spaceBefore=0, spaceAfter=0,
        alignment=TA_RIGHT, fontName='Helvetica-Bold',
    )
    total_final_style = ParagraphStyle(
        'TotalFinalStyle', parent=styles['Normal'], fontSize=13, leading=16,
        textColor=colors.HexColor('#1E3A8A'), spaceBefore=0, spaceAfter=0,
        alignment=TA_RIGHT, fontName='Helvetica-Bold',
    )
    footer_style = ParagraphStyle(
        'FooterStyle', parent=styles['Normal'], fontSize=9, leading=11,
        textColor=colors.HexColor('#718096'), alignment=TA_CENTER,
    )

    PAGE_WIDTH, PAGE_HEIGHT = A4
    MARGIN_LEFT = 1.2 * cm
    MARGIN_RIGHT = 1.2 * cm
    MARGIN_TOP = 1.0 * cm
    MARGIN_BOTTOM = 1.0 * cm
    PRINTABLE_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=MARGIN_LEFT, rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
    )

    story = []

    company_name = company.get('company_name', 'Empresa')
    company_tax_id = company.get('company_tax_id', '')
    company_address = company.get('company_address', '')

    client_name = client.get('name', 'Cliente')
    client_tax_id = client.get('tax_id') or client.get('nif') or client.get('cif') or client.get('client_tax_id') or ''
    client_address = client.get('address', '')
    budget_num = budget_number or '---'

    logo_input = company.get('company_logo', '')
    logo_element = _get_reportlab_logo(logo_input, max_w=180, max_h=80)

    today_str = __import__('datetime').date.today().strftime('%d/%m/%Y')

    if logo_element:
        header_data = [
            [logo_element, Paragraph(f"<b>Nº:</b> {budget_num}", company_info_style)],
            [Paragraph(f"<b>{company_name}</b>", company_style), Paragraph(f"<b>Fecha:</b> {today_str}", company_info_style)],
            [Paragraph(f"NIF: {company_tax_id}", company_info_style), Paragraph("", company_info_style)],
            [Paragraph(company_address, company_info_style), Paragraph("", company_info_style)],
        ]
        header_col_widths = [PRINTABLE_WIDTH * 0.5, PRINTABLE_WIDTH * 0.5]
    else:
        header_data = [
            [Paragraph(f"<b>{company_name}</b>", company_style), Paragraph(f"<b>Nº:</b> {budget_num}", company_info_style)],
            [Paragraph(f"NIF: {company_tax_id}", company_info_style), Paragraph(f"<b>Fecha:</b> {today_str}", company_info_style)],
            [Paragraph(company_address, company_info_style), Paragraph("", company_info_style)],
        ]
        header_col_widths = [PRINTABLE_WIDTH * 0.65, PRINTABLE_WIDTH * 0.35]

    header_table = Table(header_data, colWidths=header_col_widths)
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("PRESUPUESTO", title_style))
    story.append(Paragraph(f"<b>Cliente:</b> {client_name}", client_info_style))
    if client_tax_id:
        story.append(Paragraph(f"<b>NIF/CIF:</b> {client_tax_id}", client_info_style))
    if client_address:
        story.append(Paragraph(client_address, client_info_style))
    story.append(Spacer(1, 8))

    line_table = Table([['']], colWidths=[PRINTABLE_WIDTH], rowHeights=[2])
    line_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#1E3A8A'))]))
    story.append(line_table)
    story.append(Spacer(1, 10))

    col_desc_width = PRINTABLE_WIDTH * 0.68
    col_qty_width = PRINTABLE_WIDTH * 0.08
    col_price_width = PRINTABLE_WIDTH * 0.12
    col_total_width = PRINTABLE_WIDTH * 0.12
    col_widths = [col_desc_width, col_qty_width, col_price_width, col_total_width]

    headers = [
        Paragraph('Descripción', desc_header_style),
        Paragraph('Cant.', center_header_style),
        Paragraph('Precio ud.', num_header_style),
        Paragraph('Total', num_header_style),
    ]

    rows = [headers]
    item_end_indices = []

    for linea in lineas:
        desc = linea.get('description', '')
        qty = linea.get('quantity', 1)
        price = linea.get('unit_price', 0)
        line_total = linea.get('total', linea.get('base_amount', 0))

        paragraphs = split_description_into_paragraphs(desc)
        if not paragraphs:
            paragraphs = [""]

        first_p = paragraphs[0]
        rows.append([
            Paragraph(f"<b>{first_p}</b>", desc_style),
            Paragraph(f"{float(qty):.0f}", center_style),
            Paragraph(_fmt_money(price), num_style),
            Paragraph(_fmt_money(line_total), num_style),
        ])

        for sub_p in paragraphs[1:]:
            rows.append([
                Paragraph(f"&bull; {sub_p}", desc_style),
                Paragraph("", center_style),
                Paragraph("", num_style),
                Paragraph("", num_style),
            ])

        item_end_indices.append(len(rows) - 1)

    lines_table = Table(rows, colWidths=col_widths, repeatRows=1)

    table_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#1E3A8A')),
    ]

    for idx in item_end_indices:
        table_style.append(('LINEBELOW', (0, idx), (-1, idx), 0.5, colors.HexColor('#CBD5E0')))

    lines_table.setStyle(TableStyle(table_style))
    story.append(lines_table)
    story.append(Spacer(1, 10))

    vat_pct_display = vat_pct or 0
    totals_width = PRINTABLE_WIDTH * 0.40
    totals_left_offset = PRINTABLE_WIDTH - totals_width

    totals_data = [
        [Paragraph('Base imponible:', total_label_style), Paragraph(_fmt_money(base_total), total_value_style)],
        [Paragraph(f'IVA ({vat_pct_display:.1f}%):', total_label_style), Paragraph(_fmt_money(vat_total), total_value_style)],
    ]

    irpf_total = sum(l.get('irpf_amount', 0) for l in lineas)
    if irpf_total > 0:
        irpf_pct = lineas[0].get('irpf_percentage', 0) if lineas else 0
        totals_data.append([
            Paragraph(f'IRPF ({irpf_pct:.1f}%):', total_label_style),
            Paragraph(f'-{_fmt_money(irpf_total)}', total_value_style)
        ])

    totals_data.append([
        Paragraph('<b>TOTAL:</b>', total_final_style),
        Paragraph(f'<b>{_fmt_money(total)}</b>', total_final_style),
    ])

    totals_table = Table(totals_data, colWidths=[totals_width * 0.45, totals_width * 0.55])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.HexColor('#1E3A8A')),
    ]))

    totals_wrapper = Table([['', totals_table]], colWidths=[totals_left_offset, totals_width])
    totals_wrapper.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(totals_wrapper)
    story.append(Spacer(1, 15))

    story.append(Paragraph(
        "Presupuesto válido por 30 días · Gracias por confiar en nosotros",
        footer_style
    ))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    return pdf_bytes
