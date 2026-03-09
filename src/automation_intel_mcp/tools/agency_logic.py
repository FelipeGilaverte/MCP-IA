from __future__ import annotations

import re
from collections import defaultdict
from html import unescape
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin

from automation_intel_mcp.models import (
    CommercialOffer,
    CompanyAnalysis,
    DigitalMaturity,
    ImportantPage,
    NicheScore,
    OfferChannelVariants,
    OutreachDraft,
    PainCategories,
    ResearchWorkflowResult,
    SiteArtifacts,
    SiteCTA,
    SiteContactInfo,
    SiteForm,
    SiteFormField,
)


_EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_PHONE_PATTERN = re.compile(r"(?:\+?\d[\d().\s-]{8,}\d)")
_WHATSAPP_PATTERN = re.compile(
    r"https?://(?:api\.)?whatsapp\.com/send\?[^\s\"'>]*phone=([0-9]+)[^\s\"'>]*|https?://wa\.me/([0-9]+)(?:\?[^\s\"'>]*)?",
    re.IGNORECASE,
)
_TAG_STRIPPER = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")

_CTA_KEYWORDS = {
    "whatsapp": 8,
    "orcamento": 8,
    "quote": 8,
    "agende": 7,
    "agendar": 7,
    "book": 7,
    "demo": 7,
    "fale conosco": 6,
    "fale com": 6,
    "contato": 5,
    "solicite": 5,
    "saiba mais": 3,
    "comece": 5,
    "comprar": 5,
    "ligue": 5,
}
_IGNORED_CTA_TEXTS = {
    "home",
    "inicio",
    "blog",
    "menu",
    "login",
    "entrar",
    "sobre",
    "servicos",
}
_MARKETING_STACKS = {
    "Google Tag Manager": ["googletagmanager", "gtag("],
    "Google Analytics": ["google-analytics", "ga("],
    "Meta Pixel": ["fbq(", "connect.facebook.net"],
    "HubSpot": ["hubspot"],
    "RD Station": ["rdstation", "rdstation-popup", "rdst"],
    "Hotjar": ["hotjar"],
}
_SERVICE_FLOW_KEYWORDS = [
    "agend",
    "agenda",
    "reserva",
    "pedido",
    "orcamento",
    "quote",
    "consulta",
    "atendimento",
    "suporte",
    "demo",
]


class _SiteHTMLParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.forms: list[dict] = []
        self.cta_candidates: list[dict] = []
        self._current_form: dict | None = None
        self._current_anchor: dict | None = None
        self._current_button: dict | None = None
        self._order = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {key.lower(): value for key, value in attrs}
        self._order += 1

        if tag == "form":
            self._current_form = {
                "action": urljoin(self.base_url, data.get("action") or "") or None,
                "method": (data.get("method") or "get").lower(),
                "fields": [],
                "submit_text": None,
            }
            return

        if tag == "a":
            self._current_anchor = {
                "href": urljoin(self.base_url, data.get("href") or "") or None,
                "text_parts": [],
                "source": "anchor",
                "order": self._order,
                "aria_label": data.get("aria-label") or data.get("title") or "",
            }
            return

        if tag == "button":
            button_type = (data.get("type") or "button").lower()
            self._current_button = {
                "href": urljoin(self.base_url, data.get("formaction") or "") or None,
                "text_parts": [],
                "source": "button",
                "order": self._order,
                "button_type": button_type,
                "aria_label": data.get("aria-label") or data.get("title") or "",
            }
            return

        if tag in {"input", "textarea", "select"} and self._current_form is not None:
            field_type = (data.get("type") or ("textarea" if tag == "textarea" else tag)).lower()
            label = data.get("placeholder") or data.get("aria-label") or data.get("title")
            name = data.get("name") or data.get("id")
            if field_type not in {"hidden", "submit", "button", "image", "reset"}:
                self._current_form["fields"].append(
                    {
                        "name": name,
                        "field_type": field_type,
                        "label": label,
                        "required": "required" in data or data.get("aria-required") == "true",
                    }
                )
            if field_type in {"submit", "button"} and data.get("value") and not self._current_form["submit_text"]:
                self._current_form["submit_text"] = data.get("value")
                self.cta_candidates.append(
                    {
                        "href": self._current_form.get("action"),
                        "text": data.get("value"),
                        "source": "form_input",
                        "order": self._order,
                    }
                )

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_anchor is not None:
            text = _normalize_text(" ".join(self._current_anchor["text_parts"])) or _normalize_text(self._current_anchor["aria_label"])
            if text:
                self.cta_candidates.append(
                    {
                        "href": self._current_anchor["href"],
                        "text": text,
                        "source": self._current_anchor["source"],
                        "order": self._current_anchor["order"],
                    }
                )
            self._current_anchor = None
            return

        if tag == "button" and self._current_button is not None:
            text = _normalize_text(" ".join(self._current_button["text_parts"])) or _normalize_text(self._current_button["aria_label"])
            button_type = self._current_button["button_type"]
            if text:
                self.cta_candidates.append(
                    {
                        "href": self._current_button["href"] or (self._current_form or {}).get("action"),
                        "text": text,
                        "source": self._current_button["source"],
                        "order": self._current_button["order"],
                    }
                )
                if self._current_form is not None and button_type in {"submit", "button"} and not self._current_form["submit_text"]:
                    self._current_form["submit_text"] = text
            self._current_button = None
            return

        if tag == "form" and self._current_form is not None:
            self.forms.append(self._current_form)
            self._current_form = None

    def handle_data(self, data: str) -> None:
        if self._current_anchor is not None:
            self._current_anchor["text_parts"].append(data)
        if self._current_button is not None:
            self._current_button["text_parts"].append(data)


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return _WHITESPACE.sub(" ", unescape(value)).strip()


