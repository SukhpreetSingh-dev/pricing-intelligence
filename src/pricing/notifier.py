"""
PricingNotifier — genera e manda email di report prezzi ai clienti.

Il template e' pensato per le email: solo tabelle e stili inline
(Gmail e Outlook ignorano <style> e flex), leggibile anche da telefono.
Testi e numeri in formato italiano (virgola decimale).
"""

import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

import pandas as pd
from dotenv import load_dotenv

from src.pricing.analyzer import MAX_ETA_GIORNI_DEFAULT

load_dotenv()


COLORI = {
    'benzina': '#1A56DB',
    'gasolio': '#057A55',
    'gpl':     '#B45309',
    'metano':  '#6B21A8',
}
NOMI_CARBURANTE = {
    'benzina': 'Benzina', 'gasolio': 'Gasolio', 'gpl': 'GPL', 'metano': 'Metano',
}
# Il metano si vende al chilo, gli altri al litro
UNITA = {'metano': 'kg'}
GIORNI = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']
ROSSO, VERDE, GRIGIO, TESTO = '#B91C1C', '#047857', '#6B7280', '#111827'
FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,"
        "sans-serif")


# ── Pulizia dei campi anagrafici MIMIT ─────────────────────────
# I campi MIMIT sono scritti dai gestori: maiuscole a caso, CAP in coda
# all'indirizzo, spazi doppi, "nome impianto" spesso solo un codice.

def _vuoto(valore) -> bool:
    return valore is None or (isinstance(valore, float) and pd.isna(valore)) \
        or str(valore).strip() == ''


def _maiuscole_leggibili(testo: str) -> str:
    """'VIA ROMA NORD' -> 'Via Roma Nord'; lascia stare il testo gia' misto."""
    testo = re.sub(r'\s+', ' ', str(testo)).strip()
    return testo.title() if testo.isupper() else testo


def pulisci_indirizzo(indirizzo, comune=None) -> str:
    """
    Indirizzo leggibile, con il comune una volta sola.

    I gestori scrivono l'indirizzo come capita: CAP ripetuti, comune e
    provincia dentro l'indirizzo, 'VIA VIA ...'. Esempio reale MIMIT:
    'VIA S.S.   12 KM.236+614 46036, BORGO MANTOVANO (MN) 44  46036'
    -> 'Via S.S. 12 Km.236+614, Borgo Mantovano'
    """
    parti = []
    if not _vuoto(indirizzo):
        ind = re.sub(r'\s+', ' ', str(indirizzo)).strip()
        if not _vuoto(comune):                            # taglia da ', COMUNE' in poi
            ind = re.split(r',\s*' + re.escape(str(comune).strip()) + r'\b', ind,
                           maxsplit=1, flags=re.IGNORECASE)[0]
        ind = re.sub(r'\b\d{5}\b', '', ind)                 # CAP
        ind = re.sub(r'\([A-Za-z]{2}\)', '', ind)            # provincia (MN)
        ind = re.sub(r'^(via)\s+\1\b', r'\1', ind, flags=re.IGNORECASE)   # VIA VIA
        ind = re.sub(r'\s+', ' ', ind).strip(' ,')
        if ind:
            parti.append(_maiuscole_leggibili(ind))
    if not _vuoto(comune):
        com = _maiuscole_leggibili(comune)
        # aggiungi il comune, a meno che l'indirizzo non finisca gia' con quello
        if not parti or not parti[0].lower().endswith(com.lower()):
            parti.append(com)
    return ', '.join(parti) if parti else 'Indirizzo non disponibile'


def nome_distributore(riga) -> str:
    """'Esso · EGI-2GO S.r.l.' — bandiera + gestore (il 'nome' MIMIT e' spesso un codice)."""
    bandiera = '' if _vuoto(riga.get('bandiera')) else str(riga.get('bandiera')).strip()
    gestore = '' if _vuoto(riga.get('gestore')) else _maiuscole_leggibili(riga.get('gestore'))
    if len(gestore) > 42:
        gestore = gestore[:40].rstrip() + '…'
    return ' · '.join(p for p in (bandiera, gestore) if p) or 'Impianto non identificato'


# ── Formattazione all'italiana ─────────────────────────────────

def euro(valore) -> str:
    """1.994 -> '€ 1,994'"""
    return f"€ {valore:.3f}".replace('.', ',')


def _cent(valore) -> str:
    """+1,5 / −3,0 / +0,0 — virgola decimale e segno meno tipografico."""
    return f'{valore:+.1f}'.replace('.', ',').replace('-', '−')


