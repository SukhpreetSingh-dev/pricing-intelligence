"""
PricingNotifier — genera e manda email di report prezzi ai clienti.
"""

import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


class PricingNotifier:
    """
    Genera e manda email di report prezzi giornalieri.

    Uso:
        notifier = PricingNotifier()
        notifier.invia_report(cliente, report_analyzer)
    """

    def __init__(self):
        self.mittente = os.getenv("EMAIL_MITTENTE", "")
        self.password = os.getenv("EMAIL_APP_PASSWORD", "")

    def invia_report(self, report: dict) -> bool:
        cliente = report['cliente']

        if not self._config_valida():
            print(f"  ⚠️ Email non configurata")
            return False

        # Supporta sia stringa singola che lista di email
        emails = cliente['email']
        if isinstance(emails, str):
            emails = [emails]

        try:
            msg = self._costruisci_email(report)
            for email in emails:
                self._invia(msg, email)
                print(f"  ✅ Email inviata a {email}")
            return True
        except Exception as e:
            print(f"  ❌ Errore invio: {e}")
            return False

    def _config_valida(self) -> bool:
        return bool(self.mittente and self.password)

    def _costruisci_email(self, report: dict) -> MIMEMultipart:
        cliente = report['cliente']
        oggi    = datetime.now().strftime('%B %d, %Y')

        emails = cliente['email']
        if isinstance(emails, str):
            emails = [emails]

        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"📊 Fuel Price Report — {oggi}"
        msg['From']    = self.mittente
        msg['To']      = ', '.join(emails)   # lista → stringa separata da virgola

        html = self._template_html(report)
        msg.attach(MIMEText(html, 'html'))
        return msg
    def _template_html(self, report: dict) -> str:
        cliente   = report['cliente']
        oggi      = datetime.now().strftime('%B %d, %Y')
        carburanti = report['carburanti']

        # Sezioni per ogni carburante
        sezioni = ''
        for carburante, analisi in carburanti.items():
            sezioni += self._sezione_carburante(carburante, analisi,
                                                 cliente['top_n'])

        # Summary
        summary_html = ''
        for riga in report['summary']:
            summary_html += f"""
            <tr>
              <td style="padding:10px 16px;border-bottom:1px solid #E5E7EB;
                  font-size:14px;color:#374151;">{riga}</td>
            </tr>"""

        return f"""
        <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
            sans-serif;max-width:700px;margin:0 auto;background:#F9FAFB;
            padding:24px;">
          <div style="background:white;border-radius:12px;padding:32px;
              border:1px solid #E5E7EB;">

            <!-- Header -->
            <div style="border-bottom:3px solid #1A56DB;padding-bottom:16px;
                margin-bottom:24px;">
              <h1 style="color:#1A56DB;font-size:22px;margin:0 0 4px;">
                📊 Fuel Price Report</h1>
              <p style="color:#6B7280;font-size:13px;margin:0;">
                {oggi} — {cliente['nome']} — {cliente['raggio_km']} km radius
              </p>
            </div>

            <!-- Summary -->
            <h2 style="font-size:15px;color:#374151;margin:0 0 12px;">
              Positioning summary</h2>
            <table style="width:100%;border-collapse:collapse;
                background:#F9FAFB;border-radius:8px;margin-bottom:28px;">
              <tbody>{summary_html}</tbody>
            </table>

            <!-- Sezioni carburante -->
            {sezioni}

            <!-- Footer -->
            <hr style="border:none;border-top:1px solid #E5E7EB;
                margin:24px 0 16px;">
            <p style="color:#9CA3AF;font-size:12px;margin:0;">
              ⚠️ Data updated at 8:00 AM the previous day — Source: MIMIT Open Data<br>
              Self-service prices. Automatically generated.
            </p>
          </div>
        </div>"""


    def _sezione_carburante(self, carburante: str,
                             analisi: dict, top_n: int) -> str:
        """Genera la sezione HTML per un carburante."""

        COLORI = {
            'benzina': '#1A56DB',
            'gasolio': '#057A55',
            'gpl':     '#C27803',
            'metano':  '#6B7280',
        }
        colore = COLORI.get(carburante, '#1A56DB')

        # Info prezzo cliente
        if analisi['prezzo_cliente']:
            prezzo_info = f"""
            <div style="background:#F0F9FF;border-left:4px solid {colore};
                padding:12px 16px;border-radius:4px;margin-bottom:12px;">
              <p style="margin:0;font-size:14px;color:#374151;">
                <strong>Your price:</strong>
                €{analisi['prezzo_cliente']:.3f}/L &nbsp;|&nbsp;
                Position <strong>{analisi['posizione']}</strong>
                of {analisi['totale']} stations in the area
              </p>
              <p style="margin:4px 0 0;font-size:13px;color:#6B7280;">
                {analisi['raccomandazione']}
              </p>
            </div>"""
        else:
            prezzo_info = f"""
            <div style="background:#FEF3C7;border-left:4px solid #C27803;
                padding:12px 16px;border-radius:4px;margin-bottom:12px;">
              <p style="margin:0;font-size:13px;color:#92400E;">
                {analisi['raccomandazione']}
              </p>
            </div>"""

        # Tabella top N competitor
        righe = ''
        df_top = analisi['top_n']
        if not df_top.empty:
            for pos, row in df_top.iterrows():
                bg = '#EFF6FF' if pos == 1 else 'white'
                righe += f"""
                <tr style="background:{bg};">
                  <td style="padding:10px 12px;font-weight:600;
                      color:{colore};width:32px;">{pos}</td>
                  <td style="padding:10px 12px;font-size:13px;">
                    {row.get('bandiera','N/A')}</td>
                  <td style="padding:10px 12px;font-size:13px;
                      color:#6B7280;">{row.get('comune','N/A')}</td>
                  <td style="padding:10px 12px;font-weight:700;
                      font-size:14px;">€{row['prezzo']:.3f}</td>
                  <td style="padding:10px 12px;font-size:12px;
                      color:#9CA3AF;">{row['distanza_km']:.1f} km</td>
                </tr>"""
        else:
            righe = """
            <tr><td colspan="5" style="padding:12px;color:#9CA3AF;
                font-size:13px;">No data available</td></tr>"""

        return f"""
        <div style="margin-bottom:28px;">
          <h2 style="font-size:16px;color:{colore};margin:0 0 12px;
              text-transform:uppercase;letter-spacing:0.05em;">
            {carburante} — Top {top_n} cheapest</h2>

          {prezzo_info}

          <table style="width:100%;border-collapse:collapse;
              font-size:13px;border-radius:8px;overflow:hidden;">
            <thead>
              <tr style="background:{colore};color:white;">
                <th style="padding:10px 12px;text-align:left;">#</th>
                <th style="padding:10px 12px;text-align:left;">Brand</th>
                <th style="padding:10px 12px;text-align:left;">Town</th>
                <th style="padding:10px 12px;text-align:left;">Price</th>
                <th style="padding:10px 12px;text-align:left;">Distance</th>
              </tr>
            </thead>
            <tbody>{righe}</tbody>
          </table>
        </div>"""

    def _invia(self, msg: MIMEMultipart, destinatario: str) -> None:
        """Connette a Gmail e manda il messaggio."""
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(self.mittente, self.password)
            server.sendmail(self.mittente, destinatario, msg.as_string())