def _normalize_phone(value: str) -> str | None:
    raw = value.strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 10 or len(digits) > 15:
        return None
    if len(set(digits)) == 1:
        return None
    if raw.startswith("+"):
        return f"+{digits}"
    return digits


def _unique_sorted(values: list[str]) -> list[str]:
    return sorted({value for value in values if value})


def _add_unique(target: list[str], message: str, limit: int = 2) -> None:
    if message not in target and len(target) < limit:
        target.append(message)


def _plain_text_from_html(html: str) -> str:
    return _normalize_text(_TAG_STRIPPER.sub(" ", html))


def extract_contacts_from_html(html: str) -> SiteContactInfo:
    decoded = unquote(unescape(html))
    emails = _unique_sorted([match.group(0).lower() for match in _EMAIL_PATTERN.finditer(decoded)])

    phones: list[str] = []
    tel_links = re.findall(r"tel:([^\"'>\s]+)", decoded, flags=re.IGNORECASE)
    phones.extend(tel_links)
    phones.extend(match.group(0) for match in _PHONE_PATTERN.finditer(_plain_text_from_html(decoded)))
    normalized_phones = _unique_sorted([number for item in phones if (number := _normalize_phone(item))])

    whatsapp_numbers: list[str] = []
    whatsapp_links: list[str] = []
    for match in _WHATSAPP_PATTERN.finditer(decoded):
        link = match.group(0)
        digits = match.group(1) or match.group(2)
        whatsapp_links.append(link)
        if digits:
            normalized = _normalize_phone(digits)
            if normalized:
                whatsapp_numbers.append(normalized)

    normalized_whatsapp_numbers = _unique_sorted(whatsapp_numbers)
    normalized_phone_set = [phone for phone in normalized_phones if phone not in normalized_whatsapp_numbers]

    return SiteContactInfo(
        emails=emails,
        phones=normalized_phone_set,
        whatsapp_numbers=normalized_whatsapp_numbers,
        whatsapp_links=_unique_sorted(whatsapp_links),
    )


def _infer_form_purpose(action: str | None, submit_text: str | None, fields: list[SiteFormField]) -> str:
    haystack = " ".join(
        filter(
            None,
            [
                action or "",
                submit_text or "",
                *(field.name or "" for field in fields),
                *(field.label or "" for field in fields),
            ],
        )
    ).lower()
    if any(keyword in haystack for keyword in ["newsletter", "news", "inscreva", "assine"]):
        return "newsletter"
    if any(keyword in haystack for keyword in ["agend", "consulta", "reserva", "book"]):
        return "booking"
    if any(keyword in haystack for keyword in ["orcamento", "quote", "proposta"]):
        return "quote_request"
    if any(keyword in haystack for keyword in ["demo", "trial"]):
        return "demo_request"
    if any(keyword in haystack for keyword in ["login", "senha", "password"]):
        return "login"
    if any(keyword in haystack for keyword in ["busca", "search"]):
        return "search"
    if any(keyword in haystack for keyword in ["contato", "mensagem", "atendimento", "fale"]):
        return "contact"
    if any(field.field_type == "email" for field in fields):
        return "lead_capture"
    return "unknown"


