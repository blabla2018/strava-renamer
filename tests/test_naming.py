from app.athlete_profile import AthleteProfile
from app.config import Settings
from app.naming import NamingDecision, generate_title, generate_title_candidates
from app.rename_policy import is_manual_title, should_rename_activity
from app.route_analysis import (
    DetectedLandmark,
    OrderedHighlight,
    Point,
    ResolvedPlace,
    RouteEntityCluster,
    RouteHighlight,
    RouteSummary,
)


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


def test_short_intra_city_route_prefers_city_over_segment_noise():
    summary = RouteSummary(
        points=[],
        total_distance_m=11262.1,
        is_loop=False,
        start_place=make_place("València"),
        end_place=make_place("València"),
        via_places=[],
        landmark=None,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Semaforo - Tunel", kind="segment", score=7.09, position=0.808),
            OrderedHighlight(cluster_id="b", name="Tramo", kind="segment", score=7.15, position=0.924),
        ],
    )

    decision = generate_title(
        summary,
        athlete_profile=AthleteProfile(athlete_id=1, city="València", state="Valencia", country="Spain"),
    )

    assert decision.title == "València"
    assert decision.confidence < 0.75


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


def test_loop_title_omits_home_city_start_when_profile_matches():
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

    decision = generate_title(
        summary,
        athlete_profile=AthleteProfile(athlete_id=1, city="Valencia", state="Valencia", country="ES"),
    )

    assert decision.title == "Oronet - Garbi"
    assert "omitted home-city start" in decision.reason


def test_loop_title_recovers_secondary_anchor_from_late_primary_cluster_aliases():
    summary = RouteSummary(
        points=[
            Point(39.47, -0.38),
            Point(39.58, -0.28),
            Point(39.67, -0.25),
            Point(39.58, -0.28),
            Point(39.47, -0.38),
        ],
        total_distance_m=79000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        turnaround_place=make_place("Serra"),
        turnaround_highlight=DetectedLandmark(
            name="Port de l'Oronet",
            category="mountain_pass",
            distance_m=100,
            source="turnaround_poi",
            score=6.5,
        ),
        turnaround_position=0.45,
        via_places=[
            make_place("Bétera"),
            make_place("Serra"),
            make_place("Estivella"),
            make_place("Nàquera / Náquera"),
        ],
        landmark=None,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Oronet", kind="mountain_pass", score=9.7, position=0.45),
            OrderedHighlight(cluster_id="b", name="Oronet", kind="climb_segment", score=20.7, position=0.95),
        ],
        clusters=[
            RouteEntityCluster(
                cluster_id="a",
                canonical_name="Oronet",
                normalized_name="oronet",
                kind="mountain_pass",
                score=9.7,
                position_start=0.45,
                position_end=0.45,
                position_centroid=0.45,
                aliases=["Port de l'Oronet"],
                sources=["turnaround_poi"],
                signals_count=1,
            ),
            RouteEntityCluster(
                cluster_id="b",
                canonical_name="Oronet",
                normalized_name="oronet",
                kind="climb_segment",
                score=20.7,
                position_start=0.72,
                position_end=0.99,
                position_centroid=0.95,
                aliases=[
                    "Oronet - Garbí",
                    "Oronet + Garbi",
                    "Garbí desde Pico del Oronet",
                    "Canteras Oronet",
                    "Canteras Loronet",
                    "Garbi - Naquera",
                    "Real Garbí Climb",
                ],
                sources=["strava_segment"],
                signals_count=24,
            ),
        ],
    )

    decision = generate_title(
        summary,
        athlete_profile=AthleteProfile(athlete_id=1, city="València", state="Valencia", country="Spain"),
    )

    assert decision.title == "Oronet - Garbi"


def test_loop_title_keeps_start_when_profile_city_does_not_match():
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

    decision = generate_title(
        summary,
        athlete_profile=AthleteProfile(athlete_id=1, city="Madrid", state="Madrid", country="ES"),
    )

    assert decision.title == "València - Oronet - Garbi"


