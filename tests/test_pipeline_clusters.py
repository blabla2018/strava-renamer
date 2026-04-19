from app.pipeline import build_ordered_highlights, cluster_route_signals
from app.route_analysis import RawRouteSignal


def test_oronet_cluster_collapses_to_canonical_oronet():
    signals = [
        RawRouteSignal(
            name="Port de l'Oronet",
            normalized_name="oronet",
            kind="mountain_pass",
            source="strava_segment",
            score=9.4,
            position=0.70,
            aliases=["Port - Oronet"],
        ),
        RawRouteSignal(
            name="Oronet hasta el Chaparral",
            normalized_name="oronet chaparral",
            kind="climb_segment",
            source="strava_segment",
            score=17.9,
            position=0.91,
            aliases=["Oronet - Chaparral"],
        ),
    ]

    clusters = cluster_route_signals(signals)
    ordered = build_ordered_highlights(clusters, limit=4)

    assert [item.name for item in ordered] == ["Oronet"]


def test_ordered_highlights_keep_turnaround_locality_and_preserve_canteras():
    signals = [
        RawRouteSignal(
            name="Puntal dels Llops",
            normalized_name="puntal dels llops",
            kind="attraction",
            source="turnaround_poi",
            score=8.55,
            position=0.389,
        ),
        RawRouteSignal(
            name="Olocau",
            normalized_name="olocau",
            kind="turnaround_place",
            source="reverse_geocode",
            score=7.50,
            position=0.389,
        ),
        RawRouteSignal(
            name="Las Canteras",
            normalized_name="las canteras",
            kind="segment",
            source="strava_segment",
            score=8.69,
            position=0.887,
        ),
        RawRouteSignal(
            name="Olocau Muur [MAL]",
            normalized_name="olocau muur",
            kind="climb_segment",
            source="strava_segment",
            score=16.17,
            position=0.947,
        ),
    ]

    clusters = cluster_route_signals(signals)
    ordered = build_ordered_highlights(clusters, limit=6)

    assert [item.name for item in ordered] == ["Olocau", "Canteras", "Olocau - Muur"]


def test_ordered_highlights_prefer_mountain_pass_over_locality_at_same_position():
    signals = [
        RawRouteSignal(
            name="Puerto de Chirivilla",
            normalized_name="chirivilla",
            kind="mountain_pass",
            source="turnaround_poi",
            score=9.4,
            position=0.491,
        ),
        RawRouteSignal(
            name="Altura",
            normalized_name="altura",
            kind="turnaround_place",
            source="reverse_geocode",
            score=7.5,
            position=0.491,
        ),
    ]

    clusters = cluster_route_signals(signals)
    ordered = build_ordered_highlights(clusters, limit=4)

    assert [item.name for item in ordered] == ["Chirivilla"]


def test_known_cluster_label_prefers_calicanto():
    signals = [
        RawRouteSignal(
            name="Subida Calicanto Este",
            normalized_name="subida calicanto este",
            kind="climb_segment",
            source="strava_segment",
            score=12.0,
            position=0.91,
            aliases=["Calicanto Full"],
        ),
    ]

    clusters = cluster_route_signals(signals)

    assert clusters[0].canonical_name == "Calicanto"


def test_nearby_locality_and_poi_do_not_merge_on_stopwords_only():
    signals = [
        RawRouteSignal(
            name="Tavernes de la Valldigna",
            normalized_name="tavernes de la valldigna",
            kind="turnaround_place",
            source="reverse_geocode",
            score=7.5,
            position=0.485,
        ),
        RawRouteSignal(
            name="Torre de Guaita de la Vall",
            normalized_name="torre de guaita de la vall",
            kind="attraction",
            source="turnaround_poi",
            score=7.2,
            position=0.485,
        ),
    ]

    clusters = cluster_route_signals(signals)
    ordered = build_ordered_highlights(clusters, limit=4)

    assert len(clusters) == 2
    assert [item.canonical_name for item in clusters] == ["Tavernes - Valldigna", "Torre - Guaita"]
    assert [item.name for item in ordered] == ["Tavernes - Valldigna"]