def parse_site_artifacts(html: str, base_url: str) -> SiteArtifacts:
    parser = _SiteHTMLParser(base_url)
    parser.feed(html)
    parser.close()

    forms: list[SiteForm] = []
    for raw_form in parser.forms:
        fields = [SiteFormField.model_validate(field) for field in raw_form["fields"]]
        form = SiteForm(
            action=raw_form["action"],
            method=raw_form["method"],
            submit_text=_normalize_text(raw_form.get("submit_text")),
            fields=fields,
        )
        form.purpose = _infer_form_purpose(form.action, form.submit_text, form.fields)
        forms.append(form)

    primary_cta = identify_primary_cta(parser.cta_candidates)
    return SiteArtifacts(
        contacts=extract_contacts_from_html(html),
        forms=forms,
        primary_cta=primary_cta,
    )


def identify_primary_cta(candidates: list[dict]) -> SiteCTA | None:
    best_score = 0
    best_candidate: dict | None = None
    for candidate in candidates:
        text = _normalize_text(candidate.get("text"))
        if not text:
            continue
        lowered = text.lower()
        if lowered in _IGNORED_CTA_TEXTS:
            continue

        score = 1
        for keyword, weight in _CTA_KEYWORDS.items():
            if keyword in lowered:
                score += weight
        href = (candidate.get("href") or "").lower()
        if "whatsapp" in href or "wa.me" in href:
            score += 4
        if href.startswith("mailto:") or href.startswith("tel:"):
            score += 3
        if candidate.get("source") in {"button", "form_input"}:
            score += 2
        if len(text) <= 40:
            score += 1
        if candidate.get("order", 999) <= 12:
            score += 1
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if not best_candidate:
        return None

    confidence = min(round(best_score / 16, 2), 1.0)
    return SiteCTA(
        text=_normalize_text(best_candidate.get("text")),
        href=best_candidate.get("href"),
        source=best_candidate.get("source") or "unknown",
        confidence=confidence,
    )


def infer_digital_maturity(
    html: str,
    extracted_text: str,
    contacts: SiteContactInfo,
    forms: list[SiteForm],
    primary_cta: SiteCTA | None,
) -> DigitalMaturity:
    score = 10
    signals: list[str] = []
    lowered_html = html.lower()
    lowered_text = extracted_text.lower()

    if forms:
        score += 20
        signals.append(f"Site possui {len(forms)} formulario(s) de captura ou contato")
    if primary_cta and primary_cta.text:
        score += 10
        signals.append(f"CTA principal identificada: {primary_cta.text}")
    if contacts.whatsapp_numbers or contacts.whatsapp_links:
        score += 10
        signals.append("WhatsApp exposto como canal de contato")
    if len(contacts.emails) + len(contacts.phones) >= 2:
        score += 10
        signals.append("Multiplos canais de contato publicados")

    for stack_name, fingerprints in _MARKETING_STACKS.items():
        if any(fingerprint in lowered_html for fingerprint in fingerprints):
            score += 10
            signals.append(f"Sinal de stack digital detectado: {stack_name}")

    if any(keyword in lowered_html for keyword in ["calendly", "agenda", "booking", "booksy"]):
        score += 10
        signals.append("Ha sinais de agendamento digital")
    if any(keyword in lowered_html for keyword in ["intercom", "zendesk", "tawk", "crisp.chat"]):
        score += 10
        signals.append("Ha sinais de atendimento digital em tempo real")
    if any(keyword in lowered_text for keyword in ["crm", "automacao", "integracao", "portal do cliente"]):
        score += 5
        signals.append("Site comunica operacao digital mais estruturada")

    score = min(score, 100)
    if score >= 65:
        level = "high"
    elif score >= 35:
        level = "medium"
    else:
        level = "low"

    if not signals:
        signals.append("Poucos sinais tecnicos ou comerciais detectados no HTML publico")

    summary = f"Basic digital maturity inferred as {level} ({score}/100) based on public site signals."
    return DigitalMaturity(level=level, score=score, signals=signals[:6], summary=summary)


