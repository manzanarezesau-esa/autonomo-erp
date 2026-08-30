# pdf_utils.py
import io
import base64
import re
import ssl
import urllib.request
import qrcode
from qrcode.image.pil import PilImage
from jinja2 import Template
import streamlit as st
import weasyprint
from database import init_supabase
from verifactu_utils import generar_qr_verifactu

# -----------------------------------------------------------
# PLANTILLA DE FACTURA (con leyenda Veri*Factu)
# -----------------------------------------------------------
DEFAULT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Segoe UI', 'Helvetica', 'Arial', sans-serif;
    color: #2d3748;
    margin: 1.5cm;
    font-size: 11px;
}
.header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    border-bottom: 3px solid #1e3a8a;
    padding-bottom: 15px;
    margin-bottom: 25px;
}
.logo-container {
    flex: 0 0 auto;
    margin-right: 30px;
}
.logo-container img {
    max-width: 220px;
    max-height: 100px;
    width: auto;
    height: auto;
}
.company-info {
    text-align: right;
    flex: 1;
}
.company-info h1 {
    color: #1e3a8a;
    font-size: 24px;
    font-weight: 700;
    margin-bottom: 4px;
}
.company-info p {
    font-size: 11px;
    line-height: 1.4;
    color: #4a5568;
    margin-bottom: 2px;
}
.invoice-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 25px;
}
.invoice-title {
    color: #1e3a8a;
    font-size: 26px;
    font-weight: 700;
    margin-bottom: 10px;
}
.invoice-meta {
    background-color: #ebf4ff;
    padding: 12px 15px;
    border-radius: 6px;
    font-size: 11px;
}
.invoice-meta p {
    margin-bottom: 4px;
}
.client-section {
    margin: 20px 0;
    padding: 12px 15px;
    background-color: #f7fafc;
    border-left: 4px solid #1e3a8a;
    border-radius: 4px;
}
.client-section strong {
    color: #1e3a8a;
    font-size: 12px;
    display: block;
    margin-bottom: 5px;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin: 25px 0;
    font-size: 11px;
}
th {
    background-color: #1e3a8a;
    color: white;
    padding: 10px;
    text-align: left;
    font-weight: 600;
    letter-spacing: 0.5px;
}
td {
    padding: 10px;
    border-bottom: 1px solid #e2e8f0;
    vertical-align: top;
}
tr:last-child td {
    border-bottom: 2px solid #1e3a8a;
}
td.amount {
    text-align: right;
    font-family: 'Courier New', monospace;
}
.totals {
    width: 40%;
    margin-left: auto;
    margin-top: 15px;
    background-color: #f7fafc;
    padding: 12px 15px;
    border-radius: 6px;
    font-size: 12px;
}
.totals p {
    margin-bottom: 5px;
    display: flex;
    justify-content: space-between;
}
.totals .total-final {
    font-size: 14px;
    font-weight: 700;
    color: #1e3a8a;
    border-top: 1px solid #cbd5e0;
    padding-top: 5px;
    margin-top: 5px;
}
.footer {
    margin-top: 50px;
    font-size: 10px;
    border-top: 1px solid #e2e8f0;
    padding-top: 12px;
    text-align: center;
    color: #718096;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.qr-code img {
    width: 80px;
}
.payment-info {
    margin-top: 10px;
    font-size: 11px;
    background-color: #edf2f7;
    padding: 10px;
    border-radius: 4px;
}
.rectificativa-info {
    background-color: #fff3cd;
    border: 1px solid #ffc107;
    padding: 8px 12px;
    border-radius: 4px;
    margin-bottom: 15px;
    font-weight: bold;
}
.verifactu-leyenda {
    text-align: center;
    margin-top: 15px;
    font-size: 9px;
    color: #4a5568;
}
</style>
</head>
<body>
<div class="header">
{% if company.company_logo %}
<div class="logo-container">
<img src="{{ company.company_logo }}" alt="Logo">
</div>
{% endif %}
<div class="company-info">
<h1>{{ company.company_name }}</h1>
<p>{{ company.company_address }}</p>
<p>NIF: {{ company.company_tax_id }}</p>
<p>Tel: {{ company.company_phone }} | Email: {{ company.company_email }}</p>
</div>
</div>