def test_loop_title_omits_home_city_even_when_country_representation_differs():
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

    decision = generate_title(
        summary,
        athlete_profile=AthleteProfile(athlete_id=1, city="Valencia", state="Valencia", country="Spain"),
    )

    assert decision.title == "Oronet - Garbi"


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


def test_ring_loop_prefers_destination_locality_over_single_noisy_highlight():
    summary = RouteSummary(
        points=[
            Point(39.47, -0.38),
            Point(39.39, -0.29),
            Point(39.33, -0.24),
            Point(39.39, -0.29),
            Point(39.47, -0.38),
        ],
        total_distance_m=100000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        turnaround_place=make_place("Favara"),
        turnaround_position=0.5,
        via_places=[make_place("Alfafar"), make_place("Sueca"), make_place("Cullera"), make_place("Sueca")],
        landmark=None,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Cullera", kind="climb_segment", score=17.22, position=0.914),
            OrderedHighlight(cluster_id="b", name="Camino - Bega", kind="climb_segment", score=16.71, position=0.969),
        ],
    )

    decision = generate_title(summary)

    assert decision.title == "València - Cullera"
    assert decision.confidence >= 0.95


def test_ring_loop_keeps_destination_when_first_non_turnaround_highlight_is_generic_segment_chain():
    summary = RouteSummary(
        points=[
            Point(39.47, -0.38),
            Point(39.39, -0.29),
            Point(39.33, -0.24),
            Point(39.39, -0.29),
            Point(39.47, -0.38),
        ],
        total_distance_m=100000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        turnaround_place=make_place("Favara"),
        turnaround_position=0.5,
        via_places=[make_place("Alfafar"), make_place("Sueca"), make_place("Cullera"), make_place("Sueca")],
        landmark=None,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Favara", kind="turnaround_place", score=8.42, position=0.678),
            OrderedHighlight(cluster_id="b", name="Sueca - Sollana", kind="segment", score=7.6, position=0.905),
            OrderedHighlight(cluster_id="c", name="Bega", kind="climb_segment", score=16.81, position=0.986),
        ],
    )

    decision = generate_title(summary)

    assert decision.title == "València - Cullera"


def test_long_mixed_loop_uses_multiple_non_home_anchors():
    summary = RouteSummary(
        points=[],
        total_distance_m=91095.3,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        turnaround_place=make_place("Alborache"),
        turnaround_position=0.635,
        via_places=[
            make_place("Torrent"),
            make_place("Torrent"),
            make_place("Godelleta"),
            make_place("Buñol"),
            make_place("Turís"),
            make_place("Alcàsser"),
        ],
        landmark=None,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Alborache", kind="turnaround_place", score=7.74, position=0.635),
            OrderedHighlight(cluster_id="b", name="Gayarre", kind="climb_segment", score=15.56, position=0.872),
            OrderedHighlight(cluster_id="c", name="Calicanto", kind="climb_segment", score=20.21, position=0.941),
        ],
    )

    decision = generate_title(
        summary,
        athlete_profile=AthleteProfile(athlete_id=1, city="València", state="Valencia", country="Spain"),
    )

    assert decision.title == "Calicanto - Buñol - Turís"
    assert "omitted home-city start" in decision.reason


def test_long_loop_keeps_turnaround_pass_over_late_multi_anchor_noise():
    summary = RouteSummary(
        points=[],
        total_distance_m=102033.0,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        turnaround_place=make_place("Altura"),
        turnaround_position=0.491,
        turnaround_highlight=DetectedLandmark(
            name="Puerto de Chirivilla",
            category="mountain_pass",
            distance_m=120.0,
            source="turnaround_poi",
            score=9.48,
        ),
        via_places=[
            make_place("Bétera"),
            make_place("Olocau"),
            make_place("Gátova"),
            make_place("Bétera"),
        ],
        landmark=None,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Chirivilla", kind="mountain_pass", score=9.72, position=0.491),
            OrderedHighlight(cluster_id="b", name="Olocau", kind="climb_segment", score=19.93, position=0.942),
        ],
    )

    decision = generate_title(
        summary,
        athlete_profile=AthleteProfile(athlete_id=1, city="València", state="Valencia", country="Spain"),
    )

    assert decision.title == "Chirivilla"


