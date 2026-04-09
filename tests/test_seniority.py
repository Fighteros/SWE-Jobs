"""Tests for seniority level detection."""

from core.seniority import detect_seniority


class TestSeniorityDetection:
    def test_intern(self):
        assert detect_seniority("Software Engineering Intern") == "intern"

    def test_internship(self):
        assert detect_seniority("Python Internship") == "intern"

    def test_trainee(self):
        assert detect_seniority("Trainee Developer") == "intern"

    def test_coop(self):
        assert detect_seniority("Co-op Software Engineer") == "intern"

    def test_junior(self):
        assert detect_seniority("Junior Python Developer") == "junior"

    def test_jr(self):
        assert detect_seniority("Jr. Software Engineer") == "junior"

    def test_entry_level(self):
        assert detect_seniority("Entry Level Developer") == "junior"

    def test_fresh_grad(self):
        assert detect_seniority("Fresh Graduate Developer") == "junior"

    def test_associate(self):
        assert detect_seniority("Associate Software Engineer") == "junior"

    def test_senior(self):
        assert detect_seniority("Senior Backend Developer") == "senior"

    def test_sr(self):
        assert detect_seniority("Sr. Python Engineer") == "senior"

    def test_lead(self):
        assert detect_seniority("Lead Software Engineer") == "lead"

    def test_principal(self):
        assert detect_seniority("Principal Engineer") == "lead"

    def test_staff(self):
        assert detect_seniority("Staff Software Engineer") == "lead"

    def test_architect(self):
        assert detect_seniority("Solutions Architect") == "lead"

    def test_cto(self):
        assert detect_seniority("CTO") == "executive"

    def test_vp_engineering(self):
        assert detect_seniority("VP of Engineering") == "executive"

    def test_head_of(self):
        assert detect_seniority("Head of Engineering") == "executive"

    def test_director(self):
        assert detect_seniority("Director of Engineering") == "executive"

    def test_mid_default(self):
        assert detect_seniority("Python Developer") == "mid"

    def test_mid_explicit(self):
        assert detect_seniority("Mid-Level Software Engineer") == "mid"

    def test_senior_beats_intern_keyword(self):
        """'Senior' should win over embedded 'intern' in 'internal'."""
        assert detect_seniority("Senior Internal Tools Engineer") == "senior"

    def test_empty(self):
        assert detect_seniority("") == "mid"

    def test_none(self):
        assert detect_seniority(None) == "mid"
