"""Tests for the display helpers in ui.py: formatting, status badges and page links."""

import math

import ui


def test_formatting_helpers():
    assert ui.fmt_int(1234.4) == "1,234" and ui.fmt_int(None) == ui.MISSING and ui.fmt_int(math.nan) == ui.MISSING
    assert ui.fmt_num(3.14159) == "3.1" and ui.fmt_num(3.14159, 2) == "3.14"
    assert ui.fmt_pct(0.1534) == "15.3%" and ui.fmt_pct(0.1534, 2) == "15.34%"
    assert ui.fmt_pct(0.25, 0, signed=True) == "+25%" and ui.fmt_pct(-0.05, 1, signed=True) == "-5.0%"
    assert ui.fmt_money(12345.678) == "$12,346" and ui.fmt_money(12345.678, cents=True) == "$12,345.68"
    assert ui.fmt_money(-50) == "-$50" and ui.fmt_money(None) == ui.MISSING
    assert ui.fmt_date("2026-11-04") == "Nov 4, 2026" and ui.fmt_date(None) == ui.MISSING


def test_expiry_phrase_never_shows_negative_days():
    assert ui.expiry_phrase(-9) == "Expired 9 days ago"
    assert ui.expiry_phrase(-1) == "Expired 1 day ago"
    assert ui.expiry_phrase(0) == "Expires today"
    assert ui.expiry_phrase(1) == "Expires in 1 day" and ui.expiry_phrase(30) == "Expires in 30 days"


def test_status_labels_are_text_first_and_consistent():
    assert ui.plain_status("🔴 Shortage risk") == "Shortage risk" and ui.plain_status("OK") == "OK"
    for label in ["🔴 Order now", "🟡 Order soon", "🟢 OK", "🔴 No usable stock", "🔴 Shortage risk",
                  "🟡 Shortage watch", "🟢 Enough stock"]:
        badge = ui.badge_md(label)
        assert ui.plain_status(label) in badge and "🔴" not in badge and "🟡" not in badge   # text, no emoji
        assert ui.plain_status(label) in ui.STATUS                                         # one shared vocabulary
    # same state, same color: red for urgent, orange for watch, green for fine
    assert ui.STATUS["Order now"][0] == ui.STATUS["Shortage risk"][0] == "red"
    assert ui.STATUS["Order soon"][0] == ui.STATUS["Shortage watch"][0] == "orange"


def test_primary_status_is_the_more_urgent_of_the_two():
    assert ui.primary_status("🟢 OK", "🔴 Shortage risk") == "Shortage risk"
    assert ui.primary_status("🔴 Order now", "🟡 Shortage watch") == "Order now"
    assert ui.primary_status("🟡 Order soon", "🟢 OK") == "Order soon"
    assert ui.primary_status("🟢 OK", "🟢 Enough stock") == "OK"
    assert ui.primary_status("🔴 Order now", "🔴 No usable stock") == "No usable stock"


def test_page_links_round_trip_for_every_page():
    slugs = [ui.page_slug(t) for t, _, _ in ui.PAGES]
    assert len(set(slugs)) == len(slugs)
    for t, _, _ in ui.PAGES:
        assert ui.page_from_slug(ui.page_slug(t)) == t
    assert ui.page_slug("Recalls & disruptions") == "alerts" and ui.page_slug("Help") == "help"
    assert ui.page_from_slug("HELP ") == "Help" and ui.page_from_slug("nope") is None and ui.page_from_slug(None) is None


# ---------------------------------------------------------------------------
# Notification bell: count and badge text
# ---------------------------------------------------------------------------
import pandas as pd
from datetime import date

import events

TODAY = date(2026, 11, 4)
NO_RECALLS = pd.DataFrame(columns=["date", "lot_no"])
NO_OUTAGES = pd.DataFrame(columns=["supplier", "state"])
NO_LOTS = pd.DataFrame(columns=["item_id", "lot_no", "days_left", "qty"])


def lots(*rows):
    return pd.DataFrame(rows, columns=["item_id", "lot_no", "days_left", "qty"])


def test_alert_count_zero():
    c = events.alert_counts(NO_RECALLS, NO_OUTAGES, lots(("A", "L1", 120, 10)), TODAY)
    assert c == {"recalls": 0, "disruptions": 0, "expiring": 0, "total": 0}
    assert ui.badge_text(c["total"]) == "" and "::after" not in ui.bell_css(c["total"])   # no red badge
    assert ui.alerts_label(0) == "Open alerts, none active"


def test_alert_count_one():
    c = events.alert_counts(NO_RECALLS, NO_OUTAGES, lots(("A", "L1", 12, 10)), TODAY)
    assert c["total"] == 1 and c["expiring"] == 1
    assert ui.badge_text(1) == "1" and 'content:"1"' in ui.bell_css(1)
    assert ui.alerts_label(1) == "Open alerts, 1 active"


def test_alert_count_adds_up_categories():
    recalls = pd.DataFrame({"date": ["2026-11-01", "2026-10-01"], "lot_no": ["R1", "R0"]})   # one recent, one old
    outages = pd.DataFrame({"supplier": ["V1", "V2"], "state": ["🔴 Active", "Ended"]})
    c = events.alert_counts(recalls, outages, lots(("A", "L1", -3, 5), ("B", "L2", 40, 5)), TODAY)
    assert c == {"recalls": 1, "disruptions": 1, "expiring": 1, "total": 3}


def test_alert_count_never_counts_a_record_twice():
    recalls = pd.DataFrame({"date": ["2026-11-02", "2026-11-03"], "lot_no": ["L9", "L9"]})   # same lot listed twice
    outages = pd.DataFrame({"supplier": ["V1", "V1"], "state": ["🔴 Active", "🔴 Active"]})
    risk = lots(("A", "L1", -2, 5), ("A", "L2", 10, 5),      # two lots of one item: one item
                ("B", "L9", 5, 3),                            # the recalled lot: already counted as a recall
                ("C", "L3", 8, 0))                            # an empty lot is not an alert
    c = events.alert_counts(recalls, outages, risk, TODAY)
    assert c == {"recalls": 1, "disruptions": 1, "expiring": 1, "total": 3}


def test_badge_caps_at_99_plus():
    assert ui.badge_text(99) == "99" and ui.badge_text(100) == "99+" and ui.badge_text(4321) == "99+"
    assert 'content:"99+"' in ui.bell_css(250)
    assert ui.alerts_label(250) == "Open alerts, 99+ active"
