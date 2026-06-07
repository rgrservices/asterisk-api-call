"""Testes unitários para validação e normalização de telefone (app/phone.py)."""
import pytest

from app.phone import normalize_e164_input, to_trunk_dial_string, validate_e164


class TestNormalizeE164:
    def test_strips_plus(self):
        assert normalize_e164_input("+5511999999999") == "5511999999999"

    def test_strips_spaces(self):
        assert normalize_e164_input("55 11 999999999") == "5511999999999"

    def test_plain_digits(self):
        assert normalize_e164_input("5511999999999") == "5511999999999"

    def test_non_digits_raises(self):
        with pytest.raises(ValueError, match="only digits"):
            normalize_e164_input("+55abc")


class TestValidateE164:
    def test_valid_mobile_br(self):
        validate_e164("5511999999999")

    def test_valid_landline_br(self):
        validate_e164("551133334444")

    def test_too_short_raises(self):
        with pytest.raises(ValueError):
            validate_e164("551")

    def test_leading_zero_raises(self):
        with pytest.raises(ValueError):
            validate_e164("0551199999999")


class TestToTrunkDialString:
    def test_valid_br_mobile(self):
        result = to_trunk_dial_string("5511999999999", "2002")
        assert result == "200211999999999"

    def test_valid_br_landline(self):
        result = to_trunk_dial_string("551133334444", "9000")
        assert result == "90001133334444"

    def test_non_br_raises(self):
        with pytest.raises(ValueError, match="55"):
            to_trunk_dial_string("14155551234", "2002")

    def test_invalid_prefix_raises(self):
        with pytest.raises(ValueError, match="4 digits"):
            to_trunk_dial_string("5511999999999", "20")
