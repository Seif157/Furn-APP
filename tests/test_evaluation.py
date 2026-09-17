"""The deterministic half of the Phase 5D benchmark. No provider is contacted.

These tests do not measure the model. They check that the benchmark itself is
sound, so that when the live run reports a number, the number means something.
A case whose expected specification does not parse, or finds nothing, or is
scored by a metric that cannot fail, would quietly make the model look better
than it is.
"""

from decimal import Decimal

import pytest

from app.search import models
from app.search.filters import constraint_checks, satisfies_all
from app.search.service import search_products
from tests import evaluation as ev


@pytest.fixture(scope="module")
def catalogue() -> tuple:
    return ev.eligible_catalogue()


def test_the_benchmark_covers_both_languages_and_the_awkward_cases() -> None:
    names = {case.name for case in ev.CASES}
    assert len(names) == len(ev.CASES), "case names must be unique"
    languages = {case.language for case in ev.CASES}
    assert {"ar", "en"} <= languages
    assert any(case.expects_clarification for case in ev.CASES)
    assert any(case.expects_unresolved for case in ev.CASES)
    # A benchmark where everything matches never catches a widened constraint.
    assert any(case.name.endswith("no_match") for case in ev.CASES)


def test_every_expected_specification_is_valid_and_resolves_cleanly() -> None:
    for case in ev.CASES:
        build = models.build_specification(query=case.query, **case.expected)
        # A surface the vocabulary cannot map would make the case's own ground
        # truth wrong, so the benchmark must not contain one by accident.
        assert build.unresolved == (), f"{case.name}: {build.unresolved}"


def test_each_case_has_ground_truth_that_can_distinguish_answers(catalogue) -> None:
    for case in ev.CASES:
        found = ev.ground_truth_ids(case, catalogue)
        if case.name.endswith("no_match"):
            assert found == set(), case.name
            continue
        assert found, f"{case.name} finds nothing, so recall cannot fail"
        # A case that matches the entire catalogue measures nothing either,
        # unless it is deliberately the vague one.
        if not case.expects_clarification and not case.expects_unresolved:
            assert len(found) < len(catalogue), case.name


def test_ground_truth_products_satisfy_the_cases_own_constraints(catalogue) -> None:
    by_id = {product.id: product for product in catalogue}
    for case in ev.CASES:
        hard = case.specification().hard
        for product_id in ev.ground_truth_ids(case, catalogue):
            assert satisfies_all(constraint_checks(by_id[product_id], hard)), case.name


# --- the metrics have to be able to fail ------------------------------------


def test_a_perfect_parse_scores_perfectly(catalogue) -> None:
    outcomes = []
    for case in ev.CASES:
        outcomes.append(
            ev.evaluate_case(
                case,
                case.specification(),
                catalogue=catalogue,
                clarification="a question" if case.expects_clarification else None,
                unresolved=case.expects_unresolved,
            )
        )
    report = ev.Report(tuple(outcomes))

    assert report.extraction_accuracy == 1.0
    assert report.field_accuracy == 1.0
    assert report.mean_recall == 1.0
    assert report.clarification_accuracy == 1.0
    assert report.violation_rate == 0.0
    assert report.hallucination_rate == 0.0


def test_a_widened_budget_is_caught_as_a_violation(catalogue) -> None:
    # The failure that matters most: the parser drops or loosens a stated
    # limit, so the customer is shown products they ruled out. Judging against
    # the case rather than the parse is what catches it.
    case = next(c for c in ev.CASES if c.name == "ar_material_budget")
    widened = models.build_specification(
        query=case.query,
        category="سرير",
        materials=("خشب زان",),
        price=models.PriceRange(maximum=Decimal("100000")),
    ).specification

    outcome = ev.evaluate_case(
        case, widened, catalogue=catalogue, clarification=None, unresolved=()
    )

    assert outcome.violations, "a widened budget must be reported"
    assert not outcome.extraction_correct
    assert ev.Report((outcome,)).violation_rate == 1.0


def test_a_dropped_category_is_caught_by_extraction_scoring(catalogue) -> None:
    case = next(c for c in ev.CASES if c.name == "ar_width_limit")
    without_category = models.build_specification(
        query=case.query, width=models.DimensionRange(maximum_cm=Decimal("200"))
    ).specification

    outcome = ev.evaluate_case(
        case, without_category, catalogue=catalogue, clarification=None, unresolved=()
    )

    assert not outcome.extraction_correct
    category = next(f for f in outcome.fields if f.field == "category")
    assert category.expected == "sofas"
    assert category.actual == "-"


def test_a_missing_clarification_is_caught(catalogue) -> None:
    case = next(c for c in ev.CASES if c.expects_clarification)

    silent = ev.evaluate_case(
        case,
        case.specification(),
        catalogue=catalogue,
        clarification=None,
        unresolved=(),
    )

    assert not silent.clarification_correct
    assert ev.Report((silent,)).clarification_accuracy == 0.0


def test_an_unnecessary_clarification_is_caught(catalogue) -> None:
    case = next(c for c in ev.CASES if not c.expects_clarification)

    chatty = ev.evaluate_case(
        case,
        case.specification(),
        catalogue=catalogue,
        clarification="which room?",
        unresolved=(),
    )

    assert not chatty.clarification_correct


def test_recall_falls_when_results_are_missed(catalogue) -> None:
    # A parser that over-constrains returns a subset, which recall must notice.
    case = next(c for c in ev.CASES if c.name == "ar_budget_colour_style")
    narrower = models.build_specification(
        query=case.query,
        category="كنب",
        price=models.PriceRange(maximum=Decimal("10000")),
    ).specification

    outcome = ev.evaluate_case(
        case, narrower, catalogue=catalogue, clarification=None, unresolved=()
    )

    assert outcome.recall < 1.0


def test_the_report_summary_states_every_required_measurement() -> None:
    summary = ev.Report(()).summary()
    # Section 12 of the master plan names these; a report missing one is not a
    # Phase 5D report.
    for heading in (
        "extraction accuracy",
        "retrieval recall",
        "violation rate",
        "hallucination rate",
        "clarification accuracy",
    ):
        assert heading in summary


def test_hallucination_is_measurable_even_though_it_cannot_happen(catalogue) -> None:
    # Structurally impossible today: search only ever returns rows it was
    # given. The metric exists so that stops being an assumption.
    case = ev.CASES[0]
    outcome = ev.evaluate_case(
        case,
        case.specification(),
        catalogue=catalogue,
        clarification=None,
        unresolved=(),
    )

    assert outcome.hallucinated == ()
    assert all(
        product_id in {p.id for p in catalogue} for product_id in outcome.returned_ids
    )


def test_search_never_returns_a_product_outside_the_catalogue_it_was_given(
    catalogue,
) -> None:
    catalogue_ids = {product.id for product in catalogue}
    for case in ev.CASES:
        results = search_products(catalogue, case.specification())
        assert {item.product_id for item in results.items} <= catalogue_ids
