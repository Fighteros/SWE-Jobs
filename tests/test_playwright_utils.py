from sources.playwright_utils import normalize_cookies


def test_normalize_browser_export_cookies():
    cookies = normalize_cookies(
        {
            "cookies": [
                {"name": "auth_token", "value": "secret", "sameSite": "no_restriction"},
                {"name": "session", "value": "abc", "sameSite": "unspecified"},
                {"name": "bad", "value": "x", "sameSite": "invalid"},
                {"name": "empty"},
                None,
            ]
        },
        ".x.com",
    )

    assert cookies == [
        {
            "name": "auth_token",
            "value": "secret",
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": False,
            "sameSite": "None",
        },
        {
            "name": "session",
            "value": "abc",
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": False,
        },
        {
            "name": "bad",
            "value": "x",
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": False,
        },
    ]
