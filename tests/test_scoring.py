from decimal import Decimal

from conftest import make_contact, make_lead

from quantum_elite import scoring
from quantum_elite.models import DistressSignal


def test_engine_version_is_reported():
    assert scoring.explain(make_lead()).engine_version == "Neural_Smelter_v9"


def test_score_sums_signal_weights():
    lead = make_lead(
        signals=(DistressSignal.PRE_FORECLOSURE, DistressSignal.TAX_DELINQUENT),
        days_on_market=None,
    )
    assert scoring.score_lead(lead) == Decimal("0.5000")


def test_duplicate_signals_are_counted_once():
    lead = make_lead(
        signals=(DistressSignal.PROBATE, DistressSignal.PROBATE),
        days_on_market=None,
    )
    breakdown = scoring.explain(lead)
    assert [c.label for c in breakdown.components] == ["probate"]
    assert breakdown.score == Decimal("0.1800")


def test_score_is_clamped_to_one():
    lead = make_lead(signals=tuple(DistressSignal), days_on_market=365)
    assert scoring.score_lead(lead) == Decimal("1.0000")


def test_days_on_market_weight_ramps_then_saturates():
    assert scoring.days_on_market_weight(None) == Decimal("0")
    assert scoring.days_on_market_weight(0) == Decimal("0")
    assert scoring.days_on_market_weight(-5) == Decimal("0")
    assert scoring.days_on_market_weight(90) == Decimal("0.0750")
    assert scoring.days_on_market_weight(180) == scoring.DOM_MAX_WEIGHT
    assert scoring.days_on_market_weight(9000) == scoring.DOM_MAX_WEIGHT


def test_reachable_contact_adds_confidence_weighted_component():
    lead = make_lead(signals=(), days_on_market=None, contacts=(make_contact(confidence="0.8"),))
    breakdown = scoring.explain(lead)
    assert [c.label for c in breakdown.components] == ["reachable_contact"]
    assert breakdown.score == Decimal("0.0400")


def test_unreachable_contact_adds_nothing():
    lead = make_lead(
        signals=(),
        days_on_market=None,
        contacts=(make_contact(phone=None, email=None),),
    )
    assert scoring.explain(lead).components == ()
    assert scoring.score_lead(lead) == Decimal("0.0000")


def test_bands_follow_thresholds():
    def band(signals):
        return scoring.explain(make_lead(signals=signals, days_on_market=None)).band

    assert band((DistressSignal.PRE_FORECLOSURE, DistressSignal.TAX_DELINQUENT,
                 DistressSignal.PROBATE)) == "hot"
    assert band((DistressSignal.PRE_FORECLOSURE, DistressSignal.CODE_VIOLATION)) == "warm"
    assert band((DistressSignal.EXPIRED_LISTING,)) == "cold"


def test_components_are_attributable_to_every_input():
    lead = make_lead(
        signals=(DistressSignal.VACANT, DistressSignal.DIVORCE),
        days_on_market=60,
        contacts=(make_contact(),),
    )
    breakdown = scoring.explain(lead)
    assert [c.label for c in breakdown.components] == [
        "vacant",
        "divorce",
        "days_on_market",
        "reachable_contact",
    ]
    assert sum((c.weight for c in breakdown.components), Decimal("0")) == breakdown.score
