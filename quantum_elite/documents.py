"""Document automation: contracts, assignments, addendums, closing packages.

Templates are ``string.Template`` files under ``templates/``. Rendering is
strict: a missing or unused placeholder raises rather than silently producing a
malformed legal document.

These templates are drafts for operator review. They are not legal advice and
must be reviewed by a licensed attorney in the transaction's jurisdiction
before use, and nothing here signs or executes a document on anyone's behalf.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from string import Template

from .models import Assignment, DealPacket, Lead, Offer, Underwriting

TEMPLATE_DIR = Path(__file__).parent / "templates"

# Legal entity metadata auto-populated into every generated document.
LEGAL_NAME = "Joel Cottman-Boyer"
OPERATOR_NAME = "JOEL D COTTMAN"
ENTITY_ROLE = "Buyer/Assignor"

PLACEHOLDER_RE = re.compile(r"\$\{(\w+)\}")

PURCHASE_AGREEMENT = "purchase_agreement"
ASSIGNMENT_AGREEMENT = "assignment_agreement"
INSPECTION_ADDENDUM = "inspection_addendum"
CLOSING_PACKAGE = "closing_package"


class DocumentError(ValueError):
    """Raised when a template cannot be rendered exactly."""


@dataclass(frozen=True)
class RenderedDocument:
    name: str
    body: str


def money(value: Decimal) -> str:
    """Format money as it must appear in a contract: ``$1,234.56``."""
    return f"${value:,.2f}"


def template_path(name: str) -> Path:
    path = TEMPLATE_DIR / f"{name}.txt"
    if not path.is_file():
        raise DocumentError(f"unknown document template: {name}")
    return path


def required_placeholders(name: str) -> frozenset[str]:
    return frozenset(PLACEHOLDER_RE.findall(template_path(name).read_text()))


def render(name: str, context: dict[str, str]) -> RenderedDocument:
    """Render a template, rejecting both missing and unused context keys."""
    required = required_placeholders(name)
    provided = frozenset(context)
    if missing := required - provided:
        raise DocumentError(f"{name} is missing context: {sorted(missing)}")
    if unused := provided - required:
        raise DocumentError(f"{name} received unused context: {sorted(unused)}")
    body = Template(template_path(name).read_text()).substitute(context)
    return RenderedDocument(name=name, body=body)


def _party_context(lead: Lead) -> dict[str, str]:
    contact = lead.best_contact
    return {
        "seller_name": lead.owner_name,
        "seller_phone": (contact.phone if contact and contact.phone else "on file"),
        "seller_email": (contact.email if contact and contact.email else "on file"),
        "buyer_legal_name": LEGAL_NAME,
        "buyer_role": ENTITY_ROLE,
        "operator_name": OPERATOR_NAME,
        "property_address": lead.address.one_line,
    }


def purchase_agreement_context(lead: Lead, offer: Offer, as_of: date) -> dict[str, str]:
    return {
        **_party_context(lead),
        "agreement_date": as_of.isoformat(),
        "purchase_price": money(offer.amount),
        "earnest_money": money(offer.earnest_money),
        "inspection_days": str(offer.inspection_days),
        "closing_date": (as_of + timedelta(days=offer.close_days)).isoformat(),
        "offer_expires_on": offer.expires_on.isoformat(),
    }


def assignment_agreement_context(
    lead: Lead, offer: Offer, assignment: Assignment, as_of: date
) -> dict[str, str]:
    return {
        **_party_context(lead),
        "agreement_date": as_of.isoformat(),
        "assignee_name": assignment.buyer.name,
        "assignee_id": assignment.buyer.buyer_id,
        "purchase_price": money(offer.amount),
        "assignment_fee": money(assignment.fee),
        "total_to_assignee": money(offer.amount + assignment.fee),
        "closing_date": (as_of + timedelta(days=assignment.buyer.close_days)).isoformat(),
    }


def inspection_addendum_context(lead: Lead, offer: Offer, as_of: date) -> dict[str, str]:
    return {
        **_party_context(lead),
        "agreement_date": as_of.isoformat(),
        "inspection_days": str(offer.inspection_days),
        "inspection_deadline": (as_of + timedelta(days=offer.inspection_days)).isoformat(),
    }


def closing_package_context(
    lead: Lead,
    offer: Offer,
    assignment: Assignment,
    underwriting: Underwriting,
    as_of: date,
) -> dict[str, str]:
    return {
        **_party_context(lead),
        "agreement_date": as_of.isoformat(),
        "assignee_name": assignment.buyer.name,
        "purchase_price": money(offer.amount),
        "assignment_fee": money(assignment.fee),
        "arv": money(underwriting.arv),
        "repair_estimate": money(underwriting.repair_estimate),
        "closing_date": (as_of + timedelta(days=assignment.buyer.close_days)).isoformat(),
    }


def generate_documents(packet: DealPacket, as_of: date | None = None) -> dict[str, str]:
    """Render every document the packet's current state supports."""
    as_of = as_of or date.today()
    lead = packet.lead
    if packet.offer is None:
        raise DocumentError(f"lead {lead.lead_id} has no offer; nothing to paper")

    documents = {
        PURCHASE_AGREEMENT: render(
            PURCHASE_AGREEMENT, purchase_agreement_context(lead, packet.offer, as_of)
        ).body,
        INSPECTION_ADDENDUM: render(
            INSPECTION_ADDENDUM, inspection_addendum_context(lead, packet.offer, as_of)
        ).body,
    }

    if packet.assignment is not None:
        documents[ASSIGNMENT_AGREEMENT] = render(
            ASSIGNMENT_AGREEMENT,
            assignment_agreement_context(lead, packet.offer, packet.assignment, as_of),
        ).body
        if lead.underwriting is not None:
            documents[CLOSING_PACKAGE] = render(
                CLOSING_PACKAGE,
                closing_package_context(
                    lead, packet.offer, packet.assignment, lead.underwriting, as_of
                ),
            ).body
    return documents


def write_documents(documents: dict[str, str], out_dir: Path, lead_id: str) -> tuple[Path, ...]:
    """Persist rendered documents as ``<out_dir>/<lead_id>/<name>.txt``."""
    target = Path(out_dir) / lead_id
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name, body in sorted(documents.items()):
        path = target / f"{name}.txt"
        path.write_text(body)
        written.append(path)
    return tuple(written)
