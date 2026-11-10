"""The eval's scores, on hand-made results where the right number is plain to see."""

from eval.metrics import score

# Three timeouts, two bad tool calls, one store failure (the rare one) and one healthy request.
KINDS = {
    "t1": "source_timeout",
    "t2": "source_timeout",
    "t3": "source_timeout",
    "a1": "tool_arguments",
    "a2": "tool_arguments",
    "s1": "store_down",
    "h1": "healthy",
}
FAILING = {"t1": "sp_t1", "t2": "sp_t2", "t3": "sp_t3", "a1": "sp_a1", "a2": "sp_a2", "s1": "sp_s1"}


def cluster(cluster_id: str, *trace_ids: str) -> dict:
    return {"cluster_id": cluster_id, "trace_ids": list(trace_ids)}


def diagnosis(cluster_id: str, category: str, cites: tuple[str, str], check: str = "valid") -> dict:
    return {
        "cluster_id": cluster_id,
        "category": category,
        "evidence_check": check,
        "evidence": [{"trace_id": cites[0], "span_id": cites[1]}],
    }


def result(clusters: list[dict], diagnoses: list[dict]) -> dict:
    return {
        "kinds": KINDS,
        "failing_spans": FAILING,
        "clusters": clusters,
        "diagnoses": diagnoses,
        "model_usage": [{"calls": 1, "tokens": 100, "cost_usd": 0.01}] * len(diagnoses),
        "seconds": 2.0,
    }


def test_a_run_that_gets_everything_right_scores_full_marks():
    scores = score(
        result(
            [cluster("c0", "t1", "t2", "t3"), cluster("c1", "a1", "a2"), cluster("c2", "s1")],
            [
                diagnosis("c0", "infra_error", ("t1", "sp_t1")),
                diagnosis("c1", "tool_schema_error", ("a2", "sp_a2")),
                diagnosis("c2", "infra_error", ("s1", "sp_s1")),
            ],
        )
    )

    assert scores == {
        "detection": (3, 3),
        "purity": (6, 6),
        "separation": (3, 3),
        "rare_recall": (1, 1),
        "trace_recall": (6, 6),
        "false_alarms": 0,
        "category_accuracy": (3, 3),
        "evidence_valid": (3, 3),
        "evidence_relevant": (3, 3),
        "calls": 3,
        "tokens": 300,
        "cost_usd": 0.03,
        "seconds": 2.0,
    }


def test_mixed_clusters_split_faults_and_wrong_answers_each_cost_their_own_score():
    scores = score(
        result(
            [
                cluster("c0", "t1", "t2", "a1"),  # a bad tool call among the timeouts
                cluster("c1", "t3", "h1"),  # a timeout split off, with a healthy request
                cluster("c2", "a2"),
                cluster("c3", "s1"),  # the rare one, never diagnosed
            ],
            [
                diagnosis("c0", "infra_error", ("a1", "sp_a1")),
                diagnosis("c1", "model_quality", ("t3", "not_the_failing_span")),
                diagnosis("c2", "tool_schema_error", ("a2", "sp_a2"), check="unsupported"),
            ],
        )
    )

    assert scores["detection"] == (2, 3)  # store_down has no diagnosis
    assert scores["purity"] == (5, 7)  # c0 2 of 3, c1 1 of 2, c2 and c3 whole
    assert scores["separation"] == (1, 3)  # only store_down sits alone in one cluster
    assert scores["rare_recall"] == (0, 1)
    assert scores["trace_recall"] == (6, 6)  # every faulty trace is in some cluster
    assert scores["false_alarms"] == 1  # c1 holds the healthy request
    assert scores["category_accuracy"] == (2, 3)  # c1 is a timeout, not model_quality
    assert scores["evidence_valid"] == (2, 3)
    assert scores["evidence_relevant"] == (2, 3)


def test_a_false_alarm_and_a_fault_never_collected_are_counted_apart_from_the_answers():
    scores = score(
        result(
            [cluster("c0", "t1", "t2", "t3"), cluster("c1", "h1")],  # the others never collected
            [
                diagnosis("c0", "infra_error", ("t1", "sp_t1")),
                diagnosis("c1", "model_quality", ("h1", "sp_h1")),  # nothing was wrong with h1
            ],
        )
    )

    assert scores["false_alarms"] == 1
    assert scores["category_accuracy"] == (1, 1)  # the false alarm is not also a wrong answer
    assert scores["detection"] == (1, 3)
    assert scores["trace_recall"] == (3, 6)


def test_a_judged_file_adds_the_cause_scores_and_how_often_the_judge_agrees_with_a_person():
    judged = result(
        [cluster("c0", "t1", "t2", "t3"), cluster("c1", "a1", "a2"), cluster("c2", "s1")],
        [
            diagnosis("c0", "infra_error", ("t1", "sp_t1")),
            diagnosis("c1", "tool_schema_error", ("a2", "sp_a2")),
            diagnosis("c2", "infra_error", ("s1", "sp_s1")),
        ],
    )
    judged["verdicts"] = [
        {"cluster_id": "c0", "score": 2},
        {"cluster_id": "c1", "score": 1},
        {"cluster_id": "c2", "score": 0},
    ]
    assert "cause_accuracy" not in score(result([], []))  # nothing judged, nothing claimed

    scores = score(judged)
    assert scores["cause_accuracy"] == (1, 3)
    assert scores["root_cause_mean"] == 1.0
    assert "judge_agreement" not in scores

    judged["human"] = {"c0": 2, "c1": 2}  # c2 was not graded by hand
    assert score(judged)["judge_agreement"] == (1, 2)
