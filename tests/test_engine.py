"""Pure-engine tests: runnable with unittest or pytest, no database required."""
import copy
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import ValidationError
from backend.app.schema import Strategy, Condition, Expr, Rule, Action, Scenario
from backend.app.engine import evaluate, validation_report, PricingError, config_hash

ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def load(name="car_rental"):
    return Strategy.model_validate(yaml.safe_load((ROOT / "configs" / (name + ".yaml")).read_text())["strategy"])


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.config = load()
        self.context = {a.key: a.default for a in self.config.attributes}

    def calculate(self, config=None, context=None, rate="2000", at=AT, disabled=()):
        return evaluate(config or self.config, rate, self.context if context is None else context, at, disabled)

    def test_all_seeded_expected_results(self):
        for path in (ROOT / "configs").glob("*.yaml"):
            cfg = Strategy.model_validate(yaml.safe_load(path.read_text())["strategy"])
            report = validation_report(cfg, AT)
            self.assertTrue(report["valid"], report)
            self.assertGreater(report["successful_price_tests"], 0)

    def test_car_rental_expected_price(self):
        self.assertEqual(Decimal(self.calculate()["final_price"]), Decimal("14900"))

    def test_hospitality(self):
        result = self.calculate(config=load("hospitality"), context={}, rate="3000")
        self.assertEqual(Decimal(result["final_price"]), Decimal("6480"))

    def test_tour_group_tier(self):
        result = self.calculate(config=load("tours"), context={"people": 20, "package": "standard", "private_guide": False}, rate="2500")
        self.assertEqual(Decimal(result["final_price"]), Decimal("44000"))
        skipped = next(t for t in result["trace"] if t["id"] == "group_discount")
        self.assertEqual(skipped["reason"], "exclusive_group_won_by:large_group")

    def test_percentage_points_not_currency(self):
        result = self.calculate(config=load("rate_demo"), context={}, rate="9.5")
        self.assertEqual(Decimal(result["final_price"]), Decimal("9.25"))
        self.assertEqual(result["output_type"], "rate")

    def test_trace_reconciles(self):
        r = self.calculate()
        self.assertEqual(sum(Decimal(t["delta"]) for t in r["trace"]), Decimal(r["final_price"]))

    def test_exact_replay(self):
        self.assertEqual(self.calculate(), self.calculate())

    def test_input_objects_not_mutated(self):
        before = self.config.model_dump(mode="json")
        context = copy.deepcopy(self.context)
        self.calculate()
        self.assertEqual(self.config.model_dump(mode="json"), before)
        self.assertEqual(self.context, context)

    def test_domain_rename_does_not_change_calculation(self):
        cfg = self.config.model_copy(deep=True)
        cfg.id = "unseen_domain"
        cfg.name = "A completely new domain"
        self.assertEqual(self.calculate()["final_price"], self.calculate(config=cfg)["final_price"])

    def test_unknown_input_rejected(self):
        with self.assertRaises(PricingError): self.calculate(context={**self.context, "injected": 1})

    def test_string_in_numeric_input_rejected(self):
        with self.assertRaises(PricingError): self.calculate(context={**self.context, "rental_days": "8"})

    def test_boolean_in_numeric_input_rejected(self):
        with self.assertRaises(PricingError): self.calculate(context={**self.context, "rental_days": True})

    def test_fractional_integer_rejected(self):
        with self.assertRaises(PricingError): self.calculate(context={**self.context, "rental_days": 2.5})

    def test_unknown_category_rejected(self):
        with self.assertRaises(PricingError): self.calculate(context={**self.context, "vehicle": "Spaceship"})

    def test_bounds_rejected(self):
        with self.assertRaises(PricingError): self.calculate(context={**self.context, "rental_days": 0})

    def test_nan_rejected(self):
        with self.assertRaises(PricingError): self.calculate(context={**self.context, "rental_days": float("nan")})

    def test_invalid_date_rejected(self):
        with self.assertRaises(PricingError): self.calculate(config=load("hospitality"), context={"arrival": "2026-02-30"})

    def test_missing_required_without_default(self):
        cfg = self.config.model_copy(deep=True)
        cfg.attributes[0].default = None
        with self.assertRaises(PricingError): self.calculate(config=cfg, context={})

    def test_defaulted_fields_recorded(self):
        r = self.calculate(context={})
        self.assertEqual(set(r["defaulted_attributes"]), set(self.context))

    def test_disabled_rule_counterfactual(self):
        r = self.calculate(disabled=["weekly_suv"])
        self.assertEqual(Decimal(r["final_price"]), Decimal("16500"))
        self.assertEqual(next(t for t in r["trace"] if t["id"] == "weekly_suv")["reason"], "disabled")

    def test_unknown_disabled_rule_rejected(self):
        with self.assertRaises(PricingError): self.calculate(disabled=["missing"])

    def test_exclusive_group_priority_conflict(self):
        data = self.config.model_dump()
        data["rules"][1]["priority"] = data["rules"][0]["priority"]
        with self.assertRaises(ValidationError): Strategy.model_validate(data)

    def test_non_numeric_expression_field_rejected(self):
        data = self.config.model_dump()
        data["base"] = {"op": "field", "field": "vehicle"}
        with self.assertRaises(ValidationError): Strategy.model_validate(data)

    def test_unsupported_expression_rejected(self):
        with self.assertRaises(ValidationError): Expr(op="eval", value="print('unsafe')")

    def test_division_by_zero(self):
        cfg = self.config.model_copy(deep=True)
        cfg.base = Expr(op="divide", args=[Expr(value="1"), Expr(value="0")])
        with self.assertRaises(PricingError): self.calculate(config=cfg)

    def test_infeasible_bounds(self):
        cfg = self.config.model_copy(deep=True)
        cfg.constraints.minimum = Expr(value="50000")
        cfg.constraints.maximum = Expr(value="10000")
        with self.assertRaises(PricingError): self.calculate(config=cfg)

    def test_infeasible_rounding(self):
        cfg = self.config.model_copy(deep=True)
        cfg.constraints.minimum = Expr(value="14900.1")
        cfg.constraints.maximum = Expr(value="14900.9")
        with self.assertRaises(PricingError): self.calculate(config=cfg)

    def test_rounding_stays_inside_all_bounds(self):
        cfg = self.config.model_copy(deep=True)
        cfg.constraints.minimum = Expr(value="14900.1")
        cfg.constraints.maximum = Expr(value="14902.4")
        self.assertEqual(Decimal(self.calculate(config=cfg)["final_price"]), Decimal("14901"))

    def test_effective_timestamp_is_explicit(self):
        cfg = self.config.model_copy(deep=True)
        cfg.rules[0].starts_at = datetime(2027, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(Decimal(self.calculate(config=cfg)["final_price"]), Decimal("16500"))

    def test_end_timestamp_is_exclusive(self):
        cfg = self.config.model_copy(deep=True)
        cfg.rules[0].ends_at = AT
        self.assertEqual(Decimal(self.calculate(config=cfg)["final_price"]), Decimal("16500"))

    def test_timezone_required(self):
        with self.assertRaises(PricingError): self.calculate(at=datetime(2026, 10, 15))

    def test_nested_and_or_not(self):
        cfg = self.config.model_copy(deep=True)
        cfg.rules[0].when = Condition(op="all", children=[Condition(op="any", children=[Condition(op="eq", field="vehicle", value="SUV"), Condition(op="eq", field="vehicle", value="Sedan")]), Condition(op="not", children=[Condition(op="eq", field="member", value=True)])])
        self.assertEqual(self.calculate(config=cfg)["final_price"], self.calculate()["final_price"])

    def test_percentage_basis_changes_results(self):
        cfg = self.config.model_copy(deep=True)
        cfg.rules = [Rule(id="fixed", name="Fixed charge", priority=1, action=Action(type="add", value=Expr(value="1000"))), Rule(id="discount", name="Base discount", priority=2, action=Action(type="percent", basis="base_amount", value=Expr(value="-10")))]
        first = Decimal(self.calculate(config=cfg)["final_price"])
        cfg.rules[1].action.basis = "subtotal"
        second = Decimal(self.calculate(config=cfg)["final_price"])
        self.assertEqual(first-second, Decimal("100"))

    def test_failed_expected_case_blocks_validation(self):
        cfg = self.config.model_copy(deep=True)
        cfg.scenarios[0].expected_price = "1"
        self.assertFalse(validation_report(cfg, AT)["valid"])

    def test_expected_error_case(self):
        cfg = self.config.model_copy(deep=True)
        cfg.scenarios.append(Scenario(name="Invalid rental", base_rate="2000", context={**self.context, "rental_days": 0}, expected_error=True))
        self.assertTrue(validation_report(cfg, AT)["valid"])

    def test_configuration_hash_changes(self):
        cfg = self.config.model_copy(deep=True)
        cfg.rules[0].action.value = Expr(value="-12")
        self.assertNotEqual(config_hash(cfg), config_hash(self.config))


if __name__ == "__main__":
    unittest.main(verbosity=2)
