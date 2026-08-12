# pdf_utils.py
import io
import base64
import re
import qrcode
from qrcode.image.pil import PilImage
from jinja2 import Template
import streamlit as st
import weasyprint
from database import init_supabase

# -----------------------------------------------------------
# PLANTILLA DE FACTURA (sin cambios)
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
<td class="amount">{{ "%.2f"|format(item.irpf_amount) }} €</td>
<td class="amount"><strong>{{ "%.2f"|format(item.total) }} €</strong></td>
</tr>
{% endfor %}
</tbody>
</table>

<div class="totals">
<p><span>Base imponible:</span> <span>{{ "%.2f"|format(invoice.base_amount) }} €</span></p>
<p><span>IVA ({{ invoice.vat_percentage }}%):</span> <span>{{ "%.2f"|format(invoice.vat_amount) }} €</span></p>
<p><span>IRPF ({{ invoice.irpf_percentage }}%):</span> <span>{{ "%.2f"|format(invoice.irpf_amount) }} €</span></p>
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
<img src="data:image/png;base64,{{ qr_base64 }}" alt="QR">
</div>
{% endif %}
</div>
</body>
</html>"""

# -----------------------------------------------------------
# PLANTILLA DE PRESUPUESTO (mejorada – diseño técnico limpio)
# -----------------------------------------------------------
BUDGET_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Helvetica', 'Arial', sans-serif;
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
.document-title {
    color: #1e3a8a;
    font-size: 26px;
    font-weight: 700;
    margin: 20px 0 10px 0;
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

/* ----- Estilos para los bloques de partidas ----- */
.item-block {
    page-break-inside: avoid;
    margin-bottom: 25px;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 15px;
}
.item-title {
    font-weight: 700;
    text-transform: uppercase;
    color: #1e3a8a;
    font-size: 12px;
    margin-bottom: 8px;
    text-align: left;
}
.item-description {
    font-size: 11px;
    line-height: 1.5;
    margin-bottom: 12px;
    text-align: left;
}
.item-description p {
    margin-bottom: 6px;
}
.item-description ul {
    margin-left: 15px;
    list-style-type: disc;
    padding-left: 0;
}
.item-description li {
    margin-bottom: 4px;
    line-height: 1.5;
    list-style-position: outside;
}
.item-details {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    font-size: 11px;
    background-color: #f7fafc;
    padding: 8px 12px;
    border-radius: 4px;
}
.item-details span {
    margin-right: 15px;
    white-space: nowrap;
}
.item-details .item-total {
    font-weight: 700;
    color: #1e3a8a;
}

.totals {
    width: 40%;
    margin-left: auto;
    margin-top: 25px;
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

<div class="document-title">PRESUPUESTO {{ budget_number }}</div>

<div class="client-section">
<strong>DATOS DEL CLIENTE</strong>
{{ client.name }}<br>
NIF: {{ client.tax_id }}<br>
{{ client.address }}
</div>

<!-- Lista de conceptos / partidas -->
{% for item in lineas %}
<div class="item-block">
    <div class="item-title">{{ item.title }}</div>
    {% if item.description_html %}
    <div class="item-description">{{ item.description_html }}</div>
    {% endif %}
    <div class="item-details">
        <span><strong>Cantidad:</strong> {{ item.quantity }}</span>
        <span><strong>Precio ud.:</strong> {{ "%.2f"|format(item.unit_price) }} €</span>
        <span><strong>Base imp.:</strong> {{ "%.2f"|format(item.base_amount) }} €</span>
        <span><strong>IVA ({{ vat_pct }}%):</strong> {{ "%.2f"|format(item.vat_amount) }} €</span>
        {% if item.irpf_percentage != 0 %}
        <span><strong>IRPF ({{ item.irpf_percentage }}%):</strong> {{ "%.2f"|format(item.irpf_amount) }} €</span>
        {% endif %}
        <span class="item-total"><strong>Total:</strong> {{ "%.2f"|format(item.total) }} €</span>
    </div>
</div>
{% endfor %}

<div class="totals">
<p><span>Base imponible:</span> <span>{{ "%.2f"|format(base_total) }} €</span></p>
<p><span>IVA ({{ vat_pct }}%):</span> <span>{{ "%.2f"|format(vat_total) }} €</span></p>
{% if lineas and lineas[0].irpf_percentage != 0 %}
<p><span>IRPF:</span> <span>{{ "%.2f"|format(lineas | sum(attribute='irpf_amount')) }} €</span></p>
{% endif %}
<p class="total-final"><span>TOTAL:</span> <span>{{ "%.2f"|format(total) }} €</span></p>
</div>

<div class="footer">
Presupuesto válido por 30 días · Gracias por confiar en nosotros
</div>
</body>
</html>"""

# -----------------------------------------------------------
# Utilidades
# -----------------------------------------------------------
def _logo_sanitized(url):
    if not url:
        return ""
    url = str(url).strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return ""
    return url