<div class="invoice-header">
<div>
<div class="invoice-title">FACTURA{% if company.es_rectificativa %} RECTIFICATIVA{% endif %}</div>
<p style="font-size: 14px; color: #4a5568;">Nº {{ invoice.invoice_number }}</p>
{% if company.es_rectificativa and company.factura_original_num %}
<div class="rectificativa-info">
Rectifica a la factura: {{ company.factura_original_num }}
</div>
{% endif %}
</div>
<div class="invoice-meta">
<p><strong>Fecha:</strong> {{ invoice.date }}</p>
<p><strong>Periodo:</strong> {{ invoice.month }}</p>
<p><strong>Estado:</strong> {{ invoice.status if invoice.status else 'Pendiente' }}</p>
</div>
</div>

<div class="client-section">
<strong>DATOS DEL CLIENTE</strong>
{{ client.name }}<br>
NIF: {{ client.tax_id }}<br>
{{ client.address }}
</div>

<table>
<thead>
<tr>
<th>Concepto</th>
<th>Cant.</th>
<th>Precio ud.</th>
<th>Base imp.</th>
<th>IVA ({{ invoice.vat_percentage }}%)</th>
<th>IRPF ({{ invoice.irpf_percentage }}%)</th>
<th>Total</th>
</tr>
</thead>
<tbody>
{% for item in lineas %}
<tr>
<td>{{ item.description }}</td>
<td>{{ item.quantity }}</td>
<td class="amount">{{ "%.2f"|format(item.unit_price) }} €</td>
<td class="amount">{{ "%.2f"|format(item.base_amount) }} €</td>
<td class="amount">{{ "%.2f"|format(item.vat_amount) }} €</td>
<td class="amount">-{{ "%.2f"|format(item.irpf_amount) }} €</td>
<td class="amount"><strong>{{ "%.2f"|format(item.total) }} €</strong></td>
</tr>
{% endfor %}
</tbody>
</table>

<div class="totals">
<p><span>Base imponible:</span> <span>{{ "%.2f"|format(invoice.base_amount) }} €</span></p>
<p><span>IVA ({{ invoice.vat_percentage }}%):</span> <span>{{ "%.2f"|format(invoice.vat_amount) }} €</span></p>
<p><span>IRPF ({{ invoice.irpf_percentage }}%):</span> <span>-{{ "%.2f"|format(invoice.irpf_amount) }} €</span></p>
<p class="total-final"><span>TOTAL A PAGAR:</span> <span>{{ "%.2f"|format(invoice.total) }} €</span></p>
</div>

<div class="payment-info">
<strong>Forma de pago:</strong> Transferencia bancaria<br>
<strong>IBAN:</strong> {{ company.company_iban }}
</div>

