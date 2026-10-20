import pytest

from agent_memes.errors import MemeError
from agent_memes.http import redact
from agent_memes.providers.vlipsy import VlipsyProvider, normalize_query, parse_vlipsy_id


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("V1iupR0X", "V1iupR0X"),
        ("vlipsy:V1iupR0X", "V1iupR0X"),
        ("https://vlipsy.com/vlip/the-it-crowd-this-is-fine-V1iupR0X", "V1iupR0X"),
        ("https://vlipsy.com/vlip/the-it-crowd-this-is-fine-V1iupR0X?ref=share", "V1iupR0X"),
        ("https://vlp.to/wi3mmVSw", "wi3mmVSw"),
        ("https://media.vlipsy.com/vlips/t4sf7Ofc/480p.mp4", "t4sf7Ofc"),
        ("vlipsy:short", None),
        ("this is fine", None),
        ("https://example.com/vlip/foo-V1iupR0X", None),
    ],
)
def test_parse_vlipsy_id(text, expected):
    assert parse_vlipsy_id(text) == expected


def test_normalize_query():
    assert normalize_query("  This is FINE!!! 🔥 ") == "this is fine"
    assert normalize_query("what's up, doc?") == "what's up doc"


def test_to_meme_maps_fields(vlipsy_routes):
    meme = VlipsyProvider.to_meme(vlipsy_routes["/v1/vlips/search"]["data"][0])
    assert meme.ref == "vlipsy:V1iupR0X"
    assert meme.source == "The IT Crowd"
    assert meme.page_url == "https://vlipsy.com/vlip/the-it-crowd-this-is-fine-V1iupR0X"
    assert meme.variants["hd"].watermark_url.endswith("480p-watermark.mp4")
    assert meme.variants["sd"].width == 640
    assert "via Vlipsy" in meme.attribution
    compact = meme.compact()
    assert set(compact) >= {"ref", "title", "from", "duration", "preview", "page_url"}


def test_search_sends_key_and_params(make_kit):
    kit, http = make_kit()
    out = kit.search("This is FINE!", limit=500, safesearch="high")
    url, params = http.calls[-1]
    assert url.endswith("/v1/vlips/search")
    assert params == {
        "q": "this is fine",
        "limit": 100,
        "pos": 0,
        "safesearch": "high",
        "key": "test-key-not-real",
    }
    assert out["total"] == 56 and out["next_offset"] == 2
    assert out["results"][0]["ref"] == "vlipsy:V1iupR0X"


def test_safesearch_off_is_omitted(make_kit):
    kit, http = make_kit()
    kit.trending(safesearch="off")
    assert http.calls[-1][1]["safesearch"] is None


def test_missing_key_is_actionable(make_kit):
    kit, _ = make_kit(vlipsy_api_key=None)
    kit.config.vlipsy_api_key = None
    with pytest.raises(MemeError) as err:
        kit.search("hello")
    assert err.value.code == "missing_api_key"
    assert "VLIPSY_API_KEY" in err.value.hint
    assert err.value.exit_code == 3


def test_playlists(make_kit):
    kit, _ = make_kit()
    assert kit.playlists()["results"][0]["title"] == "Hello"
    assert kit.playlist("5N8mJ4Ub")["results"][0]["ref"] == "vlipsy:V1iupR0X"


def test_redact_hides_keys():
    url = "https://apiv2.vlipsy.com/v1/vlips/search?q=a&key=s3cr3t&limit=2"
    assert "s3cr3t" not in redact(url)
    assert "key=REDACTED" in redact(url)
