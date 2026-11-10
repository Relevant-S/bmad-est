#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for architect.py — Layers 1 and 3, the gates, and what gets drawn.

The claims under test are the ones that make a recommendation defensible: that a constraint
removes an option rather than lowering it, that a fact nobody verified is neither a pass nor a
fail, that the house preference cannot overturn a real result, that a platform which cannot run
the application says so, and that nothing reaches the canvas without naming why it is there.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402

arch = F.load("architect", F.ARCH / "scripts" / "architect.py")
caps = F.caps


def built(inputs=None, **kw):
    return arch.build_architecture(kw.pop("inventory", None) or F.clinical(), F.model(),
                                   caps.load_platforms(), inputs or {}, **kw)


STACKS = [
    {"id": "ts", "name": "TypeScript end to end", "axis": "one language across client and server",
     "technologies": ["typescript", "node", "postgres"], "deployable_services": 1,
     "libraries": {"identity": "an identity library", "ai_inference": "a vendor SDK"},
     "currency": {"score": 9.0, "checked": "2026-09-29", "note": "current major, monthly releases"},
     "gaps": []},
    {"id": "py", "name": "Python services with a JS client", "axis": "split runtime per surface",
     "technologies": ["python", "fastapi", "postgres", "typescript"], "deployable_services": 3,
     "libraries": {"identity": "an identity library", "ai_inference": "the vendor SDK",
                   "analytics_store": "a dataframe library"},
     "currency": {"score": 8.0, "checked": "2026-09-29"},
     "gaps": [{"stories": ["F6"], "why": "no native browser runtime"}]},
]


class ConstraintsAreGatesRatherThanPenalties(unittest.TestCase):
    """A hard constraint removes an option; it never merely discounts one.

    These originally asserted that a violating set was still enumerated and then marked
    non-viable. That was the weaker contract: the greedy fill would pull an excluded platform
    into every candidate to cover one capability it alone served, so every set came back
    non-viable and the run reported "no viable platform set" on a backlog three vendors could
    serve. The pool is now filtered before enumeration, and what the constraint cost the
    operator is recorded as a refusal — which is where these now look for it.
    """

    def test_an_excluded_platform_reaches_no_option_at_all(self):
        out = built({"constraints": [{"id": "C1", "kind": "excluded_platform",
                                      "detail": "aws", "basis": "stated"}]})
        self.assertTrue(out["layers"]["platform"]["options"],
                        "the exclusion removed every option — the gate ate the answer")
        for option in out["layers"]["platform"]["options"]:
            self.assertNotIn("aws", option["detail"]["platforms"])
        self.assertNotIn("aws", out["layers"]["platform"]["chosen"] or "")

    def test_a_mandated_platform_is_in_every_set_offered(self):
        out = built({"constraints": [{"id": "C1", "kind": "mandated_platform",
                                      "detail": "supabase", "basis": "stated"}]})
        self.assertTrue(out["layers"]["platform"]["options"], "the mandate removed everything")
        for option in out["layers"]["platform"]["options"]:
            self.assertIn("supabase", option["detail"]["platforms"])

    def test_what_the_constraint_cost_is_still_reported(self):
        """The reason the old shape existed, kept: an operator has to be able to see which
        platform the constraint took off the table, not just that one is missing."""
        out = built({"constraints": [{"id": "C1", "kind": "excluded_platform",
                                      "detail": "aws", "basis": "stated"}]})
        refusal = next(r for r in out["refusals"]
                       if r["kind"] == "platform" and "Amazon" in r["what"])
        self.assertIn("excluded by a hard constraint", refusal["why"])


