from tests.identifier_check import _sequence_fields


def test_ngn_explicit_optional_wbs_is_not_synthesized():
    fields = {"wbs": {"required": False, "cleaning": {"strategy": "NEAREST_VALID_ABOVE_APPEND_SEQUENCE"}}}
    assert _sequence_fields(fields) == {}


def test_required_wbs_keeps_existing_family_repair():
    fields = {"wbs": {"required": True, "cleaning": {"strategy": "NEAREST_VALID_ABOVE_APPEND_SEQUENCE"}}}
    assert "wbs" in _sequence_fields(fields)


def test_other_optional_sequence_fields_keep_their_explicit_policy():
    fields = {"code": {"required": False, "cleaning": {"strategy": "NEAREST_VALID_ABOVE_APPEND_SEQUENCE"}}}
    assert "code" in _sequence_fields(fields)
