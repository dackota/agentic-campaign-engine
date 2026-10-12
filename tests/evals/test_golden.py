"""The golden set: made-up threat reports, each with the key facts a campaign must carry."""

from evals.golden import load_golden


def test_golden_set_has_about_ten_reports_with_key_facts() -> None:
    golden = load_golden()

    assert 8 <= len(golden) <= 12
    assert len({g.id for g in golden}) == len(golden)
    assert all(len(g.key_facts) >= 2 for g in golden)


def test_every_key_fact_is_stated_in_its_report() -> None:
    for entry in load_golden():
        for fact in entry.key_facts:
            assert fact.lower() in entry.report.lower(), (entry.id, fact)
