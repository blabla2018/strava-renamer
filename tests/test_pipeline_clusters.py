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
