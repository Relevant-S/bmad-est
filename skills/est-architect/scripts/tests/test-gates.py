#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for gates.py — the three verification stops.

The brief was "propose several options, score each 0-10 with reasoning, and wait for me to
verify." The first real run honoured that for one layer of three: the stack choice, which
reversed a PRD's stated stack and invalidated a priced estimate, and a seven-vendor platform
set were decided and reported. These tests hold the fix to the brief.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402

arch = F.load("architect", F.ARCH / "scripts" / "architect.py")
gates = F.load("gates", F.ARCH / "scripts" / "gates.py")

STACKS = [
    {"id": "ts", "name": "TypeScript end to end", "axis": "one language throughout",
     "technologies": ["typescript", "node", "postgres"], "deployable_services": 1,
     "libraries": {"identity": "a library"},
     "currency": {"score": 9.0, "checked": "2026-09-29"}, "gaps": []},
    {"id": "py", "name": "Python services", "axis": "split runtime per surface",
     "technologies": ["python", "django", "celery"], "deployable_services": 3,
     "libraries": {"identity": "a library"},
     "currency": {"score": 8.0, "checked": "2026-09-29"}, "gaps": []},
]


def built(inventory=None, **kw):
    kw.setdefault("stacks", STACKS)
    return arch.build_architecture(inventory or F.clinical(), F.model(),
                                   F.caps.load_platforms(F.ARCH / "assets" / "platforms"),
                                   kw.pop("inputs", None) or {"house_platforms": ["aws"]}, **kw)


class TheGatesRunInOrderAndBlock(unittest.TestCase):
    def test_nothing_is_confirmed_by_default(self):
        out = built()
        for layer in gates.ORDER:
            self.assertFalse(out["layers"][layer]["confirmed"])
            self.assertIsNone(out["layers"][layer]["confirmed_by"])

    def test_each_confirmation_advances_exactly_one_gate(self):
        self.assertEqual("stack", built()["gate"]["pending"])
        self.assertEqual("sourcing", built(stack_confirmed=True)["gate"]["pending"])
        self.assertEqual("platform", built(stack_confirmed=True,
                                           sourcing_confirmed=True)["gate"]["pending"])
        self.assertIsNone(built(stack_confirmed=True, sourcing_confirmed=True,
                                platform_confirmed=True)["gate"]["pending"])

    def test_confirming_a_later_gate_does_not_skip_an_earlier_one(self):
        """Each layer constrains the next, so a platform set confirmed against an unsettled
        stack is a decision made on a premise that is about to change."""
        out = built(platform_confirmed=True)
        self.assertEqual("stack", out["gate"]["pending"])

    def test_a_confirmed_layer_records_who_confirmed_it(self):
        out = built(stack_confirmed=True)
        self.assertEqual("operator", out["layers"]["stack"]["confirmed_by"])


class TheStackGateShowsWhatIsBeingChosen(unittest.TestCase):
    def setUp(self):
        self.out = built()
        self.doc = gates.render("stack", self.out, F.clinical())

    def test_it_names_itself_as_the_first_of_three(self):
        self.assertIn("Gate 1 of 3", self.doc)
        self.assertIn("Nothing proceeds until you confirm", self.doc)

    def test_every_option_appears_with_its_score(self):
        for option in STACKS:
            self.assertIn(option["name"], self.doc)

    def test_every_sub_score_carries_the_number_it_rests_on(self):
        self.assertIn("| Sub-score | Score | Weight | Rests on |", self.doc)
        self.assertIn("scope fit", self.doc)

    def test_an_unscored_sub_score_shows_a_dash_rather_than_a_number(self):
        self.assertIn("| team fit | — |", self.doc)

    def test_it_says_how_to_continue(self):
        self.assertIn("--stack-confirmed", self.doc)


class AContradictedSourceIsCalledOut(unittest.TestCase):
    """The run reversed a PRD's Django stack for Next.js. That invalidates an estimate already
    priced on it — a commercial consequence the operator has to see while choosing."""

    def inventory_stating_django(self):
        inventory = F.clinical()
        inventory["assumptions"] = [
            {"text": "Operator decision: the stack is the PRD section 8.1 stack — Python 3.12 / "
                     "Django 5 + DRF monolith, Django templates + HTMX, Celery + Redis."}]
        return inventory

    def test_it_fires_when_the_winner_shares_nothing_with_the_recorded_stack(self):
        inventory = self.inventory_stating_django()
        out = built(inventory, inputs={"house_platforms": ["aws"], "stack_choice": "ts"})
        doc = gates.render("stack", out, inventory)
        self.assertIn("This reverses what the sources say", doc)
        self.assertIn("should be", doc)
        self.assertIn("re-run", doc)
        self.assertIn("Django", doc)

    def test_it_stays_quiet_when_the_winner_is_the_recorded_stack(self):
        inventory = self.inventory_stating_django()
        out = built(inventory, inputs={"house_platforms": ["aws"], "stack_choice": "py"})
        doc = gates.render("stack", out, inventory)
        self.assertNotIn("This reverses what the sources say", doc)

    def test_it_stays_quiet_when_no_source_states_a_stack(self):
        out = built()
        self.assertNotIn("This reverses what the sources say",
                         gates.render("stack", out, F.clinical()))

    def test_a_conflict_counts_as_a_recorded_stack_too(self):
        inventory = F.clinical()
        inventory["conflicts"] = [{"topic": "Technology stack",
                                   "detail": "PRD says Django and Celery; the workbook says "
                                             "Next.js and Supabase."}]
        self.assertTrue(gates.stated_stack(inventory))