class AnExcludedPlatformLeavesTheProjectWithOptions(unittest.TestCase):
    """Building sets out of an excluded platform and letting the gate kill them afterwards left
    a project with a banned provider NO viable set at all: every candidate had quietly pulled it
    in to cover one capability, and the run reported "no viable platform set" on a backlog three
    vendors could serve comfortably."""

    def setUp(self):
        self.out = built({"constraints": [{"id": "C1", "kind": "excluded_platform",
                                           "detail": "aws", "basis": "stated"}]})

    def test_a_viable_set_still_exists(self):
        self.assertIsNotNone(self.out["layers"]["platform"]["chosen"])
        self.assertTrue([o for o in self.out["layers"]["platform"]["options"] if o["viable"]])

    def test_the_excluded_platform_appears_in_no_option_at_all(self):
        for option in self.out["layers"]["platform"]["options"]:
            self.assertNotIn("aws", option["detail"]["platforms"])

    def test_it_is_recorded_as_a_refusal_rather_than_silently_absent(self):
        refusal = next(r for r in self.out["refusals"]
                       if r["kind"] == "platform" and "Amazon" in r["what"])
        self.assertIn("kept out of the candidate pool", refusal["why"])

    def test_the_answer_is_a_combination_because_no_single_survivor_covers_it(self):
        chosen = next(o for o in self.out["layers"]["platform"]["options"]
                      if o["id"] == self.out["layers"]["platform"]["chosen"])
        self.assertGreater(len(chosen["detail"]["platforms"]), 1)


class AMandatedPlatformIsRequiredRatherThanMerelyAllowed(unittest.TestCase):
    def test_every_offered_set_contains_it(self):
        out = built({"constraints": [{"id": "C1", "kind": "mandated_platform",
                                      "detail": "supabase", "basis": "stated"}]})
        options = out["layers"]["platform"]["options"]
        self.assertTrue(options, "the mandate removed every option")
        for option in options:
            self.assertIn("supabase", option["detail"]["platforms"])

    def test_a_mandate_no_profile_can_satisfy_says_what_to_do(self):
        out = built({"constraints": [{"id": "C1", "kind": "mandated_platform",
                                      "detail": "oracle-cloud", "basis": "stated"}]})
        refusal = next(r for r in out["refusals"] if r["what"] == "oracle-cloud")
        self.assertIn("a data file, never code", refusal["why"])


class AnUnverifiedFactIsNeitherAPassNorAFail(unittest.TestCase):
    def test_a_certification_gate_against_an_unchecked_profile_is_unevaluated(self):
        """A profile shipping `certifications: {checked: null}` has not said the platform lacks
        the certification. It has said nobody looked."""
        out = built({"constraints": [{"id": "C1", "kind": "certification",
                                      "detail": "HIPAA", "basis": "stated"}]})
        option = out["layers"]["platform"]["options"][0]
        self.assertTrue(option["viable"], "an unverified fact must not fail an option")
        self.assertTrue(option["unevaluated_gates"])
        detail = option["unevaluated_gates"][0]["detail"]
        self.assertIn("never been verified", detail)
        self.assertIn("HIPAA", detail)

    def test_the_compliance_part_scores_null_rather_than_ten(self):
        out = built({"constraints": [{"id": "C1", "kind": "certification",
                                      "detail": "HIPAA", "basis": "stated"}]})
        part = out["layers"]["platform"]["options"][0]["parts"]["constraint_compliance"]
        self.assertIsNone(part["score"], "an unevaluated gate must not score as compliant")

    def test_with_no_constraints_the_part_says_how_many_it_checked(self):
        part = built()["layers"]["platform"]["options"][0]["parts"]["constraint_compliance"]
        self.assertEqual(10.0, part["score"])
        self.assertIn("0 hard constraint(s) evaluated", part["basis"])


class TheHousePreferenceIsAWeight(unittest.TestCase):
    def test_it_cannot_make_a_non_viable_set_viable(self):
        out = built({"house_platforms": ["aws"],
                     "constraints": [{"id": "C1", "kind": "excluded_platform",
                                      "detail": "aws", "basis": "stated"}]})
        for option in out["layers"]["platform"]["options"]:
            if "aws" in option["detail"]["platforms"]:
                self.assertFalse(option["viable"])

    def test_it_says_so_when_the_tiebreak_decided_the_answer(self):
        options = [
            {"id": "a", "name": "House set", "viable": True, "score": 7.0,
             "house_bonus_applied": True, "parts": {}, "detail": {"platforms": ["aws"]}},
            {"id": "b", "name": "Other set", "viable": True, "score": 6.8,
             "parts": {}, "detail": {"platforms": ["vercel"]}},
        ]
        best, why = arch.recommend(options, F.model(), ["aws"])
        self.assertEqual("a", best["id"])
        self.assertIn("chosen on the house preference", why)
        self.assertIn("scored within", why)

    def test_a_material_win_is_reported_as_a_win_and_not_as_a_tiebreak(self):
        options = [
            {"id": "a", "name": "House set", "viable": True, "score": 9.0,
             "house_bonus_applied": True, "parts": {}, "detail": {"platforms": ["aws"]}},
            {"id": "b", "name": "Other set", "viable": True, "score": 6.0,
             "parts": {}, "detail": {"platforms": ["vercel"]}},
        ]
        _, why = arch.recommend(options, F.model(), ["aws"])
        self.assertNotIn("house preference", why)
        self.assertIn("ahead of", why)