def categorize_pains(
    niche: str | None,
    extracted_text: str,
    contacts: SiteContactInfo,
    forms: list[SiteForm],
    primary_cta: SiteCTA | None,
    digital_maturity: DigitalMaturity,
) -> PainCategories:
    combined = f"{niche or ''} {extracted_text}".lower()
    categories = PainCategories()

    if contacts.whatsapp_numbers or contacts.whatsapp_links:
        _add_unique(categories.comercial, "Leads podem entrar via WhatsApp sem qualificacao e distribuicao padronizadas.")
        _add_unique(categories.atendimento, "O atendimento parece depender de conversas manuais em canais de mensagem.")
    if forms:
        _add_unique(categories.comercial, "Formularios publicos sugerem risco de resposta lenta sem automacao de follow-up.")
        _add_unique(categories.operacional, "A coleta de dados do site pode exigir repasse manual para o time interno.")
    else:
        _add_unique(categories.marketing, "O site nao mostra formulario claro de conversao, o que pode limitar a geracao de demanda.")

    if len(contacts.emails) + len(contacts.phones) >= 2:
        _add_unique(categories.atendimento, "Multiplos canais de contato podem fragmentar historico e SLA de atendimento.")

    if primary_cta and any(keyword in primary_cta.text.lower() for keyword in ["agend", "orc", "quote", "demo", "contato"]):
        _add_unique(categories.comercial, "A CTA principal pede acao comercial imediata, exigindo triagem e follow-up consistentes.")

    if any(keyword in combined for keyword in _SERVICE_FLOW_KEYWORDS):
        _add_unique(categories.operacional, "O negocio aparenta ter fluxo recorrente de agenda, pedidos ou solicitacoes que tende a gerar gargalos manuais.")

    if digital_maturity.level == "low":
        _add_unique(categories.marketing, "A presenca digital aparenta pouca mensuracao e baixa automacao de captura.")
    elif digital_maturity.level == "medium":
        _add_unique(categories.operacional, "Ha sinais digitais basicos, mas ainda com espaco para integrar processos ponta a ponta.")

    if not any(categories.model_dump().values()):
        _add_unique(categories.operacional, "Poucos sinais publicos foram encontrados, indicando oportunidade de diagnostico operacional mais detalhado.")

    return categories


def summarize_pains(categories: PainCategories) -> list[str]:
    ordered: list[str] = []
    for field_name in ["comercial", "operacional", "atendimento", "marketing"]:
        for item in getattr(categories, field_name):
            if item not in ordered:
                ordered.append(item)
    return ordered[:6]


def derive_automation_opportunities(
    categories: PainCategories,
    forms: list[SiteForm],
    contacts: SiteContactInfo,
    primary_cta: SiteCTA | None,
) -> list[str]:
    opportunities: list[str] = []

    if categories.comercial:
        opportunities.append("Captura, qualificacao e roteamento automatico de leads em CRM.")
    if categories.atendimento:
        opportunities.append("Atendimento omnichannel com SLA, fila e follow-up automatico.")
    if categories.operacional:
        opportunities.append("Automacao de agendamento, pedidos ou repasse interno entre equipes.")
    if categories.marketing:
        opportunities.append("Tracking de origem, nutricao e reativacao automatica de oportunidades.")

    if contacts.whatsapp_numbers or contacts.whatsapp_links:
        opportunities.append("Fluxo de WhatsApp para triagem, respostas iniciais e handoff comercial.")
    if any(form.purpose == "booking" for form in forms):
        opportunities.append("Confirmacao e lembretes automaticos para agendamentos.")
    elif any(form.purpose in {"contact", "quote_request", "lead_capture", "demo_request"} for form in forms):
        opportunities.append("Resposta automatica para formularios com enriquecimento e proximo passo.")
    if primary_cta and primary_cta.text:
        opportunities.append(f"Monitoramento e conversao da CTA principal '{primary_cta.text}'.")

    unique: list[str] = []
    for item in opportunities:
        if item not in unique:
            unique.append(item)
    return unique[:6]


