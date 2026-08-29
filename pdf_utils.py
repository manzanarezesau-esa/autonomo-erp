# pdf_utils.py
import base64
from datetime import date, datetime
import io
import re

from jinja2 import Template
import qrcode
from qrcode.image.pil import PilImage
import streamlit as st
import weasyprint

from verifactu_utils import generar_qr_verifactu

# -----------------------------------------------------------
# PLANTILLA DE FACTURA
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
ul { margin-left: 15px; padding-left: 5px; }
li { margin-bottom: 3px; }
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
<td>{{ item.description_html|safe }}</td>
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
# PLANTILLA DE PRESUPUESTO HTML
# -----------------------------------------------------------
BUDGET_TEMPLATE = r"""<!DOCTYPE html>
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
    margin-bottom: 20px;
}
.logo-container {
    flex: 0 0 auto;
    margin-right: 20px;
}
.logo-container img {
    max-width: 200px;
    max-height: 90px;
    width: auto;
    height: auto;
}
.company-info {
    text-align: right;
    flex: 1;
}
.company-info h1 {
    color: #1e3a8a;
    font-size: 22px;
    font-weight: 700;
    margin-bottom: 4px;
}
.company-info p {
    font-size: 10px;
    line-height: 1.4;
    color: #4a5568;
}
.document-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 20px;
}
.document-title {
    color: #1e3a8a;
    font-size: 24px;
    font-weight: 700;
}
.client-section {
    margin: 15px 0;
    padding: 12px 15px;
    background-color: #f7fafc;
    border-left: 4px solid #1e3a8a;
    border-radius: 4px;
    font-size: 11px;
}
.client-section strong {
    color: #1e3a8a;
    font-size: 12px;
    display: block;
    margin-bottom: 4px;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin: 20px 0;
    font-size: 10px;
}
th {
    background-color: #1e3a8a;
    color: white;
    padding: 8px 10px;
    text-align: left;
    font-weight: 600;
}
td {
    padding: 8px 10px;
    border-bottom: 1px solid #e2e8f0;
    vertical-align: top;
    line-height: 1.4;
}
td.amount {
    text-align: right;
    white-space: nowrap;
}
ul {
    margin-left: 15px;
    padding-left: 5px;
}
li {
    margin-bottom: 2px;
}
.totals {
    width: 40%;
    margin-left: auto;
    margin-top: 15px;
    background-color: #f7fafc;
    padding: 12px 15px;
    border-radius: 6px;
    font-size: 11px;
}
.totals p {
    margin-bottom: 5px;
    display: flex;
    justify-content: space-between;
}
.totals .total-final {
    font-size: 13px;
    font-weight: 700;
    color: #1e3a8a;
    border-top: 1px solid #cbd5e0;
    padding-top: 5px;
    margin-top: 5px;
}
.footer {
    margin-top: 40px;
    font-size: 9px;
    border-top: 1px solid #e2e8f0;
    padding-top: 10px;
    text-align: center;
    color: #718096;
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
    {% if company.company_phone or company.company_email %}
    <p>Tel: {{ company.company_phone }} | Email: {{ company.company_email }}</p>
    {% endif %}
</div>
</div>

<div class="document-header">
    <div>
        <div class="document-title">PRESUPUESTO</div>
        <p style="font-size: 13px; color: #4a5568;">Nº {{ budget_number }}</p>
    </div>
    <div style="text-align: right; font-size: 11px;">
        <p><strong>Fecha:</strong> {{ date_today }}</p>
    </div>
</div>

<div class="client-section">
    <strong>DATOS DEL CLIENTE</strong>
    {{ client.name }}<br>
    {% if client.tax_id %}NIF: {{ client.tax_id }}<br>{% endif %}
    {{ client.address }}
</div>

<table>
<thead>
<tr>
    <th style="width: 55%;">Descripción</th>
    <th style="width: 10%; text-align: center;">Cant.</th>
    <th style="width: 15%; text-align: right;">Precio ud.</th>
    <th style="width: 20%; text-align: right;">Total</th>
</tr>
</thead>
<tbody>
{% for item in lineas %}
<tr>
    <td>{{ item.description_html|safe }}</td>
    <td style="text-align: center;">{{ item.quantity }}</td>
    <td class="amount">{{ "%.2f"|format(item.unit_price) }} €</td>
    <td class="amount"><strong>{{ "%.2f"|format(item.total) }} €</strong></td>
</tr>
{% endfor %}
</tbody>
</table>

<div class="totals">
    <p><span>Base imponible:</span> <span>{{ "%.2f"|format(base_total) }} €</span></p>
    <p><span>IVA ({{ vat_pct }}%):</span> <span>{{ "%.2f"|format(vat_total) }} €</span></p>
    <p class="total-final"><span>TOTAL:</span> <span>{{ "%.2f"|format(total) }} €</span></p>
</div>

<div class="footer">
    Presupuesto válido por 30 días · Gracias por confiar en nosotros
</div>
</body>
</html>"""

