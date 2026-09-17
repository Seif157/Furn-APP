"""Phase 5D search benchmark: cases, ground truth, and metrics.

Section 12 of the master plan asks for repeatable cases and six measurements.
The hard part is deciding what "correct" means for retrieval without writing
product ids into the benchmark by hand, where they rot the moment the seed
changes.

So ground truth is computed, not listed. Each case states the specification a
perfect parser would produce, and the products that specification finds through
the ordinary Phase 4D search *are* the right answer. That makes the benchmark
measure the thing actually in question, which is the parser, and keeps it
honest when the catalogue changes underneath it.

Two halves, run separately:

  The deterministic half needs no provider. It checks that each expected
  specification is well formed and that retrieval over it obeys every stated
  constraint. tests/test_evaluation.py runs it on every commit.

  The live half sends the sentences to a real provider and scores what comes
  back against the expected specification. scripts/live_search_evaluation.py
  runs it, only on request, because it costs money.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import TypeAdapter

from app.catalog import normalization as norm
from app.catalog.transform import is_recommendation_eligible
from app.catalog.upstream_models import UpstreamProduct
from app.search import models
from app.search.service import search_products
from tests import seed_catalogue as seed

ADAPTER = TypeAdapter(tuple[UpstreamProduct, ...])


def eligible_catalogue() -> tuple[norm.NormalizedProduct, ...]:
    """The 41 seed products the API would hand to search."""

    products = ADAPTER.validate_json(seed.as_json_fixture(), strict=True)
    return tuple(
        norm.normalize_product(product)
        for product in products
        if is_recommendation_eligible(product)
    )


@dataclass(frozen=True, slots=True)
class Case:
    """One sentence and the parse a perfect extractor would produce."""

    name: str
    query: str
    expected: dict[str, Any] = field(default_factory=dict)
    """Keyword arguments to ``build_specification``."""
    expects_clarification: bool = False
    expects_unresolved: tuple[str, ...] = ()
    """Surfaces the vocabularies should refuse to map."""

    @property
    def language(self) -> str:
        return models.detect_language(self.query)

    def specification(self) -> models.SearchSpecification:
        return models.build_specification(
            query=self.query, **self.expected
        ).specification


def _price(maximum: str) -> models.PriceRange:
    return models.PriceRange(maximum=Decimal(maximum))


def _width(maximum: str) -> models.DimensionRange:
    return models.DimensionRange(maximum_cm=Decimal(maximum))


CASES: tuple[Case, ...] = (
    Case(
        name="ar_budget_colour_style",
        query="عايز كنبة مودرن بيج أقل من ٣٠ ألف",
        expected={
            "category": "كنب",
            "price": _price("30000"),
            "preferred_colours": ("beige",),
            "styles": ("modern",),
        },
    ),
    Case(
        name="ar_material_budget",
        query="محتاج سرير خشب زان بحد أقصى ١٢ ألف",
        expected={
            "category": "سرير",
            "materials": ("خشب زان",),
            "price": _price("12000"),
        },
    ),
    Case(
        name="ar_width_limit",
        query="عايز كنبة مش أوسع من ٢٠٠ سم",
        expected={"category": "كنب", "width": _width("200")},
    ),
    Case(
        name="ar_wardrobe_colour",
        query="محتاج دولاب أبيض",
        # Colour described rather than demanded, so it ranks and does not
        # filter. The benchmark used to expect a hard colour here and a soft
        # one for the English sentence below, which measured the inconsistency
        # of the benchmark rather than of the model.
        expected={"category": "دولاب", "preferred_colours": ("white",)},
    ),
    Case(
        name="ar_wardrobe_colour_required",
        query="محتاج دولاب لازم يكون أبيض",
        # Demanded, so it filters.
        expected={"category": "دولاب", "colours": ("white",)},
    ),
    Case(
        name="ar_office_chair",
        query="عايز كرسي مكتب",
        expected={"category": "كرسي مكتب"},
    ),
    Case(
        name="ar_dining",
        query="عايز سفرة خشب",
        expected={"category": "سفرة", "materials": ("خشب",)},
    ),
    Case(
        name="ar_cheap_sofa_no_match",
        query="عايز كنبة بمية جنيه",
        expected={"category": "كنب", "price": _price("100")},
    ),
    Case(
        name="ar_vague",
        query="عايز أثاث",
        expected={},
        expects_clarification=True,
    ),
    Case(
        name="en_full_sentence",
        query="I need a modern beige sofa under 30,000 EGP",
        expected={
            "category": "sofa",
            "price": _price("30000"),
            "preferred_colours": ("beige",),
            "styles": ("modern",),
        },
    ),
    Case(
        name="en_material_budget",
        query="a beech wood bed under 20000",
        expected={
            "category": "bed",
            "materials": ("beech",),
            "price": _price("20000"),
        },
    ),
    Case(
        name="en_width_limit",
        query="a sofa no wider than 200 cm",
        expected={"category": "sofa", "width": _width("200")},
    ),
    Case(
        name="en_unstocked_category",
        query="I need a turquoise coffee table",
        expected={},
        expects_unresolved=("coffee table",),
    ),
    Case(
        name="mixed_dining",
        query="عايز modern dining table",
        expected={"category": "dining table", "styles": ("modern",)},
    ),
    Case(
        name="en_wardrobe_budget",
        query="a white wardrobe under 12000",
        expected={
            "category": "wardrobe",
            "preferred_colours": ("white",),
            "price": _price("12000"),
        },
    ),
    Case(
        name="ar_in_stock_relaxed",
        query="عايز كنبة حتى لو مش متوفرة دلوقتي",
        expected={"category": "كنب", "in_stock_only": False},
    ),
)


def ground_truth_ids(case: Case, catalogue: tuple[norm.NormalizedProduct, ...]) -> set:
    """Products the expected specification finds, which is the right answer."""

    results = search_products(catalogue, case.specification())
    return {item.product_id for item in results.items}


@dataclass(frozen=True, slots=True)
class FieldScore:
    """Whether one part of the specification was extracted correctly."""

    field: str
    expected: str
    actual: str

    @property
    def correct(self) -> bool:
        return self.expected == self.actual


def _render(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, tuple):
        return ",".join(sorted(str(item) for item in value)) or "-"
    if isinstance(value, models.PriceRange):
        return f"{value.minimum}..{value.maximum}"
    if isinstance(value, models.DimensionRange):
        return f"{value.minimum_cm}..{value.maximum_cm}"
    return str(value)


COMPARED_FIELDS = (
    "category",
    "colours",
    "materials",
    "price",
    "width",
    "height",
    "depth",
    "in_stock_only",
)


def score_specification(
    case: Case, actual: models.SearchSpecification
) -> tuple[FieldScore, ...]:
    """Compare every hard field of a parse against the expected one.

    Hard constraints only. Soft preferences change ranking rather than
    correctness, and holding a model to an exact style list would measure
    wording rather than understanding.
    """

    expected = case.specification()
    return tuple(
        FieldScore(
            field=name,
            expected=_render(getattr(expected.hard, name)),
            actual=_render(getattr(actual.hard, name)),
        )
        for name in COMPARED_FIELDS
    )


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    """Everything measured for one case in one run."""

    case: Case
    fields: tuple[FieldScore, ...]
    returned_ids: frozenset
    expected_ids: frozenset
    clarification_asked: bool
    unresolved_surfaces: tuple[str, ...]
    violations: tuple[str, ...]
    """Returned products that break a constraint the case actually stated."""
    hallucinated: tuple[str, ...]
    """Returned ids absent from the catalogue. The target is zero."""

    @property
    def extraction_correct(self) -> bool:
        return all(score.correct for score in self.fields)

    @property
    def recall(self) -> float:
        if not self.expected_ids:
            return 1.0
        return len(self.expected_ids & self.returned_ids) / len(self.expected_ids)

    @property
    def clarification_correct(self) -> bool:
        return self.clarification_asked == self.case.expects_clarification

    @property
    def unresolved_correct(self) -> bool:
        expected = {norm.normalize_text(s) for s in self.case.expects_unresolved}
        actual = {norm.normalize_text(s) for s in self.unresolved_surfaces}
        return expected <= actual


def evaluate_case(
    case: Case,
    specification: models.SearchSpecification,
    *,
    catalogue: tuple[norm.NormalizedProduct, ...],
    clarification: str | None,
    unresolved: tuple[str, ...],
) -> CaseOutcome:
    """Run retrieval for a parsed specification and measure it against the case."""

    from app.search.filters import constraint_checks, satisfies_all

    results = search_products(catalogue, specification)
    returned = {item.product_id for item in results.items}
    by_id = {product.id: product for product in catalogue}

    expected_hard = case.specification().hard
    violations = []
    hallucinated = []
    for product_id in returned:
        product = by_id.get(product_id)
        if product is None:
            hallucinated.append(str(product_id))
            continue
        # Judged against what the case asked for, not against whatever the
        # parser decided, so a lenient parse cannot excuse a bad product.
        if not satisfies_all(constraint_checks(product, expected_hard)):
            violations.append(str(product_id))

    return CaseOutcome(
        case=case,
        fields=score_specification(case, specification),
        returned_ids=frozenset(returned),
        expected_ids=frozenset(ground_truth_ids(case, catalogue)),
        clarification_asked=clarification is not None,
        unresolved_surfaces=unresolved,
        violations=tuple(sorted(violations)),
        hallucinated=tuple(sorted(hallucinated)),
    )


@dataclass(frozen=True, slots=True)
class Report:
    outcomes: tuple[CaseOutcome, ...]

    @property
    def extraction_accuracy(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(o.extraction_correct for o in self.outcomes) / len(self.outcomes)

    @property
    def field_accuracy(self) -> float:
        scores = [score for o in self.outcomes for score in o.fields]
        if not scores:
            return 0.0
        return sum(score.correct for score in scores) / len(scores)

    @property
    def mean_recall(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(o.recall for o in self.outcomes) / len(self.outcomes)

    @property
    def violation_rate(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(bool(o.violations) for o in self.outcomes) / len(self.outcomes)

    @property
    def hallucination_rate(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(bool(o.hallucinated) for o in self.outcomes) / len(self.outcomes)

    @property
    def clarification_accuracy(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(o.clarification_correct for o in self.outcomes) / len(self.outcomes)

    def summary(self) -> str:
        return "\n".join(
            (
                f"cases:                    {len(self.outcomes)}",
                f"extraction accuracy:      {self.extraction_accuracy:.0%}",
                f"field accuracy:           {self.field_accuracy:.0%}",
                f"mean retrieval recall:    {self.mean_recall:.0%}",
                f"clarification accuracy:   {self.clarification_accuracy:.0%}",
                f"constraint violation rate:{self.violation_rate:.0%}  (target 0%)",
                f"hallucination rate:       {self.hallucination_rate:.0%}  (target 0%)",
            )
        )
