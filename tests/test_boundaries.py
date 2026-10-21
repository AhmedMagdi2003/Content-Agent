from decimal import Decimal

import pytest

from content_app.content import check_grounding
from content_app.errors import Conflict
from content_app.models import Usage
from content_app.observability import cost_summary


def test_partial_cost_is_not_presented_as_complete():
    rows = [
        Usage(
            provider="fake",
            model="x",
            operation="extract",
            run_id="one",
            estimated_usd=Decimal("0.01"),
        ),
        Usage(provider="fake", model="x", operation="categorize", run_id="one"),
    ]
    total = next(g for g in cost_summary(rows) if g["dimension"] == "overall")
    assert total == {
        "dimension": "overall",
        "key": "all",
        "known_estimate_usd": "0.01",
        "unknown_calls": 1,
        "calls": 2,
    }


@pytest.mark.parametrize(
    "draft",
    [
        "We achieved 92% accuracy.",
        "https://madeup.test",
        'A researcher said "An invented quotation".',
    ],
)
def test_grounding_rejects_unsourced_numbers_quotes_links(draft):
    with pytest.raises(Conflict):
        check_grounding("The fictional team reviewed a checklist.", {"website": draft})