# -----------------------------------------------------------
# Funciones Auxiliares
# -----------------------------------------------------------
def _logo_sanitized(url):
    if not url:
        return ""
    url = str(url).strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return ""
    return url

def _process_description(desc_text):
    """Limpia caracteres duplicados (•, ■, -) y los transforma en HTML limpio."""
    if not desc_text:
        return ""
    lines = [l.strip() for l in str(desc_text).strip().split('\n') if l.strip()]
    has_bullets = any(re.match(r'^[•\-\■]\s*', l) for l in lines)
    
    if has_bullets:
        html_items = []
        for line in lines:
            clean_line = re.sub(r'^[•\-\■]\s*', '', line)
            html_items.append(f"<li>{clean_line}</li>")
        return f"<ul>{''.join(html_items)}</ul>"
    else:
        return "<br>".join(lines)

def get_qr_base64(invoice, client, company_config):
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
    try:
        return weasyprint.HTML(string=html_str).write_pdf()
    except Exception as e:
        st.error(f"Error generando PDF: {e}")
        return None

# -----------------------------------------------------------
# Generación de PDF de Factura (WeasyPrint)
# -----------------------------------------------------------
def make_invoice_pdf_from_template(invoice, client, company_config, lineas):
    qr_base64 = get_qr_base64(invoice, client, company_config)
    template_html = company_config.get("codigo_html") or DEFAULT_TEMPLATE
    template_css = company_config.get("codigo_css") or ""

    company_safe = dict(company_config)
    company_safe["company_logo"] = _logo_sanitized(company_safe.get("company_logo", ""))

    lineas_processed = []
    for item in (lineas or []):
        item_copy = dict(item)
        item_copy['description_html'] = _process_description(item.get('description', ''))
        lineas_processed.append(item_copy)

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
        lineas=lineas_processed
    )
    return _html_to_pdf(html_str)

# -----------------------------------------------------------
# Generación de PDF de Presupuesto (WeasyPrint con Logo)
# -----------------------------------------------------------
def make_budget_pdf(company, client, lineas, base_total, vat_total, total, vat_pct, budget_number=None):
    company_safe = dict(company)
    company_safe["company_logo"] = _logo_sanitized(company_safe.get("company_logo", ""))

    lineas_processed = []
    for item in lineas:
        item_copy = dict(item)
        item_copy['description_html'] = _process_description(item.get('description', ''))
        item_copy['total'] = item.get('total', item.get('base_amount', 0))
        lineas_processed.append(item_copy)

    template = Template(BUDGET_TEMPLATE)
    html_str = template.render(
        company=company_safe,
        client=client or {},
        lineas=lineas_processed,
        base_total=base_total,
        vat_total=vat_total,
        total=total,
        vat_pct=vat_pct or 0,
        budget_number=budget_number or "---",
        date_today=date.today().strftime('%d/%m/%Y')
    )
    return _html_to_pdf(html_str)
