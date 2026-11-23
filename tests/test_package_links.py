"""Package text: source links and hashtags must be in the description and FB post body."""
from app import pipeline, prompts

URL1 = "https://a.example/1"
URL2 = "https://a.example/2"
URL3 = "https://a.example/3"
URL4 = "https://a.example/4"


def test_with_links_adds_missing_url_and_tags():
    got = pipeline._with_links("第一段。", [URL1], ["#AI工具", "#Claude"])
    assert URL1 in got
    assert got.endswith("#AI工具 #Claude")


def test_with_links_keeps_complete_body_unchanged():
    body = f"摘要\n\n來源連結：\n{URL1}\n\n#AI工具 #Claude"
    assert pipeline._with_links(body, [URL1], ["#AI工具", "#Claude"]) == body


def test_finish_package_fills_description_and_fb_post():
    pk = {"description": "摘要", "fb_post": "貼文", "hashtags": ["#AI工具"]}
    pipeline._finish_package(pk, [URL1, URL2, URL3, URL4])
    assert URL4 in pk["description"]
    assert URL4 not in pk["fb_post"]  # FB gets at most 3 links
    assert pk["fb_post"].endswith("#AI工具")
    assert pk["description"].endswith("#AI工具")


def test_source_urls_dedup_and_skip_non_http():
    ep = {"source_urls": [URL1, "ftp://x", URL1], "auto_source_urls": [URL2]}
    assert pipeline._source_urls(ep) == [URL1, URL2]


def test_package_prompt_lists_urls_and_tag_rule():
    sys, _ = prompts.package({"topic": "測試", "format": "long", "style_id": None}, {}, 3, 2, [URL1])
    assert URL1 in sys
    assert "hashtags" in sys


def test_package_prompt_without_urls_forbids_inventing():
    sys, _ = prompts.package({"topic": "測試", "format": "long", "style_id": None}, {}, 3, 2, [])
    assert "不編造網址" in sys
