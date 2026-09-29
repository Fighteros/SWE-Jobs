from sources import linkedin_posts
from sources.linkedin_posts import _parse_post, _scrape_search


class TextElement:
    def __init__(self, text):
        self.text = text

    def inner_text(self):
        return self.text


class LinkElement:
    def __init__(self, href, text=""):
        self.href = href
        self.text = text

    def get_attribute(self, name):
        return self.href if name == "href" else None

    def inner_text(self):
        return self.text


class PostElement:
    def __init__(self):
        self.permalink = LinkElement(
            "https://www.linkedin.com/feed/update/urn:li:activity:123456?trk=feed",
            "View post",
        )
        self.external_link = LinkElement("https://jobs.example/apply?ref=linkedin")

    def query_selector(self, selector):
        if selector == 'a[href*="/feed/update/"], a[href*="/posts/"]':
            return self.permalink
        if selector == '[data-urn]':
            return None
        if selector == 'span.feed-shared-actor__name, span.update-components-actor__name':
            return TextElement("Acme Hiring")
        if selector == 'div.feed-shared-text, span.break-words, div.update-components-text':
            return TextElement(
                "We are hiring a Senior Software Engineer!\nLocation: Cairo, Egypt\n"
                "Apply now for this exciting opportunity."
            )
        return None

    def query_selector_all(self, selector):
        if selector == "a.app-aware-link[href]":
            return [self.permalink, self.external_link]
        return []


class SearchPage:
    def __init__(self, posts=None, url="https://www.linkedin.com/search/results/content/"):
        self.posts = posts or []
        self.url = url
        self.waited_for = []
        self.searched_url = ""
        self.mouse = self

    def goto(self, url, **kwargs):
        self.searched_url = url

    def wait_for_selector(self, selector, **kwargs):
        self.waited_for.append(selector)

    def wait_for_timeout(self, timeout):
        pass

    def wheel(self, *args):
        pass

    def query_selector_all(self, selector):
        assert selector == linkedin_posts.POST_SELECTOR
        return self.posts


def test_parse_post_extracts_job_and_apply_link():
    job = _parse_post(PostElement())

    assert job is not None
    assert job.source == "linkedin_posts"
    assert job.title == "Senior Software Engineer"
    assert job.company == "Acme Hiring"
    assert job.url == "https://jobs.example/apply"


def test_search_uses_post_container_selector_and_encodes_keywords(monkeypatch):
    monkeypatch.setattr(linkedin_posts, "MAX_SCROLLS", 0)
    post = PostElement()
    page = SearchPage([post])

    jobs = _scrape_search(page, "#hiring software engineer")

    assert len(jobs) == 1
    assert "keywords=%23hiring+software+engineer" in page.searched_url
    assert linkedin_posts.POST_SELECTOR in page.waited_for[0]


def test_search_stops_when_linkedin_redirects_to_authentication():
    page = SearchPage(url="https://www.linkedin.com/checkpoint/challenge")

    assert _scrape_search(page, "software engineer") == []
    assert page.waited_for == []


def test_fetch_skips_without_cookie_file(monkeypatch, tmp_path):
    monkeypatch.setenv("LINKEDIN_COOKIES_FILE", str(tmp_path / "missing.json"))

    assert linkedin_posts.fetch_linkedin_posts() == []