def build_summary(
    company_name: str,
    niche: str | None,
    contacts: SiteContactInfo,
    forms: list[SiteForm],
    primary_cta: SiteCTA | None,
    digital_maturity: DigitalMaturity,
) -> str:
    channels: list[str] = []
    if contacts.emails:
        channels.append(f"{len(contacts.emails)} email(s)")
    if contacts.phones:
        channels.append(f"{len(contacts.phones)} phone number(s)")
    if contacts.whatsapp_numbers or contacts.whatsapp_links:
        channels.append("WhatsApp")
    channel_text = ", ".join(channels) if channels else "limited public contact channels"
    form_text = f"{len(forms)} form(s) detected" if forms else "no clear conversion form detected"
    cta_text = primary_cta.text if primary_cta and primary_cta.text else "direct contact"
    niche_text = niche or "the current niche"
    return (
        f"{company_name} appears to operate in {niche_text}. The site emphasizes '{cta_text}', publishes {channel_text}, "
        f"and shows {form_text}. Estimated digital maturity is {digital_maturity.level} ({digital_maturity.score}/100)."
    )


def suggest_offer(categories: PainCategories, primary_cta: SiteCTA | None, contacts: SiteContactInfo) -> str:
    if categories.comercial and (contacts.whatsapp_numbers or contacts.whatsapp_links):
        return "Diagnostico de captacao e follow-up com fluxo inicial de WhatsApp + CRM."
    if categories.operacional:
        return "Diagnostico operacional com automacao de intake, agenda e repasse interno."
    if categories.marketing:
        return "Sprint de captacao digital com formularios, tracking e automacoes de nutricao."
    cta_text = primary_cta.text if primary_cta and primary_cta.text else "atendimento"
    return f"Diagnostico rapido de automacao focado na jornada de {cta_text.lower()}."


def _extract_important_pages(html: str, base_url: str) -> list[ImportantPage]:
    candidates = [
        ("contact", "Contact page or contact intent"),
        ("contato", "Contact page or contact intent"),
        ("servic", "Services page"),
        ("solu", "Solutions page"),
        ("produto", "Products page"),
        ("sobre", "About page"),
        ("about", "About page"),
        ("orc", "Pricing or quote page"),
    ]
    pages: list[ImportantPage] = []
    for keyword, reason in candidates:
        if keyword in html.lower() and all(page.reason != reason for page in pages):
            pages.append(ImportantPage(title=reason, url=base_url, reason=reason))
    return pages[:6]


def _extract_service_signals(extracted_text: str) -> list[str]:
    chunks = re.split(r"[\n\.\|]", extracted_text)
    signals: list[str] = []
    for chunk in chunks:
        cleaned = _normalize_text(chunk)
        lowered = cleaned.lower()
        if len(cleaned) < 12:
            continue
        if any(token in lowered for token in ["servic", "produto", "solucao", "tratamento", "consultoria", "agendamento"]):
            if cleaned not in signals:
                signals.append(cleaned)
    return signals[:6]


def _build_confidence_notes(
    artifacts: SiteArtifacts,
    digital_maturity: DigitalMaturity,
    external_research: ResearchWorkflowResult | None,
) -> list[str]:
    notes: list[str] = []
    if artifacts.contacts.emails or artifacts.contacts.phones or artifacts.contacts.whatsapp_numbers:
        notes.append("Contact signals were extracted directly from the public HTML.")
    if artifacts.forms:
        notes.append("Form detection is based on actual HTML forms found on the page.")
    if digital_maturity.level == "low":
        notes.append("Digital maturity inference is heuristic and should be validated against operational context.")
    if external_research is None:
        notes.append("No external research enrichment was used for this analysis.")
    else:
        notes.append("External research enrichment was added through the research MCP flow.")
    return notes[:5]