def formatta_eta(eta) -> str:
    if eta is None or pd.isna(eta):
        return 'data di aggiornamento non disponibile'
    eta = int(eta)
    if eta == 0:
        return 'aggiornato oggi'
    return 'aggiornato ieri' if eta == 1 else f'aggiornato {eta} giorni fa'


def formatta_data(data) -> str:
    if data is None or pd.isna(data):
        return 'n.d.'
    return data.strftime('%d/%m/%Y %H:%M')


def formatta_giorno(giorno) -> str:
    """date(2026, 10, 25) -> 'domenica 25/10/2026'"""
    return f"{GIORNI[giorno.weekday()]} {giorno:%d/%m/%Y}"


def giorno_prezzi(report: dict):
    """Il giorno a cui si riferiscono i prezzi: dalla riga di estrazione MIMIT,
    altrimenti dall'ultima comunicazione presente nei dati."""
    if report.get('estrazione'):
        return report['estrazione']
    rif = report.get('riferimento')
    return None if rif is None or pd.isna(rif) else rif.date()


class PricingNotifier:
    """
    Uso:
        notifier = PricingNotifier()
        stato = notifier.invia_report(report)   # 'inviata' | 'saltata' | 'errore'
    """

    def __init__(self):
        self.mittente = os.getenv("EMAIL_MITTENTE", "")
        self.password = os.getenv("EMAIL_APP_PASSWORD", "")

    # ── Invio ──────────────────────────────────────────────────

    def invia_report(self, report: dict) -> str:
        cliente = report['cliente']

        if not self._config_valida():
            print("  ⏭️  Email non configurata — invio saltato")
            return 'saltata'

        emails = cliente['email']
        if isinstance(emails, str):
            emails = [emails]

        try:
            msg = self._costruisci_email(report)
            for email in emails:
                self._invia(msg, email)
                print(f"  ✅ Email inviata a {email}")
            return 'inviata'
        except Exception as e:
            print(f"  ❌ Errore invio: {e}")
            return 'errore'

    def _config_valida(self) -> bool:
        return bool(self.mittente and self.password)

    def _costruisci_email(self, report: dict) -> MIMEMultipart:
        cliente = report['cliente']
        emails = cliente['email']
        if isinstance(emails, str):
            emails = [emails]

        giorno = giorno_prezzi(report)
        msg = MIMEMultipart('alternative')
        msg['Subject'] = (f"Prezzi carburanti — {cliente['nome']} — "
                          f"{'prezzi del ' + format(giorno, '%d/%m/%Y') if giorno else datetime.now().strftime('%d/%m/%Y')}")
        msg['From'] = self.mittente
        msg['To'] = ', '.join(emails)
        msg.attach(MIMEText(self._template_html(report), 'html', 'utf-8'))
        return msg

    def _invia(self, msg: MIMEMultipart, destinatario: str) -> None:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(self.mittente, self.password)
            server.sendmail(self.mittente, destinatario, msg.as_string())

    # ── Template ───────────────────────────────────────────────

    def _template_html(self, report: dict) -> str:
        cliente = report['cliente']
        info = cliente.get('impianto') or {}

        if info:
            sottotitolo = (f"{escape(nome_distributore(info))}<br>"
                           f"{escape(pulisci_indirizzo(info.get('indirizzo'), info.get('comune')))}")
        else:
            sottotitolo = escape(cliente.get('indirizzo', ''))

        giorno = giorno_prezzi(report)
        quando = (f"prezzi in vigore alle 8:00 di {formatta_giorno(giorno)}"
                  if giorno else "data dei prezzi non disponibile")
        tipo = 'self-service' if cliente.get('is_self', True) else 'servito'
        max_eta = cliente.get('max_eta_giorni', MAX_ETA_GIORNI_DEFAULT)
        sezioni = ''.join(self._sezione_carburante(carb, analisi, cliente)
                          for carb, analisi in report['carburanti'].items())

        return f"""<!doctype html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prezzi carburanti — {escape(cliente['nome'])}</title></head>
<body style="margin:0;padding:0;background:#F3F4F6;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
  style="background:#F3F4F6;font-family:{FONT};color:{TESTO};">
<tr><td align="center" style="padding:16px 8px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
  style="max-width:640px;background:#FFFFFF;border-radius:12px;
  border:1px solid #E5E7EB;">

  <tr><td style="padding:24px 24px 16px;border-bottom:1px solid #E5E7EB;">
    <div style="font-size:12px;color:{GRIGIO};text-transform:uppercase;
      letter-spacing:.06em;">Report prezzi carburanti · {quando}</div>
    <div style="font-size:22px;font-weight:700;margin:6px 0 4px;">
      {escape(cliente['nome'])}</div>
    <div style="font-size:13px;color:{GRIGIO};line-height:1.5;">{sottotitolo}</div>
    <div style="font-size:13px;color:{GRIGIO};margin-top:8px;">
      Concorrenti entro <strong style="color:{TESTO};">{cliente['raggio_km']} km</strong>
      · prezzi {tipo}</div>
  </td></tr>

  {sezioni}

  <tr><td style="padding:16px 24px 24px;font-size:11px;color:#9CA3AF;
    line-height:1.6;border-top:1px solid #E5E7EB;">
    Fonte: open data del Ministero delle Imprese e del Made in Italy (MIMIT).
    Sono i prezzi comunicati dai gestori, che il Ministero pubblica ogni mattina
    con i valori in vigore alle 8:00 del giorno precedente.
    Report generato il {datetime.now().strftime('%d/%m/%Y alle %H:%M')}.
    Per GPL e metano sono inclusi anche i prezzi del servito.
    Non sono considerati i concorrenti che non aggiornano il prezzo da più di
    {max_eta} giorni.
    «Diff.» = prezzo del concorrente meno il tuo, in centesimi:
    <span style="color:{ROSSO};">rosso</span> = costa meno di te.
  </td></tr>

</table>
</td></tr></table>
</body></html>"""

    def _sezione_carburante(self, carburante: str, analisi: dict,
                            cliente: dict) -> str:
        colore = COLORI.get(carburante, '#1A56DB')
        nome = NOMI_CARBURANTE.get(carburante, carburante.title())
        unita = UNITA.get(carburante, 'L')

        return f"""
  <tr><td style="padding:20px 24px 4px;">
    <div style="font-size:15px;font-weight:700;color:{colore};
      text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px;">
      {nome}</div>
    {self._riquadro(analisi, colore, unita)}
    {self._classifica(analisi, cliente, colore)}
  </td></tr>"""

    def _riquadro(self, analisi: dict, colore: str, unita: str) -> str:
        """Riquadro in alto: il tuo prezzo e come sei posizionato."""
        prezzo = analisi['prezzo_cliente']

        if prezzo is None:
            return self._avviso('Il tuo prezzo per questo carburante non è presente '
                                'nei dati MIMIT. Sotto trovi comunque i concorrenti.')

        eta_c = analisi.get('eta_cliente')
        riga_eta = escape(formatta_eta(eta_c))
        if eta_c is not None and eta_c > analisi['max_eta_giorni']:
            riga_eta = (f'<span style="color:{ROSSO};font-weight:600;">⏳ '
                        f'{riga_eta} — controlla che sia ancora giusto</span>')

        if analisi['posizione'] is None:
            dettaglio = 'Nessun prezzo aggiornato dei concorrenti nel raggio.'
        else:
            dettaglio = (
                f"<strong>{analisi['posizione']}°</strong> su "
                f"{analisi['totale']} impianti · "
                f"{self._colorato(analisi['diff_vs_min'])} rispetto al più economico "
                f"({euro(analisi['prezzo_min'])}) · "
                f"{self._colorato(analisi['diff_vs_media'])} rispetto alla media "
                f"({euro(analisi['prezzo_medio'])})")
            dettaglio += (f"<div style=\"margin-top:4px;\">"
                          f"{escape(analisi['raccomandazione'])}</div>")

        return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
      style="background:#F9FAFB;border-left:4px solid {colore};border-radius:6px;">
    <tr><td style="padding:12px 14px;">
      <div style="font-size:12px;color:{GRIGIO};">Il tuo prezzo · {riga_eta}</div>
      <div style="font-size:24px;font-weight:700;margin:2px 0 6px;">
        {euro(prezzo)}<span style="font-size:13px;font-weight:400;color:{GRIGIO};">/{unita}</span></div>
      <div style="font-size:13px;line-height:1.6;color:#374151;">{dettaglio}</div>
    </td></tr></table>"""

    def _classifica(self, analisi: dict, cliente: dict, colore: str) -> str:
        """Top N con la riga del cliente inserita al suo posto."""
        df = analisi['top_n']
        prezzo_c = analisi['prezzo_cliente']
        pos_c = analisi.get('posizione')

        if df.empty:
            return ''

        righe, cliente_mostrato = [], False
        for _, row in df.iterrows():
            if (prezzo_c is not None and pos_c is not None and not cliente_mostrato
                    and row['rank'] > pos_c):
                righe.append(self._riga_cliente(analisi, cliente, colore))
                cliente_mostrato = True
            righe.append(self._riga_competitor(row))

        if prezzo_c is not None and pos_c is not None and not cliente_mostrato:
            if pos_c > len(df) + 1:
                righe.append(f"""
      <tr><td colspan="3" style="padding:4px 10px;text-align:center;
        color:#9CA3AF;font-size:13px;">⋯ {'1 altro' if pos_c - len(df) == 2 else f'altri {pos_c - len(df) - 1}'} ⋯</td></tr>""")
            righe.append(self._riga_cliente(analisi, cliente, colore))

        n = len(df)
        if analisi['n_competitor'] > n:
            titolo = (f"I {n} più economici su {analisi['n_competitor']} concorrenti "
                      f"entro {cliente['raggio_km']} km")
        elif n == 1:
            titolo = f"L'unico concorrente entro {cliente['raggio_km']} km"
        else:
            titolo = f"Tutti i {n} concorrenti entro {cliente['raggio_km']} km"

        esclusi = ''
        k = analisi.get('n_esclusi')
        if k:
            testo = (f"1 concorrente escluso perché non aggiorna il prezzo"
                     if k == 1 else
                     f"{k} concorrenti esclusi perché non aggiornano il prezzo")
            esclusi = (f"<div style=\"font-size:11px;color:#9CA3AF;margin-top:6px;\">"
                       f"{testo} da più di {analisi['max_eta_giorni']} giorni.</div>")

        return f"""
    <div style="font-size:12px;color:{GRIGIO};margin:14px 0 6px;">{titolo}</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
      style="border-collapse:collapse;font-size:13px;">
      <tr style="color:{GRIGIO};font-size:11px;text-transform:uppercase;
        letter-spacing:.04em;">
        <td style="padding:6px 10px;border-bottom:2px solid {colore};width:28px;">#</td>
        <td style="padding:6px 10px;border-bottom:2px solid {colore};">Impianto</td>
        <td style="padding:6px 10px;border-bottom:2px solid {colore};
          text-align:right;white-space:nowrap;">Prezzo · diff.</td>
      </tr>
      {''.join(righe)}
    </table>{esclusi}"""

    def _riga_competitor(self, row) -> str:
        km = f"{row['distanza_km']:.1f}".replace('.', ',')
        dettagli = (f"{escape(pulisci_indirizzo(row.get('indirizzo'), row.get('comune')))}"
                    f"<br>a {km} km · {escape(formatta_eta(row.get('eta_giorni')))}")
        diff = row.get('diff_vs_cliente')
        vs = '' if diff is None or pd.isna(diff) else \
            f"<div style=\"font-size:12px;\">{self._colorato(diff, invertito=True)}</div>"
        return f"""
      <tr>
        <td style="padding:10px;border-bottom:1px solid #F3F4F6;color:{GRIGIO};
          vertical-align:top;font-weight:600;">{int(row['rank'])}</td>
        <td style="padding:10px;border-bottom:1px solid #F3F4F6;vertical-align:top;">
          <div style="font-weight:600;">{escape(nome_distributore(row))}</div>
          <div style="font-size:12px;color:{GRIGIO};line-height:1.5;">{dettagli}</div>
        </td>
        <td style="padding:10px;border-bottom:1px solid #F3F4F6;text-align:right;
          vertical-align:top;white-space:nowrap;">
          <div style="font-weight:700;">{euro(row['prezzo'])}</div>{vs}
        </td>
      </tr>"""

    def _riga_cliente(self, analisi: dict, cliente: dict, colore: str) -> str:
        return f"""
      <tr style="background:#FEF9C3;">
        <td style="padding:10px;border-bottom:1px solid #FDE68A;font-weight:700;
          vertical-align:top;">{analisi['posizione']}</td>
        <td style="padding:10px;border-bottom:1px solid #FDE68A;vertical-align:top;">
          <div style="font-weight:700;">▶ TU — {escape(cliente['nome'])}</div>
        </td>
        <td style="padding:10px;border-bottom:1px solid #FDE68A;text-align:right;
          vertical-align:top;font-weight:700;white-space:nowrap;">
          {euro(analisi['prezzo_cliente'])}</td>
      </tr>"""

    @staticmethod
    def _colorato(valore, invertito: bool = False) -> str:
        """
        Centesimi colorati. Normale (te vs mercato): positivo = sei piu' caro = rosso.
        Invertito (competitor vs te): negativo = costa meno di te = rosso.
        """
        cattivo = valore < 0 if invertito else valore > 0
        buono = valore > 0 if invertito else valore < 0
        colore = ROSSO if cattivo else (VERDE if buono else GRIGIO)
        return (f'<span style="color:{colore};font-weight:600;">'
                f'{_cent(valore)} cent</span>')

    @staticmethod
    def _avviso(testo: str) -> str:
        return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
      style="background:#FEF3C7;border-left:4px solid #D97706;border-radius:6px;">
    <tr><td style="padding:12px 14px;font-size:13px;color:#92400E;">
      ⚠️ {escape(testo)}</td></tr></table>"""
