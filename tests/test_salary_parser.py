"""Tests for salary extraction and normalization."""

from core.salary_parser import parse_salary


class TestParseSalaryUSD:
    def test_range_with_dollar_sign(self):
        result = parse_salary("$80,000 - $120,000")
        assert result == {"min": 80000, "max": 120000, "currency": "USD"}

    def test_range_with_k_shorthand(self):
        result = parse_salary("$80k - $120k")
        assert result == {"min": 80000, "max": 120000, "currency": "USD"}

    def test_single_value(self):
        result = parse_salary("$100,000/year")
        assert result == {"min": 100000, "max": 100000, "currency": "USD"}

    def test_usd_prefix(self):
        result = parse_salary("USD 50000-60000")
        assert result == {"min": 50000, "max": 60000, "currency": "USD"}

    def test_range_no_spaces(self):
        result = parse_salary("$70000-$90000")
        assert result == {"min": 70000, "max": 90000, "currency": "USD"}


class TestParseSalaryOtherCurrencies:
    def test_eur(self):
        result = parse_salary("EUR 50k-70k")
        assert result == {"min": 50000, "max": 70000, "currency": "EUR"}

    def test_euro_sign(self):
        result = parse_salary("€50,000 - €70,000")
        assert result == {"min": 50000, "max": 70000, "currency": "EUR"}

    def test_gbp(self):
        result = parse_salary("£45,000/year")
        assert result == {"min": 45000, "max": 45000, "currency": "GBP"}

    def test_gbp_range(self):
        result = parse_salary("GBP 40,000 - 60,000")
        assert result == {"min": 40000, "max": 60000, "currency": "GBP"}


class TestParseSalaryPeriodConversion:
    def test_monthly_to_yearly(self):
        result = parse_salary("EGP 15,000 - 25,000/month")
        assert result == {"min": 180000, "max": 300000, "currency": "EGP"}

    def test_hourly_to_yearly(self):
        result = parse_salary("$50/hour")
        assert result == {"min": 104000, "max": 104000, "currency": "USD"}

    def test_hourly_range(self):
        result = parse_salary("$40 - $60/hr")
        assert result == {"min": 83200, "max": 124800, "currency": "USD"}


class TestParseSalaryEdgeCases:
    def test_empty_string(self):
        assert parse_salary("") is None

    def test_no_salary(self):
        assert parse_salary("Competitive") is None

    def test_none_input(self):
        assert parse_salary(None) is None

    def test_unparseable(self):
        assert parse_salary("Great benefits package") is None

    def test_sar_currency(self):
        result = parse_salary("SAR 10,000 - 15,000/month")
        assert result == {"min": 120000, "max": 180000, "currency": "SAR"}
