"""Tests for country detection from location strings."""

from core.country_detector import detect_country


class TestCountryDetection:
    def test_egypt_english(self):
        assert detect_country("Cairo, Egypt") == "EG"

    def test_egypt_arabic(self):
        assert detect_country("القاهرة، مصر") == "EG"

    def test_egypt_city(self):
        assert detect_country("Alexandria") == "EG"

    def test_saudi_english(self):
        assert detect_country("Riyadh, Saudi Arabia") == "SA"

    def test_saudi_arabic(self):
        assert detect_country("الرياض") == "SA"

    def test_saudi_ksa(self):
        assert detect_country("Jeddah, KSA") == "SA"

    def test_us(self):
        assert detect_country("San Francisco, CA, United States") == "US"

    def test_us_short(self):
        assert detect_country("New York, USA") == "US"

    def test_uk(self):
        assert detect_country("London, United Kingdom") == "GB"

    def test_uk_short(self):
        assert detect_country("Manchester, UK") == "GB"

    def test_germany(self):
        assert detect_country("Berlin, Germany") == "DE"

    def test_remote(self):
        assert detect_country("Remote") == ""

    def test_anywhere(self):
        assert detect_country("Anywhere") == ""

    def test_empty(self):
        assert detect_country("") == ""

    def test_none(self):
        assert detect_country(None) == ""

    def test_canada(self):
        assert detect_country("Toronto, Canada") == "CA"

    def test_india(self):
        assert detect_country("Bangalore, India") == "IN"

    def test_uae(self):
        assert detect_country("Dubai, UAE") == "AE"
