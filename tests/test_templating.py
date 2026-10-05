from app.templating import static_version


def test_static_version_is_a_fingerprint_of_the_file():
    assert static_version("app.css") == static_version("app.css")
    assert static_version("app.css") != static_version("player.js")
    assert len(static_version("app.css")) == 10
