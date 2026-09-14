from src.tracker.dashboard import _is_usd_observation


def test_explicit_usd_observation_is_included():
    assert _is_usd_observation({"value_type": "usd", "reports": []})


def test_quantity_observation_is_excluded():
    assert not _is_usd_observation({"value_type": "quantity", "reports": []})


def test_legacy_usd_observation_remains_supported():
    doc = {"reports": [{"value_type": "usd"}, {"value_type": "usd"}]}
    assert _is_usd_observation(doc)


def test_legacy_quantity_observation_is_excluded():
    doc = {"reports": [{"value_type": "quantity"}]}
    assert not _is_usd_observation(doc)
