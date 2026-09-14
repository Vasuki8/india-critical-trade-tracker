from scripts.check_source import parse_status


def test_parse_status():
    html = """
    <html><body>
    Data available:Jan 2018 to Jun 2026 ((R) Revised Final upto Mar 2026, (F) Final upto Jun 2026)
    Data last updated on: 13/08/2026
    ITC HS Code of the Commodity is either dropped or re-allocated and the unit of the commodity may be changed from April 2026.
    </body></html>
    """
    parsed = parse_status(html)
    assert parsed["data_available"] == "Jan 2018 to Jun 2026"
    assert parsed["last_updated"] == "13/08/2026"
    assert parsed["final_through"] == "Jun 2026"
    assert parsed["revised_final_through"] == "Mar 2026"
