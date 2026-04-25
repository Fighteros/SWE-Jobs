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

    def test_automation_resolves_to_testing(self):
        # 'automation' is ambiguous (QA vs AI); we resolve to QA/testing.
        assert parse_role_query("automation") == "testing"

    def test_all_alias_targets_are_valid_egytech_titles(self):
        """Every value in _ROLE_ALIASES must be a real egytech title."""
        from core.egytech_mapping import _ROLE_ALIASES
        for alias, title in _ROLE_ALIASES.items():
            assert title in EGYTECH_TITLES, f"{alias!r} -> {title!r} not in EGYTECH_TITLES"

    def test_role_aliases_has_no_duplicate_keys(self):
        """Catch duplicate dict keys (which Python silently overwrites) by parsing the source."""
        import ast
        from pathlib import Path
        import core.egytech_mapping as _mod

        src = Path(_mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)

        for node in ast.walk(tree):
            target_name = None
            value = None
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "_ROLE_ALIASES":
                        target_name = t.id
                        value = node.value
                        break
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "_ROLE_ALIASES":
                    target_name = node.target.id
                    value = node.value
            if target_name == "_ROLE_ALIASES" and isinstance(value, ast.Dict):
                keys = [k.value for k in value.keys if isinstance(k, ast.Constant)]
                duplicates = [k for k in keys if keys.count(k) > 1]
                assert not duplicates, f"Duplicate keys in _ROLE_ALIASES: {sorted(set(duplicates))}"
                return
        raise AssertionError("_ROLE_ALIASES not found in core/egytech_mapping.py")