def test_branched_loop_prefers_turnaround_locality_and_branch_highlight():
    summary = RouteSummary(
        points=[
            Point(39.47, -0.38),
            Point(39.55, -0.38),
            Point(39.62, -0.30),
            Point(39.55, -0.38),
            Point(39.47, -0.38),
            Point(39.47, -0.28),
            Point(39.47, -0.38),
        ],
        total_distance_m=61000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        turnaround_place=make_place("Olocau"),
        turnaround_position=0.389,
        turnaround_highlight=DetectedLandmark(
            name="Puntal dels Llops",
            category="archaeological_site",
            distance_m=449.6,
            source="turnaround_poi",
            score=8.05,
        ),
        via_places=[],
        landmark=None,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Olocau", kind="turnaround_place", score=7.74, position=0.389),
            OrderedHighlight(cluster_id="b", name="Canteras", kind="segment", score=9.17, position=0.905),
            OrderedHighlight(cluster_id="c", name="Olocau - Muur", kind="climb_segment", score=17.87, position=0.968),
        ],
    )

    decision = generate_title(summary)

    assert decision.title == "València - Olocau - Canteras"
    assert decision.confidence >= 0.95


def test_branched_loop_drops_low_score_tail_highlight():
    summary = RouteSummary(
        points=[
            Point(39.47, -0.38),
            Point(39.55, -0.36),
            Point(39.62, -0.31),
            Point(39.56, -0.35),
            Point(39.49, -0.38),
            Point(39.50, -0.30),
            Point(39.47, -0.38),
        ],
        total_distance_m=69000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        turnaround_place=make_place("Serra"),
        turnaround_position=0.68,
        turnaround_highlight=DetectedLandmark(
            name="Port de l'Oronet",
            category="mountain_pass",
            distance_m=160.0,
            source="turnaround_poi",
            score=18.0,
        ),
        via_places=[],
        landmark=None,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Oronet", kind="mountain_pass", score=9.73, position=0.592),
            OrderedHighlight(cluster_id="b", name="Sacacorchos", kind="climb_segment", score=2.23, position=0.997),
        ],
    )

    decision = generate_title(summary)

    assert decision.title == "València - Oronet"


def test_branched_loop_prefers_composite_highlight_over_subsumed_turnaround():
    summary = RouteSummary(
        points=[
            Point(39.47, -0.38),
            Point(39.55, -0.36),
            Point(39.62, -0.31),
            Point(39.56, -0.35),
            Point(39.49, -0.38),
            Point(39.50, -0.30),
            Point(39.47, -0.38),
        ],
        total_distance_m=78000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        turnaround_place=make_place("Serra"),
        turnaround_position=0.68,
        turnaround_highlight=DetectedLandmark(
            name="Port de l'Oronet",
            category="mountain_pass",
            distance_m=160.0,
            source="turnaround_poi",
            score=18.0,
        ),
        via_places=[],
        landmark=None,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Serra", kind="turnaround_place", score=7.74, position=0.68),
            OrderedHighlight(cluster_id="b", name="Oronet - Garbi", kind="mountain_pass", score=18.91, position=0.937),
            OrderedHighlight(cluster_id="c", name="Hachazoserra", kind="climb_segment", score=3.35, position=0.987),
        ],
    )

    decision = generate_title(summary)

    assert decision.title == "València - Oronet - Garbi"
    assert decision.confidence >= 0.95