def get_qr_base64(invoice, client):
    qr_data = f"Factura: {invoice.get('invoice_number','')}\nFecha: {invoice.get('date','')}\nTotal: {invoice.get('total',0):.2f} EUR\nNIF: {client.get('tax_id','')}"
    qr = qrcode.QRCode(box_size=4, border=1)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(image_factory=PilImage)
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

def _html_to_pdf(html_str):
    """Convierte HTML a PDF usando WeasyPrint (nativo Python)."""
    try:
        return weasyprint.HTML(string=html_str).write_pdf()
    except Exception as e:
        st.error(f"Error generando PDF: {e}")
        return None

def _process_description(desc_text):
    """
    Convierte un texto con viñetas (•) y saltos de línea en HTML semántico.
    - Las líneas que empiezan con '•' o '-' se convierten en una lista <ul>.
    - Los párrafos separados por doble salto de línea se envuelven en <p>.
    - Se respeta el interlineado y márgenes mediante CSS (ya en plantilla).
    """
    if not desc_text:
        return ""
    # Dividir en bloques de párrafo (separados por al menos una línea en blanco)
    paragraphs = re.split(r'\n\s*\n', desc_text.strip())
    html_parts = []
    for para in paragraphs:
        lines = para.split('\n')
        # Si todas las líneas empiezan con viñeta, las tratamos como lista
        if all(re.match(r'^\s*[•-]\s', line) for line in lines if line.strip()):
            ul_items = []
            for line in lines:
                if line.strip():
                    # Quitamos el bullet y espacios iniciales
                    content = re.sub(r'^\s*[•-]\s*', '', line)
                    ul_items.append(f'<li>{content}</li>')
            html_parts.append('<ul>' + ''.join(ul_items) + '</ul>')
        else:
            # Es un párrafo normal (puede contener saltos de línea simples)
            # Reemplazamos los saltos de línea por <br> para respetar el formato
            text_with_br = '<br>'.join(lines)
            html_parts.append(f'<p>{text_with_br}</p>')
    return ''.join(html_parts)

# -----------------------------------------------------------
# Factura (sin cambios en lógica, solo usa WeasyPrint)
# -----------------------------------------------------------
def make_invoice_pdf_from_template(invoice, client, company_config, lineas):
    qr_base64 = get_qr_base64(invoice, client)
    template_html = company_config.get("codigo_html") or DEFAULT_TEMPLATE
    template_css = company_config.get("codigo_css") or ""

    company_safe = dict(company_config)
    company_safe["company_logo"] = _logo_sanitized(company_safe.get("company_logo", ""))
    company_safe.setdefault("company_phone", "")
    company_safe.setdefault("company_email", "")
    company_safe.setdefault("es_rectificativa", False)
    company_safe.setdefault("factura_original_num", None)

    # Inyectar CSS personalizado si existe
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
# Presupuesto (con procesamiento de descripciones)
# -----------------------------------------------------------
def make_budget_pdf(company, client, lineas, base_total, vat_total, total, vat_pct, budget_number=None):
    supabase = init_supabase()
    user_id = company.get("user_id")
    custom_html, custom_css = "", ""
    if user_id:
        try:
            config_res = supabase.table("settings").select("budget_html", "budget_css").eq("user_id", user_id).execute()
            if config_res.data:
                custom_html = config_res.data[0].get("budget_html") or ""
                custom_css = config_res.data[0].get("budget_css") or ""
        except Exception:
            pass

    template_html = custom_html.strip() if custom_html.strip() else BUDGET_TEMPLATE
    if custom_css.strip():
        if "<head" in template_html.lower():
            head_idx = template_html.lower().find("<head")
            insert = template_html.lower().find(">", head_idx)
            if insert != -1:
                template_html = template_html[:insert+1] + f"\n<style>{custom_css}</style>\n" + template_html[insert+1:]
        else:
            template_html = f"<style>{custom_css}</style>\n" + template_html

    # Procesar cada línea para extraer título y descripción HTML
    enriched_lineas = []
    for linea in lineas:
        desc = linea.get("description", "")
        # Si hay salto de línea, la primera línea es el título
        if '\n' in desc:
            lines = desc.split('\n', 1)
            title = lines[0].strip()
            rest = lines[1].strip() if len(lines) > 1 else ""
        else:
            title = desc.strip()
            rest = ""
        desc_html = _process_description(rest) if rest else ""
        new_item = linea.copy()
        new_item["title"] = title.upper()  # Forzamos mayúsculas
        new_item["description_html"] = desc_html
        enriched_lineas.append(new_item)

    t = Template(template_html)
    html_str = t.render(
        company=company or {},
        client=client or {},
        lineas=enriched_lineas,
        base_total=base_total or 0,
        vat_total=vat_total or 0,
        total=total or 0,
        vat_pct=vat_pct or 0,
        budget_number=budget_number or "---"
    )
    return _html_to_pdf(html_str)

