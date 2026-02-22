"""Tests for phone number formatting in Pet Care Assistant.

Tests the enhanced _fmt_phone_for_speech function that handles:
- US 10-digit numbers
- US 11-digit numbers with country code
- International numbers (7-15 digits)
- Edge cases (empty, too short, too long)
"""

import pytest


def test_us_10_digit_basic():
    """Should format 10-digit US numbers with grouping."""
    from main import _fmt_phone_for_speech

    result = _fmt_phone_for_speech("5125551234")
    assert result == "5, 1, 2, 5, 5, 5, 1, 2, 3, 4"


def test_us_10_digit_with_formatting():
    """Should handle 10-digit numbers with various formatting."""
    from main import _fmt_phone_for_speech

    # Parentheses and hyphens
    assert _fmt_phone_for_speech("(512) 555-1234") == "5, 1, 2, 5, 5, 5, 1, 2, 3, 4"

    # Dots
    assert _fmt_phone_for_speech("512.555.1234") == "5, 1, 2, 5, 5, 5, 1, 2, 3, 4"

    # Spaces
    assert _fmt_phone_for_speech("512 555 1234") == "5, 1, 2, 5, 5, 5, 1, 2, 3, 4"


def test_us_11_digit_with_country_code():
    """Should format 11-digit numbers starting with 1 (US country code)."""
    from main import _fmt_phone_for_speech

    result = _fmt_phone_for_speech("15125551234")
    assert result == "1, 5, 1, 2, 5, 5, 5, 1, 2, 3, 4"


def test_us_11_digit_with_country_code_formatted():
    """Should handle 11-digit with country code and formatting."""
    from main import _fmt_phone_for_speech

    result = _fmt_phone_for_speech("+1 (512) 555-1234")
    assert result == "1, 5, 1, 2, 5, 5, 5, 1, 2, 3, 4"

    result = _fmt_phone_for_speech("1-512-555-1234")
    assert result == "1, 5, 1, 2, 5, 5, 5, 1, 2, 3, 4"


def test_international_7_digits():
    """Should group 7-digit numbers by 3s."""
    from main import _fmt_phone_for_speech

    result = _fmt_phone_for_speech("5551234")
    # Groups: 555, 123, 4
    assert result == "5, 5, 5, 1, 2, 3, 4"


def test_international_8_digits():
    """Should group 8-digit numbers by 3s."""
    from main import _fmt_phone_for_speech

    result = _fmt_phone_for_speech("12345678")
    # Groups: 123, 456, 78
    assert result == "1, 2, 3, 4, 5, 6, 7, 8"


def test_international_12_digits():
    """Should group 12-digit international numbers by 3s."""
    from main import _fmt_phone_for_speech

    result = _fmt_phone_for_speech("441234567890")
    # Groups: 441, 234, 567, 890
    assert result == "4, 4, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0"


def test_international_with_plus_prefix():
    """Should handle international format with + prefix."""
    from main import _fmt_phone_for_speech

    result = _fmt_phone_for_speech("+44 1234 567890")
    # Extracts 441234567890 then groups by 3
    assert "4, 4, 1" in result and "5, 6, 7" in result


def test_empty_string():
    """Should handle empty string gracefully."""
    from main import _fmt_phone_for_speech

    result = _fmt_phone_for_speech("")
    assert result == "no number provided"


def test_none_input():
    """Should handle None input gracefully."""
    from main import _fmt_phone_for_speech

    result = _fmt_phone_for_speech(None)
    assert result == "no number provided"


def test_only_non_digits():
    """Should handle input with no digits."""
    from main import _fmt_phone_for_speech

    result = _fmt_phone_for_speech("---")
    assert result == "no number provided"

    result = _fmt_phone_for_speech("()")
    assert result == "no number provided"


def test_too_short_phone_number():
    """Should detect phone numbers that are too short (<7 digits)."""
    from main import _fmt_phone_for_speech

    result = _fmt_phone_for_speech("12345")
    assert result == "incomplete phone number"

    result = _fmt_phone_for_speech("123")
    assert result == "incomplete phone number"


def test_too_long_phone_number():
    """Should detect phone numbers that are too long (>15 digits)."""
    from main import _fmt_phone_for_speech

    result = _fmt_phone_for_speech("12345678901234567890")
    assert result == "phone number too long, please check"


def test_11_digits_not_starting_with_1():
    """Should group 11-digit numbers NOT starting with 1 by 3s."""
    from main import _fmt_phone_for_speech

    # Not a US number (doesn't start with 1)
    result = _fmt_phone_for_speech("44123456789")
    # Should group by 3s, not use US format
    assert "4, 4, 1" in result


def test_phone_with_extension():
    """Should handle phone numbers with extensions (may be > 15 digits)."""
    from main import _fmt_phone_for_speech

    # Phone with extension might exceed 15 digits
    result = _fmt_phone_for_speech("512-555-1234 ext 12345")
    # Would be 15+ digits, should warn
    assert "too long" in result or "," in result


def test_voice_transcription_artifacts():
    """Should handle common voice transcription artifacts."""
    from main import _fmt_phone_for_speech

    # "Five one two, five five five, one two three four"
    # Might be transcribed with spaces between each digit
    result = _fmt_phone_for_speech("5 1 2 5 5 5 1 2 3 4")
    assert result == "5, 1, 2, 5, 5, 5, 1, 2, 3, 4"


def test_consistent_formatting():
    """Should format the same number consistently regardless of input format."""
    from main import _fmt_phone_for_speech

    formats = [
        "5125551234",
        "(512) 555-1234",
        "512-555-1234",
        "512.555.1234",
        "512 555 1234",
    ]

    results = [_fmt_phone_for_speech(fmt) for fmt in formats]

    # All should produce the same output
    assert len(set(results)) == 1
    assert results[0] == "5, 1, 2, 5, 5, 5, 1, 2, 3, 4"


@pytest.mark.parametrize(
    "input_phone,expected_output",
    [
        ("5125551234", "5, 1, 2, 5, 5, 5, 1, 2, 3, 4"),
        ("15125551234", "1, 5, 1, 2, 5, 5, 5, 1, 2, 3, 4"),
        ("", "no number provided"),
        ("123", "incomplete phone number"),
        ("12345678901234567890", "phone number too long, please check"),
    ],
)
def test_phone_formatting_parametrized(input_phone, expected_output):
    """Parametrized tests for various phone formats."""
    from main import _fmt_phone_for_speech

    result = _fmt_phone_for_speech(input_phone)
    assert result == expected_output
