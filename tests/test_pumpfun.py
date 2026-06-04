from clusterdetect.domain.pumpfun import classify_pumpfun_graduation


def test_pumpfun_graduation_fixture_response():
    fixture = {
        "mint": "DemoMint",
        "symbol": "DEMO",
        "complete": False,
        "bonding_curve_progress": 94.2,
    }

    status = classify_pumpfun_graduation(fixture)

    assert status.status == "near-graduation"
    assert status.eligible is True
    assert status.progress_pct == 94.2


def test_pumpfun_graduated_and_noneligible_cases():
    graduated = classify_pumpfun_graduation({"complete": True})
    early = classify_pumpfun_graduation({"progress": 0.42})
    unknown = classify_pumpfun_graduation({})

    assert graduated.status == "graduated"
    assert graduated.eligible is True
    assert early.status == "bonding-curve"
    assert early.progress_pct == 42.0
    assert early.eligible is False
    assert unknown.status == "unknown"
