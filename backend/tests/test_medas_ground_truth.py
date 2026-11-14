"""The eval's answer key on Medas: one entry per fault switch, and enough ways to trigger each."""

from eval.medas_ground_truth import CONTROL_SETS, FAULTS, LOOK_ALIKES, MedasFault

# The fields of Medas's FaultSettings (medas-api/faults.py), one per switch.
SWITCHES = {
    "empty_retrieval",
    "tool_schema",
    "truncated_prompt",
    "context_tokens",
    "weak_model",
    "upstream_timeout",
}
# The question ids in Medas's dataset/traffic/queries.yaml (Nelev/medas PR 10).
QUESTION_IDS = (
    {f"N{n:02}" for n in range(1, 15)}
    | {f"E{n:02}" for n in range(1, 12)}
    | {f"A{n:02}" for n in range(1, 9)}
)
# The most traces a low-volume fault may send in one input set and still be expected unclustered.
LOW_VOLUME_MAX = 2


def sent(fault: MedasFault) -> list[int]:
    return [len(input_set.ids) * input_set.repeat for input_set in fault.input_sets]


def test_every_switch_has_one_entry_turned_on_by_its_own_variable():
    assert set(FAULTS) == SWITCHES
    for name, fault in FAULTS.items():
        assert list(fault.switch) == [f"FAULT_{name.upper()}"], name


def test_every_fault_has_two_different_input_sets_of_known_questions():
    for name, fault in FAULTS.items():
        assert len(set(fault.input_sets)) >= 2, name
        for input_set in fault.input_sets:
            assert set(input_set.ids) <= QUESTION_IDS, name


def test_a_diagnosis_is_graded_on_a_cause_that_is_not_the_symptom():
    for name, fault in FAULTS.items():
        assert fault.cause != fault.symptom, name


def test_there_is_a_look_alike_pair_of_real_faults():
    assert LOOK_ALIKES
    for first, second in LOOK_ALIKES:
        assert first != second and {first, second} <= set(FAULTS)


def test_there_is_a_low_volume_fault_sent_too_rarely_to_cluster():
    low = [fault for fault in FAULTS.values() if fault.low_volume]

    assert low
    assert all(max(sent(fault)) <= LOW_VOLUME_MAX for fault in low)


def test_the_controls_send_known_questions_and_no_adversarial_ones():
    ids = {question for input_set in CONTROL_SETS for question in input_set.ids}

    assert ids <= QUESTION_IDS
    assert not any(question.startswith("A") for question in ids)
