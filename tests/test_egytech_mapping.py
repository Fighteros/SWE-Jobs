"""Unit tests for core.egytech_mapping."""

from core.egytech_mapping import (
    SENIORITY_TO_LEVEL,
    TOPIC_TO_TITLE,
    parse_role_query,
    EGYTECH_TITLES,
    EGYTECH_LEVELS,
)


class TestSeniorityMapping:
    def test_all_our_seniorities_map(self):
        for s in ("intern", "junior", "mid", "senior", "lead", "executive"):
            assert s in SENIORITY_TO_LEVEL
            assert SENIORITY_TO_LEVEL[s] in EGYTECH_LEVELS


class TestTopicMapping:
    def test_known_topics_map(self):
        assert TOPIC_TO_TITLE["backend"] == "backend"
        assert TOPIC_TO_TITLE["frontend"] == "frontend"
        assert TOPIC_TO_TITLE["fullstack"] == "fullstack"
        assert TOPIC_TO_TITLE["mobile"] == "mobile"
        assert TOPIC_TO_TITLE["devops"] == "devops_sre_platform"
        assert TOPIC_TO_TITLE["qa"] == "testing"
        assert TOPIC_TO_TITLE["cybersecurity"] == "security"

    def test_all_mapped_titles_are_valid_egytech_titles(self):
        for title in TOPIC_TO_TITLE.values():
            assert title in EGYTECH_TITLES

    def test_unmapped_topics_return_none(self):
        for t in ("gamedev", "blockchain", "erp", "internships", "general", "egypt", "saudi"):
            assert TOPIC_TO_TITLE.get(t) is None


class TestParseRoleQuery:
    def test_canonical_titles_pass_through(self):
        assert parse_role_query("backend") == "backend"
        assert parse_role_query("frontend") == "frontend"

    def test_aliases_resolve(self):
        assert parse_role_query("python") == "backend"
        assert parse_role_query("java") == "backend"
        assert parse_role_query("node") == "backend"
        assert parse_role_query("react") == "frontend"
        assert parse_role_query("vue") == "frontend"
        assert parse_role_query("ios") == "mobile"
        assert parse_role_query("android") == "mobile"
        assert parse_role_query("flutter") == "mobile"
        assert parse_role_query("devops") == "devops_sre_platform"
        assert parse_role_query("sre") == "devops_sre_platform"

    def test_case_insensitive(self):
        assert parse_role_query("Python") == "backend"
        assert parse_role_query("REACT") == "frontend"

    def test_unknown_returns_none(self):
        assert parse_role_query("gamedev") is None
        assert parse_role_query("xyzzy") is None
        assert parse_role_query("") is None
        assert parse_role_query(None) is None
