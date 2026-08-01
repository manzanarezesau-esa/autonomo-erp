
# pdf_utils.py
import io
import os
import base64
import pdfkit
from jinja2 import Template
import qrcode
from qrcode.image.pil import PilImage
import streamlit as st
from database import init_supabase

# -------------------------------------------------------------------
# Configurar la ruta de wkhtmltopdf (Windows)
# -------------------------------------------------------------------
_POSSIBLE_WKHTML_PATHS = [
    r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe',
    r'C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe',
    os.path.expanduser(r'~\AppData\Local\Programs\wkhtmltopdf\bin\wkhtmltopdf.exe'),
    r'C:\wkhtmltopdf\bin\wkhtmltopdf.exe',
    r'D:\wkhtmltopdf\bin\wkhtmltopdf.exe',
]

pdfkit_config = None
for path in _POSSIBLE_WKHTML_PATHS:
    if os.path.exists(path):
        pdfkit_config = pdfkit.configuration(wkhtmltopdf=path)
        break

if pdfkit_config is None:
    st.error(
        "❌ No se encontró wkhtmltopdf. Verifica que esté instalado.\n\n"
        "Descárgalo desde: https://wkhtmltopdf.org/downloads.html\n\n"
        "Rutas buscadas:\n" +
        "\n".join(_POSSIBLE_WKHTML_PATHS) +
        "\n\nSi lo instalaste en otra ruta, agrégala a la lista _POSSIBLE_WKHTML_PATHS en pdf_utils.py."
    )

# -------------------------------------------------------------------
# PLANTILLA DE FACTURA (soporta rectificativas)
# -------------------------------------------------------------------
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

# -------------------------------------------------------------------
# PLANTILLA DE PRESUPUESTO (sin cambios)
# -------------------------------------------------------------------
BUDGET_TEMPLATE = r"""..."""  # (mantén la misma plantilla de presupuesto que ya tenías)

# -------------------------------------------------------------------
# Funciones auxiliares y generación de PDFs (con pdfkit)
# -------------------------------------------------------------------
def _logo_sanitized(url):
    if not url:
        return ""
    url = str(url).strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return ""
    return url

def get_qr_base64(invoice, client):
    qr_data = (
        f"Factura: {invoice.get('invoice_number', '')}\n"
        f"Fecha: {invoice.get('date', '')}\n"
        f"Total: {invoice.get('total', 0):.2f} EUR\n"
        f"NIF Cliente: {client.get('tax_id', '')}"
    )
    qr = qrcode.QRCode(box_size=4, border=1)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(image_factory=PilImage)
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

def make_invoice_pdf_from_template(invoice, client, company_config, lineas):
    if pdfkit_config is None:
        st.error("No se puede generar el PDF porque no se encontró wkhtmltopdf.")
        return None

    qr_base64 = get_qr_base64(invoice, client)
    template_html = company_config.get("codigo_html") or DEFAULT_TEMPLATE
    template_css = company_config.get("codigo_css") or ""

    company_safe = dict(company_config)
    company_safe["company_logo"] = _logo_sanitized(company_safe.get("company_logo", ""))
    company_safe.setdefault("company_phone", "")
    company_safe.setdefault("company_email", "")
    company_safe.setdefault("es_rectificativa", False)
    company_safe.setdefault("factura_original_num", None)

    html_content = template_html
    if template_css and template_css.strip():
        if "<head" in html_content.lower():
            head_idx = html_content.lower().find("<head")
            insert = html_content.lower().find(">", head_idx)
            if insert != -1:
                html_content = html_content[:insert+1] + f"\n<style>{template_css}</style>\n" + html_content[insert+1:]
            else:
                html_content = f"<style>{template_css}</style>\n" + html_content
        else:
            html_content = f"<style>{template_css}</style>\n" + html_content

    template = Template(html_content)
    html_str = template.render(
        invoice=invoice or {},
        client=client or {},
        company=company_safe,
        qr_base64=qr_base64,
        lineas=lineas or []
    )

    options = {
        'page-size': 'A4',
        'margin-top': '10mm',
        'margin-right': '10mm',
        'margin-bottom': '10mm',
        'margin-left': '10mm',
        'encoding': 'UTF-8',
        'enable-local-file-access': None,
        'print-media-type': None,
        'no-stop-slow-scripts': None
    }

    try:
        pdf_bytes = pdfkit.from_string(html_str, False, options=options, configuration=pdfkit_config)
        return pdf_bytes
    except Exception as e:
        st.error(f"Error generando PDF: {e}")
        return None

def make_budget_pdf(company, client, lineas, base_total, vat_total, total, vat_pct, budget_number=None):
    # ... (sin cambios, igual que antes)
    pass  # Reemplaza esto con la implementación actual que ya tienes













