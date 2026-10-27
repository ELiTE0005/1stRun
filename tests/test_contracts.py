from onestrun.models import Classification, FailureClass, Runbook, RunState, Step


def test_runbook_round_trip():
    rb = Runbook(source_url="file://x.md", steps=[Step(id=1, intent="install", command="pip install x")])
    assert Runbook.model_validate_json(rb.model_dump_json()) == rb


def test_classification_top():
    c = Classification(probabilities={FailureClass.DOCS_BUG: 0.8, FailureClass.ENVIRONMENT: 0.1,
                                      FailureClass.PRODUCT_BUG: 0.05, FailureClass.NEEDS_SECRET: 0.05})
    assert c.top is FailureClass.DOCS_BUG and c.confidence == 0.8


def test_stubs_import():
    import onestrun.budget, onestrun.classify, onestrun.cli, onestrun.executor, onestrun.patch  # noqa: F401
    import onestrun.planner, onestrun.precedents, onestrun.recovery, onestrun.report  # noqa: F401
    import onestrun.sandbox, onestrun.state, onestrun.verify  # noqa: F401
    assert RunState(run_id="r", source_url="u").status.value == "running"