<div class="footer">
<span>Factura generada electrónicamente · Gracias por su confianza</span>
{% if qr_base64 %}
<div class="qr-code">
<img src="data:image/png;base64,{{ qr_base64 }}" alt="QR VeriFactu">
</div>
{% endif %}
</div>
<div class="verifactu-leyenda">
Sistema de facturación verificable / VERI*FACTU - Factura verificable en la sede electrónica de la AEAT
</div>
</body>
</html>"""

# -----------------------------------------------------------
# UTILIDADES DE IMAGEN Y TEXTO
# -----------------------------------------------------------
def _logo_sanitized(url):
    if not url:
        return ""
    return str(url).strip()

def _get_reportlab_logo(logo_input, max_w=180, max_h=80):
    """Carga imágenes para ReportLab desde URL, Base64 o archivo local."""
    if not logo_input:
        return None
    logo_input = str(logo_input).strip()
    if not logo_input:
        return None

    try:
        from PIL import Image as PILImage
        from reportlab.platypus import Image as RLImage

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
    """Genera QR Veri*Factu con formato exacto de la AEAT."""
    invoice_number = invoice.get('invoice_number', '')
    if '-' in invoice_number:
        parts = invoice_number.split('-')
        serie = parts[0] if len(parts) > 1 else "0"
        numero = parts[-1]
    else:
        serie = "0"
        numero = invoice_number
    
    nif_emisor = company_config.get('company_tax_id', '')
    fecha = invoice.get('date', '')
    importe_total = invoice.get('total', 0)
    hash_factura = invoice.get('hash', '')
    
    qr_data = generar_qr_verifactu(
        nif_emisor=nif_emisor,
        numero_factura=numero,
        serie=serie,
        fecha_expedicion=fecha,
        importe_total=importe_total,
        hash_factura=hash_factura
    )
    
    qr = qrcode.QRCode(box_size=4, border=1)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(image_factory=PilImage)
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

def _html_to_pdf(html_str):
    """Convierte HTML a PDF usando WeasyPrint."""
    try:
        return weasyprint.HTML(string=html_str).write_pdf()
    except Exception as e:
        st.error(f"Error generando PDF: {e}")
        return None

# -----------------------------------------------------------
# FACTURA (WEASYPRINT)
# -----------------------------------------------------------
def make_invoice_pdf_from_template(invoice, client, company_config, lineas):
    qr_base64 = get_qr_base64(invoice, client, company_config)
    template_html = company_config.get("codigo_html") or DEFAULT_TEMPLATE
    template_css = company_config.get("codigo_css") or ""

    company_safe = dict(company_config)
    company_safe["company_logo"] = _logo_sanitized(company_safe.get("company_logo", ""))
    company_safe.setdefault("company_phone", "")
    company_safe.setdefault("company_email", "")
    company_safe.setdefault("es_rectificativa", False)
    company_safe.setdefault("factura_original_num", None)

    if template_css.strip():
        if "<head" in template_html.lower():
            head_idx = template_html.lower().find("<head")
            insert = template_html.lower().find(">", head_idx)
            if insert != -1:
                template_html = template_html[:insert+1] + f"\n<style>{template_css}</style>\n" + template_html[insert+1:]
        else:
            template_html = f"<style>{template_css}</style>\n" + template_html

    template = Template(template_html)
    html_str = template.render(
        invoice=invoice or {},
        client=client or {},
        company=company_safe,
        qr_base64=qr_base64,
        lineas=lineas or []
    )
    return _html_to_pdf(html_str)

# -----------------------------------------------------------
# PRESUPUESTO (REPORTLAB MULTIPÁGINA Y SÍMBOLOS LIMPIOS)
# -----------------------------------------------------------
def split_description_into_paragraphs(desc_text):
    """
    Divide un texto largo en párrafos independientes y elimina
    caracteres como el cuadrado (■) para evitar superposiciones con las viñetas.
    """
    if not desc_text:
        return [""]
    
    desc_text = str(desc_text).strip()
    
    # Reemplazar cuadrados y caracteres especiales por saltos de línea
    desc_text = re.sub(r'[■\u25a0\u25a1\u25aa\u25ab\u25fe\u25fd\uFFFD]', '\n', desc_text)
    
    raw_lines = desc_text.split('\n')
    paragraphs = []
    
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
            
        # Eliminar cualquier viñeta o cuadrado al inicio
        cleaned = re.sub(r'^[•\-\*\s■\u25a0\u25a1\u25aa\u25ab\u25fe\u25fd\uFFFD]+', '', line).strip()
        # Eliminar cualquier cuadrado remanente dentro del texto
        cleaned = re.sub(r'[■\u25a0\u25a1\u25aa\u25ab\u25fe\u25fd\uFFFD]', '', cleaned).strip()
        
        if not cleaned:
            continue
            
        # Si un solo párrafo excede 300 caracteres sin saltos, dividir por palabras
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

def make_budget_pdf(company, client, lineas, base_total, vat_total, total, vat_pct, budget_number=None):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    )
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER

    PAGE_WIDTH, PAGE_HEIGHT = A4
    MARGIN_LEFT = 1.2 * cm
    MARGIN_RIGHT = 1.2 * cm
    MARGIN_TOP = 1.0 * cm
    MARGIN_BOTTOM = 1.0 * cm
    
    PRINTABLE_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

    styles = getSampleStyleSheet()

    company_style = ParagraphStyle(
        'CompanyStyle',
        parent=styles['Heading2'],
        fontSize=15,
        leading=18,
        textColor=colors.HexColor('#1E3A8A'),
        spaceAfter=3,
    )
    
    company_info_style = ParagraphStyle(
        'CompanyInfoStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=13,
        textColor=colors.HexColor('#4A5568'),
        spaceAfter=2,
    )
    
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Title'],
        fontSize=18,
        leading=21,
        textColor=colors.HexColor('#1E3A8A'),
        spaceAfter=6,
        alignment=TA_CENTER,
    )
    
    client_info_style = ParagraphStyle(
        'ClientInfoStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=13,
        textColor=colors.HexColor('#2D3748'),
        spaceAfter=2,
        alignment=TA_CENTER,
    )

    desc_style = ParagraphStyle(
        'DescStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#2D3748'),
        spaceBefore=0,
        spaceAfter=0,
        alignment=TA_LEFT,
    )

    desc_header_style = ParagraphStyle(
        'DescHeaderStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=12,
        textColor=colors.white,
        fontName='Helvetica-Bold',
        spaceBefore=0,
        spaceAfter=0,
        alignment=TA_LEFT,
    )

    num_style = ParagraphStyle(
        'NumStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#2D3748'),
        spaceBefore=0,
        spaceAfter=0,
        alignment=TA_RIGHT,
    )

    num_header_style = ParagraphStyle(
        'NumHeaderStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=12,
        textColor=colors.white,
        fontName='Helvetica-Bold',
        spaceBefore=0,
        spaceAfter=0,
        alignment=TA_RIGHT,
    )

    center_style = ParagraphStyle(
        'CenterStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#2D3748'),
        spaceBefore=0,
        spaceAfter=0,
        alignment=TA_CENTER,
    )

    center_header_style = ParagraphStyle(
        'CenterHeaderStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=12,
        textColor=colors.white,
        fontName='Helvetica-Bold',
        spaceBefore=0,
        spaceAfter=0,
        alignment=TA_CENTER,
    )

    total_label_style = ParagraphStyle(
        'TotalLabelStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=13,
        textColor=colors.HexColor('#2D3748'),
        spaceBefore=0,
        spaceAfter=0,
        alignment=TA_LEFT,
    )

    total_value_style = ParagraphStyle(
        'TotalValueStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=13,
        textColor=colors.HexColor('#1E3A8A'),
        spaceBefore=0,
        spaceAfter=0,
        alignment=TA_RIGHT,
        fontName='Helvetica-Bold',
    )

    total_final_style = ParagraphStyle(
        'TotalFinalStyle',
        parent=styles['Normal'],
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#1E3A8A'),
        spaceBefore=0,
        spaceAfter=0,
        alignment=TA_RIGHT,
        fontName='Helvetica-Bold',
    )

    footer_style = ParagraphStyle(
        'FooterStyle',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
        textColor=colors.HexColor('#718096'),
        alignment=TA_CENTER,
    )

    def fmt_money(valor):
        try:
            return f"{float(valor):,.2f} €"
        except (ValueError, TypeError):
            return "0.00 €"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
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
            Paragraph(fmt_money(price), num_style),
            Paragraph(fmt_money(line_total), num_style),
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
        [Paragraph('Base imponible:', total_label_style), Paragraph(fmt_money(base_total), total_value_style)],
        [Paragraph(f'IVA ({vat_pct_display:.1f}%):', total_label_style), Paragraph(fmt_money(vat_total), total_value_style)],
    ]

    irpf_total = sum(l.get('irpf_amount', 0) for l in lineas)
    if irpf_total > 0:
        irpf_pct = lineas[0].get('irpf_percentage', 0) if lineas else 0
        totals_data.append([
            Paragraph(f'IRPF ({irpf_pct:.1f}%):', total_label_style),
            Paragraph(f'-{fmt_money(irpf_total)}', total_value_style)
        ])

    totals_data.append([
        Paragraph('<b>TOTAL:</b>', total_final_style),
        Paragraph(f'<b>{fmt_money(total)}</b>', total_final_style),
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