class RuntimeFitCatchesAPlatformThatCannotRunTheWork(unittest.TestCase):
    def test_a_runtime_that_cannot_hold_a_process_open_is_penalised_and_names_why(self):
        """Asserted on the option that a request-scoped platform HOSTS, not on a vendor name:
        Vercel and Netlify are indistinguishable for this backlog and now collapse into one
        option with the other as a tied variant, which is the honest presentation of two
        genuinely equivalent choices."""
        out = built()
        request_scoped = {"vercel", "netlify"}
        options = out["layers"]["platform"]["options"]
        hosted = [o for o in options
                  if (o["detail"]["binding"].get("application")
                      or o["detail"]["primary"]) in request_scoped]
        self.assertTrue(hosted, "no request-scoped platform hosted the application anywhere")
        for option in hosted:
            part = option["parts"]["runtime_fit"]
            self.assertLess(part["score"], 10.0)
            self.assertIn("cannot do long_running", part["basis"])
            self.assertIn("async work is built", part["basis"])

    def test_tied_variants_are_kept_rather_than_dropped(self):
        out = built()
        with_variants = [o for o in out["layers"]["platform"]["options"] if o.get("variants")]
        self.assertTrue(with_variants, "nothing tied — the collapsing is untested")
        option = with_variants[0]
        self.assertIn("tied variant", option["name"])
        self.assertTrue(option["variants_differ_in"])
        for variant in option["variants"]:
            self.assertTrue(variant["platforms"])

    def test_options_that_differ_in_shape_are_never_collapsed(self):
        """Two sets can tie on the headline with completely different sub-scores — one strong on
        runtime, the other on reversibility. Folding those into one row would hide the trade."""
        out = built()
        seen = {}
        for option in out["layers"]["platform"]["options"]:
            shape = tuple(sorted((k, v.get("score")) for k, v in option["parts"].items()))
            self.assertNotIn(shape, seen, "two options share an identical sub-score vector")
            seen[shape] = option["id"]

    def test_the_requirement_is_derived_from_the_sourcing_decision_not_assumed(self):
        """Buying the async work removes the requirement, which is the coupling between the
        layers doing its job rather than a fixed list of runtime needs."""
        candidates = {"async_work": {"buy": {
            "name": "A managed queue", "covers": ["F4", "F5"], "gaps": [],
            "health": {"score": 9.0}, "pricing_model": "per request",
            "interface": "standard"}}}
        out = built(candidates=candidates)
        decisions = out["layers"]["sourcing"]["decisions"]
        self.assertEqual("buy", next(d for d in decisions
                                     if d["capability"] == "async_work")["mode"])
        self.assertEqual({}, arch.runtime_needs(decisions))


class TheEnumerationProducesCombinations(unittest.TestCase):
    def test_more_than_one_set_is_offered_and_at_least_one_uses_two_vendors(self):
        out = built()
        options = out["layers"]["platform"]["options"]
        self.assertGreater(len(options), 1)
        self.assertTrue(any(len(o["detail"]["platforms"]) > 1 for o in options),
                        "no combination was ever generated — the design cannot express one")

    def test_a_vendor_adding_nothing_unique_is_refused_with_that_stated(self):
        out = built()
        vendor_refusals = [r for r in out["refusals"] if r["kind"] == "vendor"]
        self.assertTrue(vendor_refusals)
        self.assertIn("adds nothing", vendor_refusals[0]["why"])

    def test_the_enumeration_is_deterministic(self):
        """Two readings of one project have to be comparable."""
        first = [o["id"] for o in built()["layers"]["platform"]["options"]]
        second = [o["id"] for o in built()["layers"]["platform"]["options"]]
        self.assertEqual(first, second)


