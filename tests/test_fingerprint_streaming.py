import hashlib
import json
from copy import deepcopy

from scripts.ingest_tradestat import FETCH_TIME_ONLY_KEYS, observation_fingerprint


def _legacy_revision_payload(value):
    if isinstance(value, dict):
        return {
            key: _legacy_revision_payload(item)
            for key, item in sorted(value.items())
            if key not in FETCH_TIME_ONLY_KEYS
        }
    if isinstance(value, list):
        return [_legacy_revision_payload(item) for item in value]
    return value


def _legacy_observation_fingerprint(doc):
    payload = json.dumps(
        _legacy_revision_payload(doc),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _representative_observation():
    rows = [
        {
            "partner_country": f"COUNTRY {index:03d}",
            "value": index * 1.25,
            "note": "₹ / café / escaped \"text\" / newline\nvalue" if index == 3 else None,
        }
        for index in range(250)
    ]
    return {
        "schema_version": 3,
        "period": "2026-06",
        "value_type": "usd",
        "year_type": "calendar",
        "commodity": {
            "id": "test_commodity",
            "name": "Test Commodity",
            "category": "Test",
            "hs_codes": ["12345678"],
            "classification_note": None,
        },
        "status": "ok",
        "reports": [
            {
                "trade_type": "import",
                "hs_code": "12345678",
                "rows": rows,
                "totals": {"value": sum(row["value"] for row in rows)},
                "source": {
                    "report_date": "15 September 2026",
                    "retrieved_at": "2026-09-15T10:00:00+00:00",
                    "checksum_sha256": "semantic-checksum",
                },
            }
        ],
        "metrics": {
            "imports": 123.456,
            "flags": [True, False, None],
        },
        "failures": [],
    }


def test_streaming_fingerprint_matches_legacy_digest_exactly():
    doc = _representative_observation()
    assert observation_fingerprint(doc) == _legacy_observation_fingerprint(doc)


def test_streaming_fingerprint_keeps_fetch_time_fields_non_semantic():
    original = _representative_observation()
    refetched = deepcopy(original)
    source = refetched["reports"][0]["source"]
    source["report_date"] = "16 September 2026"
    source["retrieved_at"] = "2026-09-16T12:30:00+00:00"

    assert observation_fingerprint(original) == observation_fingerprint(refetched)
    assert observation_fingerprint(refetched) == _legacy_observation_fingerprint(refetched)


def test_streaming_fingerprint_detects_nested_semantic_change():
    original = _representative_observation()
    revised = deepcopy(original)
    revised["reports"][0]["rows"][173]["value"] += 0.5

    assert observation_fingerprint(original) != observation_fingerprint(revised)
    assert observation_fingerprint(revised) == _legacy_observation_fingerprint(revised)
