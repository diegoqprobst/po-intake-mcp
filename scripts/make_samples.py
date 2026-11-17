"""Generate the synthetic inbox in data/inbox/. Every company, person and number here is invented.

Run: uv run --group dev python scripts/make_samples.py
"""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fpdf import FPDF

INBOX = Path(__file__).resolve().parents[1] / "data" / "inbox"
TZ = timezone(timedelta(hours=-3))  # Montevideo


def pdf(lines: list[str]) -> bytes:
    doc = FPDF()
    doc.add_page()
    doc.set_font("Helvetica", size=11)
    for ln in lines:
        doc.cell(0, 7, ln, new_x="LMARGIN", new_y="NEXT")
    return bytes(doc.output())


def write(name: str, sender: str, subject: str, body: str, when: datetime,
          attachments: list[tuple[str, str, bytes]] = ()) -> None:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "pedidos@empaques.example"
    msg["Subject"] = subject
    msg["Date"] = format_datetime(when)
    msg["Message-ID"] = f"<{name}@mail.example>"
    msg.set_content(body)
    for fname, ctype, data in attachments:
        maintype, subtype = ctype.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=fname)
    (INBOX / f"{name}.eml").write_bytes(bytes(msg))


LACTEOS_BODY = """Buenos días,

Adjuntamos la siguiente orden de compra.

ORDEN DE COMPRA N° OC-4501
Fecha de entrega: 2026-12-10
Moneda: USD

SKU | Descripción | Cantidad | Unidad | Precio unitario
BOB-1001 | Bobina BOPP/PE laminada 60 micras | 1.500 | kg | 4,80
TAP-4001 | Tapa de aluminio termosellable | 200 | millar | 14,00

Total: USD 10.000,00

Saludos,
Compras - Lácteos del Sur
"""


def main() -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    for old in INBOX.glob("*.eml"):
        old.unlink()
    d = datetime(2026, 11, 16, 9, 12, tzinfo=TZ)

    # 1. known customer, known email-body layout, every rule passes -> draft
    write("01_lacteos_OC-4501", "Compras <compras@lacteosdelsur.example>",
          "Orden de compra OC-4501", LACTEOS_BODY, d)

    # 2. CSV export from the customer's system; one line breaks the pack multiple -> exception
    csv_text = (
        "oc,sku,descripcion,cantidad,unidad,precio_unit,fecha_entrega,moneda\n"
        "PO-8812,BOB-1002,Bobina PET/AL/PE 3 capas,600,kg,7.20,2026-12-15,USD\n"
        "PO-8812,BSU-2001,Bolsa stand-up 250 g con zipper,12,millar,95.00,2026-12-15,USD\n"
        "PO-8812,ETQ-3001,Etiqueta termocontraible PVC,22,millar,22.50,2026-12-15,USD\n"
    )
    write("02_snacks_PO-8812", "Abastecimiento <abastecimiento@snacksandinos.example>",
          "PO-8812 empaques diciembre", "Hola, va la PO de diciembre en CSV.\nGracias.", d + timedelta(minutes=40),
          [("PO-8812.csv", "text/csv", csv_text.encode())])

    # 3. PDF in a known layout, price 8 % over list -> exception
    cafe_pdf = pdf([
        "Cafe Rambla S.R.L.",
        "ORDEN DE COMPRA N° OC-0093",
        "Fecha de entrega: 2026-12-20",
        "Moneda: USD",
        "",
        "SKU | Descripcion | Cantidad | Unidad | Precio unitario",
        "BSU-2002 | Bolsa stand-up 1 kg con valvula | 10 | millar | 194,40",
        "",
        "Total: USD 1.944,00",
    ])
    write("03_cafe_OC-0093", "Administración <admin@caferambla.example>", "OC-0093",
          "Estimados, adjunto OC-0093. Saludos.", d + timedelta(hours=2),
          [("OC-0093.pdf", "application/pdf", cafe_pdf)])

    # 4. unknown sender, free-form PDF -> exception (needs a person, or the LLM fallback)
    nuevo_pdf = pdf([
        "Distribuidora Nueva - Pedido",
        "Necesitamos para la semana del 14 de diciembre:",
        "  - unas 300 bolsas stand-up de 250 g (las de zipper)",
        "  - bobina laminada BOPP, 800 kilos",
        "Precio como la cotizacion de octubre.",
        "Contacto: Ana, compras.",
    ])
    write("04_nuevo_cliente", "Ana <ana@distribuidoranueva.example>", "Pedido",
          "Les paso el pedido adjunto.", d + timedelta(hours=3),
          [("pedido.pdf", "application/pdf", nuevo_pdf)])

    # 5. same PO sent again by the same customer -> duplicate
    write("05_lacteos_OC-4501_reenvio", "Compras <compras@lacteosdelsur.example>",
          "RV: Orden de compra OC-4501", LACTEOS_BODY, d + timedelta(hours=5))

    # 6. not a purchase order -> ignored
    write("06_snacks_consulta", "Abastecimiento <abastecimiento@snacksandinos.example>",
          "Consulta de stock", "¿Tienen stock de bobina PET/AL/PE para enero? Gracias.", d + timedelta(hours=6))
    print(f"wrote {len(list(INBOX.glob('*.eml')))} emails to {INBOX}")


if __name__ == "__main__":
    main()