def analyze_company_site(
    company_name: str,
    company_url: str,
    niche: str | None,
    html: str,
    extracted_text: str,
    usage: dict | None = None,
    external_research: ResearchWorkflowResult | None = None,
    external_research_mode: str | None = None,
) -> CompanyAnalysis:
    artifacts = parse_site_artifacts(html, company_url)
    artifacts.important_pages = _extract_important_pages(html, company_url)
    artifacts.service_signals = _extract_service_signals(extracted_text)
    digital_maturity = infer_digital_maturity(
        html=html,
        extracted_text=extracted_text,
        contacts=artifacts.contacts,
        forms=artifacts.forms,
        primary_cta=artifacts.primary_cta,
    )
    pain_categories = categorize_pains(
        niche=niche,
        extracted_text=extracted_text,
        contacts=artifacts.contacts,
        forms=artifacts.forms,
        primary_cta=artifacts.primary_cta,
        digital_maturity=digital_maturity,
    )
    likely_pains = summarize_pains(pain_categories)
    automation_opportunities = derive_automation_opportunities(
        categories=pain_categories,
        forms=artifacts.forms,
        contacts=artifacts.contacts,
        primary_cta=artifacts.primary_cta,
    )
    company_summary = build_summary(
        company_name=company_name,
        niche=niche,
        contacts=artifacts.contacts,
        forms=artifacts.forms,
        primary_cta=artifacts.primary_cta,
        digital_maturity=digital_maturity,
    )
    suggested_offer = suggest_offer(pain_categories, artifacts.primary_cta, artifacts.contacts)
    outreach = build_outreach(
        company_name=company_name,
        niche=niche or "nicho local",
        pain_summary=(likely_pains or ["atendimento e operacao comercial"])[0],
        solution_summary=(automation_opportunities or ["um fluxo de automacao sob medida"])[0],
    )
    confidence_notes = _build_confidence_notes(artifacts, digital_maturity, external_research)
    return build_company_analysis(
        company_name=company_name,
        company_url=company_url,
        niche=niche,
        summary=company_summary,
        likely_pains=likely_pains,
        automation_opportunities=automation_opportunities,
        suggested_offer=suggested_offer,
        contacts=artifacts.contacts,
        forms=artifacts.forms,
        primary_cta=artifacts.primary_cta,
        digital_maturity=digital_maturity,
        pain_categories=pain_categories,
        usage=usage or {},
        company_summary=company_summary,
        contact_points=artifacts.contacts,
        pain_points=likely_pains,
        offer=suggested_offer,
        outreach=outreach.model_dump(),
        confidence_notes=confidence_notes,
        important_pages=artifacts.important_pages,
        services_or_products=artifacts.service_signals,
        external_research=external_research,
        external_research_mode=external_research_mode,
    )


def score_niche_locally(niche: str) -> NicheScore:
    text = niche.lower()
    breakdown = defaultdict(int)
    reasoning: list[str] = []

    if any(word in text for word in ["clinica", "estetica", "imobili", "escritorio", "academia", "pet", "restaurante", "delivery"]):
        breakdown["service_operations"] += 20
        reasoning.append("The niche shows recurring service operations.")

    if any(word in text for word in ["whatsapp", "lead", "agendamento", "agenda", "atendimento", "crm"]):
        breakdown["lead_and_followup"] += 20
        reasoning.append("There are clear lead and follow-up signals that fit automation.")

    if any(word in text for word in ["manual", "planilha", "repetitivo", "cadastro", "cobranca", "relatorio"]):
        breakdown["manual_work"] += 20
        reasoning.append("Manual and repetitive work increases automation ROI.")

    if any(word in text for word in ["premium", "alto ticket", "particular", "b2b", "empresa", "consultorio"]):
        breakdown["ability_to_pay"] += 20
        reasoning.append("The niche appears able to pay for custom solutions.")

    if any(word in text for word in ["franquia", "cadeia", "rede", "escalavel"]):
        breakdown["upsell_and_scale"] += 20
        reasoning.append("There is room to replicate and scale the offer.")

    score = min(sum(breakdown.values()), 100)
    if not reasoning:
        reasoning.append("Not enough signals yet; this niche needs more validation before a strong automation offer.")
    if not breakdown:
        breakdown["generic"] = 35
    return NicheScore(niche=niche, score=score, breakdown=dict(breakdown), reasoning=reasoning)


def build_outreach(
    company_name: str,
    niche: str,
    pain_summary: str,
    solution_summary: str,
    channel: str = "whatsapp",
) -> OutreachDraft:
    channel = channel.lower().strip()
    if channel == "email":
        subject = f"Quick automation idea for {company_name}"
        message = (
            f"Hello,\n\n"
            f"I reviewed {company_name} in the {niche} space and noticed a likely opportunity around {pain_summary.lower()}.\n\n"
            f"A practical first step would be {solution_summary.lower()}, reducing manual work and speeding up response time.\n\n"
            f"If useful, I can outline the flow in a few minutes."
        )
        return OutreachDraft(channel=channel, subject=subject, message=message)

    message = (
        f"Oi! Dei uma olhada em {company_name} e vi uma oportunidade em {pain_summary.lower()}. "
        f"Daria para atacar isso com {solution_summary.lower()}, reduzindo atraso e retrabalho. "
        f"Se fizer sentido, eu te mando um desenho rapido do fluxo."
    )
    return OutreachDraft(channel=channel, message=message)