def test_branched_loop_places_turnaround_between_composite_branch_parts():
    summary = RouteSummary(
        points=[
            Point(39.47, -0.38),
            Point(39.55, -0.36),
            Point(39.62, -0.31),
            Point(39.56, -0.35),
            Point(39.49, -0.38),
            Point(39.50, -0.30),
            Point(39.47, -0.38),
        ],
        total_distance_m=78000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        turnaround_place=make_place("Serra"),
        turnaround_position=0.68,
        turnaround_highlight=DetectedLandmark(
            name="Port de l'Oronet",
            category="mountain_pass",
            distance_m=160.0,
            source="turnaround_poi",
            score=18.0,
        ),
        via_places=[],
        landmark=None,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Serra", kind="turnaround_place", score=7.74, position=0.68),
            OrderedHighlight(cluster_id="b", name="Canteras - Garbi", kind="climb_segment", score=18.91, position=0.937),
            OrderedHighlight(cluster_id="c", name="Sacacorchos", kind="climb_segment", score=3.35, position=0.987),
        ],
    )

    decision = generate_title(
        summary,
        athlete_profile=AthleteProfile(athlete_id=1, city="València", state="Valencia", country="Spain"),
    )

    assert decision.title == "Canteras - Oronet - Garbi"
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


def test_loop_prefers_turnaround_locality_when_it_is_the_last_meaningful_via_place():
    summary = RouteSummary(
        points=[
            Point(39.47, -0.38),
            Point(39.43, -0.35),
            Point(39.39, -0.33),
            Point(39.31, -0.30),
            Point(39.39, -0.33),
            Point(39.43, -0.35),
            Point(39.47, -0.38),
        ],
        total_distance_m=48000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        turnaround_place=make_place("El Perellonet"),
        turnaround_position=0.57,
        via_places=[
            make_place("Faitanar"),
            make_place("La Torre"),
            make_place("Alfafar"),
            make_place("El Perellonet"),
        ],
        landmark=None,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="There - Back", kind="segment", score=7.32, position=0.649),
            OrderedHighlight(cluster_id="b", name="Perellonet", kind="turnaround_place", score=9.73, position=0.786),
            OrderedHighlight(cluster_id="c", name="Puente - Sedaví", kind="climb_segment", score=17.64, position=0.964),
        ],
    )

    decision = generate_title(summary)

    assert decision.title == "València - El Perellonet"


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


def test_should_not_rename_manual_ride_title_when_overwrite_disabled():
    settings = Settings(webhook_verify_token="token", overwrite_manual_titles=False)
    decision = NamingDecision(title="València - Alborache - Calicanto", confidence=0.96, reason="test")

    allowed, reason = should_rename_activity("Buñol", decision, "Ride", settings)

    assert not allowed
    assert reason == "activity appears to have been manually renamed already"


def test_should_rename_previous_generated_title_when_generated_overwrite_enabled():
    settings = Settings(
        webhook_verify_token="token",
        overwrite_manual_titles=False,
        overwrite_existing_generated_titles=True,
    )
    decision = NamingDecision(title="Buñol", confidence=0.96, reason="test")

    allowed, reason = should_rename_activity(
        "València - Alborache",
        decision,
        "Ride",
        settings,
        previous_generated_name="València - Alborache",
    )

    assert allowed
    assert reason == "eligible to overwrite previous generated title"


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


def test_generate_title_candidates_returns_best_candidate_first():
    summary = RouteSummary(
        points=[],
        total_distance_m=56000,
        is_loop=True,
        start_place=make_place("València"),
        end_place=make_place("València"),
        turnaround_place=make_place("Cullera"),
        turnaround_position=0.5,
        via_places=[],
        landmark=None,
        ordered_highlights=[
            OrderedHighlight(cluster_id="a", name="Oronet", kind="climb_segment", score=14.8, position=0.2),
            OrderedHighlight(cluster_id="b", name="Garbi", kind="climb_segment", score=14.1, position=0.5),
            OrderedHighlight(cluster_id="c", name="Cullera", kind="turnaround_place", score=13.5, position=0.8),
        ],
    )

    candidates = generate_title_candidates(summary)
    decision = generate_title(summary)

    assert candidates
    assert candidates[0].title == decision.title
    assert candidates[0].reason == decision.reason
