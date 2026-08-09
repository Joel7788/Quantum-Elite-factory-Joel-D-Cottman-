import hcl2
import pytest

from conftest import REPO_ROOT

HUNTOR_TF = REPO_ROOT / "Quantum_Huntor.tf"


def unquote(value):
    return value.strip('"') if isinstance(value, str) else value


@pytest.fixture(scope="module")
def base44_core():
    config = hcl2.loads(HUNTOR_TF.read_text())
    resources = config["resource"]
    assert len(resources) == 1
    return resources[0]['"quantum_system"']['"base44_core"']


def test_config_is_valid_hcl(base44_core):
    assert unquote(base44_core["name"]) == "Quantum-Elite-Factory-Joel-Cottman"


def test_replication_is_positive_integer(base44_core):
    assert isinstance(base44_core["replication"], int)
    assert base44_core["replication"] > 0


def test_declared_capabilities(base44_core):
    assert [unquote(c) for c in base44_core["capabilities"]] == [
        "self_healing",
        "autonomous_expansion",
        "neon_logic",
    ]


def test_nested_config_block(base44_core):
    block = base44_core["config"][0]
    assert unquote(block["predictive_engine"]) == "Neural_Smelter_v9"
    assert unquote(block["speaker_layer"]) == "Decentralized_Nostr_Bridge"