class Layer3DoesNotReChooseLayer2sVendor(unittest.TestCase):
    """Buying Clerk for identity drew Amazon Cognito on the diagram whenever AWS sorted ahead of
    Clerk in the fill — the two layers disagreeing about a decision one of them had made."""

    def candidates(self, platform="clerk"):
        return {"identity": {"buy": {
            "name": "Clerk", "platform": platform, "covers": ["F1", "F2", "F3"], "gaps": [],
            "health": {"score": 9.0}, "pricing_model": "per MAU", "interface": "standard"}}}

    def test_the_named_vendor_is_bound_to_the_capability(self):
        out = built(candidates=self.candidates())
        chosen = next(o for o in out["layers"]["platform"]["options"]
                      if o["id"] == out["layers"]["platform"]["chosen"])
        self.assertEqual("clerk", chosen["detail"]["binding"]["identity"])

    def test_the_component_drawn_is_the_vendor_that_was_bought(self):
        out = built(candidates=self.candidates())
        identity = next(c for c in out["components"] if c["capability"] == "identity")
        self.assertEqual("clerk", identity["platform"])
        self.assertIn("Clerk", identity["name"])

    def test_an_unpinned_buy_still_falls_to_the_fill(self):
        out = built(candidates=self.candidates(platform=None))
        chosen = next(o for o in out["layers"]["platform"]["options"]
                      if o["id"] == out["layers"]["platform"]["chosen"])
        self.assertIn("identity", chosen["detail"]["binding"])


class TheFillTakesTheBroadestPlatformNotTheFirstAlphabetically(unittest.TestCase):
    def test_the_documented_behaviour_is_the_actual_behaviour(self):
        """platform-binding.md has always said "whichever remaining platform covers the most".
        The code took the alphabetically first platform covering anything, so the broadest
        vendor swept up every leftover purely because of its name."""
        model = F.model()
        platforms = F.caps.load_platforms(F.ARCH / "assets" / "platforms")
        needed = {"application": "x", "relational_store": "x", "object_store": "x",
                  "identity": "x", "cache": "x"}
        sets, _ = arch.enumerate_sets(needed, platforms, model, [])
        self.assertTrue(sets)
        for pset in sets:
            self.assertLessEqual(len(pset["platforms"]), 3,
                                 f"{pset['platforms']} is more vendors than this needs")

    def test_a_preferred_second_makes_combinations_reachable(self):
        """Without it a platform serving nearly everything absorbed every leftover in every set,
        and a two-vendor combination could not be enumerated at all."""
        model = F.model()
        platforms = F.caps.load_platforms(F.ARCH / "assets" / "platforms")
        needed = {"application": "x", "relational_store": "x", "identity": "x"}
        sets, _ = arch.enumerate_sets(needed, platforms, model, [])
        primaries = {s["primary"] for s in sets}
        self.assertGreater(len(primaries), 3, "only a handful of primaries were ever tried")
        self.assertTrue(any(len(s["platforms"]) > 1 for s in sets))


class SprawlCountsOnlyTheVendorsTheProjectChose(unittest.TestCase):
    """Stripe for payments and a deliverability vendor for email are settled capabilities —
    nobody chose them. Charging a set for vendors it had no say over punishes the wrong thing,
    which is the identical mistake `balance()` was already corrected for."""

    def test_a_vendor_forced_by_a_settled_capability_is_not_counted(self):
        out = built()
        for option in out["layers"]["platform"]["options"]:
            part = option["parts"]["vendor_sprawl"]
            self.assertIn("vendor(s) this set chose", part["basis"])
            if "forced by settled capabilities" in part["basis"]:
                self.assertIn("not counted against it", part["basis"])

    def test_the_penalty_keeps_discriminating_past_five_vendors(self):
        """`max(0, 10 - 2.5*(n-1))` was 0 at five vendors and 0 at twenty, so the term stopped
        working exactly where it was needed. A real seven-vendor set scored 0.0 and still won."""
        model = F.model()
        decay = model["vendor_sprawl"]["decay"]
        scores = [round(10.0 * (decay ** max(0, n - 1)), 2) for n in range(1, 12)]
        self.assertEqual(sorted(scores, reverse=True), scores)
        self.assertGreater(scores[6], 0.0, "seven vendors still bottoms out")
        self.assertGreater(scores[6], scores[10], "it stopped discriminating")


