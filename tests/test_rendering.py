"""Dashboard cards and Exceptional push text, with and without confidence signals.
Run: python tests/test_rendering.py   (or pytest)"""

from rare_weather import dashboard
from rare_weather.config import Settings, Spot
from rare_weather.opportunities import Opportunity
from rare_weather.pipeline import alert_text

CFG = Settings({"timezone": "America/Los_Angeles", "home_base": {"name": "Portland, OR"}})
HOOD = Spot("mt-hood", "Mt. Hood", 45.3735, -121.6959, phenomena=["lenticular"])
T_1700 = 1789923600  # 2026-09-20T17:00Z = 10:00 PDT
T_2000 = 1789934400

SIGNALS = [
    {"name": "wave_airmet", "text": "wave AIRMET active"},
    {"name": "wave_pireps", "text": "4 PIREPs reporting wave"},
]


def _opp(signals=None) -> Opportunity:
    return Opportunity(
        id="mt-hood:lenticular:1", spot="mt-hood", phenomenon="lenticular",
        start=T_1700, end=T_2000, peak_score=0.91, tier="exceptional",
        alerted_tier="exceptional", signals=signals or [],
    )


def _card(opp: Opportunity) -> str:
    page = dashboard.render_html(dashboard.build_data(CFG, [HOOD], {}, [opp], {}, T_1700))
    start = page.index('<article class="opp"')
    return page[start : page.index("</article>", start)]


def test_card_shows_signals():
    card = _card(_opp(SIGNALS))
    assert "wave AIRMET active" in card
    assert "4 PIREPs reporting wave" in card


def test_card_without_signals_has_no_signal_line():
    assert 'class="signals"' not in _card(_opp())


def test_signals_are_in_the_published_data():
    data = dashboard.build_data(CFG, [HOOD], {}, [_opp(SIGNALS)], {}, T_1700)
    assert data["opportunities"][0]["signals"] == ["wave AIRMET active", "4 PIREPs reporting wave"]


def test_exceptional_push_lists_the_signals():
    title, body = alert_text("detected", _opp(SIGNALS), "Mt. Hood", "wind 45 kt at 700 hPa", "", CFG.timezone)
    assert title == "\N{CLOUD}\ufe0f Lenticular EXCEPTIONAL — Mt. Hood"
    assert body == (
        "Sun Sep 20 10:00–13:00 · peak score 0.91\n"
        "wind 45 kt at 700 hPa\n"
        "✈️ wave AIRMET active · 4 PIREPs reporting wave"
    )


def test_exceptional_push_without_signals_is_unchanged():
    _, body = alert_text("detected", _opp(), "Mt. Hood", "wind 45 kt at 700 hPa", "Mt. Adams", CFG.timezone)
    assert body == "Sun Sep 20 10:00–13:00 · peak score 0.91\nwind 45 kt at 700 hPa\nAlso: Mt. Adams"


def test_upgrade_push_lists_the_signals_before_the_also_line():
    title, body = alert_text("upgraded", _opp(SIGNALS), "Mt. Hood", "x", "Mt. Adams", CFG.timezone)
    assert title == "\N{CLOUD}\ufe0f Lenticular upgraded to EXCEPTIONAL — Mt. Hood"
    assert body.splitlines()[-2:] == [
        "✈️ wave AIRMET active · 4 PIREPs reporting wave",
        "Also: Mt. Adams",
    ]


def test_cancellation_push_is_unchanged():
    title, body = alert_text("cancelled", _opp(SIGNALS), "Mt. Hood", "", "", CFG.timezone)
    assert title == "\N{CLOUD}\ufe0f Lenticular cancelled — Mt. Hood"
    assert body == "The Exceptional window Sun Sep 20 10:00–13:00 no longer holds."


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all tests pass")
