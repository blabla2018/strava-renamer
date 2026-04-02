from app.config import Settings
from app.naming import generate_title, is_manual_title, should_rename_activity
from app.route_analysis import DetectedLandmark, OrderedHighlight, Point, ResolvedPlace, RouteHighlight, RouteSummary


def make_place(locality, district=None, suburb=None):
    return ResolvedPlace(locality=locality, district=district, suburb=suburb, country="ES", road=None, raw_rank=4)


def test_point_to_point_title_prefers_distinct_endpoints():
    summary = RouteSummary(
        points=[],
        total_distance_m=24000,
        is_loop=False,
        start_place=make_place("Madrid"),
        end_place=make_place("Alcobendas"),
        via_places=[],
        landmark=None,
    )

    decision = generate_title(summary)

    assert decision.title == "Madrid - Alcobendas"
    assert decision.confidence >= 0.9


def test_loop_title_uses_landmark_when_available():
    summary = RouteSummary(
        points=[],
        total_distance_m=31000,
        is_loop=True,
        start_place=make_place("Barcelona"),
        end_place=make_place("Barcelona"),
        via_places=[],
        landmark=DetectedLandmark(name="Montjuic", category="park", distance_m=120),
    )

    decision = generate_title(summary)

    assert decision.title == "Barcelona - Montjuic Loop"
    assert decision.confidence >= 0.85


def test_loop_title_prefers_ranked_highlight_when_available():
    summary = RouteSummary(
        points=[],
        total_distance_m=72000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        via_places=[make_place("Serra")],
        landmark=DetectedLandmark(name="Garbi", category="peak", distance_m=350),
        highlights=[
            RouteHighlight(name="Oronet", category="climb_segment", source="strava_segment", score=12.5),
            RouteHighlight(name="Garbi", category="peak", source="osm", score=8.1, distance_m=350),
        ],
    )

    decision = generate_title(summary)

    assert decision.title == "València - Oronet Loop"
    assert decision.confidence >= 0.9


def test_loop_title_uses_two_ordered_highlights_when_available():
    summary = RouteSummary(
        points=[],
        total_distance_m=78000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        via_places=[make_place("Serra")],
        landmark=None,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Oronet", kind="climb_segment", score=14.8, position=0.4),
            OrderedHighlight(cluster_id="b", name="Garbi", kind="climb_segment", score=14.1, position=0.7),
        ],
    )

    decision = generate_title(summary)

    assert decision.title == "València - Oronet - Garbi"
    assert decision.confidence >= 0.94


def test_ring_like_loop_can_include_three_highlights():
    summary = RouteSummary(
        points=[
            Point(39.47, -0.38),
            Point(39.57, -0.38),
            Point(39.57, -0.25),
            Point(39.47, -0.25),
            Point(39.47, -0.38),
        ],
        total_distance_m=56000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        via_places=[],
        landmark=None,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Oronet", kind="climb_segment", score=14.8, position=0.2),
            OrderedHighlight(cluster_id="b", name="Garbi", kind="climb_segment", score=14.1, position=0.5),
            OrderedHighlight(cluster_id="c", name="Cullera", kind="turnaround_place", score=13.5, position=0.8),
        ],
    )

    decision = generate_title(summary)

    assert decision.title == "València - Oronet - Garbi - Cullera"
    assert decision.confidence >= 0.95


def test_elongated_loop_prefers_farthest_destination():
    summary = RouteSummary(
        points=[
            Point(39.47, -0.38),
            Point(39.55, -0.34),
            Point(39.62, -0.30),
            Point(39.70, -0.26),
            Point(39.62, -0.30),
            Point(39.55, -0.34),
            Point(39.47, -0.38),
        ],
        total_distance_m=42000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        turnaround_place=make_place("Cullera"),
        turnaround_position=0.5,
        via_places=[make_place("Sueca")],
        landmark=None,
    )

    decision = generate_title(summary)

    assert decision.title == "València - Cullera"
    assert decision.confidence >= 0.95