class TheHousePreferenceIsOnlyCreditedWhenItDecided(unittest.TestCase):
    """A run reported "chosen on the house preference" for two sets tied at 7.64, both of which
    carried the bonus. The bonus separated neither of them; the sort order did."""

    def options(self, both):
        return [{"id": "a", "name": "A", "viable": True, "score": 7.0,
                 "house_bonus_applied": True, "parts": {}, "detail": {"platforms": ["aws"]}},
                {"id": "b", "name": "B", "viable": True, "score": 6.9,
                 "house_bonus_applied": both, "parts": {}, "detail": {"platforms": ["gcp"]}}]

    def test_it_is_credited_when_only_the_winner_has_it(self):
        _, why = arch.recommend(self.options(False), F.model(), ["aws"])
        self.assertIn("chosen on the house preference", why)

    def test_it_is_not_credited_when_both_have_it(self):
        _, why = arch.recommend(self.options(True), F.model(), ["aws"])
        self.assertNotIn("chosen on the house preference", why)
        self.assertIn("the bonus separated neither of them", why)
        self.assertIn("the order did", why)


class ACatalogueGapIsNotASetGap(unittest.TestCase):
    def test_a_capability_no_profile_serves_is_reported_as_a_catalogue_gap(self):
        out = built()
        gaps = {g["capability"] for g in out["catalogue_gaps"]}
        # sms_push, not payments: the catalogue gained a Stripe profile, so payments is served
        # now. A gap test has to name something genuinely unserved or it stops testing anything.
        self.assertIn("sms_push", gaps)
        self.assertIn("a data file, never code", out["catalogue_gaps"][0]["detail"])

    def test_it_does_not_penalise_any_set(self):
        """A missing Stripe profile is not a flaw in AWS, and scoring it as one penalises every
        candidate identically while telling the reader nothing they can act on."""
        for option in built()["layers"]["platform"]["options"]:
            self.assertNotIn("sms_push", option["detail"]["uncovered"])
            self.assertEqual(10.0, option["parts"]["capability_coverage"]["score"])


class NothingIsDrawnWithoutSayingWhyItIsThere(unittest.TestCase):
    def test_every_component_serves_a_story_a_standing_item_or_an_assumption(self):
        for component in built()["components"]:
            serves = component["serves"]
            self.assertTrue(serves["stories"] or serves["standing_work"] or serves["assumptions"],
                            f"{component['id']} is on the canvas serving nothing")

    def test_a_component_that_serves_nothing_is_refused_rather_than_drawn(self):
        out = built()
        drawn = {c["capability"] for c in out["components"]}
        for decision in out["layers"]["sourcing"]["decisions"]:
            if decision["capability"] not in drawn:
                self.assertTrue(any(r["what"] == decision["name"] for r in out["refusals"]))

    def test_the_graph_runs_from_an_actor_to_the_data(self):
        out = built()
        tiers = {c["id"]: c["tier"] for c in out["components"]}
        self.assertTrue(any(tiers.get(e["from"]) == "actors" for e in out["connections"]))
        self.assertTrue(any(tiers.get(e["to"]) == "data" for e in out["connections"]))

    def test_no_connection_points_at_a_component_that_is_not_drawn(self):
        out = built()
        ids = {c["id"] for c in out["components"]}
        for edge in out["connections"]:
            self.assertIn(edge["from"], ids)
            self.assertIn(edge["to"], ids)


