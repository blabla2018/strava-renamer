from app.eval_tools import build_eval_row


def test_build_eval_row_accepts_alternative_title_as_exact_match():
    row = build_eval_row(
        activity_id=1,
        expected_title="València - Calicanto",
        generated_title="València - Godelleta",
        current_name="Morning Ride",
        accepted_titles=["València - Godelleta"],
        review_comment="both are acceptable",
        route_summary=None,
    )

    assert row["exact_match"] is True
    assert row["normalized_exact_match"] is True
    assert row["matched_reference_title"] == "València - Godelleta"
    assert row["review_comment"] == "both are acceptable"


def test_build_eval_row_prefers_best_reference_for_similarity():
    row = build_eval_row(
        activity_id=2,
        expected_title="Cullera",
        generated_title="València - Cullera",
        current_name="Morning Ride",
        accepted_titles=["València - Cullera"],
        review_comment=None,
        route_summary=None,
    )

    assert row["matched_reference_title"] == "València - Cullera"
    assert row["normalized_exact_match"] is True