def build_company_analysis(
    company_name: str,
    company_url: str,
    niche: str | None,
    summary: str,
    likely_pains: list[str],
    automation_opportunities: list[str],
    suggested_offer: str,
    contacts: SiteContactInfo | None = None,
    forms: list[SiteForm] | None = None,
    primary_cta: SiteCTA | None = None,
    digital_maturity: DigitalMaturity | None = None,
    pain_categories: PainCategories | None = None,
    usage: dict | None = None,
    company_summary: str | None = None,
    contact_points: SiteContactInfo | None = None,
    pain_points: list[str] | None = None,
    offer: str | None = None,
    outreach: dict | None = None,
    confidence_notes: list[str] | None = None,
    important_pages: list[ImportantPage] | None = None,
    services_or_products: list[str] | None = None,
    external_research: ResearchWorkflowResult | None = None,
    external_research_mode: str | None = None,
) -> CompanyAnalysis:
    resolved_contacts = contacts or SiteContactInfo()
    resolved_pain_categories = pain_categories or PainCategories()
    return CompanyAnalysis(
        company_name=company_name,
        company_url=company_url,
        niche=niche,
        company_summary=company_summary or summary,
        contact_points=contact_points or resolved_contacts,
        digital_maturity=digital_maturity,
        pain_points=pain_points or likely_pains,
        pain_categories=resolved_pain_categories,
        automation_opportunities=automation_opportunities,
        offer=offer or suggested_offer,
        outreach=outreach or {},
        confidence_notes=confidence_notes or [],
        important_pages=important_pages or [],
        services_or_products=services_or_products or [],
        primary_cta=primary_cta,
        forms=forms or [],
        external_research=external_research,
        external_research_used=external_research is not None,
        external_research_mode=external_research_mode,
        external_research_search_calls=(external_research.search_calls if external_research is not None else 0),
        external_research_cost_usd=((external_research.usage or {}).get("execution_cost_usd") if external_research is not None else None),
        usage=usage or {},
        summary=summary,
        likely_pains=likely_pains,
        suggested_offer=suggested_offer,
        contacts=resolved_contacts,
    )





def _normalize_urgency(urgency_level: str) -> str:
    value = urgency_level.strip().lower()
    aliases = {
        "alta": "high",
        "alto": "high",
        "high": "high",
        "urgente": "high",
        "media": "medium",
        "medio": "medium",
        "moderada": "medium",
        "medium": "medium",
        "baixa": "low",
        "baixo": "low",
        "low": "low",
    }
    return aliases.get(value, "medium")


def _offer_promise(niche: str, pain: str, solution: str, urgency_level: str) -> str:
    if urgency_level == "high":
        return f"Implantar rapidamente um fluxo para atacar {pain.lower()} em {niche}, usando {solution.lower()} sem depender de um projeto longo."
    if urgency_level == "low":
        return f"Estruturar uma base comercial e operacional mais previsivel em {niche}, resolvendo {pain.lower()} com {solution.lower()} de forma escalavel."
    return f"Reduzir {pain.lower()} em {niche} com {solution.lower()}, criando uma operacao mais rapida, previsivel e facil de escalar."


def _offer_deliverables(solution: str, urgency_level: str) -> list[str]:
    deliverables = [
        f"Diagnostico comercial e operacional focado em {solution.lower()}.",
        "Mapa do fluxo atual, gargalos e pontos de perda de tempo ou receita.",
        f"Desenho do fluxo futuro com {solution.lower()} e criterios claros de handoff.",
        "Implementacao de MVP com automacoes, mensagens e regras iniciais.",
        "Ritual de acompanhamento com ajustes nas primeiras semanas.",
    ]
    if urgency_level == "high":
        deliverables.insert(1, "Plano de go-live acelerado com priorizacao do que entra em producao primeiro.")
    elif urgency_level == "low":
        deliverables.append("Roadmap de segunda fase para expandir a automacao apos o MVP.")
    return deliverables[:6]