class TheStackLayer(unittest.TestCase):
    def test_a_gap_costs_scope_fit_and_names_the_story(self):
        out = built(stacks=STACKS)
        py = next(o for o in out["layers"]["stack"]["options"] if o["id"] == "py")
        ts = next(o for o in out["layers"]["stack"]["options"] if o["id"] == "ts")
        self.assertLess(py["parts"]["scope_fit"]["score"], ts["parts"]["scope_fit"]["score"])
        self.assertIn("F6", py["parts"]["scope_fit"]["basis"])

    def test_team_fit_is_null_when_the_preferences_are_unanswered(self):
        out = built(stacks=STACKS)
        for option in out["layers"]["stack"]["options"]:
            self.assertIsNone(option["parts"]["team_fit"]["score"])
            self.assertIn("UNANSWERED", option["parts"]["team_fit"]["basis"])

    def test_team_fit_scores_once_the_preferences_are_answered(self):
        prefs = {"delivered_in": ["typescript", "node", "postgres"], "house_platforms": ["aws"],
                 "existing_subscriptions": None, "will_not_run": None, "will_not_buy": None}
        out = built(stacks=STACKS, prefs=prefs)
        ts = next(o for o in out["layers"]["stack"]["options"] if o["id"] == "ts")
        py = next(o for o in out["layers"]["stack"]["options"] if o["id"] == "py")
        self.assertEqual(10.0, ts["parts"]["team_fit"]["score"])
        self.assertLess(py["parts"]["team_fit"]["score"], 10.0)
        self.assertIn("no delivered project for", py["parts"]["team_fit"]["basis"])

    def test_an_unfamiliar_stack_is_penalised_at_the_models_own_coefficient(self):
        prefs = {"delivered_in": ["typescript", "node", "postgres"], "house_platforms": [],
                 "existing_subscriptions": None, "will_not_run": None, "will_not_buy": None}
        out = built(stacks=STACKS, prefs=prefs)
        py = next(o for o in out["layers"]["stack"]["options"] if o["id"] == "py")
        self.assertIn("1.15x", py["parts"]["estimate_impact"]["basis"])
        self.assertTrue(py["detail"]["novel"])

    def test_the_stack_profile_is_derived_and_says_what_it_switches_on(self):
        out = built(stacks=STACKS)
        py = next(o for o in out["layers"]["stack"]["options"] if o["id"] == "py")
        self.assertEqual("multi_service", py["detail"]["stack_profile"])
        self.assertIn("standing-work", py["detail"]["stack_profile_why"])
        ts = next(o for o in out["layers"]["stack"]["options"] if o["id"] == "ts")
        self.assertEqual("standard_saas", ts["detail"]["stack_profile"])

    def test_an_undated_currency_claim_is_not_evidence(self):
        undated = [dict(STACKS[0], currency={"score": 9.0})]
        out = built(stacks=undated)
        part = out["layers"]["stack"]["options"][0]["parts"]["ecosystem_currency"]
        self.assertIsNone(part["score"])
        self.assertIn("without a date", part["basis"])


class TheHandoffIsEvidenceAndNotAVerdict(unittest.TestCase):
    def test_it_carries_the_stack_profile_with_its_reason(self):
        out = built(stacks=STACKS)
        handoff = out["handoff"]["stack_profile"]
        self.assertIn(handoff["value"], ("standard_saas", "multi_service", "mobile_plus_backend"))
        self.assertTrue(handoff["why"])

    def test_a_sourcing_note_describes_the_story_without_deciding_its_band(self):
        candidates = {"identity": {"buy": {
            "name": "A managed identity service", "covers": ["F1", "F2", "F3"], "gaps": [],
            "health": {"score": 9.0}, "pricing_model": "per MAU", "interface": "standard"}}}
        out = built(candidates=candidates)
        notes = [n for n in out["handoff"]["sourcing_notes"] if n["capability"] == "identity"]
        self.assertEqual({"F1", "F2", "F3"}, {n["story"] for n in notes})
        for note in notes:
            self.assertIn("integrates", note["note"])
            self.assertNotIn("size_band", str(note))
            self.assertNotIn("hours", str(note))

    def test_buying_a_capability_does_not_remove_its_stories_from_the_map(self):
        """The most dangerous failure available here: an architecture that 'buys auth' and
        quietly drops the auth stories has re-priced the deal without telling anyone."""
        plain = built()
        candidates = {"identity": {"buy": {
            "name": "A managed identity service", "covers": ["F1", "F2", "F3"], "gaps": [],
            "health": {"score": 9.0}, "pricing_model": "per MAU", "interface": "standard"}}}
        bought = built(candidates=candidates)
        self.assertEqual(plain["capability_map"]["identity"]["stories"],
                         bought["capability_map"]["identity"]["stories"])


class TheUnsourcedSubscoresAreNamed(unittest.TestCase):
    def test_the_run_says_which_scores_rest_on_nothing(self):
        out = built(stacks=STACKS)
        unsourced = out["research"]["unsourced_subscores"]
        self.assertIn("stack.team_fit", unsourced)
        self.assertTrue(any(u.startswith("sourcing.") for u in unsourced))