def test_elongated_loop_ignores_noisy_intermediate_highlights():
    summary = RouteSummary(
        points=[
            Point(39.47, -0.38),
            Point(39.55, -0.34),
            Point(39.62, -0.30),
            Point(39.70, -0.26),
            Point(39.62, -0.30),
            Point(39.55, -0.34),
            Point(39.47, -0.38),
        ],
        total_distance_m=42000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        turnaround_place=make_place("Formentor"),
        turnaround_position=0.5,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Lookout - Corner", kind="climb_segment", score=15.0, position=0.8),
            OrderedHighlight(cluster_id="b", name="Far - Formentor", kind="turnaround_place", score=9.0, position=0.5),
        ],
        via_places=[],
        landmark=None,
    )

    decision = generate_title(summary)

    assert decision.title == "València - Formentor"


def test_elongated_loop_prefers_composite_climb_over_generic_turnaround_locality():
    summary = RouteSummary(
        points=[
            Point(39.47, -0.38),
            Point(39.55, -0.34),
            Point(39.62, -0.30),
            Point(39.70, -0.26),
            Point(39.62, -0.30),
            Point(39.55, -0.34),
            Point(39.47, -0.38),
        ],
        total_distance_m=78000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        turnaround_place=make_place("Serra"),
        turnaround_position=0.5,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Serra", kind="turnaround_place", score=7.7, position=0.5),
            OrderedHighlight(cluster_id="b", name="Oronet - Garbi", kind="mountain_pass", score=18.8, position=0.9),
        ],
        via_places=[],
        landmark=None,
    )

    decision = generate_title(summary)

    assert decision.title == "València - Oronet - Garbi"


def test_elongated_loop_can_include_midpoint_and_farthest_destination():
    summary = RouteSummary(
        points=[
            Point(39.47, -0.38),
            Point(39.58, -0.31),
            Point(39.69, -0.24),
            Point(39.80, -0.17),
            Point(39.69, -0.24),
            Point(39.58, -0.31),
            Point(39.47, -0.38),
        ],
        total_distance_m=42000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        turnaround_place=make_place("Tavernes De La Valldigna"),
        turnaround_position=0.5,
        via_places=[make_place("Sueca"), make_place("Cullera")],
        landmark=None,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Cullera", kind="turnaround_place", score=8.3, position=0.75),
        ],
    )

    decision = generate_title(summary)

    assert decision.title == "València - Cullera - Tavernes De La Valldigna"


def test_loop_title_prefers_clean_turnaround_highlight_over_admin_locality():
    summary = RouteSummary(
        points=[],
        total_distance_m=109756,
        is_loop=True,
        start_place=make_place("Pla de Mallorca"),
        end_place=make_place("Pla de Mallorca"),
        turnaround_place=make_place("Escorca"),
        turnaround_highlight=DetectedLandmark(
            name='"Sa Calobra"',
            category="climb_segment",
            distance_m=150,
            source="turnaround_poi",
            score=18.0,
        ),
        via_places=[make_place("Escorca")],
        landmark=None,
    )

    decision = generate_title(summary)

    assert decision.title == "Pla De Mallorca - Sa Calobra"
    assert decision.confidence >= 0.95


def test_manual_title_detection_respects_default_allowlist():
    settings = Settings(webhook_verify_token="token")

    assert not is_manual_title("Morning Ride", "Ride", settings)
    assert is_manual_title("Sunday Sierra Spin", "Ride", settings)


def test_should_not_rename_when_confidence_is_below_threshold():
    settings = Settings(webhook_verify_token="token", confidence_threshold=0.9)
    summary = RouteSummary(
        points=[],
        total_distance_m=15000,
        is_loop=True,
        start_place=make_place("Seville"),
        end_place=make_place("Seville"),
        via_places=[],
        landmark=None,
    )

    decision = generate_title(summary)
    allowed, reason = should_rename_activity("Morning Run", decision, "Run", settings)

    assert not allowed
    assert "below threshold" in reason
