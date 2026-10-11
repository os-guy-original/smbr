"""Decision layer: constrained answers, low confidence routes to the user."""

from __future__ import annotations

from smbr.decisions import (
    LOW_CONFIDENCE,
    ConstrainedJsonProvider,
    DecisionProfile,
    DecisionRouter,
    DisabledDecisionProvider,
)


def test_boolean_from_constrained_json(stub_client_factory) -> None:
    client = stub_client_factory([{"answer": True, "confidence": 0.93}])
    provider = ConstrainedJsonProvider(client)
    decision = provider.boolean("Does this comment restate the code?")
    assert decision.value is True
    assert decision.confidence == 0.93
    assert decision.trustworthy
    # the schema handed to the model is fixed — it cannot ramble
    assert set(client.calls[0][1]["properties"]) == {"answer", "confidence"}


def test_malformed_model_output_is_not_a_guess(stub_client_factory) -> None:
    provider = ConstrainedJsonProvider(stub_client_factory([{"yes": "probably"}]))
    decision = provider.boolean("...")
    assert decision.confidence == 0.0
    assert not decision.trustworthy


def test_model_failure_is_not_a_guess(stub_client_factory) -> None:
    provider = ConstrainedJsonProvider(stub_client_factory(boom=True))
    assert provider.boolean("...").confidence == 0.0


def test_choice_rejects_value_outside_options(stub_client_factory) -> None:
    client = stub_client_factory([{"choice": "cobol", "confidence": 0.9}])
    provider = ConstrainedJsonProvider(client)
    decision = provider.choice("pick a language", ("python", "typescript"))
    assert decision.confidence == 0.0  # enum violation → no answer


def test_confidence_is_clamped(stub_client_factory) -> None:
    provider = ConstrainedJsonProvider(stub_client_factory([{"answer": False, "confidence": 7.5}]))
    assert provider.boolean("...").confidence == 1.0


def test_disabled_provider_always_asks_the_user() -> None:
    provider = DisabledDecisionProvider()
    assert provider.boolean("...").confidence == 0.0
    assert provider.choice("pick", ("a", "b")).confidence == 0.0


def test_router_routes_low_confidence_to_user(stub_client_factory) -> None:
    client = stub_client_factory([{"answer": True, "confidence": LOW_CONFIDENCE - 0.1}])
    router = DecisionRouter(ConstrainedJsonProvider(client))
    assert router.needs_user(router.boolean("..."))


def test_profile_answers_you_decide() -> None:
    router = DecisionRouter(
        DisabledDecisionProvider(),
        DecisionProfile(defaults={"web backend": "Python, FastAPI, SQLite"}),
    )
    assert router.decide_for_user("web backend") == "Python, FastAPI, SQLite"
    assert router.decide_for_user("unknown") is None