class ASoftwareAndItsRuntimeAreTwoItems(unittest.TestCase):
    """"Django on Fargate" was one box carrying two products. The split is a field, not a parse:
    the framework comes from the stack layer and the runtime from the platform profile."""

    def design(self, **kw):
        return arch.build_architecture(F.clinical(), F.model(), F.caps.load_platforms(),
                                       dict({"house_platforms": ["aws"]}, **kw))

    def application(self, design):
        return next(c for c in design["components"] if c["capability"] == "application")

    def test_the_framework_is_read_from_the_stack_not_guessed(self):
        """"The first technology" is the LANGUAGE, and a Python logo on the application box says
        nothing a reader did not already know."""
        self.assertEqual("Django", arch.stack_software(
            {"detail": {"technologies": ["python", "django", "htmx"]}}))
        self.assertEqual("Rails", arch.stack_software({"framework": "Rails", "detail": {}}))

    def test_a_stack_that_named_no_framework_returns_none_rather_than_a_guess(self):
        self.assertIsNone(arch.stack_software({"detail": {"technologies": ["python"]}}))
        self.assertIsNone(arch.stack_software(None))

    def test_only_an_explicit_runtime_counts(self):
        """`serves[cap].service` is a description and sometimes a choice — AWS answers
        `application` with "AWS App Runner, ECS Fargate or Lambda", which is three services."""
        self.assertIsNone(arch.runtime_of(
            {"service": "AWS App Runner, ECS Fargate or Lambda"}, "aws", {}))
        found = arch.runtime_of({"service": "x", "runtime": "AWS Fargate",
                                 "runtime_alternatives": ["AWS Lambda"]}, "aws", {})
        self.assertEqual("AWS Fargate", found["service"])
        self.assertEqual(["AWS Lambda"], found["alternatives"])

    def test_the_application_component_names_the_software_and_carries_its_runtime(self):
        component = self.application(self.design())
        runtime = component.get("runs_on") or {}
        self.assertTrue(runtime.get("service"))
        self.assertNotIn(runtime["service"].lower(), component["name"].lower())

    def test_a_bought_component_is_one_thing_and_gains_no_runtime(self):
        design = self.design()
        for component in design["components"]:
            if component.get("mode") == "buy":
                self.assertNotIn("runs_on", component)


class OnlyAChosenThingIsANamedProduct(unittest.TestCase):
    """A capability's own label is not a product, and looking one up in a brand catalogue finds
    somebody else's: "Identity and access" resolves to PING IDENTITY."""

    def design(self):
        return arch.build_architecture(F.clinical(), F.model(), F.caps.load_platforms(),
                                       {"house_platforms": ["aws"]})

    def test_every_component_declares_whether_it_named_a_product(self):
        for component in self.design()["components"]:
            if component.get("mode") == "actor":
                continue
            self.assertIn("product", component)

    def test_a_component_that_chose_nothing_keeps_its_capability_label(self):
        catalogue = F.caps.capabilities(F.model())
        for component in self.design()["components"]:
            if component.get("mode") != "actor" and not component.get("product"):
                self.assertEqual(catalogue[component["capability"]]["name"], component["name"])

    def test_a_named_product_is_the_label(self):
        for component in self.design()["components"]:
            if component.get("product"):
                self.assertEqual(component["product"], component["name"])


class AnOverrideThatNamesNothingIsRecorded(unittest.TestCase):
    """`component_overrides` was declared, echoed into architecture.json and read by nothing. An
    input nobody applies is worse than one that does not exist, because the file says it was
    honoured."""

    def components(self):
        return [{"id": "application", "capability": "application", "name": "Application",
                 "product": None, "platform": "aws", "mode": "build",
                 "serves": {"stories": ["F1"], "standing_work": [], "assumptions": []}}]

    def test_a_name_becomes_the_label_and_the_product(self):
        out, unknown = arch.apply_component_overrides(
            self.components(), {"application": {"name": "Django", "why": "the chosen stack"}})
        self.assertEqual("Django", out[0]["name"])
        self.assertEqual("Django", out[0]["product"])
        self.assertEqual([], unknown)

    def test_the_reason_lands_beside_the_stories(self):
        out, _ = arch.apply_component_overrides(
            self.components(), {"application": {"name": "Django", "why": "PRD 8.1"}})
        self.assertTrue(any("PRD 8.1" in a for a in out[0]["serves"]["assumptions"]))

    def test_a_runtime_can_be_stated_and_removed(self):
        out, _ = arch.apply_component_overrides(
            self.components(), {"application": {"runs_on": {"service": "AWS Fargate"}}})
        self.assertEqual("aws", out[0]["runs_on"]["platform"])
        out, _ = arch.apply_component_overrides(out, {"application": {"runs_on": None}})
        self.assertNotIn("runs_on", out[0])

    def test_an_override_for_an_undrawn_capability_is_reported(self):
        _, unknown = arch.apply_component_overrides(
            self.components(), {"nonesuch": {"name": "Something"}})
        self.assertEqual(["nonesuch"], unknown)


