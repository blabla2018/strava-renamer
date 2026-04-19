from app.title_validation import (
    is_generic_locality_highlight,
    is_specific_highlight,
    is_title_worthy_highlight,
    should_prefer_highlight_over_turnaround_name,
)


def test_is_title_worthy_highlight_rejects_pure_generic_fragment():
    assert not is_title_worthy_highlight("Lookout Corner")


def test_is_title_worthy_highlight_accepts_compact_route_anchor():
    assert is_title_worthy_highlight("Oronet - Garbi")


def test_is_title_worthy_highlight_rejects_noisy_segment_tail():
    assert not is_title_worthy_highlight("Tramo - Libre")
    assert not is_title_worthy_highlight("Barco")
    assert not is_title_worthy_highlight("CV-331 Climb")


def test_should_prefer_highlight_over_turnaround_name_for_generic_turnaround():
    assert should_prefer_highlight_over_turnaround_name("Oronet - Garbi", "Serra")


def test_is_specific_highlight_rejects_destination_echo():
    assert not is_specific_highlight("Cullera", "Cullera")


def test_is_generic_locality_highlight_marks_known_generic_locality():
    assert is_generic_locality_highlight("Náquera")