def _offer_objections(desired_ticket: str, urgency_level: str) -> list[str]:
    objections = [
        f"Nao sei se um ticket de {desired_ticket} se paga no meu contexto.",
        "Meu time ja esta sobrecarregado e pode resistir a mudar o processo.",
        "Ja tentamos algo parecido e nao deu resultado consistente.",
        "Preciso garantir que a operacao nao vai parar durante a implantacao.",
    ]
    if urgency_level == "high":
        objections[3] = "Preciso de resultado rapido e tenho receio de um projeto que demore para entrar no ar."
    return objections


def _offer_roi_argument(pain: str, solution: str, desired_ticket: str, urgency_level: str) -> str:
    speed = "em poucas semanas" if urgency_level == "high" else "ao longo dos primeiros ciclos"
    return (
        f"Se {pain.lower()} hoje consome horas do time, atrasa resposta ou faz oportunidades escaparem, {solution.lower()} tende a se pagar {speed}. "
        f"Na pratica, bastam alguns atendimentos recuperados, menos retrabalho ou um ganho pequeno de conversao para justificar um ticket de {desired_ticket}."
    )


def _offer_final_cta(urgency_level: str) -> str:
    if urgency_level == "high":
        return "Se fizer sentido, marcamos 20 minutos ainda hoje ou amanha para eu te mostrar um plano de implantacao enxuto."
    if urgency_level == "low":
        return "Se quiser, marcamos uma call de discovery sem compromisso para mapear prioridade, escopo e melhor momento de implantacao."
    return "Se fizer sentido, marcamos uma call de discovery de 20 minutos nesta semana para validar escopo, ROI e proximo passo."


def _offer_channel_versions(
    niche: str,
    pain: str,
    solution: str,
    desired_ticket: str,
    promise: str,
    roi_argument: str,
    final_cta: str,
) -> OfferChannelVariants:
    whatsapp = (
        f"Oi! Vi uma oportunidade clara em {niche}: {pain.lower()}. "
        f"Minha proposta seria {promise.lower()} "
        f"A ideia e usar {solution.lower()} para criar retorno sobre um ticket de {desired_ticket}. "
        f"{final_cta}"
    )
    email_subject = f"Proposta de automacao para atacar {pain.lower()} em {niche}"
    email_body = (
        f"Ola,\n\n"
        f"Montei uma proposta comercial enxuta para atacar {pain.lower()} em {niche}.\n\n"
        f"Promessa central: {promise}\n\n"
        f"Argumento de ROI: {roi_argument}\n\n"
        f"Ticket alvo: {desired_ticket}.\n\n"
        f"{final_cta}"
    )
    discovery_call = (
        f"Abertura sugerida: hoje eu quero entender como {pain.lower()} impacta sua operacao, validar se {solution.lower()} faz sentido e medir se um projeto na faixa de {desired_ticket} fecha conta. "
        f"Se houver aderencia, eu te mostro um plano inicial e proximos passos."
    )
    return OfferChannelVariants(
        whatsapp=whatsapp,
        email_subject=email_subject,
        email_body=email_body,
        discovery_call=discovery_call,
    )


def build_commercial_offer(
    niche: str,
    pain: str,
    solution: str,
    desired_ticket: str,
    urgency_level: str,
) -> CommercialOffer:
    normalized_urgency = _normalize_urgency(urgency_level)
    promise = _offer_promise(niche, pain, solution, normalized_urgency)
    deliverables = _offer_deliverables(solution, normalized_urgency)
    probable_objections = _offer_objections(desired_ticket, normalized_urgency)
    roi_argument = _offer_roi_argument(pain, solution, desired_ticket, normalized_urgency)
    final_cta = _offer_final_cta(normalized_urgency)
    channel_versions = _offer_channel_versions(
        niche=niche,
        pain=pain,
        solution=solution,
        desired_ticket=desired_ticket,
        promise=promise,
        roi_argument=roi_argument,
        final_cta=final_cta,
    )
    return CommercialOffer(
        niche=niche,
        pain=pain,
        solution=solution,
        desired_ticket=desired_ticket,
        urgency_level=normalized_urgency,
        promise=promise,
        deliverables=deliverables,
        probable_objections=probable_objections,
        roi_argument=roi_argument,
        final_cta=final_cta,
        channel_versions=channel_versions,
    )






