from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import AS_OF, make_buyer, make_contact, make_lead, make_property

from quantum_elite import documents as docs
from quantum_elite import underwriting as uw
from quantum_elite.models import Assignment, DealPacket, Offer

ALL_TEMPLATES = (
    docs.PURCHASE_AGREEMENT,
    docs.ASSIGNMENT_AGREEMENT,
    docs.INSPECTION_ADDENDUM,
    docs.CLOSING_PACKAGE,
)


def build_packet(with_assignment=True, with_underwriting=True):
    lead = make_lead(contacts=(make_contact(email="marcus@example.com"),))
    lead.property_data = make_property()
    if with_underwriting:
        lead.underwriting = uw.underwrite(lead.property_data, as_of=AS_OF)
    offer = Offer(
        lead_id=lead.lead_id,
        amount=Decimal("116512"),
        earnest_money=Decimal("1165.12"),
        inspection_days=10,
        close_days=21,
        expires_on=AS_OF + timedelta(days=7),
    )
    assignment = (
        Assignment(buyer=make_buyer(name="Harborline Capital"), fee=Decimal("10000"),
                   match_score=Decimal("0.9"))
        if with_assignment
        else None
    )
    return DealPacket(lead=lead, offer=offer, assignment=assignment)


def test_money_formatting():
    assert docs.money(Decimal("1234.5")) == "$1,234.50"


def test_template_path_rejects_unknown_template():
    with pytest.raises(docs.DocumentError, match="unknown document template"):
        docs.template_path("nonexistent")


@pytest.mark.parametrize("name", ALL_TEMPLATES)
def test_every_template_has_placeholders(name):
    assert docs.required_placeholders(name)


def test_render_rejects_missing_context():
    with pytest.raises(docs.DocumentError, match="missing context"):
        docs.render(docs.PURCHASE_AGREEMENT, {})


def test_render_rejects_unused_context():
    packet = build_packet()
    context = docs.purchase_agreement_context(packet.lead, packet.offer, AS_OF)
    with pytest.raises(docs.DocumentError, match="unused context"):
        docs.render(docs.PURCHASE_AGREEMENT, {**context, "stray": "value"})


@pytest.mark.parametrize("name", ALL_TEMPLATES)
def test_rendered_documents_have_no_unsubstituted_placeholders(name):
    generated = docs.generate_documents(build_packet(), as_of=AS_OF)
    assert "${" not in generated[name]


def test_legal_metadata_is_auto_populated():
    generated = docs.generate_documents(build_packet(), as_of=AS_OF)
    for body in generated.values():
        assert docs.LEGAL_NAME in body
    assignment = generated[docs.ASSIGNMENT_AGREEMENT]
    assert "Harborline Capital" in assignment
    assert "$116,512.00" in assignment
    assert "$10,000.00" in assignment


def test_documents_are_drafts_pending_attorney_review():
    for body in docs.generate_documents(build_packet(), as_of=AS_OF).values():
        assert "attorney" in body.lower()


def test_contact_details_fall_back_when_unknown():
    packet = build_packet()
    packet.lead.contacts = ()
    body = docs.generate_documents(packet, as_of=AS_OF)[docs.PURCHASE_AGREEMENT]
    assert "on file" in body


def test_acquisition_only_packet_papers_two_documents():
    generated = docs.generate_documents(build_packet(with_assignment=False), as_of=AS_OF)
    assert set(generated) == {docs.PURCHASE_AGREEMENT, docs.INSPECTION_ADDENDUM}


def test_assignment_without_underwriting_skips_closing_package():
    generated = docs.generate_documents(
        build_packet(with_underwriting=False), as_of=AS_OF
    )
    assert docs.CLOSING_PACKAGE not in generated
    assert docs.ASSIGNMENT_AGREEMENT in generated


def test_generate_documents_requires_an_offer():
    packet = DealPacket(lead=make_lead())
    with pytest.raises(docs.DocumentError, match="nothing to paper"):
        docs.generate_documents(packet)


def test_generate_documents_defaults_to_today():
    generated = docs.generate_documents(build_packet())
    assert date.today().isoformat() in generated[docs.PURCHASE_AGREEMENT]


def test_deadlines_are_derived_from_the_agreement_date():
    packet = build_packet()
    context = docs.inspection_addendum_context(packet.lead, packet.offer, AS_OF)
    assert context["inspection_deadline"] == (AS_OF + timedelta(days=10)).isoformat()


def test_write_documents_lays_out_files_per_lead(tmp_path):
    generated = docs.generate_documents(build_packet(), as_of=AS_OF)
    written = docs.write_documents(generated, tmp_path, "QE-TEST")
    assert [path.name for path in written] == [
        "assignment_agreement.txt",
        "closing_package.txt",
        "inspection_addendum.txt",
        "purchase_agreement.txt",
    ]
    assert all(path.parent.name == "QE-TEST" for path in written)
    assert written[0].read_text() == generated[docs.ASSIGNMENT_AGREEMENT]


@pytest.mark.parametrize("lead_id", ["../escape", "a/b", "", "..", "lead\x00id"])
def test_write_documents_rejects_unsafe_lead_ids(tmp_path, lead_id):
    generated = docs.generate_documents(build_packet(), as_of=AS_OF)
    with pytest.raises(docs.DocumentError, match="unsafe lead_id"):
        docs.write_documents(generated, tmp_path, lead_id)
    assert list(tmp_path.iterdir()) == []
