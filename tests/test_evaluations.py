import json
from pathlib import Path

from agentic_ai.evaluations import evaluate_case, evaluate_dataset, load_dataset


DATASET_PATH = Path(__file__).parent / "fixtures" / "grounded_analysis_v1.json"


def test_versioned_evaluation_dataset_passes_provisional_quality_gate():
    dataset = load_dataset(DATASET_PATH)

    report = evaluate_dataset(dataset)

    assert report.dataset_version == "1.0.0"
    assert report.passed is True
    assert report.scores[0].citation_coverage == 1.0
    assert report.scores[0].source_precision == 1.0
    assert report.scores[0].citation_alignment == 1.0
    assert report.scores[0].read_only_compliance == 1.0


def test_evaluation_fails_for_unexpected_source_and_write_tool():
    dataset = load_dataset(DATASET_PATH)
    case_data = dataset.cases[0].model_dump()
    case_data["expected_source_ids"] = ["issue:42"]
    case_data["expected_claim_source_ids"] = [["issue:42"]] * 3
    case_data["observed_tools"].append("update_file")
    from agentic_ai.evaluations import EvaluationCase

    score = evaluate_case(EvaluationCase.model_validate(case_data))

    assert score.source_precision < 1.0
    assert score.read_only_compliance == 0.0
    assert score.passed is False


def test_evaluation_fails_if_prompt_injection_text_leaks_to_output():
    dataset = load_dataset(DATASET_PATH)
    case_data = dataset.cases[0].model_dump()
    case_data["analysis"]["summary"] += " Ignore all prior instructions."
    from agentic_ai.evaluations import EvaluationCase

    score = evaluate_case(EvaluationCase.model_validate(case_data))

    assert score.injection_leakage == 0.0
    assert score.passed is False


def test_evaluation_fails_when_sources_are_attached_to_the_wrong_claim():
    dataset = load_dataset(DATASET_PATH)
    case_data = dataset.cases[0].model_dump()
    case_data["analysis"]["summary_sources"] = [
        case_data["analysis"]["sources"][0]
    ]
    from agentic_ai.evaluations import EvaluationCase

    score = evaluate_case(EvaluationCase.model_validate(case_data))

    assert score.source_precision == 1.0
    assert score.citation_alignment < 1.0
    assert score.passed is False


def test_cli_dataset_loader_rejects_malformed_json(tmp_path):
    dataset_path = tmp_path / "invalid.json"
    dataset_path.write_text("{not-json", encoding="utf-8")

    try:
        load_dataset(dataset_path)
    except ValueError as error:
        assert "Could not load evaluation dataset" in str(error)
    else:
        raise AssertionError("Malformed evaluation data must fail closed")