class ADrawnEdgeIsADecisionAboutTheDesign(unittest.TestCase):
    """passenger-seat, 2026-11-10. Every actor was drawn into the WAF, so learners on a mobile app
    entered through the staff console's door; and `reaches` is company-wide, so an API that sends
    nothing itself was still drawn sending email."""

    def build(self, **inputs):
        return arch.build_architecture(F.clinical(), F.model(), F.caps.load_platforms(),
                                       {"house_platforms": ["aws"], **inputs})

    def test_an_actor_that_names_what_it_uses_is_joined_to_that(self):
        out = self.build(actors=[{"name": "Staff", "why": "admin", "reaches": ["web_client"]}])
        edges = {(e["from"], e["to"]) for e in out["connections"] if e["from"].startswith("actor")}
        self.assertEqual({("actor-0", "web_client")}, edges)

    def test_an_actor_naming_nothing_drawn_falls_back_to_the_front_door(self):
        out = self.build(actors=[{"name": "Staff", "why": "admin", "reaches": ["no_such_thing"]}])
        edges = [e for e in out["connections"] if e["from"] == "actor-0"]
        self.assertEqual(1, len(edges))

    def test_a_removed_connection_is_gone_and_says_why(self):
        base = {(e["from"], e["to"]) for e in self.build()["connections"]}
        self.assertIn(("application", "email"), base)
        out = self.build(connection_overrides={"remove": [
            {"from": "application", "to": "email", "why": "sent by the workers"}]})
        edges = {(e["from"], e["to"]) for e in out["connections"]}
        self.assertNotIn(("application", "email"), edges)
        self.assertIn({"what": "application -> email", "kind": "connection",
                       "why": "sent by the workers"}, out["refusals"])
        self.assertEqual("sent by the workers",
                         out["inputs"]["connection_overrides"]["remove"][0]["why"])

    def test_removing_an_edge_that_is_not_drawn_is_recorded(self):
        out = self.build(connection_overrides={"remove": [
            {"from": "application", "to": "no_such_thing", "why": "typo"}]})
        self.assertTrue(any(r["kind"] == "connection_override" for r in out["refusals"]))

    def test_a_removal_without_a_reason_is_refused(self):
        with self.assertRaises(SystemExit):
            self.build(connection_overrides={"remove": [{"from": "application", "to": "email"}]})


class TheRunSaysWhichCopyOfTheSkillWroteIt(unittest.TestCase):
    """A project installs the module by copy, and one real run was reviewed for a day against
    this repository's behaviour before anyone noticed it had executed a copy three weeks old."""

    def test_the_architecture_carries_a_revision(self):
        design = arch.build_architecture(F.clinical(), F.model(), F.caps.load_platforms(),
                                         {"house_platforms": ["aws"]})
        stamp = design.get("produced_by") or {}
        self.assertEqual("est-architect", stamp.get("skill"))
        self.assertRegex(stamp.get("revision", ""), r"^[0-9a-f]{12}$")
        self.assertGreater(stamp.get("files", 0), 20)

    def test_it_changes_when_a_file_does(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "est-architect"
            (root / "scripts").mkdir(parents=True)
            (root / "scripts" / "a.py").write_text("one", encoding="utf-8")
            before = F.caps.revision(root)["revision"]
            (root / "scripts" / "a.py").write_text("two", encoding="utf-8")
            self.assertNotEqual(before, F.caps.revision(root)["revision"])


if __name__ == "__main__":
    unittest.main()
