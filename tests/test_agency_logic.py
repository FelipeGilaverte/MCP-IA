from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from automation_intel_mcp.tools.agency_logic import (
    analyze_company_site,
    infer_digital_maturity,
    parse_site_artifacts,
)


SAMPLE_HTML = """
<html>
  <head>
    <title>Acme Dental</title>
    <script async src="https://www.googletagmanager.com/gtag/js?id=GA-123"></script>
  </head>
  <body>
    <header>
      <a href="/contato">Fale conosco</a>
      <a href="https://wa.me/5511999999999?text=Oi">Chamar no WhatsApp</a>
    </header>
    <main>
      <section>
        <h1>Clinica odontologica com agendamento online</h1>
        <p>Email: contato@acme.test</p>
        <p>Telefone: +55 (11) 4002-8922</p>
      </section>
      <form action="/orcamento" method="post">
        <input type="text" name="name" placeholder="Seu nome" required />
        <input type="email" name="email" placeholder="Seu email" required />
        <textarea name="message" placeholder="Conte seu caso"></textarea>
        <button type="submit">Solicitar orcamento</button>
      </form>
    </main>
  </body>
</html>
"""


class AgencyLogicTests(unittest.TestCase):
    def test_parse_site_artifacts_extracts_contacts_forms_and_cta(self) -> None:
        artifacts = parse_site_artifacts(SAMPLE_HTML, "https://acme.test")

        self.assertEqual(artifacts.contacts.emails, ["contato@acme.test"])
        self.assertEqual(artifacts.contacts.phones, ["+551140028922"])
        self.assertEqual(artifacts.contacts.whatsapp_numbers, ["5511999999999"])
        self.assertEqual(artifacts.contacts.whatsapp_links, ["https://wa.me/5511999999999?text=Oi"])

        self.assertEqual(len(artifacts.forms), 1)
        form = artifacts.forms[0]
        self.assertEqual(form.action, "https://acme.test/orcamento")
        self.assertEqual(form.method, "post")
        self.assertEqual(form.purpose, "quote_request")
        self.assertEqual(form.submit_text, "Solicitar orcamento")
        self.assertEqual([field.name for field in form.fields], ["name", "email", "message"])

        self.assertIsNotNone(artifacts.primary_cta)
        self.assertEqual(artifacts.primary_cta.text, "Chamar no WhatsApp")
        self.assertEqual(artifacts.primary_cta.source, "anchor")
        self.assertGreaterEqual(artifacts.primary_cta.confidence, 0.5)

    def test_infer_digital_maturity_uses_site_signals(self) -> None:
        artifacts = parse_site_artifacts(SAMPLE_HTML, "https://acme.test")

        maturity = infer_digital_maturity(
            html=SAMPLE_HTML,
            extracted_text="Clinica odontologica com agendamento e atendimento por WhatsApp.",
            contacts=artifacts.contacts,
            forms=artifacts.forms,
            primary_cta=artifacts.primary_cta,
        )

        self.assertEqual(maturity.level, "high")
        self.assertGreaterEqual(maturity.score, 65)
        self.assertTrue(any("Google Tag Manager" in signal for signal in maturity.signals))

    def test_analyze_company_site_returns_stable_structured_json(self) -> None:
        analysis = analyze_company_site(
            company_name="Acme Dental",
            company_url="https://acme.test",
            niche="clinica odontologica",
            html=SAMPLE_HTML,
            extracted_text="Clinica odontologica com agendamento online, contato por WhatsApp e formulario de orcamento.",
            usage={"cached": True},
        )
        payload = analysis.model_dump()

        self.assertEqual(payload["company_name"], "Acme Dental")
        self.assertIn("contacts", payload)
        self.assertIn("forms", payload)
        self.assertIn("primary_cta", payload)
        self.assertIn("digital_maturity", payload)
        self.assertIn("pain_categories", payload)
        self.assertEqual(sorted(payload["pain_categories"].keys()), ["atendimento", "comercial", "marketing", "operacional"])
        self.assertTrue(payload["likely_pains"])
        self.assertTrue(payload["automation_opportunities"])
        self.assertEqual(payload["usage"], {"cached": True})


if __name__ == "__main__":
    unittest.main()