class TheModelsOwnDisagreementIsLabelledAsItsOwn(unittest.TestCase):
    """A run put two of its own proposals behind an option labelled `(Recommended)`, the
    operator ticked it, and the log recorded them as operator corrections."""

    def proposals(self):
        return {"house_platforms": ["aws"],
                "model_counter_proposals": {
                    "async_work": {"mode": "adopt",
                                   "why": "the team has delivered this queue before"}}}

    def test_a_counter_proposal_does_not_change_the_decision(self):
        out = built(inputs=self.proposals())
        decision = next(d for d in out["layers"]["sourcing"]["decisions"]
                        if d["capability"] == "async_work")
        self.assertTrue(decision["model_counter_proposal"])
        self.assertEqual(decision["scored_mode"], decision["mode"],
                         "the scored answer must stand until a human changes it")
        self.assertEqual("adopt", decision["proposed_mode"])

    def test_the_gate_presents_it_as_the_workflows_proposal(self):
        doc = gates.render("sourcing", built(inputs=self.proposals()), None)
        self.assertIn("Where the workflow disagrees with its own scoring", doc)
        self.assertIn("the workflow's proposals, not yours", doc)
        self.assertIn("delivered this queue before", doc)

    def test_an_operator_override_is_recorded_as_the_operators(self):
        out = built(inputs={"house_platforms": ["aws"],
                            "sourcing_overrides": {"async_work": {
                                "mode": "adopt", "why": "we have run this before"}}})
        decision = next(d for d in out["layers"]["sourcing"]["decisions"]
                        if d["capability"] == "async_work")
        self.assertEqual("operator", decision["source"])
        self.assertEqual("adopt", decision["mode"])
        self.assertIn("operator chose adopt", decision["why"])
        self.assertIn(decision["scored_mode"], ("build", "adopt", "buy"))


class TheSourcingAndPlatformGates(unittest.TestCase):
    def test_the_sourcing_gate_carries_the_batch_and_the_balance(self):
        doc = gates.render("sourcing", built(), None)
        self.assertIn("Gate 2 of 3", doc)
        self.assertIn("Not a queue", doc)
        self.assertIn("--sourcing-confirmed", doc)

    def test_a_balance_finding_is_presented_as_a_question_to_answer(self):
        out = built()
        out["layers"]["sourcing"]["balance"]["findings"] = [
            {"kind": "all_buy", "detail": "5 of 5 bought."}]
        doc = gates.render("sourcing", out, None)
        self.assertIn("all_buy", doc)
        self.assertIn("a question the report has to answer, not an error", doc)

    def test_the_platform_gate_leads_with_sprawl_runtime_and_reversibility(self):
        doc = gates.render("platform", built(), None)
        self.assertIn("Gate 3 of 3", doc)
        for column in ("Vendor sprawl", "Runtime fit", "Reversibility"):
            self.assertIn(column, doc)
        self.assertIn("--platform-confirmed", doc)

    def test_refused_vendors_are_shown_at_the_gate_not_only_in_the_report(self):
        doc = gates.render("platform", built(), None)
        self.assertIn("Vendors refused", doc)

    def test_tied_variants_are_named_at_the_gate(self):
        out = built()
        doc = gates.render("platform", out, None)
        if any(o.get("variants") for o in out["layers"]["platform"]["options"]):
            self.assertIn("Tied variants, differing in", doc)


class TheRunReproducesFromItsOwnDeliverable(unittest.TestCase):
    def test_the_override_payload_is_echoed_into_architecture_json(self):
        """A real run's overrides lived only in a scratch file that was not among the copied
        deliverables, so the folder a reader was handed could not rebuild what it described."""
        inputs = {"house_platforms": ["aws"],
                  "capability_overrides": {"cache": {"set": [], "why": "no story asks for one"}},
                  "sourcing_overrides": {"async_work": {"mode": "adopt", "why": "delivered"}}}
        echoed = built(inputs=inputs)["inputs"]
        self.assertEqual(inputs["capability_overrides"], echoed["capability_overrides"])
        self.assertEqual(inputs["sourcing_overrides"], echoed["sourcing_overrides"])


if __name__ == "__main__":
    unittest.main()
