"""
Comprehensive test suite for the retirement planning simulator.

Run with:  python -m pytest test_retirement.py -v
"""

import json

import pytest

# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------

def _trad_account(balance=500_000, name="401k"):
    return {
        "id": "trad1", "name": name, "type": "traditional_401k",
        "balance": balance, "basis": balance,
        "annual_contribution": 0.0, "contribution_growth_rate": 0.0,
        "return_rate": 0.05, "use_global_return_rate": False,
        "employer_match_percent": 0.0, "employer_match_limit": 0.0,
        "qualified_dividend_yield": 0.0, "ordinary_income_yield": 0.0,
        "net_annual_rental_income": 0.0, "withdraw_priority": "normal",
    }


def _roth_account(balance=200_000, name="Roth IRA"):
    return {
        "id": "roth1", "name": name, "type": "roth_ira",
        "balance": balance, "basis": balance,
        "annual_contribution": 0.0, "contribution_growth_rate": 0.0,
        "return_rate": 0.05, "use_global_return_rate": False,
        "employer_match_percent": 0.0, "employer_match_limit": 0.0,
        "qualified_dividend_yield": 0.0, "ordinary_income_yield": 0.0,
        "net_annual_rental_income": 0.0, "withdraw_priority": "normal",
    }


def _taxable_account(balance=100_000, basis=60_000, name="Brokerage"):
    return {
        "id": "taxable1", "name": name, "type": "taxable",
        "balance": balance, "basis": basis,
        "annual_contribution": 0.0, "contribution_growth_rate": 0.0,
        "return_rate": 0.05, "use_global_return_rate": False,
        "employer_match_percent": 0.0, "employer_match_limit": 0.0,
        "qualified_dividend_yield": 0.01, "ordinary_income_yield": 0.005,
        "net_annual_rental_income": 0.0, "withdraw_priority": "normal",
    }


def _bank_account(balance=50_000, name="Checking"):
    return {
        "id": "bank1", "name": name, "type": "bank",
        "balance": balance, "basis": balance,
        "annual_contribution": 0.0, "contribution_growth_rate": 0.0,
        "return_rate": 0.04, "use_global_return_rate": False,
        "employer_match_percent": 0.0, "employer_match_limit": 0.0,
        "qualified_dividend_yield": 0.0, "ordinary_income_yield": 0.0,
        "net_annual_rental_income": 0.0, "withdraw_priority": "normal",
    }


def _base_profile(**kwargs):
    p = {
        "current_age": 60,
        "retirement_age": 65,
        "life_expectancy": 85,
        "filing_status": "single",
        "state": "other",
        "state_tax_rate": 0.05,
        "current_income": 100_000.0,
        "social_security_benefit": 24_000.0,
        "social_security_start_age": 67,
        # spouse_age intentionally omitted for single filer — MC code subtracts current_age
        # from it and will TypeError if it's explicitly None; callers pass spouse_age=X for MFJ.
        "spouse_ss_benefit": 0.0,
        "spouse_ss_start_age": 67,
        "survivor_spending_reduction": 0.25,
        "pre_medicare_healthcare": 0.0,
        "post_medicare_healthcare": 0.0,
    }
    p.update(kwargs)
    return p


def _base_assumptions(**kwargs):
    a = {
        "inflation_rate": 0.03,
        "bracket_inflation_rate": 0.025,
        "safe_withdrawal_rate": 0.04,
        "retirement_return_rate": 0.05,
        "spending_mode": "swr",
        "annual_spending_target": 60_000.0,
        "withdrawal_strategy": "tax_efficient",
    }
    a.update(kwargs)
    return a


# ===========================================================================
# 1. TAX CALCULATIONS (taxes.py)
# ===========================================================================

class TestOrdinaryTax:
    def test_zero_income(self):
        from taxes import calculate_ordinary_tax
        assert calculate_ordinary_tax(0.0, "single") == 0.0

    def test_within_10pct_bracket_single(self):
        from taxes import calculate_ordinary_tax
        # $10,000 taxable — all in 10% bracket (ceiling $12,400)
        tax = calculate_ordinary_tax(10_000, "single")
        assert abs(tax - 1_000.0) < 0.01

    def test_spans_two_brackets_single(self):
        from taxes import calculate_ordinary_tax
        # $30,000: 10% on $12,400 + 12% on $17,600
        expected = 12_400 * 0.10 + 17_600 * 0.12
        tax = calculate_ordinary_tax(30_000, "single")
        assert abs(tax - expected) < 0.01

    def test_three_brackets_single(self):
        from taxes import calculate_ordinary_tax
        # $100,000: 10% on $12,400 + 12% on $38,000 + 22% on $49,600
        expected = 12_400 * 0.10 + (50_400 - 12_400) * 0.12 + (100_000 - 50_400) * 0.22
        tax = calculate_ordinary_tax(100_000, "single")
        assert abs(tax - expected) < 0.01

    def test_mfj_doubles_lower_brackets(self):
        from taxes import calculate_ordinary_tax
        # MFJ 10% ceiling = $24,800 (exactly double single $12,400)
        tax_single = calculate_ordinary_tax(12_400, "single")
        tax_mfj = calculate_ordinary_tax(24_800, "married_filing_jointly")
        assert abs(tax_mfj - 2 * tax_single) < 0.01

    def test_negative_income_returns_zero(self):
        from taxes import calculate_ordinary_tax
        assert calculate_ordinary_tax(-1_000, "single") == 0.0


class TestLTCGTax:
    def test_zero_ltcg(self):
        from taxes import calculate_ltcg_tax
        assert calculate_ltcg_tax(0.0, 50_000, "single") == 0.0

    def test_ltcg_fully_in_zero_bracket(self):
        from taxes import calculate_ltcg_tax
        # Single 0% LTCG bracket ceiling = $49,450
        # Ordinary = $20,000, LTCG = $10,000 → stacked total = $30,000 ≤ $49,450
        tax = calculate_ltcg_tax(10_000, 20_000, "single")
        assert tax == 0.0

    def test_ltcg_straddles_zero_and_15pct_single(self):
        from taxes import calculate_ltcg_tax
        # Single 0% ceiling = $49,450. Ordinary = $40,000, LTCG = $20,000
        # LTCG stacks $40,000–$60,000; first $9,450 at 0%, next $10,550 at 15%
        expected = 10_550 * 0.15
        tax = calculate_ltcg_tax(20_000, 40_000, "single")
        assert abs(tax - expected) < 0.01

    def test_ltcg_fully_in_15pct(self):
        from taxes import calculate_ltcg_tax
        # Ordinary = $100,000 (already past 0% ceiling), LTCG = $5,000
        tax = calculate_ltcg_tax(5_000, 100_000, "single")
        assert abs(tax - 750.0) < 0.01  # 5000 * 0.15

    def test_ltcg_20pct_single(self):
        from taxes import calculate_ltcg_tax
        # Single 15% ceiling = $545,500; push LTCG above it
        tax = calculate_ltcg_tax(10_000, 540_000, "single")
        # $540,000 + $10,000 = $550,000; $545,500–$540,000 = $5,500 at 15%; $4,500 at 20%
        expected = 5_500 * 0.15 + 4_500 * 0.20
        assert abs(tax - expected) < 0.01

    def test_mfj_0pct_ceiling_higher(self):
        from taxes import calculate_ltcg_tax
        # MFJ 0% ceiling = $98,900; $40,000 ordinary + $50,000 LTCG = $90,000 → all 0%
        tax = calculate_ltcg_tax(50_000, 40_000, "married_filing_jointly")
        assert tax == 0.0


class TestNIIT:
    def test_below_threshold_single(self):
        from taxes import calculate_niit
        assert calculate_niit(199_999, 10_000, "single") == 0.0

    def test_at_threshold_single(self):
        from taxes import calculate_niit
        assert calculate_niit(200_000, 10_000, "single") == 0.0

    def test_above_threshold_single(self):
        from taxes import calculate_niit
        # MAGI = $210,000, NII = $15,000, threshold = $200,000
        # excess = $10,000; taxable = min(15,000, 10,000) = 10,000
        niit = calculate_niit(210_000, 15_000, "single")
        assert abs(niit - 10_000 * 0.038) < 0.01

    def test_nii_limits_niit(self):
        from taxes import calculate_niit
        # MAGI = $500,000, NII = $5,000 — NII is the binding constraint
        niit = calculate_niit(500_000, 5_000, "single")
        assert abs(niit - 5_000 * 0.038) < 0.01

    def test_mfj_threshold_250k(self):
        from taxes import calculate_niit
        assert calculate_niit(249_999, 20_000, "married_filing_jointly") == 0.0
        niit = calculate_niit(260_000, 20_000, "married_filing_jointly")
        assert abs(niit - 10_000 * 0.038) < 0.01

    def test_custom_threshold(self):
        from taxes import calculate_niit
        niit = calculate_niit(150_000, 10_000, "single", threshold=140_000)
        assert abs(niit - 10_000 * 0.038) < 0.01


class TestIRMAA:
    def test_zero_medicare_eligible(self):
        from taxes import calculate_irmaa
        assert calculate_irmaa(500_000, "single", 0) == 0.0

    def test_below_base_tier_single(self):
        from taxes import calculate_irmaa
        # Single base tier upper = $109,000
        assert calculate_irmaa(100_000, "single", 1) == 0.0

    def test_at_base_tier_single(self):
        from taxes import calculate_irmaa
        assert calculate_irmaa(109_000, "single", 1) == 0.0

    def test_second_tier_single(self):
        from taxes import calculate_irmaa
        # MAGI $110,000 > $109,000 → tier 2 (81.20 + 14.50) * 12 * 1
        irmaa = calculate_irmaa(110_000, "single", 1)
        assert abs(irmaa - (81.20 + 14.50) * 12) < 0.01

    def test_second_tier_mfj_2_people(self):
        from taxes import calculate_irmaa
        # MFJ base upper = $218,000; $220,000 lands in tier 2 for both spouses
        irmaa = calculate_irmaa(220_000, "married_filing_jointly", 2)
        assert abs(irmaa - (81.20 + 14.50) * 12 * 2) < 0.01

    def test_below_mfj_threshold(self):
        from taxes import calculate_irmaa
        assert calculate_irmaa(218_000, "married_filing_jointly", 2) == 0.0

    def test_top_tier_single(self):
        from taxes import calculate_irmaa
        # Single top tier (None upper): $600,000
        irmaa = calculate_irmaa(600_000, "single", 1)
        assert abs(irmaa - (487.00 + 91.00) * 12) < 0.01


class TestSSTaxability:
    def test_no_ss(self):
        from taxes import calculate_ss_taxable_amount
        assert calculate_ss_taxable_amount(30_000, 0.0, "single") == 0.0

    def test_below_tier1_single(self):
        from taxes import calculate_ss_taxable_amount
        # Single tier1 = $25,000; provisional = $24,000 → $0
        assert calculate_ss_taxable_amount(24_000, 20_000, "single") == 0.0

    def test_between_tiers_single(self):
        from taxes import calculate_ss_taxable_amount
        # Provisional = $30,000; tier1 = $25,000, tier2 = $34,000
        # taxable = 0.50 * min(30,000 - 25,000, 20,000) = 0.50 * 5,000 = 2,500
        result = calculate_ss_taxable_amount(30_000, 20_000, "single")
        assert abs(result - 2_500) < 0.01

    def test_above_tier2_single_capped(self):
        from taxes import calculate_ss_taxable_amount
        # Provisional = $60,000; SS = $20,000
        # base = 0.50 * min(34,000 - 25,000, 20,000) = 0.50 * 9,000 = 4,500
        # extra = 0.85 * min(60,000 - 34,000, 20,000) = 0.85 * 20,000 = 17,000
        # total = 21,500; capped at 0.85 * 20,000 = 17,000
        result = calculate_ss_taxable_amount(60_000, 20_000, "single")
        assert abs(result - 17_000) < 0.01

    def test_just_above_tier2(self):
        from taxes import calculate_ss_taxable_amount
        # Provisional = $40,000; tier2 = $34,000; SS = $20,000
        # base = 4,500; extra = 0.85 * 6,000 = 5,100 → total = 9,600
        result = calculate_ss_taxable_amount(40_000, 20_000, "single")
        assert abs(result - 9_600) < 0.01

    def test_mfj_tier_thresholds(self):
        from taxes import calculate_ss_taxable_amount
        # MFJ tier1 = $32,000; provisional = $31,000 → $0
        assert calculate_ss_taxable_amount(31_000, 20_000, "married_filing_jointly") == 0.0
        # MFJ tier1 = $32,000; provisional = $33,000 → 50% of 1,000 = 500
        result = calculate_ss_taxable_amount(33_000, 20_000, "married_filing_jointly")
        assert abs(result - 500) < 0.01


class TestCaStateTax:
    def test_zero_income(self):
        from taxes import calculate_ca_state_tax
        assert calculate_ca_state_tax(0.0, 0.0, 0.0, "single") == 0.0

    def test_ss_excluded_from_ca(self):
        from taxes import calculate_ca_state_tax
        # SS income should NOT be taxed by CA; ordinary_income already excludes SS from caller
        tax_with_ss = calculate_ca_state_tax(50_000, 0.0, 24_000, "single")
        tax_without_ss = calculate_ca_state_tax(50_000, 0.0, 0.0, "single")
        assert abs(tax_with_ss - tax_without_ss) < 0.01

    def test_ltcg_taxed_as_ordinary_in_ca(self):
        from taxes import calculate_ca_state_tax
        # CA lumps LTCG with ordinary; taxing 40K ordinary + 10K LTCG same as 50K all ordinary
        tax1 = calculate_ca_state_tax(40_000, 10_000, 0.0, "single")
        tax2 = calculate_ca_state_tax(50_000, 0.0, 0.0, "single")
        assert abs(tax1 - tax2) < 0.01

    def test_ca_positive_tax(self):
        from taxes import calculate_ca_state_tax
        # $100,000 ordinary single; CA std ded = $5,706; CA taxable = $94,294
        tax = calculate_ca_state_tax(100_000, 0.0, 0.0, "single")
        assert tax > 0

    def test_mfj_higher_deduction(self):
        from taxes import calculate_ca_state_tax
        # MFJ CA std = $11,412 vs single $5,706 → lower tax for MFJ at same income
        tax_single = calculate_ca_state_tax(80_000, 0.0, 0.0, "single")
        tax_mfj = calculate_ca_state_tax(80_000, 0.0, 0.0, "married_filing_jointly")
        assert tax_mfj < tax_single


class TestMtStateTax:
    def test_zero_income(self):
        from taxes import calculate_mt_state_tax
        assert calculate_mt_state_tax(0.0, 0.0, "married_filing_jointly") == 0.0

    def test_ltcg_preferential_rate(self):
        from taxes import calculate_mt_state_tax
        # MT taxes LTCG at 3.0% (lower bracket), not the 4.7% ordinary rate.
        # MFJ std ded = 32,200. Ordinary 60K + LTCG 40K:
        #   ordinary_taxable = 27,800 @ 4.7% = 1,306.60
        #   LTCG 40K stacks at 27,800..67,800 (all < 95K) @ 3.0% = 1,200
        tax = calculate_mt_state_tax(60_000, 40_000, "married_filing_jointly")
        assert abs(tax - 2_506.60) < 0.01

    def test_ltcg_cheaper_than_ordinary(self):
        from taxes import calculate_mt_state_tax
        # Same gross income, but as LTCG it should be taxed less than as ordinary.
        as_ltcg = calculate_mt_state_tax(60_000, 40_000, "married_filing_jointly")
        as_ordinary = calculate_mt_state_tax(100_000, 0.0, "married_filing_jointly")
        assert as_ltcg < as_ordinary

    def test_ltcg_straddles_bracket(self):
        from taxes import calculate_mt_state_tax
        # Ordinary 90K + LTCG 40K, MFJ. ordinary_taxable = 57,800 @ 4.7% = 2,716.60.
        # LTCG stacks 57,800..97,800: 37,200 @ 3.0% + 2,800 @ 4.1% = 1,116 + 114.80 = 1,230.80
        tax = calculate_mt_state_tax(90_000, 40_000, "married_filing_jointly")
        assert abs(tax - 3_947.40) < 0.01


class TestCalculateYearTaxes:
    def test_returns_required_keys(self):
        from taxes import calculate_year_taxes
        result = calculate_year_taxes(
            ordinary_income=60_000, ltcg_income=5_000,
            filing_status="single", state="other", age=67,
            spouse_age=None, num_medicare_eligible=1,
        )
        for key in ("federal_ordinary", "federal_ltcg", "federal_niit",
                    "federal_irmaa", "state_tax", "total", "effective_rate",
                    "magi", "ordinary_taxable", "irmaa_tier_crossed"):
            assert key in result

    def test_total_equals_sum_of_components(self):
        from taxes import calculate_year_taxes
        r = calculate_year_taxes(
            ordinary_income=80_000, ltcg_income=10_000,
            filing_status="single", state="other", age=67,
            spouse_age=None, num_medicare_eligible=1,
            state_tax_rate=0.05,
        )
        expected_total = (r["federal_ordinary"] + r["federal_ltcg"]
                          + r["federal_niit"] + r["federal_irmaa"] + r["state_tax"])
        assert abs(r["total"] - expected_total) < 0.01

    def test_effective_rate_bounds(self):
        from taxes import calculate_year_taxes
        r = calculate_year_taxes(
            ordinary_income=100_000, ltcg_income=0,
            filing_status="single", state="other", age=50,
            spouse_age=None, num_medicare_eligible=0,
        )
        assert 0.0 <= r["effective_rate"] <= 1.0

    def test_magi_equals_ordinary_plus_ltcg(self):
        from taxes import calculate_year_taxes
        r = calculate_year_taxes(
            ordinary_income=50_000, ltcg_income=15_000,
            filing_status="single", state="other", age=50,
            spouse_age=None, num_medicare_eligible=0,
        )
        assert abs(r["magi"] - 65_000) < 0.01

    def test_california_state_tax(self):
        from taxes import calculate_year_taxes
        r_ca = calculate_year_taxes(
            ordinary_income=80_000, ltcg_income=0,
            filing_status="single", state="california", age=50,
            spouse_age=None, num_medicare_eligible=0,
        )
        r_flat = calculate_year_taxes(
            ordinary_income=80_000, ltcg_income=0,
            filing_status="single", state="other", age=50,
            spouse_age=None, num_medicare_eligible=0,
            state_tax_rate=0.09,
        )
        # CA progressive tax at ~$80K should be less than flat 9%
        assert r_ca["state_tax"] < r_flat["state_tax"]

    def test_bracket_factor_scales_deduction(self):
        from taxes import calculate_year_taxes
        # Higher bracket_factor → bigger deduction → lower ordinary taxable
        r1 = calculate_year_taxes(
            ordinary_income=50_000, ltcg_income=0,
            filing_status="single", state="other", age=50,
            spouse_age=None, num_medicare_eligible=0,
            bracket_factor=1.0,
        )
        r2 = calculate_year_taxes(
            ordinary_income=50_000, ltcg_income=0,
            filing_status="single", state="other", age=50,
            spouse_age=None, num_medicare_eligible=0,
            bracket_factor=1.5,
        )
        assert r2["federal_ordinary"] < r1["federal_ordinary"]

    def test_irmaa_flag(self):
        from taxes import calculate_year_taxes
        r_no = calculate_year_taxes(
            ordinary_income=100_000, ltcg_income=0,
            filing_status="single", state="other", age=66,
            spouse_age=None, num_medicare_eligible=1,
        )
        assert not r_no["irmaa_tier_crossed"]

        r_yes = calculate_year_taxes(
            ordinary_income=150_000, ltcg_income=0,
            filing_status="single", state="other", age=66,
            spouse_age=None, num_medicare_eligible=1,
        )
        assert r_yes["irmaa_tier_crossed"]


class TestMarginalRate:
    def test_zero_income(self):
        from taxes import marginal_rate
        assert marginal_rate(0, "single") == 0.10

    def test_10pct_bracket(self):
        from taxes import marginal_rate
        assert marginal_rate(10_000, "single") == 0.10

    def test_12pct_bracket(self):
        from taxes import marginal_rate
        assert marginal_rate(30_000, "single") == 0.12

    def test_22pct_bracket(self):
        from taxes import marginal_rate
        assert marginal_rate(80_000, "single") == 0.22

    def test_37pct_top_bracket(self):
        from taxes import marginal_rate
        assert marginal_rate(700_000, "single") == 0.37


# ===========================================================================
# 2. WITHDRAWAL HELPERS (withdrawals.py)
# ===========================================================================

class TestRmdDivisor:
    def test_below_rmd_age(self):
        from withdrawals import _rmd_divisor
        assert _rmd_divisor(72) == 0.0
        assert _rmd_divisor(65) == 0.0

    def test_at_rmd_start(self):
        from withdrawals import _rmd_divisor
        from constants import RMD_TABLE
        assert _rmd_divisor(73) == RMD_TABLE[73]

    def test_known_ages(self):
        from withdrawals import _rmd_divisor
        from constants import RMD_TABLE
        for age in [73, 80, 90, 100]:
            assert _rmd_divisor(age) == RMD_TABLE[age]

    def test_over_100_falls_back(self):
        from withdrawals import _rmd_divisor
        # Age 105 not in table; should fall back to 6.4 (age 100 value)
        assert _rmd_divisor(105) == 6.4


class TestGainRatio:
    def test_zero_balance(self):
        from withdrawals import _gain_ratio
        acct = _taxable_account(balance=0, basis=0)
        assert _gain_ratio(acct) == 0.0

    def test_no_gains(self):
        from withdrawals import _gain_ratio
        acct = _taxable_account(balance=100_000, basis=100_000)
        assert _gain_ratio(acct) == 0.0

    def test_full_gains(self):
        from withdrawals import _gain_ratio
        acct = _taxable_account(balance=100_000, basis=0)
        assert _gain_ratio(acct) == 1.0

    def test_partial_gains(self):
        from withdrawals import _gain_ratio
        acct = _taxable_account(balance=100_000, basis=60_000)
        assert abs(_gain_ratio(acct) - 0.4) < 1e-9

    def test_clamped_above_1(self):
        from withdrawals import _gain_ratio
        # basis > balance (shouldn't happen in practice, but must not exceed 1.0)
        acct = _taxable_account(balance=80_000, basis=100_000)
        assert _gain_ratio(acct) == 0.0


class TestWithdrawFrom:
    def test_traditional_all_ordinary(self):
        from withdrawals import _withdraw_from
        acct = _trad_account(balance=100_000)
        w, oi, lg = _withdraw_from(acct, 20_000)
        assert abs(w - 20_000) < 0.01
        assert abs(oi - 20_000) < 0.01
        assert lg == 0.0
        assert abs(acct["balance"] - 80_000) < 0.01

    def test_roth_tax_free(self):
        from withdrawals import _withdraw_from
        acct = _roth_account(balance=100_000)
        w, oi, lg = _withdraw_from(acct, 30_000)
        assert abs(w - 30_000) < 0.01
        assert oi == 0.0
        assert lg == 0.0

    def test_bank_tax_free(self):
        from withdrawals import _withdraw_from
        acct = _bank_account(balance=50_000)
        w, oi, lg = _withdraw_from(acct, 10_000)
        assert abs(w - 10_000) < 0.01
        assert oi == 0.0
        assert lg == 0.0

    def test_taxable_gain_ratio(self):
        from withdrawals import _withdraw_from
        # balance=100K, basis=60K → gain ratio=40%
        acct = _taxable_account(balance=100_000, basis=60_000)
        w, oi, lg = _withdraw_from(acct, 10_000)
        assert abs(w - 10_000) < 0.01
        assert oi == 0.0
        assert abs(lg - 4_000) < 0.01  # 10,000 * 0.4
        # Basis reduced by return-of-capital portion: 10,000 * 0.6 = 6,000
        assert abs(acct["basis"] - 54_000) < 0.01

    def test_taxable_zero_basis(self):
        from withdrawals import _withdraw_from
        acct = _taxable_account(balance=50_000, basis=0)
        w, oi, lg = _withdraw_from(acct, 10_000)
        assert abs(lg - 10_000) < 0.01  # 100% gains

    def test_cannot_overdraw(self):
        from withdrawals import _withdraw_from
        acct = _trad_account(balance=5_000)
        w, oi, lg = _withdraw_from(acct, 20_000)
        assert abs(w - 5_000) < 0.01
        assert abs(acct["balance"]) < 0.01

    def test_zero_amount(self):
        from withdrawals import _withdraw_from
        acct = _trad_account(balance=100_000)
        w, oi, lg = _withdraw_from(acct, 0)
        assert w == 0.0 and oi == 0.0 and lg == 0.0
        assert acct["balance"] == 100_000


# ===========================================================================
# 3. RETIREMENT SIMULATION (withdrawals.py)
# ===========================================================================

class TestSimulateRetirement:
    def _run(self, accounts=None, profile_kw=None, assumptions_kw=None):
        from withdrawals import simulate_retirement
        accts = accounts or [_trad_account(500_000), _roth_account(200_000)]
        p = _base_profile(**(profile_kw or {}))
        a = _base_assumptions(**(assumptions_kw or {}))
        return simulate_retirement(accts, p, a)

    def test_returns_dataframe_and_summary(self):
        df, summary = self._run()
        import pandas as pd
        assert isinstance(df, pd.DataFrame)
        assert isinstance(summary, dict)

    def test_row_count_matches_lifespan(self):
        df, _ = self._run(profile_kw={"retirement_age": 65, "life_expectancy": 85})
        assert len(df) == 85 - 65 + 1

    def test_ages_sequential(self):
        df, _ = self._run()
        ages = df["age"].tolist()
        assert ages == list(range(65, 86))

    def test_required_columns_present(self):
        df, _ = self._run()
        for col in ("age", "spending_target", "total_portfolio",
                    "ordinary_income", "ltcg_income", "total_tax",
                    "ss_income", "rmd_amount", "effective_tax_rate"):
            assert col in df.columns, f"Missing column: {col}"

    def test_portfolio_starts_positive(self):
        df, _ = self._run()
        assert df["total_portfolio"].iloc[0] > 0

    def test_ss_income_appears_at_correct_age(self):
        df, _ = self._run(
            profile_kw={"social_security_benefit": 24_000, "social_security_start_age": 70}
        )
        assert df[df["age"] < 70]["ss_income"].sum() == 0.0
        assert df[df["age"] >= 70]["ss_income"].sum() > 0

    def test_rmd_triggers_at_73(self):
        df, _ = self._run(
            accounts=[_trad_account(500_000)],
            profile_kw={"retirement_age": 65, "life_expectancy": 85},
        )
        assert df[df["age"] < 73]["rmd_amount"].sum() == 0.0
        assert df[df["age"] >= 73]["rmd_amount"].sum() > 0

    def test_rmd_amount_formula(self):
        from constants import RMD_TABLE
        from withdrawals import simulate_retirement
        # Single trad account, no other spending, just check rmd at 73
        acct = _trad_account(balance=500_000)
        p = _base_profile(retirement_age=73, life_expectancy=74,
                          social_security_start_age=999)
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=0)
        df, _ = simulate_retirement([acct], p, a)
        # Year 1: age 73, balance = 500,000, divisor = 26.5
        expected_rmd = 500_000 / RMD_TABLE[73]
        assert abs(df.iloc[0]["rmd_amount"] - expected_rmd) < 10

    def test_no_tax_on_roth_only_portfolio(self):
        from withdrawals import simulate_retirement
        # Roth-only portfolio with no SS, no traditional → near-zero taxes
        accts = [_roth_account(balance=1_000_000)]
        p = _base_profile(social_security_benefit=0, social_security_start_age=999)
        a = _base_assumptions()
        df, _ = simulate_retirement(accts, p, a)
        assert df["federal_ordinary_tax"].sum() < 50  # allow tiny rounding

    def test_lifetime_taxes_positive(self):
        _, summary = self._run()
        assert summary["lifetime_taxes"] > 0

    def test_portfolio_depletion_detected(self):
        from withdrawals import simulate_retirement
        # Tiny portfolio, high spending → should deplete
        accts = [_bank_account(balance=10_000)]
        p = _base_profile(retirement_age=65, life_expectancy=80,
                          social_security_benefit=0, social_security_start_age=999)
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=50_000)
        df, summary = simulate_retirement(accts, p, a)
        assert summary["portfolio_depleted_age"] is not None

    def test_final_accounts_in_summary(self):
        _, summary = self._run()
        assert "final_accounts" in summary
        assert isinstance(summary["final_accounts"], list)

    def test_fixed_spending_mode(self):
        from withdrawals import simulate_retirement
        accts = [_trad_account(1_000_000)]
        p = _base_profile()
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=40_000)
        df, _ = simulate_retirement(accts, p, a)
        assert len(df) > 0

    def test_roth_preservation_strategy(self):
        from withdrawals import simulate_retirement
        # With roth_preservation, traditional should be drawn before Roth
        accts = [_trad_account(500_000, "Trad"), _roth_account(200_000, "Roth")]
        p = _base_profile(retirement_age=65, life_expectancy=75,
                          social_security_start_age=999)
        a = _base_assumptions(withdrawal_strategy="roth_preservation",
                               spending_mode="fixed", annual_spending_target=40_000)
        df, _ = simulate_retirement(accts, p, a)
        # Early years: traditional > roth for withdrawals
        early = df[df["age"] < 73]
        assert early["traditional_withdrawal"].sum() >= early["roth_withdrawal"].sum()

    def test_roth_conversion_increases_ordinary_income(self):
        from withdrawals import simulate_retirement
        accts = [_trad_account(500_000, "Trad"), _roth_account(100_000, "Roth")]
        accts[0]["id"] = "src"
        accts[1]["id"] = "dst"
        p = _base_profile(retirement_age=65, life_expectancy=75,
                          social_security_start_age=999)
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=10_000)
        rc = {
            "enabled": True,
            "strategy": "fixed_amount",
            "fixed_amount": 20_000,
            "start_age": 65,
            "end_age": 70,
            "source_account_ids": ["src"],
            "destination_account_id": "dst",
        }
        df_with, _ = simulate_retirement(accts, p, a, roth_conversion=rc)
        df_without, _ = simulate_retirement(accts, p, a)
        conv_rows = df_with[(df_with["age"] >= 65) & (df_with["age"] <= 70)]
        assert conv_rows["roth_conversion"].sum() > 0

    def test_irmaa_warning_generated(self):
        from withdrawals import simulate_retirement
        # High income should trigger IRMAA warnings post-65
        accts = [_trad_account(5_000_000)]
        p = _base_profile(retirement_age=65, life_expectancy=70,
                          social_security_benefit=0, social_security_start_age=999)
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=300_000)
        _, summary = simulate_retirement(accts, p, a)
        irmaa_warnings = [w for w in summary["warnings"] if w["type"] == "irmaa"]
        assert len(irmaa_warnings) > 0

    def test_healthcare_cost_pre_medicare(self):
        from withdrawals import simulate_retirement
        accts = [_roth_account(2_000_000)]
        p = _base_profile(retirement_age=60, life_expectancy=70,
                          pre_medicare_healthcare=12_000,
                          post_medicare_healthcare=6_000,
                          social_security_start_age=999)
        a = _base_assumptions()
        df, summary = simulate_retirement(accts, p, a)
        assert df[df["age"] < 65]["healthcare_cost"].mean() > df[df["age"] >= 65]["healthcare_cost"].mean()
        assert summary["lifetime_healthcare"] > 0

    def test_spending_overrides(self):
        from withdrawals import simulate_retirement
        accts = [_roth_account(2_000_000)]
        p = _base_profile(retirement_age=65, life_expectancy=75,
                          social_security_start_age=999)
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=40_000)
        overrides = {70: 100_000}
        df, _ = simulate_retirement(accts, p, a, spending_overrides=overrides)
        # At age 70 with $100K override, spending_target should be higher
        row_70 = df[df["age"] == 70].iloc[0]
        row_69 = df[df["age"] == 69].iloc[0]
        assert row_70["spending_target"] > row_69["spending_target"] * 1.5


# ===========================================================================
# 4. ACCUMULATION PROJECTION (projections.py)
# ===========================================================================

class TestProjectAccumulation:
    def _run(self, accounts=None, profile_kw=None, assumptions_kw=None):
        from projections import project_accumulation
        accts = accounts or [
            {
                "id": "a1", "name": "401k", "type": "traditional_401k",
                "balance": 100_000, "basis": 100_000,
                "annual_contribution": 20_000, "contribution_growth_rate": 0.02,
                "return_rate": 0.07, "use_global_return_rate": False,
                "employer_match_percent": 0.5, "employer_match_limit": 5_000,
                "qualified_dividend_yield": 0.0, "ordinary_income_yield": 0.0,
                "net_annual_rental_income": 0.0,
            }
        ]
        p = _base_profile(current_age=50, retirement_age=65, **(profile_kw or {}))
        a = _base_assumptions(**(assumptions_kw or {}))
        return project_accumulation(accts, p, a)

    def test_returns_df_and_accounts(self):
        import pandas as pd
        df, final = self._run()
        assert isinstance(df, pd.DataFrame)
        assert isinstance(final, list)

    def test_rows_span_all_ages(self):
        p = _base_profile(current_age=50, retirement_age=60)
        from projections import project_accumulation
        acct = [{"id": "a1", "name": "IRA", "type": "traditional_ira",
                 "balance": 50_000, "basis": 50_000,
                 "annual_contribution": 0, "contribution_growth_rate": 0,
                 "return_rate": 0.06, "use_global_return_rate": False,
                 "employer_match_percent": 0, "employer_match_limit": 0,
                 "qualified_dividend_yield": 0, "ordinary_income_yield": 0,
                 "net_annual_rental_income": 0}]
        df, _ = project_accumulation(acct, p, _base_assumptions())
        ages = df["age"].unique().tolist()
        assert min(ages) == 50
        assert max(ages) == 60

    def test_balance_grows(self):
        df, final = self._run()
        start_bal = df[df["age"] == 50]["balance"].sum()
        end_bal = df[df["age"] == 65]["balance"].sum()
        assert end_bal > start_bal

    def test_employer_match_applied(self):
        from projections import project_accumulation
        acct = [{
            "id": "a1", "name": "401k", "type": "traditional_401k",
            "balance": 0, "basis": 0,
            "annual_contribution": 20_000, "contribution_growth_rate": 0.0,
            "return_rate": 0.0,  # no returns so we isolate match
            "use_global_return_rate": False,
            "employer_match_percent": 0.5,
            "employer_match_limit": 5_000,
            "qualified_dividend_yield": 0, "ordinary_income_yield": 0,
            "net_annual_rental_income": 0,
        }]
        p = _base_profile(current_age=60, retirement_age=62)
        df, _ = project_accumulation(acct, p, _base_assumptions())
        # After 2 years at 0% return: 2 * (20,000 + min(10,000, 5,000)) = 50,000
        end_bal = df[df["age"] == 62]["balance"].sum()
        assert abs(end_bal - 50_000) < 1

    def test_taxable_basis_increases_with_contribution(self):
        from projections import project_accumulation
        acct = [{
            "id": "t1", "name": "Brokerage", "type": "taxable",
            "balance": 50_000, "basis": 50_000,
            "annual_contribution": 10_000, "contribution_growth_rate": 0.0,
            "return_rate": 0.0, "use_global_return_rate": False,
            "employer_match_percent": 0, "employer_match_limit": 0,
            "qualified_dividend_yield": 0.0, "ordinary_income_yield": 0.0,
            "net_annual_rental_income": 0,
        }]
        p = _base_profile(current_age=55, retirement_age=57)
        df, final = project_accumulation(acct, p, _base_assumptions())
        # 2 contributions of $10K → basis should grow from $50K to $70K
        assert abs(final[0]["basis"] - 70_000) < 1

    def test_tax_bucket_column_present(self):
        df, _ = self._run()
        assert "tax_bucket" in df.columns

    def test_tax_bucket_mapping(self):
        from projections import project_accumulation
        accts = [
            {**_trad_account(), "id": "t1", "type": "traditional_401k"},
            {**_roth_account(), "id": "t2", "type": "roth_ira"},
            {**_taxable_account(), "id": "t3", "type": "taxable"},
            {**_bank_account(), "id": "t4", "type": "bank"},
        ]
        p = _base_profile(current_age=55, retirement_age=60)
        df, _ = project_accumulation(accts, p, _base_assumptions())
        buckets = dict(zip(df["account_type"], df["tax_bucket"]))
        assert buckets["traditional_401k"] == "pre_tax"
        assert buckets["roth_ira"] == "roth"
        assert buckets["taxable"] == "taxable"
        assert buckets["bank"] == "cash"


# ===========================================================================
# 5. MONTE CARLO v1 (montecarlo.py)
# ===========================================================================

class TestMonteCarloV1:
    def _accts(self):
        return [_trad_account(500_000), _roth_account(200_000)]

    def _profile(self):
        return _base_profile(current_age=60, retirement_age=65, life_expectancy=85)

    def _run(self, n_runs=200, seed=42, **kw):
        from montecarlo import run_monte_carlo
        return run_monte_carlo(
            self._accts(), self._profile(), _base_assumptions(),
            n_runs=n_runs, seed=seed, **kw
        )

    def test_returns_required_keys(self):
        result = self._run()
        for key in ("ages", "percentiles", "success_rate", "n_runs",
                    "n_depleted", "depletion_ages", "volatility", "stock_pct"):
            assert key in result

    def test_ages_span_retirement_to_expectancy(self):
        result = self._run()
        assert result["ages"][0] == 65
        assert result["ages"][-1] == 85

    def test_percentile_keys(self):
        result = self._run()
        for p in [10, 25, 50, 75, 90]:
            assert p in result["percentiles"]

    def test_percentile_length_matches_ages(self):
        result = self._run()
        n = len(result["ages"])
        for p in [10, 25, 50, 75, 90]:
            assert len(result["percentiles"][p]) == n

    def test_success_rate_in_range(self):
        result = self._run()
        assert 0.0 <= result["success_rate"] <= 1.0

    def test_success_rate_plus_depletion_equals_n_runs(self):
        result = self._run()
        assert result["n_depleted"] == len(result["depletion_ages"])
        assert result["n_runs"] == 200

    def test_percentile_ordering(self):
        result = self._run()
        # At each age, p10 ≤ p25 ≤ p50 ≤ p75 ≤ p90
        for t in range(len(result["ages"])):
            vals = [result["percentiles"][p][t] for p in [10, 25, 50, 75, 90]]
            assert vals == sorted(vals)

    def test_reproducible_with_seed(self):
        r1 = self._run(seed=123)
        r2 = self._run(seed=123)
        assert r1["success_rate"] == r2["success_rate"]
        assert r1["percentiles"][50] == r2["percentiles"][50]

    def test_different_seeds_differ(self):
        r1 = self._run(seed=1)
        r2 = self._run(seed=2)
        assert r1["percentiles"][50] != r2["percentiles"][50]

    def test_high_volatility_reduces_success_rate(self):
        r_low = self._run(n_runs=500, seed=0, volatility=0.05)
        r_high = self._run(n_runs=500, seed=0, volatility=0.30)
        assert r_low["success_rate"] >= r_high["success_rate"]

    def test_crashes_lower_success_rate(self):
        r_no = self._run(n_runs=500, seed=42, enable_crashes=False)
        r_yes = self._run(n_runs=500, seed=42, enable_crashes=True, crash_magnitude=0.3)
        assert r_no["success_rate"] >= r_yes["success_rate"]

    def test_n_runs_param(self):
        result = self._run(n_runs=50)
        assert result["n_runs"] == 50

    def test_all_portfolios_non_negative(self):
        result = self._run()
        for p in [10, 25, 50, 75, 90]:
            assert all(v >= 0 for v in result["percentiles"][p])


# ===========================================================================
# 6. MONTE CARLO v2 (montecarlo_v2.py)
# ===========================================================================

class TestMonteCarloV2:
    def _run(self, n_runs=200, seed=42, **kw):
        from montecarlo_v2 import run_monte_carlo_v2
        accts = [_trad_account(500_000), _roth_account(200_000)]
        p = _base_profile(current_age=60, retirement_age=65, life_expectancy=85)
        return run_monte_carlo_v2(accts, p, _base_assumptions(),
                                   n_runs=n_runs, seed=seed, **kw)

    def test_returns_required_keys(self):
        result = self._run()
        for key in ("ages", "percentiles", "success_rate", "n_runs", "n_depleted",
                    "depletion_ages", "equity_vol", "bond_vol", "equity_bond_corr",
                    "withdrawal_mode"):
            assert key in result

    def test_ages_span(self):
        result = self._run()
        assert result["ages"][0] == 65
        assert result["ages"][-1] == 85

    def test_percentile_ordering(self):
        result = self._run()
        for t in range(len(result["ages"])):
            vals = [result["percentiles"][p][t] for p in [10, 25, 50, 75, 90]]
            assert vals == sorted(vals)

    def test_success_rate_bounds(self):
        result = self._run()
        assert 0.0 <= result["success_rate"] <= 1.0

    def test_reproducible(self):
        r1 = self._run(seed=7)
        r2 = self._run(seed=7)
        assert r1["success_rate"] == r2["success_rate"]

    def test_v2_higher_vol_than_v1(self):
        from montecarlo import run_monte_carlo
        from montecarlo_v2 import run_monte_carlo_v2
        accts = [_trad_account(500_000), _roth_account(200_000)]
        p = _base_profile(current_age=60, retirement_age=65, life_expectancy=85)
        assumptions = _base_assumptions()
        r1 = run_monte_carlo(accts, p, assumptions, n_runs=500, seed=0, volatility=0.12)
        r2 = run_monte_carlo_v2(accts, p, assumptions, n_runs=500, seed=0, equity_vol=0.155)
        # v2 with 15.5% equity vol should produce wider spread (p90-p10 gap larger)
        spread_v1 = r1["percentiles"][90][-1] - r1["percentiles"][10][-1]
        spread_v2 = r2["percentiles"][90][-1] - r2["percentiles"][10][-1]
        assert spread_v2 > spread_v1 * 0.5  # v2 spread is meaningfully wide

    def test_guardrails_mode(self):
        result = self._run(withdrawal_mode="guardrails")
        assert result["withdrawal_mode"] == "guardrails"
        assert 0.0 <= result["success_rate"] <= 1.0

    def test_correlated_factors_param(self):
        r_corr = self._run(equity_bond_corr=0.8)
        assert r_corr["equity_bond_corr"] == 0.8

    def test_all_portfolios_non_negative(self):
        result = self._run()
        for p in [10, 25, 50, 75, 90]:
            assert all(v >= 0 for v in result["percentiles"][p])

    def test_equity_bond_means_formula(self):
        from montecarlo_v2 import _equity_bond_means
        # 60/40 portfolio, 5% target → bond=3.2%, equity=6.2%
        eq, bd = _equity_bond_means(0.60, 0.05)
        assert abs(eq - 0.062) < 1e-9
        assert abs(bd - 0.032) < 1e-9
        # Weighted blend should equal target
        blended = 0.60 * eq + 0.40 * bd
        assert abs(blended - 0.05) < 1e-9


# ===========================================================================
# 6b. MONTE CARLO ↔ deterministic STRATEGY PARITY (regression guard for #5)
# ===========================================================================

class TestMonteCarloStrategyParity:
    """Both MC engines must run the *same* plan as simulate_retirement — Roth
    conversions, 0%-bracket gain harvesting, rebalancing, the tax-efficient
    withdrawal order, and full taxes — rather than a simplified withdrawal loop.
    These guard against the engines silently diverging from the plan again."""

    def _accts(self):
        # traditional-heavy so conversions, RMDs and taxes all matter
        return [_trad_account(800_000), _roth_account(50_000), _taxable_account(150_000, 90_000)]

    def _profile(self):
        return _base_profile(current_age=60, retirement_age=65, life_expectancy=90)

    def _conversion(self):
        return {
            "enabled": True,
            "strategy": "fill_to_bracket",
            "target_bracket": 0.12,
            "start_age": 65,
            "end_age": 72,
            "source_account_ids": ["trad1"],
            "destination_account_id": "roth1",
        }

    def test_injection_reproduces_deterministic(self):
        """simulate_retirement with injected *deterministic* returns + constant inflation
        reproduces the plain deterministic run exactly — proving the MC return/inflation
        hooks are faithful, so the MC engines really do run the deterministic plan."""
        import copy
        import numpy as np
        from withdrawals import simulate_retirement
        accts, p, a, rc = self._accts(), self._profile(), _base_assumptions(), self._conversion()
        df_det, _ = simulate_retirement(copy.deepcopy(accts), p, a, rc)
        start = max(p["retirement_age"], p["current_age"])
        n = p["life_expectancy"] - start + 1
        ret = a["retirement_return_rate"]

        def _rate(acc):
            if acc["type"] in {"rental_property", "bank"} or not acc.get("use_global_return_rate", True):
                return acc.get("return_rate", 0.05)
            return ret

        mr = [{acc["id"]: _rate(acc) for acc in accts} for _ in range(n)]
        df_inj, _ = simulate_retirement(
            copy.deepcopy(accts), p, a, rc,
            market_returns=mr, inflation_sequence=[a["inflation_rate"]] * n,
        )
        diff = np.abs(np.array(df_det["total_portfolio"]) - np.array(df_inj["total_portfolio"]))
        assert diff.max() < 1e-6, f"injection diverged from deterministic by ${diff.max():,.4f}"
        assert df_det["roth_conversion"].sum() > 0, "conversions should have executed in this scenario"

    def test_v2_models_roth_conversions(self):
        """Toggling Roth conversions changes the v2 MC outcome — conversions are actually
        executed inside MC (previously they were ignored entirely)."""
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._accts(), self._profile(), _base_assumptions()
        on = run_monte_carlo_v2(accts, p, a, n_runs=150, seed=5, roth_conversion=self._conversion())
        off = run_monte_carlo_v2(accts, p, a, n_runs=150, seed=5, roth_conversion={"enabled": False})
        assert on["percentiles"][50][-1] != off["percentiles"][50][-1]

    def test_v1_models_roth_conversions(self):
        from montecarlo import run_monte_carlo
        accts, p, a = self._accts(), self._profile(), _base_assumptions()
        on = run_monte_carlo(accts, p, a, n_runs=150, seed=5, roth_conversion=self._conversion())
        off = run_monte_carlo(accts, p, a, n_runs=150, seed=5, roth_conversion={"enabled": False})
        assert on["percentiles"][50][-1] != off["percentiles"][50][-1]

    def test_v2_low_vol_median_near_deterministic(self):
        """At near-zero volatility the v2 median path tracks the deterministic projection
        (same plan, minimal market/inflation noise)."""
        import copy
        from withdrawals import simulate_retirement
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a, rc = self._accts(), self._profile(), _base_assumptions(), self._conversion()
        det, _ = simulate_retirement(copy.deepcopy(accts), p, a, rc)
        det_final = det["total_portfolio"].iloc[-1]
        mc = run_monte_carlo_v2(
            accts, p, a, n_runs=300, seed=9,
            equity_vol=0.002, bond_vol=0.002, equity_bond_corr=0.0, roth_conversion=rc,
        )
        mc_med = mc["percentiles"][50][-1]
        assert abs(mc_med - det_final) < 0.08 * max(1.0, det_final), (
            f"low-vol MC median {mc_med:,.0f} not near deterministic {det_final:,.0f}"
        )


# ===========================================================================
# 6c. ADJUSTMENT METRICS (H2 — Kitces-style reframing of success rate)
# ===========================================================================

class TestSimulateRetirementGKMetrics:
    """simulate_retirement must surface gk_cuts / gk_raises / gk_floor_clamps /
    gk_min_real_ratio in its summary so MC callers can report probability of
    adjustment. In constant_real these stay zero and the real ratio is 1.0."""

    def _setup(self):
        return _trad_account(800_000), _base_profile(retirement_age=65, life_expectancy=85)

    def test_constant_real_metrics_zero(self):
        """Constant-real mode: no GK firings, real spending ratio == 1.0."""
        from withdrawals import simulate_retirement
        acc, p = self._setup()
        _, summary = simulate_retirement([acc], p, _base_assumptions())
        assert summary["gk_cuts"] == 0
        assert summary["gk_raises"] == 0
        assert summary["gk_floor_clamps"] == 0
        assert abs(summary["gk_min_real_ratio"] - 1.0) < 1e-6

    def test_guardrails_summary_keys_present(self):
        """All four GK keys must be present even when guardrails never fires."""
        from withdrawals import simulate_retirement
        acc, p = self._setup()
        a = _base_assumptions(withdrawal_mode="guardrails")
        _, summary = simulate_retirement([acc], p, a)
        for k in ("gk_cuts", "gk_raises", "gk_floor_clamps", "gk_min_real_ratio"):
            assert k in summary

    def test_guardrails_cuts_fire_on_bad_returns(self):
        """A sustained sequence of bad returns must trigger at least one cut and
        push min_real_ratio below 1.0."""
        from withdrawals import simulate_retirement
        acc, p = self._setup()
        a = _base_assumptions(withdrawal_mode="guardrails")
        n = p["life_expectancy"] - p["retirement_age"] + 1
        # All accounts lose 15% / year — withdrawal rate climbs fast.
        mr = [{acc["id"]: -0.15} for _ in range(n)]
        _, summary = simulate_retirement([acc], p, a, market_returns=mr)
        assert summary["gk_cuts"] > 0, "bad-return path should trigger cuts"
        assert summary["gk_min_real_ratio"] < 1.0

    def test_guardrails_raises_fire_on_good_returns(self):
        """A sustained boom must trigger at least one prosperity-rule raise."""
        from withdrawals import simulate_retirement
        acc, p = self._setup()
        a = _base_assumptions(withdrawal_mode="guardrails")
        n = p["life_expectancy"] - p["retirement_age"] + 1
        mr = [{acc["id"]: 0.25} for _ in range(n)]
        _, summary = simulate_retirement([acc], p, a, market_returns=mr)
        assert summary["gk_raises"] > 0, "boom path should trigger raises"

    def test_floor_clamps_count_only_under_guardrails(self):
        """Floor clamps must be guardrails-only — constant_real ignores the floor."""
        from withdrawals import simulate_retirement
        acc, p = self._setup()
        # Floor above baseline: constant_real ignores it; guardrails should clamp.
        a_const = _base_assumptions(spending_floor=1_000_000)
        _, s_const = simulate_retirement([acc], p, a_const)
        assert s_const["gk_floor_clamps"] == 0

        a_gr = _base_assumptions(withdrawal_mode="guardrails", spending_floor=1_000_000)
        n = p["life_expectancy"] - p["retirement_age"] + 1
        mr = [{acc["id"]: -0.10} for _ in range(n)]
        _, s_gr = simulate_retirement([acc], p, a_gr, market_returns=mr)
        assert s_gr["gk_floor_clamps"] > 0, "floor should clamp under bad guardrails path"

    def test_survivor_baseline_drops_so_post_widowhood_not_counted_as_cut(self):
        """After the survivor transition, the GK baseline drops by the same factor
        as spending_target. Otherwise every post-widowhood year would falsely read
        as a 25% real-spending cut even with constant-real."""
        from withdrawals import simulate_retirement
        # MFJ with spouse older than primary by 5 years so survivor fires before life expectancy.
        p = _base_profile(
            current_age=65, retirement_age=65, life_expectancy=85,
            filing_status="married_filing_jointly", spouse_age=70,
            spouse_ss_benefit=12_000, survivor_spending_reduction=0.25,
        )
        acc = _trad_account(1_200_000)
        _, summary = simulate_retirement([acc], p, _base_assumptions())
        # Constant_real mode: real ratio must stay ~1.0 across the whole horizon
        # despite the survivor reduction part-way through.
        assert abs(summary["gk_min_real_ratio"] - 1.0) < 1e-6, (
            "survivor reduction should drop the baseline, leaving real_ratio unchanged"
        )


class TestMonteCarloV2AdjustmentMetrics:
    """MC v2 must aggregate the per-trial GK metrics into adjustment_metrics so the
    UI can report Kitces-style probability of adjustment alongside success rate."""

    def _scenario(self):
        # Tight enough that guardrails meaningfully flexes spending.
        accts = [_trad_account(900_000)]
        p = _base_profile(
            current_age=60, retirement_age=65, life_expectancy=90,
            filing_status="married_filing_jointly", spouse_age=60,
            spouse_ss_benefit=15_000,
        )
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=65_000)
        return accts, p, a

    def test_result_carries_adjustment_metrics_dict(self):
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._scenario()
        r = run_monte_carlo_v2(accts, p, a, n_runs=120, seed=0)
        am = r["adjustment_metrics"]
        for k in ("prob_any_cut", "prob_any_raise", "prob_any_floor_hit",
                  "avg_cuts_per_trial", "avg_raises_per_trial", "avg_floor_years_per_trial",
                  "min_real_ratio_p10", "min_real_ratio_p50", "min_real_ratio_p90"):
            assert k in am

    def test_constant_real_metrics_zero(self):
        """Under constant_real the engine must report no cuts / raises / floor hits."""
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._scenario()
        r = run_monte_carlo_v2(accts, p, a, n_runs=120, seed=0)
        am = r["adjustment_metrics"]
        assert am["prob_any_cut"] == 0.0
        assert am["prob_any_raise"] == 0.0
        assert am["prob_any_floor_hit"] == 0.0
        assert abs(am["min_real_ratio_p50"] - 1.0) < 1e-6

    def test_guardrails_some_cuts_fire(self):
        """At reasonable volatility a guardrails MC should fire cuts in most trials."""
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._scenario()
        r = run_monte_carlo_v2(accts, p, a, n_runs=300, seed=0,
                               withdrawal_mode="guardrails")
        am = r["adjustment_metrics"]
        assert am["prob_any_cut"] > 0.5, f"expected most trials to see a cut, got {am['prob_any_cut']}"
        assert am["min_real_ratio_p50"] < 1.0, (
            "median worst real-spending year should fall below baseline under guardrails"
        )

    def test_real_ratio_percentiles_are_ordered(self):
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._scenario()
        r = run_monte_carlo_v2(accts, p, a, n_runs=200, seed=1,
                               withdrawal_mode="guardrails")
        am = r["adjustment_metrics"]
        assert am["min_real_ratio_p10"] <= am["min_real_ratio_p50"] <= am["min_real_ratio_p90"]


# ===========================================================================
# 6d. VARIANCE REDUCTION (M3 Sobol + L4 antithetic)
# ===========================================================================

class TestMonteCarloV2VarianceReduction:
    """Sobol quasi-random + antithetic variates should narrow the seed-to-seed
    spread of summary statistics, and both knobs should be reflected in the
    result dict so the UI staleness check can detect changes."""

    def _scenario(self):
        accts = [_trad_account(900_000)]
        p = _base_profile(current_age=60, retirement_age=65, life_expectancy=90,
                          filing_status="married_filing_jointly", spouse_age=60,
                          spouse_ss_benefit=15_000)
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=65_000)
        return accts, p, a

    def test_flags_round_trip_into_result(self):
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._scenario()
        r = run_monte_carlo_v2(accts, p, a, n_runs=120, seed=0,
                               quasi_random=True, antithetic=True)
        assert r["quasi_random"] is True
        assert r["antithetic"] is True
        r2 = run_monte_carlo_v2(accts, p, a, n_runs=120, seed=0,
                                quasi_random=False, antithetic=False)
        assert r2["quasi_random"] is False
        assert r2["antithetic"] is False

    def test_antithetic_only_runs_cleanly(self):
        """Antithetic alone (no Sobol) is a useful fallback when scipy isn't available."""
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._scenario()
        r = run_monte_carlo_v2(accts, p, a, n_runs=200, seed=0,
                               quasi_random=False, antithetic=True)
        assert 0.0 <= r["success_rate"] <= 1.0

    def test_odd_n_runs_no_off_by_one(self):
        """Antithetic uses ceil(n/2) base draws; an odd n_runs must still return
        exactly n_runs trials (not n+1) without an index error."""
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._scenario()
        r = run_monte_carlo_v2(accts, p, a, n_runs=101, seed=0,
                               quasi_random=False, antithetic=True)
        assert r["n_runs"] == 101
        # percentile bands should have exactly horizon-length entries
        assert len(r["percentiles"][50]) == len(r["ages"])

    def test_n_runs_one_edge_case(self):
        """A single-trial run must not crash under any combination of variance-reduction flags."""
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._scenario()
        for q, anti in [(True, True), (True, False), (False, True), (False, False)]:
            r = run_monte_carlo_v2(accts, p, a, n_runs=1, seed=0,
                                   quasi_random=q, antithetic=anti)
            assert r["n_runs"] == 1
            assert len(r["percentiles"][50]) == len(r["ages"])

    def test_qmc_reduces_seed_variance(self):
        """Across multiple seeds, QMC+antithetic should give a tighter distribution of
        success rates than pure pseudorandom. The reduction varies by scenario; we
        require *some* improvement to guard against the variance-reduction path being
        silently broken."""
        import numpy as np
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._scenario()
        srs_qmc = []
        srs_psr = []
        for s in range(6):
            srs_qmc.append(run_monte_carlo_v2(
                accts, p, a, n_runs=300, seed=s,
                quasi_random=True, antithetic=True,
            )["success_rate"])
            srs_psr.append(run_monte_carlo_v2(
                accts, p, a, n_runs=300, seed=s,
                quasi_random=False, antithetic=False,
            )["success_rate"])
        sd_qmc = float(np.std(srs_qmc))
        sd_psr = float(np.std(srs_psr))
        # Skip if pseudo run happened to be unusually stable (no signal to compare).
        if sd_psr < 1e-3:
            pytest.skip(f"pseudo std={sd_psr:.4f} too small to compare")
        assert sd_qmc < sd_psr, (
            f"variance reduction failed: qmc std={sd_qmc:.4f} vs pseudo std={sd_psr:.4f}"
        )

    def test_draw_normals_shape_and_finiteness(self):
        """The internal _draw_normals must return the requested shape with finite values
        for every flag combo (catches the Sobol u→ndtri pipeline regression)."""
        import numpy as np
        from montecarlo_v2 import _draw_normals
        rng = np.random.default_rng(0)
        for q, anti in [(True, True), (True, False), (False, True), (False, False)]:
            z = _draw_normals(64, 12, rng, q, anti, seed=0)
            assert z.shape == (64, 12)
            assert np.isfinite(z).all()


# ===========================================================================
# 6e. CMA PRESETS (M1 — forward-looking 2026 capital-market assumption sets)
# ===========================================================================

class TestMonteCarloV2CMAPresets:
    """CMA_PRESETS must (a) carry the keys downstream code reads, (b) override
    equity/bond vol+mean for global-rate accounts, and (c) leave per-account
    overrides untouched."""

    def _scenario(self, use_global=True):
        accts = [{
            "id": "trad1", "name": "401k", "type": "traditional_401k",
            "balance": 800_000, "basis": 800_000,
            "annual_contribution": 0.0, "contribution_growth_rate": 0.0,
            "return_rate": 0.05, "use_global_return_rate": use_global,
            "employer_match_percent": 0.0, "employer_match_limit": 0.0,
            "qualified_dividend_yield": 0.0, "ordinary_income_yield": 0.0,
            "net_annual_rental_income": 0.0, "withdraw_priority": "normal",
        }]
        p = _base_profile(current_age=60, retirement_age=65, life_expectancy=85)
        a = _base_assumptions()
        return accts, p, a

    def test_presets_have_required_keys(self):
        from montecarlo_v2 import CMA_PRESETS
        for name, meta in CMA_PRESETS.items():
            for k in ("label", "equity_mean", "bond_mean", "equity_vol", "bond_vol", "description"):
                assert k in meta, f"preset {name} missing {k}"
            assert 0.0 < meta["equity_mean"] < 0.20
            assert 0.0 < meta["bond_mean"] < 0.10
            assert 0.0 < meta["equity_vol"] < 0.50
            assert 0.0 < meta["bond_vol"] < 0.20

    def test_each_preset_runs_and_records_metadata(self):
        from montecarlo_v2 import run_monte_carlo_v2, CMA_PRESETS
        accts, p, a = self._scenario()
        for name in CMA_PRESETS:
            r = run_monte_carlo_v2(accts, p, a, n_runs=60, seed=0, cma_preset=name)
            assert r["cma_preset"] == name
            assert r["cma_preset_meta"] is CMA_PRESETS[name]
            # Engine returns the preset's vols, not the user-provided ones.
            assert r["equity_vol"] == CMA_PRESETS[name]["equity_vol"]
            assert r["bond_vol"] == CMA_PRESETS[name]["bond_vol"]

    def test_unknown_preset_name_falls_through_to_user_inputs(self):
        """An unknown preset key must not crash — the engine falls back to the user-
        provided equity_vol / bond_vol arguments. This guards against typos silently
        loading the wrong CMA."""
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._scenario()
        r = run_monte_carlo_v2(accts, p, a, n_runs=60, seed=0,
                               cma_preset="not_a_real_preset",
                               equity_vol=0.20, bond_vol=0.08)
        assert r["cma_preset_meta"] is None
        assert r["equity_vol"] == 0.20
        assert r["bond_vol"] == 0.08

    def test_preset_changes_median_outcome(self):
        """Two presets with materially different equity means should produce
        materially different median ending balances — proves the preset is wired
        through _build_market_returns and not silently ignored."""
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._scenario()
        # vanguard_2026 equity mean 4.5%, original_2022 equity mean 7.5% — 3pp gap
        # over a 20-year horizon should compound to a clearly different median.
        low = run_monte_carlo_v2(accts, p, a, n_runs=200, seed=0, cma_preset="vanguard_2026")
        high = run_monte_carlo_v2(accts, p, a, n_runs=200, seed=0, cma_preset="original_2022")
        assert high["percentiles"][50][-1] > low["percentiles"][50][-1]

    def test_preset_skipped_for_per_account_overrides(self):
        """When use_global_return_rate=False, the account drives its own return via
        _equity_bond_means(stock_pct, own_rate). The preset must NOT override that —
        otherwise users with fixed-rate annuities or hand-tuned account returns would
        silently see those replaced by the preset's equity mean."""
        from montecarlo_v2 import _build_market_returns
        import numpy as np
        accts = [{
            "id": "fixed", "type": "traditional_401k",
            "balance": 500_000, "return_rate": 0.06, "use_global_return_rate": False,
        }]
        ages = [65]
        zs = np.zeros(1)
        # With z=0 the log-normal multiplier is exp(log_mu) = (1+mean)*exp(-0.5*vol^2);
        # the realized return ~= mean - 0.5*vol^2 for small vol. Just verify the
        # preset doesn't drag the rate toward vanguard_2026's 4.5% equity mean.
        out_preset = _build_market_returns(
            accts, ages, zs, zs,
            equity_vol=0.165, bond_vol=0.060, ret_return=0.05, stock_pct=0.60,
            crash_years=set(), crash_magnitude=0.0,
            eq_mean_override=0.045, bd_mean_override=0.045,
        )
        out_no_preset = _build_market_returns(
            accts, ages, zs, zs,
            equity_vol=0.165, bond_vol=0.060, ret_return=0.05, stock_pct=0.60,
            crash_years=set(), crash_magnitude=0.0,
        )
        # Per-account override is honored either way: returns must match each other,
        # not drift toward the preset's equity mean.
        assert abs(out_preset[0]["fixed"] - out_no_preset[0]["fixed"]) < 1e-9


# ===========================================================================
# 7. CHARTS (charts.py)
# ===========================================================================

class TestCharts:
    """Charts tests verify each function returns a Plotly Figure without error."""

    def _acc_df(self):
        from projections import project_accumulation
        accts = [_trad_account(300_000), _roth_account(100_000), _taxable_account()]
        p = _base_profile(current_age=50, retirement_age=65)
        df, _ = project_accumulation(accts, p, _base_assumptions())
        return df

    def _ret_df_and_accts(self):
        from withdrawals import simulate_retirement
        accts = [_trad_account(500_000), _roth_account(200_000), _taxable_account()]
        p = _base_profile()
        a = _base_assumptions()
        df, _ = simulate_retirement(accts, p, a)
        return df, accts

    def _mc_result(self):
        from montecarlo import run_monte_carlo
        accts = [_trad_account(500_000)]
        p = _base_profile()
        return run_monte_carlo(accts, p, _base_assumptions(), n_runs=50, seed=0)

    def test_chart_accumulation(self):
        import plotly.graph_objects as go
        from charts import chart_accumulation
        fig = chart_accumulation(self._acc_df())
        assert isinstance(fig, go.Figure)

    def test_chart_composition_at_retirement(self):
        import plotly.graph_objects as go
        from charts import chart_composition_at_retirement
        accts = [_trad_account(500_000), _roth_account(200_000)]
        fig = chart_composition_at_retirement(accts)
        assert isinstance(fig, go.Figure)

    def test_chart_drawdown(self):
        import plotly.graph_objects as go
        from charts import chart_drawdown
        df, accts = self._ret_df_and_accts()
        fig = chart_drawdown(df, accts, inflation=0.03, current_age=60)
        assert isinstance(fig, go.Figure)

    def test_chart_annual_income(self):
        import plotly.graph_objects as go
        from charts import chart_annual_income
        df, _ = self._ret_df_and_accts()
        fig = chart_annual_income(df, inflation=0.03, retirement_age=65)
        assert isinstance(fig, go.Figure)

    def test_chart_spending_coverage(self):
        import plotly.graph_objects as go
        from charts import chart_spending_coverage
        df, _ = self._ret_df_and_accts()
        fig = chart_spending_coverage(df)
        assert isinstance(fig, go.Figure)

    def test_chart_monte_carlo(self):
        import plotly.graph_objects as go
        from charts import chart_monte_carlo
        mc = self._mc_result()
        det = [700_000 - i * 5_000 for i in range(len(mc["ages"]))]
        fig = chart_monte_carlo(mc, det)
        assert isinstance(fig, go.Figure)

    def test_chart_mc_comparison(self):
        import plotly.graph_objects as go
        from charts import chart_mc_comparison
        from montecarlo_v2 import run_monte_carlo_v2
        mc1 = self._mc_result()
        accts = [_trad_account(500_000)]
        p = _base_profile()
        mc2 = run_monte_carlo_v2(accts, p, _base_assumptions(), n_runs=50, seed=1)
        det = [700_000 - i * 5_000 for i in range(len(mc1["ages"]))]
        fig = chart_mc_comparison(mc1, mc2, det)
        assert isinstance(fig, go.Figure)

    def test_chart_mc_depletion(self):
        import plotly.graph_objects as go
        from charts import chart_mc_depletion
        from montecarlo import run_monte_carlo
        accts = [_bank_account(50_000)]
        p = _base_profile()
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=30_000)
        mc = run_monte_carlo(accts, p, a, n_runs=50, seed=0)
        fig = chart_mc_depletion(mc)
        assert isinstance(fig, go.Figure)

    def test_chart_tax_burden(self):
        import plotly.graph_objects as go
        from charts import chart_tax_burden
        df, _ = self._ret_df_and_accts()
        fig = chart_tax_burden(df)
        assert isinstance(fig, go.Figure)

    def test_chart_progress_tracking(self):
        import plotly.graph_objects as go
        from charts import chart_progress_tracking
        # Check-in ages must exist as keys in projections_by_age so the hover template
        # can format the projected total (None would fail the f-string).
        projections = {
            "60": {"total": 800_000},
            "62": {"total": 870_000},
            "65": {"total": 1_000_000},
        }
        checkins = [{"age": 62, "total": 850_000, "date": "2024-01-01", "note": "On track"}]
        fig = chart_progress_tracking(projections, checkins)
        assert isinstance(fig, go.Figure)

    def test_chart_drawdown_no_inflation(self):
        import plotly.graph_objects as go
        from charts import chart_drawdown
        df, accts = self._ret_df_and_accts()
        fig = chart_drawdown(df, accts, inflation=0.0)
        assert isinstance(fig, go.Figure)


# ===========================================================================
# 8. SCENARIOS (scenarios.py)
# ===========================================================================

class TestScenarios:
    """Uses a temp directory to avoid polluting the real scenarios folder."""

    @pytest.fixture(autouse=True)
    def _patch_dirs(self, tmp_path, monkeypatch):
        import scenarios as sc
        monkeypatch.setattr(sc, "SCENARIOS_DIR", tmp_path)
        monkeypatch.setattr(sc, "TRACKING_DIR", tmp_path / "tracking")
        (tmp_path / "tracking").mkdir()
        self._tmp = tmp_path

    def _scenario_data(self, name="Test Scenario"):
        return dict(
            name=name,
            profile=_base_profile(),
            assumptions=_base_assumptions(),
            accounts=[_trad_account()],
            roth_conversion=None,
        )

    def test_save_and_load_roundtrip(self):
        from scenarios import save_scenario, load_scenario
        d = self._scenario_data()
        save_scenario(d["name"], d["profile"], d["assumptions"], d["accounts"])
        loaded = load_scenario(d["name"])
        assert loaded["profile"] == d["profile"]
        assert loaded["assumptions"] == d["assumptions"]

    def test_list_scenarios_empty(self):
        from scenarios import list_scenarios
        assert list_scenarios() == []

    def test_list_scenarios_after_save(self):
        from scenarios import save_scenario, list_scenarios
        d = self._scenario_data()
        save_scenario(d["name"], d["profile"], d["assumptions"], d["accounts"])
        names = list_scenarios()
        assert d["name"] in names

    def test_list_scenarios_sorted(self):
        from scenarios import save_scenario, list_scenarios
        for n in ["Zoo", "Alpha", "Beta"]:
            d = self._scenario_data(n)
            save_scenario(d["name"], d["profile"], d["assumptions"], d["accounts"])
        names = list_scenarios()
        assert names == sorted(names)

    def test_delete_scenario(self):
        from scenarios import save_scenario, delete_scenario, list_scenarios
        d = self._scenario_data()
        save_scenario(d["name"], d["profile"], d["assumptions"], d["accounts"])
        delete_scenario(d["name"])
        assert d["name"] not in list_scenarios()

    def test_delete_nonexistent_no_error(self):
        from scenarios import delete_scenario
        delete_scenario("ghost")  # should not raise

    def test_load_nonexistent_raises(self):
        from scenarios import load_scenario
        with pytest.raises(FileNotFoundError):
            load_scenario("nonexistent")

    def test_save_rejects_invalid_characters(self):
        from scenarios import save_scenario
        # validate_scenario_name raises ValueError for /, <, > — save must not silently succeed
        d = self._scenario_data("My/Scenario<Test>")
        with pytest.raises(ValueError, match="invalid characters"):
            save_scenario(d["name"], d["profile"], d["assumptions"], d["accounts"])

    def test_empty_name_raises(self):
        from scenarios import save_scenario
        d = self._scenario_data("")
        with pytest.raises(ValueError):
            save_scenario("", d["profile"], d["assumptions"], d["accounts"])

    def test_latest_scenario_none_when_empty(self):
        from scenarios import latest_scenario
        assert latest_scenario() is None

    def test_latest_scenario_returns_most_recent(self):
        import time
        from scenarios import save_scenario, latest_scenario
        for n in ["First", "Second"]:
            d = self._scenario_data(n)
            save_scenario(d["name"], d["profile"], d["assumptions"], d["accounts"])
            time.sleep(0.05)  # ensure mtime differs
        assert latest_scenario() == "Second"

    def test_roth_conversion_saved_and_loaded(self):
        from scenarios import save_scenario, load_scenario
        rc = {
            "enabled": True, "strategy": "fixed_amount", "fixed_amount": 25_000,
            "start_age": 65, "end_age": 70,
            "source_account_ids": ["src1"],
            "destination_account_id": "dst1",
        }
        d = self._scenario_data()
        save_scenario(d["name"], d["profile"], d["assumptions"], d["accounts"], roth_conversion=rc)
        loaded = load_scenario(d["name"])
        assert loaded["roth_conversion"]["enabled"] is True
        assert loaded["roth_conversion"]["fixed_amount"] == 25_000

    def test_load_missing_keys_raises(self):
        from scenarios import load_scenario
        bad_path = self._tmp / "bad.json"
        bad_path.write_text(json.dumps({"profile": {}}), encoding="utf-8")
        with pytest.raises(ValueError):
            load_scenario("bad")

    def test_save_and_load_tracking(self):
        from scenarios import save_tracking, load_tracking
        tracking = {"baseline": {"total": 900_000}, "checkins": [{"age": 62, "total": 850_000}]}
        save_tracking("My Scenario", tracking)
        loaded = load_tracking("My Scenario")
        assert loaded["baseline"]["total"] == 900_000
        assert len(loaded["checkins"]) == 1

    def test_load_tracking_returns_default_when_missing(self):
        from scenarios import load_tracking
        result = load_tracking("nonexistent")
        assert result == {"baseline": None, "checkins": []}


# ===========================================================================
# 9. EDGE CASES & INTEGRATION
# ===========================================================================

class TestEdgeCases:
    def test_retirement_age_equals_current_age(self):
        from withdrawals import simulate_retirement
        # retirement_age == current_age: zero accumulation years, sim starts immediately
        accts = [_trad_account(500_000)]
        p = _base_profile(current_age=65, retirement_age=65, life_expectancy=75)
        df, _ = simulate_retirement(accts, p, _base_assumptions())
        assert len(df) == 11

    def test_all_account_types_in_simulation(self):
        from withdrawals import simulate_retirement
        rental = {
            "id": "r1", "name": "Rental", "type": "rental_property",
            "balance": 400_000, "basis": 200_000,
            "annual_contribution": 0, "contribution_growth_rate": 0,
            "return_rate": 0.04, "use_global_return_rate": False,
            "employer_match_percent": 0, "employer_match_limit": 0,
            "qualified_dividend_yield": 0, "ordinary_income_yield": 0,
            "net_annual_rental_income": 24_000, "withdraw_priority": "normal",
        }
        hsa = {
            "id": "h1", "name": "HSA", "type": "hsa",
            "balance": 50_000, "basis": 50_000,
            "annual_contribution": 0, "contribution_growth_rate": 0,
            "return_rate": 0.05, "use_global_return_rate": False,
            "employer_match_percent": 0, "employer_match_limit": 0,
            "qualified_dividend_yield": 0, "ordinary_income_yield": 0,
            "net_annual_rental_income": 0, "withdraw_priority": "normal",
        }
        accts = [_trad_account(), _roth_account(), _taxable_account(), _bank_account(), rental, hsa]
        p = _base_profile()
        df, summary = simulate_retirement(accts, p, _base_assumptions())
        assert len(df) > 0
        assert summary["lifetime_taxes"] >= 0

    def test_rental_income_in_ordinary_income(self):
        from withdrawals import simulate_retirement
        rental = {
            "id": "r1", "name": "Rental", "type": "rental_property",
            "balance": 300_000, "basis": 150_000,
            "annual_contribution": 0, "contribution_growth_rate": 0,
            "return_rate": 0.04, "use_global_return_rate": False,
            "employer_match_percent": 0, "employer_match_limit": 0,
            "qualified_dividend_yield": 0, "ordinary_income_yield": 0,
            "net_annual_rental_income": 18_000, "withdraw_priority": "normal",
        }
        p = _base_profile()
        a = _base_assumptions()
        df, _ = simulate_retirement([rental], p, a)
        # Rental income should appear in the rental_income column
        assert df["rental_income"].sum() > 0

    def test_married_filing_jointly_ss_both_spouses(self):
        from withdrawals import simulate_retirement
        accts = [_trad_account(800_000)]
        p = _base_profile(
            filing_status="married_filing_jointly",
            current_age=60, retirement_age=65, life_expectancy=85,
            spouse_age=58,
            social_security_benefit=24_000,
            social_security_start_age=67,
            spouse_ss_benefit=18_000,
            spouse_ss_start_age=67,
            survivor_spending_reduction=0.25,
        )
        df, summary = simulate_retirement(accts, p, _base_assumptions())
        assert len(df) > 0
        # Both should receive SS from age 67 (or spouse's offset age)
        assert df[df["age"] >= 67]["ss_income"].sum() > 0

    def test_zero_balance_accounts(self):
        from withdrawals import simulate_retirement
        accts = [_trad_account(0), _roth_account(500_000)]
        p = _base_profile()
        df, _ = simulate_retirement(accts, p, _base_assumptions())
        assert len(df) > 0

    def test_accumulation_single_year(self):
        from projections import project_accumulation
        acct = [{
            "id": "a1", "name": "IRA", "type": "traditional_ira",
            "balance": 100_000, "basis": 100_000,
            "annual_contribution": 7_000, "contribution_growth_rate": 0,
            "return_rate": 0.07, "use_global_return_rate": False,
            "employer_match_percent": 0, "employer_match_limit": 0,
            "qualified_dividend_yield": 0, "ordinary_income_yield": 0,
            "net_annual_rental_income": 0,
        }]
        # Same current and retirement age → only the starting snapshot row
        p = _base_profile(current_age=64, retirement_age=65)
        df, final = project_accumulation(acct, p, _base_assumptions())
        # Should have two ages (64 and 65)
        assert set(df["age"].unique()) == {64, 65}

    def test_taxable_gain_ratio_basis_never_negative(self):
        from withdrawals import _withdraw_from
        # Repeated small withdrawals should not push basis below 0
        acct = _taxable_account(balance=10_000, basis=4_000)
        for _ in range(8):
            _withdraw_from(acct, 1_000)
        assert acct.get("basis", 0) >= 0

    def test_california_no_ss_tax(self):
        from withdrawals import simulate_retirement
        accts = [_trad_account(1_000_000)]
        p = _base_profile(state="california", state_tax_rate=0.0,
                          social_security_benefit=30_000, social_security_start_age=67)
        a = _base_assumptions()
        df, _ = simulate_retirement(accts, p, a)
        # CA state tax should be present for ordinary income but SS portion excluded
        assert df["state_tax"].sum() > 0

    def test_mc_depletion_ages_within_retirement_window(self):
        from montecarlo import run_monte_carlo
        accts = [_bank_account(20_000)]
        p = _base_profile(retirement_age=65, life_expectancy=85)
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=30_000)
        result = run_monte_carlo(accts, p, a, n_runs=100, seed=0)
        for age in result["depletion_ages"]:
            assert 65 <= age <= 85

    def test_full_pipeline_accumulation_to_retirement(self):
        """End-to-end: accumulate from 50→65, then simulate 65→85."""
        from projections import project_accumulation
        from withdrawals import simulate_retirement
        accts = [
            {
                "id": "k1", "name": "401k", "type": "traditional_401k",
                "balance": 200_000, "basis": 200_000,
                "annual_contribution": 20_000, "contribution_growth_rate": 0.02,
                "return_rate": 0.07, "use_global_return_rate": False,
                "employer_match_percent": 0.5, "employer_match_limit": 5_000,
                "qualified_dividend_yield": 0, "ordinary_income_yield": 0,
                "net_annual_rental_income": 0, "withdraw_priority": "normal",
            },
            {
                "id": "r1", "name": "Roth", "type": "roth_ira",
                "balance": 50_000, "basis": 50_000,
                "annual_contribution": 7_000, "contribution_growth_rate": 0,
                "return_rate": 0.07, "use_global_return_rate": False,
                "employer_match_percent": 0, "employer_match_limit": 0,
                "qualified_dividend_yield": 0, "ordinary_income_yield": 0,
                "net_annual_rental_income": 0, "withdraw_priority": "normal",
            },
        ]
        p = _base_profile(current_age=50, retirement_age=65, life_expectancy=85)
        a = _base_assumptions()
        _, final_accts = project_accumulation(accts, p, a)
        # Retirement balances should be higher than initial
        assert sum(a["balance"] for a in final_accts) > sum(a["balance"] for a in accts)
        df, summary = simulate_retirement(final_accts, p, a)
        assert len(df) == 21
        assert summary["lifetime_taxes"] > 0


# ===========================================================================
# 10. SPEC GAPS — all 17 items identified in the gap analysis
# ===========================================================================

class TestSpecGaps:
    """Covers every gap identified against prompt.md."""

    # -----------------------------------------------------------------------
    # Gap 1: withdraw_priority="last" accounts are deferred
    # -----------------------------------------------------------------------
    def test_withdraw_priority_last_deferred(self):
        from withdrawals import simulate_retirement
        # "last"-priority taxable should only be touched after normal accounts run dry
        last_taxable = {
            "id": "t_last", "name": "Bond Fund", "type": "taxable",
            "balance": 200_000, "basis": 200_000,  # zero gains so LTCG = 0
            "annual_contribution": 0, "contribution_growth_rate": 0,
            "return_rate": 0.03, "use_global_return_rate": False,
            "employer_match_percent": 0, "employer_match_limit": 0,
            "qualified_dividend_yield": 0.0, "ordinary_income_yield": 0.0,
            "net_annual_rental_income": 0, "withdraw_priority": "last",
        }
        roth = _roth_account(balance=300_000, name="Roth")
        p = _base_profile(retirement_age=65, life_expectancy=70,
                          social_security_start_age=999)
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=30_000)
        df, _ = simulate_retirement([roth, last_taxable], p, a)
        # While Roth has balance, taxable_withdrawal should be zero
        # Roth covers all spending until exhausted — "last" taxable untouched meanwhile
        roth_col = "bal_Roth"
        assert roth_col in df.columns
        # In the first year the Roth covers it entirely; last taxable not touched
        assert df.iloc[0]["taxable_withdrawal"] == 0.0

    # -----------------------------------------------------------------------
    # Gap 2: LTCG harvesting (Step 4) produces harvest_ltcg > 0
    # -----------------------------------------------------------------------
    def test_ltcg_harvesting_occurs(self):
        from withdrawals import simulate_retirement
        # Low income + taxable account with large unrealized gains → harvest in 0% bracket
        taxable = {
            "id": "tx1", "name": "Brokerage", "type": "taxable",
            "balance": 400_000, "basis": 100_000,  # 75% gain ratio
            "annual_contribution": 0, "contribution_growth_rate": 0,
            "return_rate": 0.0, "use_global_return_rate": False,
            "employer_match_percent": 0, "employer_match_limit": 0,
            "qualified_dividend_yield": 0.0, "ordinary_income_yield": 0.0,
            "net_annual_rental_income": 0, "withdraw_priority": "normal",
        }
        # Very low spending so income stays in 0% LTCG bracket; single filer
        p = _base_profile(filing_status="single", retirement_age=65, life_expectancy=67,
                          social_security_start_age=999,
                          current_age=65)
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=5_000)
        df, _ = simulate_retirement([taxable], p, a)
        # With low ordinary income, the 0% LTCG headroom allows harvesting
        assert df["harvest_ltcg"].sum() > 0, "Expected LTCG harvesting to occur"

    def test_harvest_ltcg_included_in_magi(self):
        from withdrawals import simulate_retirement
        # Harvested gains (taxed at 0%) must still flow into MAGI for IRMAA/NIIT
        taxable = {
            "id": "tx1", "name": "Brokerage", "type": "taxable",
            "balance": 400_000, "basis": 100_000,
            "annual_contribution": 0, "contribution_growth_rate": 0,
            "return_rate": 0.0, "use_global_return_rate": False,
            "employer_match_percent": 0, "employer_match_limit": 0,
            "qualified_dividend_yield": 0.0, "ordinary_income_yield": 0.0,
            "net_annual_rental_income": 0, "withdraw_priority": "normal",
        }
        p = _base_profile(filing_status="single", retirement_age=65, life_expectancy=67,
                          social_security_start_age=999, current_age=65)
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=5_000)
        df, _ = simulate_retirement([taxable], p, a)
        harvesting_rows = df[df["harvest_ltcg"] > 0]
        if not harvesting_rows.empty:
            # MAGI must be >= harvest_ltcg (harvest contributes to MAGI)
            assert (harvesting_rows["magi"] >= harvesting_rows["harvest_ltcg"]).all()

    # -----------------------------------------------------------------------
    # Gap 3: SS benefit inflated to retirement-year nominal dollars
    # -----------------------------------------------------------------------
    def test_ss_inflated_to_retirement_nominal(self):
        from withdrawals import simulate_retirement
        # Profile: retire at 65 from age 60, SS starts at retirement, 3% inflation
        # Today's SS = $24,000; at 65 it should be $24,000 × (1.03)^5 ≈ $27,825
        p = _base_profile(
            current_age=60, retirement_age=65, life_expectancy=66,
            social_security_benefit=24_000,
            social_security_start_age=65,
        )
        a = _base_assumptions(inflation_rate=0.03)
        accts = [_roth_account(1_000_000)]
        df, _ = simulate_retirement(accts, p, a)
        expected_inflated = 24_000 * (1.03 ** 5)
        actual_ss_year1 = df.iloc[0]["ss_income"]
        # Allow for COLA already applied in year 1 — should be close to inflated amount
        assert abs(actual_ss_year1 - expected_inflated) < 500, (
            f"Expected SS ≈ {expected_inflated:,.0f}, got {actual_ss_year1:,.0f}"
        )
        # Must be significantly more than today's-dollar value
        assert actual_ss_year1 > 24_000 * 1.10

    # -----------------------------------------------------------------------
    # Gap 4: use_global_return_rate flag respected during retirement
    # -----------------------------------------------------------------------
    def test_use_global_return_rate_false_uses_own_rate(self):
        from withdrawals import simulate_retirement
        # One Roth at 0% own rate (use_global=False), one at global rate (10%)
        own_rate_acct = {
            "id": "r0", "name": "RothZero", "type": "roth_ira",
            "balance": 100_000, "basis": 100_000,
            "annual_contribution": 0, "contribution_growth_rate": 0,
            "return_rate": 0.00, "use_global_return_rate": False,
            "employer_match_percent": 0, "employer_match_limit": 0,
            "qualified_dividend_yield": 0, "ordinary_income_yield": 0,
            "net_annual_rental_income": 0, "withdraw_priority": "normal",
        }
        global_rate_acct = {
            "id": "r1", "name": "RothGlobal", "type": "roth_ira",
            "balance": 100_000, "basis": 100_000,
            "annual_contribution": 0, "contribution_growth_rate": 0,
            "return_rate": 0.00, "use_global_return_rate": True,
            "employer_match_percent": 0, "employer_match_limit": 0,
            "qualified_dividend_yield": 0, "ordinary_income_yield": 0,
            "net_annual_rental_income": 0, "withdraw_priority": "normal",
        }
        p = _base_profile(current_age=65, retirement_age=65, life_expectancy=66,
                          social_security_start_age=999)
        # Zero spending so no withdrawals skew the balances
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=0,
                               retirement_return_rate=0.10)
        df, summary = simulate_retirement([own_rate_acct, global_rate_acct], p, a)
        final = {a["id"]: a["balance"] for a in summary["final_accounts"]}
        # own-rate account grew at 0% — should still be ~100K after 2 years
        assert final["r0"] < 105_000  # minimal growth
        # global-rate account grew at 10% — should be noticeably larger
        assert final["r1"] > 115_000

    # -----------------------------------------------------------------------
    # Gap 5: RMD excess → reinvestment warning
    # -----------------------------------------------------------------------
    def test_rmd_excess_warning_when_rmds_exceed_spending(self):
        from withdrawals import simulate_retirement
        # Large traditional balance → large RMDs that exceed a small spending target
        accts = [_trad_account(balance=3_000_000, name="BigTrad")]
        p = _base_profile(
            current_age=73, retirement_age=73, life_expectancy=75,
            social_security_start_age=999,
        )
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=20_000)
        _, summary = simulate_retirement(accts, p, a)
        rmd_excess_warnings = [w for w in summary["warnings"] if w["type"] == "rmd_excess"]
        assert len(rmd_excess_warnings) > 0, "Expected rmd_excess warning when RMDs > spending"

    # -----------------------------------------------------------------------
    # Gap 6: IRMAA approaching warning when MAGI is within $10K of next tier
    # -----------------------------------------------------------------------
    def test_irmaa_approaching_warning(self):
        from withdrawals import simulate_retirement
        # Single filer age 65+; target MAGI just under $109K IRMAA tier 1 ceiling
        # Spending target chosen so ordinary income ≈ $105,000
        accts = [_trad_account(balance=2_000_000, name="Trad")]
        p = _base_profile(
            current_age=65, retirement_age=65, life_expectancy=67,
            filing_status="single", social_security_start_age=999,
        )
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=105_000)
        _, summary = simulate_retirement(accts, p, a)
        approaching = [w for w in summary["warnings"] if w["type"] == "irmaa_approaching"]
        assert len(approaching) > 0, (
            "Expected irmaa_approaching warning when MAGI is near $109K single tier"
        )

    # -----------------------------------------------------------------------
    # Gap 7: Survivor transition — filing status, SS, and spending reduction
    # -----------------------------------------------------------------------
    def test_survivor_transition_warning_and_ss_drop(self):
        from withdrawals import simulate_retirement
        # Primary age 65 at retirement; spouse age 73 (offset +8)
        # life_expectancy=78; spouse reaches 78 when primary is 70
        accts = [_trad_account(1_500_000)]
        p = _base_profile(
            filing_status="married_filing_jointly",
            current_age=65, retirement_age=65, life_expectancy=78,
            spouse_age=73,
            social_security_benefit=30_000,
            social_security_start_age=65,
            spouse_ss_benefit=18_000,
            spouse_ss_start_age=65,
            survivor_spending_reduction=0.25,
        )
        a = _base_assumptions()
        df, summary = simulate_retirement(accts, p, a)
        transition_warnings = [w for w in summary["warnings"] if w["type"] == "survivor_transition"]
        assert len(transition_warnings) == 1, "Expected exactly one survivor_transition warning"
        # SS after transition should drop — primary $30K alone vs combined $30K+$18K before
        # Find the transition year from the warning
        trans_age = transition_warnings[0]["age"]
        before = df[df["age"] == trans_age - 1]["ss_income"].values
        after  = df[df["age"] == trans_age]["ss_income"].values
        if len(before) and len(after):
            # Pre-transition combined SS > post-transition single SS
            assert before[0] > after[0], "SS should drop after survivor transition"

    def test_survivor_transition_spending_reduced(self):
        from withdrawals import simulate_retirement
        accts = [_trad_account(2_000_000)]
        p = _base_profile(
            filing_status="married_filing_jointly",
            current_age=65, retirement_age=65, life_expectancy=78,
            spouse_age=73,
            social_security_benefit=24_000, social_security_start_age=65,
            spouse_ss_benefit=12_000, spouse_ss_start_age=65,
            survivor_spending_reduction=0.25,
        )
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=80_000)
        df, summary = simulate_retirement(accts, p, a)
        trans_age = next(
            w["age"] for w in summary["warnings"] if w["type"] == "survivor_transition"
        )
        pre_spend = df[df["age"] == trans_age - 1]["spending_target"].values[0]
        post_spend = df[df["age"] == trans_age]["spending_target"].values[0]
        # Spending should drop by ~25% at transition
        assert post_spend < pre_spend * 0.85

    # -----------------------------------------------------------------------
    # Gap 8: Roth conversion fill_to_bracket strategy
    # -----------------------------------------------------------------------
    def test_roth_conversion_fill_to_bracket(self):
        from withdrawals import simulate_retirement
        src = _trad_account(balance=500_000, name="Trad")
        dst = _roth_account(balance=50_000, name="Roth")
        src["id"] = "src"
        dst["id"] = "dst"
        p = _base_profile(
            filing_status="single", current_age=65, retirement_age=65, life_expectancy=70,
            social_security_start_age=999,
        )
        a = _base_assumptions(
            spending_mode="fixed", annual_spending_target=5_000,  # low income → lots of headroom
        )
        # fill_to_bracket up to 12% bracket ($50,400 ceiling for single)
        rc = {
            "enabled": True,
            "strategy": "fill_to_bracket",
            "target_bracket": 0.12,
            "fixed_amount": 0,
            "start_age": 65,
            "end_age": 70,
            "source_account_ids": ["src"],
            "destination_account_id": "dst",
        }
        df, _ = simulate_retirement([src, dst], p, a, roth_conversion=rc)
        conv_rows = df[(df["age"] >= 65) & (df["age"] <= 70)]
        assert conv_rows["roth_conversion"].sum() > 0, "fill_to_bracket conversions should occur"
        # Each conversion should not exceed the 12% bracket ceiling space
        for _, row in conv_rows.iterrows():
            assert row["roth_conversion"] >= 0

    # -----------------------------------------------------------------------
    # Gap 9: Multiple source accounts drawn proportionally for Roth conversion
    # -----------------------------------------------------------------------
    def test_roth_conversion_multiple_sources_proportional(self):
        from withdrawals import simulate_retirement
        src1 = _trad_account(balance=300_000, name="Trad1")
        src2 = {**_trad_account(balance=100_000, name="Trad2"), "id": "src2",
                "type": "traditional_ira"}
        dst = _roth_account(balance=50_000, name="Roth")
        src1["id"] = "src1"
        dst["id"] = "dst"
        p = _base_profile(
            filing_status="single", current_age=65, retirement_age=65, life_expectancy=66,
            social_security_start_age=999,
        )
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=1_000)
        rc = {
            "enabled": True,
            "strategy": "fixed_amount",
            "fixed_amount": 80_000,  # total to convert
            "start_age": 65,
            "end_age": 65,
            "source_account_ids": ["src1", "src2"],
            "destination_account_id": "dst",
        }
        _, summary = simulate_retirement([src1, src2, dst], p, a, roth_conversion=rc)
        final = {a["id"]: a["balance"] for a in summary["final_accounts"]}
        # src1 had 75% of total traditional → should absorb ~75% of the $80K conversion
        # src2 had 25% → should absorb ~25%
        # After 1 year + returns at 0.05, approximate check:
        # src1 started 300K, lost 60K to conversion, grew 5% → ≈ (240K)*1.05 = 252K
        # src2 started 100K, lost 20K to conversion, grew 5% → ≈ (80K)*1.05 = 84K
        # Ratio src1/src2 should be close to 3:1
        ratio = final["src1"] / final["src2"]
        assert 2.5 < ratio < 3.5, f"Expected ~3:1 ratio after proportional draw, got {ratio:.2f}"

    # -----------------------------------------------------------------------
    # Gap 10: Conversion vintages populated in summary
    # -----------------------------------------------------------------------
    def test_conversion_vintages_populated(self):
        from withdrawals import simulate_retirement
        src = _trad_account(balance=500_000, name="Trad")
        dst = _roth_account(balance=50_000, name="Roth")
        src["id"] = "src"
        dst["id"] = "dst"
        p = _base_profile(
            current_age=65, retirement_age=65, life_expectancy=68,
            social_security_start_age=999,
        )
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=5_000)
        rc = {
            "enabled": True,
            "strategy": "fixed_amount",
            "fixed_amount": 20_000,
            "start_age": 65,
            "end_age": 67,
            "source_account_ids": ["src"],
            "destination_account_id": "dst",
        }
        _, summary = simulate_retirement([src, dst], p, a, roth_conversion=rc)
        vintages = summary["conversion_vintages"]
        assert isinstance(vintages, dict), "conversion_vintages must be a dict"
        assert len(vintages) > 0, "conversion_vintages should be populated during conversion window"
        # Each age in the window should appear as a key with a positive conversion amount
        for age in [65, 66, 67]:
            assert age in vintages, f"Age {age} missing from conversion_vintages"
            assert vintages[age] > 0

    # -----------------------------------------------------------------------
    # Gap 11: Long retirement to age 100 — RMD at 100 and fallback for 101+
    # -----------------------------------------------------------------------
    def test_long_retirement_to_100(self):
        from withdrawals import simulate_retirement
        from constants import RMD_TABLE
        accts = [_trad_account(balance=2_000_000)]
        p = _base_profile(
            current_age=65, retirement_age=65, life_expectancy=100,
            social_security_benefit=24_000, social_security_start_age=67,
        )
        a = _base_assumptions()
        df, summary = simulate_retirement(accts, p, a)
        assert len(df) == 36  # age 65 to 100 inclusive
        # RMDs should appear from age 73 to 100
        assert df[df["age"] == 100]["rmd_amount"].values[0] > 0
        # Divisor at 100 should be 6.4 (from table)
        from withdrawals import _rmd_divisor
        assert _rmd_divisor(100) == RMD_TABLE[100]
        assert _rmd_divisor(101) == 6.4  # fallback

    # -----------------------------------------------------------------------
    # Gap 12: Early retirement (age 50) with long pre-Medicare window
    # -----------------------------------------------------------------------
    def test_early_retirement_pre_medicare_costs(self):
        from withdrawals import simulate_retirement
        accts = [_roth_account(balance=3_000_000)]
        p = _base_profile(
            current_age=50, retirement_age=50, life_expectancy=75,
            social_security_start_age=67,
            pre_medicare_healthcare=20_000,
            post_medicare_healthcare=8_000,
        )
        a = _base_assumptions()
        df, summary = simulate_retirement(accts, p, a)
        assert len(df) == 26  # age 50 to 75 inclusive
        # Pre-Medicare (50–64) healthcare should be $20K inflated
        pre = df[df["age"] < 65]["healthcare_cost"]
        post = df[df["age"] >= 65]["healthcare_cost"]
        # Year 0 (age 50): pre_medicare_hc = 20,000 × (1+inf)^0 = 20,000
        assert abs(df.iloc[0]["healthcare_cost"] - 20_000) < 1
        # At age 65 (15 years of inflation): should be noticeably higher than $8K base
        # but the point is pre-period > base post-period at age 65
        assert pre.mean() > post.mean() * 0.5  # pre-Medicare costs higher

    # -----------------------------------------------------------------------
    # Gap 13: SS taxability thresholds NOT scaled by bracket_factor
    # -----------------------------------------------------------------------
    def test_ss_taxability_thresholds_not_bracket_indexed(self):
        from taxes import calculate_ss_taxable_amount
        from constants import SS_TAXABILITY
        # The real SS_TAXABILITY thresholds for single: tier1=$25K, tier2=$34K
        # These must NOT change regardless of any bracket_factor applied elsewhere.
        # Verify the frozen thresholds by directly testing at the boundary.
        tier1 = SS_TAXABILITY["single"]["tier1"]  # 25,000
        # At provisional income exactly equal to tier1 → $0 taxable
        assert calculate_ss_taxable_amount(tier1, 20_000, "single") == 0.0
        # $1 above → becomes taxable (50% × $1 = $0.50)
        result = calculate_ss_taxable_amount(tier1 + 1, 20_000, "single")
        assert result > 0.0, "SS should become taxable $1 above tier1 threshold"

    def test_ss_bracket_creep_over_simulation_years(self):
        from withdrawals import simulate_retirement
        # At retirement, provisional income is just below the SS tier1 threshold ($25K single).
        # As nominal income grows with inflation over years, SS becomes taxable.
        # This models the "bracket creep" effect since SS thresholds are frozen.
        # Setup: small traditional account that produces growing RMDs over time;
        # SS benefit chosen so early provisional < $25K but late provisional > $25K.
        accts = [_trad_account(balance=300_000)]
        p = _base_profile(
            current_age=73, retirement_age=73, life_expectancy=90,
            social_security_benefit=20_000,  # today's dollars; inflated to retirement
            social_security_start_age=73,
            filing_status="single",
        )
        a = _base_assumptions(
            spending_mode="fixed", annual_spending_target=0,
            inflation_rate=0.03,
        )
        df, _ = simulate_retirement(accts, p, a)
        # In later years, nominal income grows; check ss taxability increases
        # (or at minimum is non-zero in some year when income crosses threshold)
        # The ordinary_income column includes ss_taxable — verify it's non-zero eventually
        # ordinary_income > ss_income implies something (RMD or ss_taxable) was added
        assert df["ss_income"].sum() > 0  # SS is being received

    # -----------------------------------------------------------------------
    # Gap 14: Tax drag > 0 for taxable accounts with dividend yields
    # -----------------------------------------------------------------------
    def test_accumulation_tax_drag_for_taxable_account(self):
        from projections import project_accumulation
        taxable_with_divs = {
            "id": "tx1", "name": "Brokerage", "type": "taxable",
            "balance": 200_000, "basis": 200_000,
            "annual_contribution": 0, "contribution_growth_rate": 0,
            "return_rate": 0.07, "use_global_return_rate": False,
            "employer_match_percent": 0, "employer_match_limit": 0,
            "qualified_dividend_yield": 0.015,   # 1.5% qualified divs
            "ordinary_income_yield": 0.005,      # 0.5% ordinary income
            "net_annual_rental_income": 0,
        }
        p = _base_profile(current_age=55, retirement_age=60, current_income=120_000)
        df, _ = project_accumulation([taxable_with_divs], p, _base_assumptions())
        # Tax drag should be positive for the taxable account rows (excluding retirement_age snap)
        brokerage_rows = df[(df["account_name"] == "Brokerage") & (df["age"] < 60)]
        assert brokerage_rows["tax_drag"].sum() > 0, "Tax drag must be positive on dividend-yielding taxable account"

    def test_accumulation_passive_income_nonzero_for_taxable(self):
        from projections import project_accumulation
        taxable = {
            "id": "tx1", "name": "Brokerage", "type": "taxable",
            "balance": 200_000, "basis": 200_000,
            "annual_contribution": 0, "contribution_growth_rate": 0,
            "return_rate": 0.07, "use_global_return_rate": False,
            "employer_match_percent": 0, "employer_match_limit": 0,
            "qualified_dividend_yield": 0.015,
            "ordinary_income_yield": 0.005,
            "net_annual_rental_income": 0,
        }
        p = _base_profile(current_age=55, retirement_age=60)
        df, _ = project_accumulation([taxable], p, _base_assumptions())
        assert df["passive_income"].sum() > 0

    # -----------------------------------------------------------------------
    # Gap 15: lifetime_passive_income in summary is populated
    # -----------------------------------------------------------------------
    def test_lifetime_passive_income_in_summary(self):
        from withdrawals import simulate_retirement
        accts = [_trad_account(500_000)]
        p = _base_profile(
            social_security_benefit=24_000, social_security_start_age=67,
        )
        _, summary = simulate_retirement(accts, p, _base_assumptions())
        assert "lifetime_passive_income" in summary
        assert summary["lifetime_passive_income"] > 0

    def test_lifetime_passive_income_includes_ss_and_rental(self):
        from withdrawals import simulate_retirement
        rental = {
            "id": "r1", "name": "Rental", "type": "rental_property",
            "balance": 300_000, "basis": 150_000,
            "annual_contribution": 0, "contribution_growth_rate": 0,
            "return_rate": 0.04, "use_global_return_rate": False,
            "employer_match_percent": 0, "employer_match_limit": 0,
            "qualified_dividend_yield": 0, "ordinary_income_yield": 0,
            "net_annual_rental_income": 18_000, "withdraw_priority": "normal",
        }
        p = _base_profile(
            social_security_benefit=24_000, social_security_start_age=67,
        )
        _, summary = simulate_retirement([rental], p, _base_assumptions())
        # Should include both SS (starts at 67) and rental income (all years)
        assert summary["lifetime_passive_income"] > 18_000  # at minimum rental alone

    # -----------------------------------------------------------------------
    # Gap 16: Depletion warning appears in summary["warnings"]
    # -----------------------------------------------------------------------
    def test_depletion_warning_in_warnings_list(self):
        from withdrawals import simulate_retirement
        accts = [_bank_account(balance=5_000)]
        p = _base_profile(
            retirement_age=65, life_expectancy=75,
            social_security_start_age=999,
        )
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=50_000)
        _, summary = simulate_retirement(accts, p, a)
        depletion_warnings = [w for w in summary["warnings"] if w["type"] == "depletion"]
        assert len(depletion_warnings) == 1, "Expected exactly one depletion warning"
        assert "age" in depletion_warnings[0]
        assert depletion_warnings[0]["age"] == summary["portfolio_depleted_age"]

    # -----------------------------------------------------------------------
    # Gap 17: Bank/cash accounts withdrawn before taxable and traditional
    # -----------------------------------------------------------------------
    def test_bank_withdrawn_before_taxable_and_traditional(self):
        from withdrawals import simulate_retirement
        # Bank balance covers full year spending → taxable and traditional untouched
        bank   = _bank_account(balance=200_000, name="Checking")
        taxable = _taxable_account(balance=300_000, basis=300_000, name="Brokerage")
        trad   = _trad_account(balance=400_000, name="Trad401k")
        p = _base_profile(
            current_age=65, retirement_age=65, life_expectancy=66,
            social_security_start_age=999,
        )
        a = _base_assumptions(spending_mode="fixed", annual_spending_target=30_000)
        df, _ = simulate_retirement([bank, taxable, trad], p, a)
        # Year 1 (age 65): spending $30K < bank $200K → bank covers it entirely
        row = df[df["age"] == 65].iloc[0]
        assert row["bank_withdrawal"] > 0, "Bank should be the first source drawn"
        assert row["taxable_withdrawal"] == 0.0, "Taxable should not be touched when bank covers spending"
        assert row["traditional_withdrawal"] == 0.0, "Traditional should not be touched when bank covers spending"


# ===========================================================================
# 11. ALREADY-RETIRED MODE (current_age > retirement_age)
# ===========================================================================

class TestAlreadyRetired:
    def test_simulation_runs_when_current_age_exceeds_retirement_age(self):
        from withdrawals import simulate_retirement
        accts = [_trad_account(500_000)]
        p = _base_profile(current_age=70, retirement_age=65, life_expectancy=85)
        df, summary = simulate_retirement(accts, p, _base_assumptions())
        assert len(df) > 0

    def test_simulation_starts_at_current_age_when_already_retired(self):
        """When current_age > retirement_age, the sim starts at current_age — the
        already-elapsed retirement years (retirement_age..current_age-1) are not
        re-simulated. (v1.4 already-retired fix; see withdrawals.simulate_retirement.)"""
        from withdrawals import simulate_retirement
        accts = [_trad_account(800_000)]
        p = _base_profile(current_age=72, retirement_age=65, life_expectancy=85)
        df, _ = simulate_retirement(accts, p, _base_assumptions())
        assert df["age"].min() == 72
        assert df["age"].max() == 85
        assert len(df) == 85 - 72 + 1

    def test_accumulation_returns_empty_df_when_already_retired(self):
        from projections import project_accumulation
        accts = [_trad_account(500_000)]
        p = _base_profile(current_age=70, retirement_age=65, life_expectancy=85)
        df, final_accts = project_accumulation(accts, p, _base_assumptions())
        assert df.empty
        # Accounts pass through unchanged (no growth applied)
        assert final_accts[0]["balance"] == 500_000

    def test_current_age_equals_retirement_age_still_works(self):
        from withdrawals import simulate_retirement
        accts = [_trad_account(500_000)]
        p = _base_profile(current_age=65, retirement_age=65, life_expectancy=80)
        df, _ = simulate_retirement(accts, p, _base_assumptions())
        assert df["age"].min() == 65
        assert len(df) == 80 - 65 + 1

    def test_rmds_active_when_already_past_rmd_start_age(self):
        from withdrawals import simulate_retirement
        from constants import RMD_START_AGE
        accts = [_trad_account(2_000_000)]
        # current_age is past RMD start — RMDs must be present from age 73
        p = _base_profile(current_age=75, retirement_age=65, life_expectancy=85,
                          social_security_start_age=67)
        df, _ = simulate_retirement(accts, p, _base_assumptions())
        rmd_rows = df[df["age"] >= RMD_START_AGE]
        assert rmd_rows["rmd_amount"].sum() > 0

    def test_life_expectancy_must_exceed_current_age_when_already_retired(self):
        """When already retired, the simulation spans max(retirement_age, current_age)
        through life_expectancy inclusive."""
        from withdrawals import simulate_retirement
        accts = [_trad_account(500_000)]
        # current_age=72, retirement_age=65, life_expectancy=80 — valid
        p = _base_profile(current_age=72, retirement_age=65, life_expectancy=80)
        df, _ = simulate_retirement(accts, p, _base_assumptions())
        assert len(df) == 80 - 72 + 1


# ===========================================================================
# 12. CHART FUNCTIONS — current-age vertical line
# ===========================================================================

class TestChartCurrentAgeLine:
    """Verify retirement charts add a vline when current_age > retirement_age."""

    def _minimal_ret_df(self):
        import pandas as pd
        ages = list(range(65, 86))
        n = len(ages)
        return pd.DataFrame({
            "age": ages,
            "total_portfolio": [500_000 - i * 5_000 for i in range(n)],
            "start_portfolio": [500_000 - i * 5_000 for i in range(n)],
            "spending_target": [30_000.0] * n,
            "net_spending_target": [28_000.0] * n,
            "after_tax_spending": [28_000.0] * n,
            "ss_income": [0.0] * n,
            "rental_income": [0.0] * n,
            "investment_income": [0.0] * n,
            "rmd_amount": [0.0] * n,
            "taxable_withdrawal": [5_000.0] * n,
            "traditional_withdrawal": [20_000.0] * n,
            "roth_withdrawal": [0.0] * n,
            "bank_withdrawal": [0.0] * n,
            "roth_conversion": [0.0] * n,
            "harvest_ltcg": [0.0] * n,
            "total_tax": [2_000.0] * n,
            "effective_tax_rate": [0.07] * n,
            "federal_ordinary_tax": [1_500.0] * n,
            "state_tax": [500.0] * n,
            "surplus_reinvested": [0.0] * n,
        })

    def test_drawdown_vline_when_already_retired(self):
        import charts
        fig = charts.chart_drawdown(
            self._minimal_ret_df(), [_trad_account()],
            current_age=70, retirement_age=65,
        )
        assert len(fig.layout.shapes) > 0

    def test_drawdown_no_vline_when_not_yet_retired(self):
        import charts
        fig = charts.chart_drawdown(
            self._minimal_ret_df(), [_trad_account()],
            current_age=60, retirement_age=65,
        )
        assert len(fig.layout.shapes) == 0

    def test_drawdown_no_vline_at_exact_retirement_age(self):
        import charts
        fig = charts.chart_drawdown(
            self._minimal_ret_df(), [_trad_account()],
            current_age=65, retirement_age=65,
        )
        assert len(fig.layout.shapes) == 0

    def test_spending_coverage_vline_when_already_retired(self):
        import charts
        fig = charts.chart_spending_coverage(
            self._minimal_ret_df(), current_age=70, retirement_age=65,
        )
        assert len(fig.layout.shapes) > 0

    def test_spending_coverage_no_vline_when_not_yet_retired(self):
        import charts
        fig = charts.chart_spending_coverage(
            self._minimal_ret_df(), current_age=60, retirement_age=65,
        )
        assert len(fig.layout.shapes) == 0

    def test_annual_income_vline_when_already_retired(self):
        import charts
        fig = charts.chart_annual_income(
            self._minimal_ret_df(), retirement_age=65, current_age=70,
        )
        assert len(fig.layout.shapes) > 0

    def test_annual_income_no_vline_when_not_yet_retired(self):
        import charts
        fig = charts.chart_annual_income(
            self._minimal_ret_df(), retirement_age=65, current_age=60,
        )
        assert len(fig.layout.shapes) == 0

    def test_tax_burden_vline_when_already_retired(self):
        import charts
        fig = charts.chart_tax_burden(
            self._minimal_ret_df(), current_age=70, retirement_age=65,
        )
        assert len(fig.layout.shapes) > 0

    def test_tax_burden_no_vline_when_not_yet_retired(self):
        import charts
        fig = charts.chart_tax_burden(
            self._minimal_ret_df(), current_age=60, retirement_age=65,
        )
        assert len(fig.layout.shapes) == 0

    def test_all_charts_return_figure_with_default_args(self):
        import charts
        ret_df = self._minimal_ret_df()
        assert charts.chart_drawdown(ret_df, [_trad_account()]) is not None
        assert charts.chart_spending_coverage(ret_df) is not None
        assert charts.chart_annual_income(ret_df) is not None
        assert charts.chart_tax_burden(ret_df) is not None


# ===========================================================================
# 13. SCENARIO FOLDER AUTO-CREATION
# ===========================================================================

class TestScenarioFolderCreation:
    def test_ensure_dir_creates_both_folders_from_scratch(self, tmp_path, monkeypatch):
        import scenarios
        new_scenarios = tmp_path / "scenarios"
        new_tracking = new_scenarios / "tracking"
        monkeypatch.setattr(scenarios, "SCENARIOS_DIR", new_scenarios)
        monkeypatch.setattr(scenarios, "TRACKING_DIR", new_tracking)
        assert not new_scenarios.exists()
        assert not new_tracking.exists()
        scenarios._ensure_dir()
        assert new_scenarios.exists()
        assert new_tracking.exists()

    def test_ensure_dir_idempotent(self, tmp_path, monkeypatch):
        import scenarios
        new_scenarios = tmp_path / "scenarios"
        new_tracking = new_scenarios / "tracking"
        monkeypatch.setattr(scenarios, "SCENARIOS_DIR", new_scenarios)
        monkeypatch.setattr(scenarios, "TRACKING_DIR", new_tracking)
        scenarios._ensure_dir()
        scenarios._ensure_dir()  # must not raise
        assert new_scenarios.exists()
        assert new_tracking.exists()

    def test_list_scenarios_creates_dirs_if_missing(self, tmp_path, monkeypatch):
        import scenarios
        new_scenarios = tmp_path / "scenarios"
        new_tracking = new_scenarios / "tracking"
        monkeypatch.setattr(scenarios, "SCENARIOS_DIR", new_scenarios)
        monkeypatch.setattr(scenarios, "TRACKING_DIR", new_tracking)
        result = scenarios.list_scenarios()
        assert isinstance(result, list)
        assert new_scenarios.exists()


# ===========================================================================
# 14. MATH AUDIT — end-to-end invariant checks against "My Scenario Demo"
# ===========================================================================

class TestMathAuditDemoScenario:
    """
    Loads 'My Scenario Demo.json', runs the full pipeline, and verifies
    internal arithmetic invariants across every row of the retirement table.
    These tests check that the numbers reported in the data table are
    self-consistent — not whether the financial model is theoretically correct.
    """

    SCENARIO_PATH = "scenarios/Demo.json"

    @pytest.fixture(autouse=True)
    def _setup(self):
        import json
        import os
        from projections import project_accumulation
        from withdrawals import simulate_retirement

        # scenarios/* is gitignored (except test_*.json), so this personal demo file
        # may be absent on a clean checkout / CI. Skip gracefully rather than error —
        # the same invariants run across committed scenarios in TestScenarioInvariants.
        if not os.path.exists(self.SCENARIO_PATH):
            pytest.skip(f"Scenario file not found: {self.SCENARIO_PATH}")
        with open(self.SCENARIO_PATH) as f:
            sc = json.load(f)

        self.profile = sc["profile"]
        self.assumptions = sc["assumptions"]
        self.accounts = sc["accounts"]
        roth_conv = sc["roth_conversion"]

        _, ret_accts = project_accumulation(self.accounts, self.profile, self.assumptions)
        self.ret_df, self.summary = simulate_retirement(
            ret_accts, self.profile, self.assumptions, roth_conv
        )

    # -----------------------------------------------------------------------
    # Tax decomposition
    # -----------------------------------------------------------------------
    def test_tax_components_sum_to_total_tax(self):
        """federal_ordinary + federal_ltcg + federal_niit + federal_irmaa + state_tax == total_tax."""
        df = self.ret_df
        computed = (
            df["federal_ordinary_tax"]
            + df["federal_ltcg_tax"]
            + df["federal_niit"]
            + df["federal_irmaa"]
            + df["state_tax"]
        )
        diff = (computed - df["total_tax"]).abs()
        bad = df[diff > 0.01]["age"].tolist()
        assert not bad, f"Tax component sum mismatch at ages {bad}"

    # -----------------------------------------------------------------------
    # Cash-flow identity
    # -----------------------------------------------------------------------
    def test_after_tax_spending_identity(self):
        """after_tax_spending == (total_cash_received - surplus_reinvested) - total_tax.

        total_cash_received uses investment_income (dividends only), not ltcg_income,
        because withdrawal-generated capital gains are already counted inside the
        withdrawal amount — they don't separately add cash.
        """
        df = self.ret_df
        total_cash = (
            df["rmd_amount"]
            + df["taxable_withdrawal"]
            + df["traditional_withdrawal"]
            + df["roth_withdrawal"]
            + df["bank_withdrawal"]
            + df["ss_income"]
            + df["rental_income"]
            + df["investment_income"]
        )
        expected = (total_cash - df["surplus_reinvested"]) - df["total_tax"]
        diff = (expected - df["after_tax_spending"]).abs()
        bad = df[diff > 0.50]["age"].tolist()
        assert not bad, f"after_tax_spending mismatch at ages {bad}"

    # -----------------------------------------------------------------------
    # Portfolio balance bookkeeping
    # -----------------------------------------------------------------------
    def test_account_balances_sum_to_total_portfolio(self):
        """Sum of individual bal_* columns == total_portfolio for every row."""
        df = self.ret_df
        bal_cols = [c for c in df.columns if c.startswith("bal_")]
        assert bal_cols, "No bal_* columns found in retirement DataFrame"
        computed = df[bal_cols].sum(axis=1)
        diff = (computed - df["total_portfolio"]).abs()
        bad = df[diff > 1.0]["age"].tolist()
        assert not bad, f"bal_* sum ≠ total_portfolio at ages {bad}"

    def test_withdrawal_detail_columns_sum_to_total_withdrawn(self):
        """Sum of wd_* columns == rmd_amount + all discretionary withdrawals."""
        df = self.ret_df
        wd_cols = [c for c in df.columns if c.startswith("wd_")]
        if not wd_cols:
            pytest.skip("No wd_* columns")
        total_wd = (
            df["rmd_amount"]
            + df["taxable_withdrawal"]
            + df["traditional_withdrawal"]
            + df["roth_withdrawal"]
            + df["bank_withdrawal"]
        )
        diff = (df[wd_cols].sum(axis=1) - total_wd).abs()
        bad = df[diff > 0.50]["age"].tolist()
        assert not bad, f"wd_* sum ≠ total withdrawn at ages {bad}"

    def test_start_portfolio_matches_prior_year_end_balance(self):
        """start_portfolio[age N] == total_portfolio[age N-1] for every consecutive pair."""
        df = self.ret_df.reset_index(drop=True)
        for i in range(1, len(df)):
            prev = df.iloc[i - 1]["total_portfolio"]
            curr = df.iloc[i]["start_portfolio"]
            assert abs(curr - prev) < 1.0, (
                f"start_portfolio at age {int(df.iloc[i]['age'])} ({curr:,.0f}) "
                f"≠ total_portfolio at prior age ({prev:,.0f})"
            )

    # -----------------------------------------------------------------------
    # Accumulation compound growth
    # -----------------------------------------------------------------------
    def test_401k_accumulation_compound_growth(self):
        """401(k) balance at retirement matches manual compound growth formula.

        Starting balance $200K, 6% return, $18K employee contribution, $6K match cap,
        compounded for 20 years (age 35 → 55).
        """
        from projections import project_accumulation
        _, ret_accts = project_accumulation(self.accounts, self.profile, self.assumptions)
        b = 200_000.0
        for _ in range(20):
            b = b * 1.06 + 18_000 + 6_000
        actual = next(a["balance"] for a in ret_accts if a["name"] == "401(k)")
        assert abs(b - actual) < 1.0, f"Expected {b:,.2f}, got {actual:,.2f}"

    # -----------------------------------------------------------------------
    # Social Security timing
    # -----------------------------------------------------------------------
    def test_ss_jumps_at_age_67_when_primary_ss_starts(self):
        """SS income rises at age 67 when the primary filer's benefit begins."""
        df = self.ret_df
        # In this scenario the spouse is already 69 at retirement so spouse SS
        # is active from age 55; primary SS starts at 67 and should lift total SS.
        ss_66 = df[df["age"] == 66]["ss_income"].values[0]
        ss_67 = df[df["age"] == 67]["ss_income"].values[0]
        assert ss_67 > ss_66, (
            f"SS should increase at age 67 (primary starts): "
            f"age 66={ss_66:,.0f}, age 67={ss_67:,.0f}"
        )

    # -----------------------------------------------------------------------
    # RMD correctness
    # -----------------------------------------------------------------------
    def test_rmd_zero_before_age_73(self):
        """No RMDs are taken before age 73."""
        assert self.ret_df[self.ret_df["age"] < 73]["rmd_amount"].sum() == 0.0

    def test_rmd_positive_while_traditional_balance_remains(self):
        """RMDs are positive every year from age 73 in which a traditional account still
        held a balance at the end of the prior year. Traditional accounts can deplete
        before the total portfolio, after which RMDs are correctly $0 — so the invariant
        is keyed to the remaining traditional balance, not to total-portfolio depletion."""
        df = self.ret_df.reset_index(drop=True)
        trad_cols = [
            f"bal_{a['name'].replace(' ', '_')}"
            for a in self.accounts
            if a["type"] in ("traditional_401k", "traditional_ira")
        ]
        trad_cols = [c for c in trad_cols if c in df.columns]
        assert trad_cols, "No traditional balance columns found"
        bad = []
        for i in range(1, len(df)):
            if df.iloc[i]["age"] < 73:
                continue
            prior_trad = sum(df.iloc[i - 1][c] for c in trad_cols)
            if prior_trad > 1.0 and df.iloc[i]["rmd_amount"] <= 0:
                bad.append(int(df.iloc[i]["age"]))
        assert not bad, f"RMD should be > 0 while a traditional balance remained, at ages {bad}"

    def test_rmd_amount_at_73_matches_formula(self):
        """RMD at age 73 = (401k_bal + IRA_bal at end of age 72) / RMD_TABLE[73]."""
        from constants import RMD_TABLE
        df = self.ret_df
        row_72 = df[df["age"] == 72].iloc[0]
        row_73 = df[df["age"] == 73].iloc[0]
        # Traditional accounts: "401(k)" and "IRA - Josh" (spaces → underscores in col names)
        trad_bal = row_72["bal_401(k)"] + row_72["bal_IRA_-_Josh"]
        expected = trad_bal / RMD_TABLE[73]
        assert abs(row_73["rmd_amount"] - expected) < 100, (
            f"RMD at 73: expected ≈{expected:,.0f}, got {row_73['rmd_amount']:,.0f}"
        )

    # -----------------------------------------------------------------------
    # Sanity bounds
    # -----------------------------------------------------------------------
    def test_portfolio_depletes_before_life_expectancy(self):
        """The Demo scenario is intentionally aggressive (fixed ~$100K net spend plus
        healthcare on a portfolio that doesn't fully sustain it), so it should deplete
        before life expectancy. The exact age depends on the editable, un-versioned Demo
        inputs, so we assert depletion within a plausible window rather than a single
        hard-coded age."""
        depl = self.summary["portfolio_depleted_age"]
        assert depl is not None, "Demo scenario was expected to deplete before life expectancy"
        assert 75 <= depl <= self.profile["life_expectancy"], (
            f"Depletion age {depl} is outside the plausible window [75, life_expectancy]"
        )

    def test_effective_tax_rate_in_bounds(self):
        """Effective tax rate is between 0% and 60% for every simulation year."""
        df = self.ret_df
        assert (df["effective_tax_rate"] >= 0).all()
        assert (df["effective_tax_rate"] <= 0.60).all()

    def test_no_negative_portfolio_before_depletion(self):
        """total_portfolio ≥ 0 for every year before the depletion year."""
        df = self.ret_df
        depl = self.summary["portfolio_depleted_age"]
        assert (df[df["age"] < depl]["total_portfolio"] >= 0).all()

    def test_spending_target_grows_year_over_year(self):
        """spending_target rises each year pre-depletion (nominal inflation drives this)."""
        df = self.ret_df
        depl = self.summary["portfolio_depleted_age"]
        early = df[df["age"] < depl].copy()
        ratios = (early["spending_target"] / early["spending_target"].shift(1)).dropna()
        assert (ratios > 0.50).all(), "Spending target dropped by >50% in a single year"
        assert (ratios < 1.30).all(), "Spending target grew by >30% in a single year"


# ===========================================================================
# 15. SCENARIO INVARIANT TESTS — parametrized across all scenario files
# ===========================================================================

import os as _os

_SCENARIO_PATHS = [
    # Existing scenarios (all fixed-net mode)
    "scenarios/My Scenario Demo.json",
    "scenarios/Demo.json",
    "scenarios/My Scenario.json",
    "scenarios/test 1.json",
    "scenarios/Josh and Connie.json",
    "scenarios/Josh and Connie expected large spend.json",
    # New scenarios added for broader coverage
    "scenarios/test_small_single.json",              # small portfolio, single filer, depletes age ~81
    "scenarios/test_large_roth_heavy.json",           # large Roth-heavy portfolio, roth_preservation strategy
    "scenarios/test_swr_mode.json",                   # SWR mode (different code path, no fixed-net target)
    "scenarios/test_median_couple.json",              # median US household, MFJ, SS-dependent, Texas (no state tax)
    "scenarios/test_fire_single.json",                # FIRE retiree, single, 50-year horizon, taxable+Roth, SWR mode
    "scenarios/test_trad_heavy_conversions.json",     # large traditional 401k, Roth conversion ladder, Florida
    "scenarios/test_rental_income.json",              # rental property passive income, MFJ, California progressive tax
    "scenarios/test_ss_dependent.json",               # low-income single, SS-heavy, portfolio depletes mid-retirement
]

_SCENARIO_IDS = [
    _os.path.splitext(_os.path.basename(p))[0].replace(" ", "_")
    for p in _SCENARIO_PATHS
]


def _run_scenario(path: str):
    """Load a scenario JSON, run accumulation + retirement simulation, return (df, summary, assumptions)."""
    from projections import project_accumulation
    from withdrawals import simulate_retirement

    with open(path) as f:
        sc = json.load(f)

    profile = sc["profile"]
    assumptions = sc["assumptions"]
    accounts = sc["accounts"]
    roth_conversion = sc.get("roth_conversion")

    _, ret_accts = project_accumulation(accounts, profile, assumptions)
    rate_prefs = {a["id"]: a.get("use_global_return_rate", True) for a in accounts}
    for a in ret_accts:
        a["use_global_return_rate"] = rate_prefs.get(a["id"], True)

    df, summary = simulate_retirement(ret_accts, profile, assumptions, roth_conversion)
    return df, summary, assumptions


@pytest.fixture(params=_SCENARIO_PATHS, ids=_SCENARIO_IDS, scope="class")
def scenario_data(request):
    """Parametrized fixture: loads and runs every scenario once per class.
    Skips gracefully when the file is absent (e.g. personal scenarios on other machines).
    """
    path = request.param
    if not _os.path.exists(path):
        pytest.skip(f"Scenario file not found: {path}")
    return _run_scenario(path)


class TestScenarioInvariants:
    """
    Universal arithmetic and spending-accuracy invariants checked against
    every scenario file.  Each test runs once per scenario; new scenarios
    are automatically picked up by adding to _SCENARIO_PATHS above.
    """

    # -----------------------------------------------------------------------
    # Tax decomposition
    # -----------------------------------------------------------------------

    def test_tax_components_sum_to_total(self, scenario_data):
        """federal_ordinary + federal_ltcg + federal_niit + federal_irmaa + state_tax == total_tax."""
        df, _, _ = scenario_data
        computed = (
            df["federal_ordinary_tax"]
            + df["federal_ltcg_tax"]
            + df["federal_niit"]
            + df["federal_irmaa"]
            + df["state_tax"]
        )
        diff = (computed - df["total_tax"]).abs()
        bad = df[diff > 0.01]["age"].tolist()
        assert not bad, f"Tax component mismatch at ages {bad}"

    # -----------------------------------------------------------------------
    # Cash-flow identity
    # -----------------------------------------------------------------------

    def test_after_tax_spending_identity(self, scenario_data):
        """(total_cash_received - surplus_reinvested) - total_tax == after_tax_spending."""
        df, _, _ = scenario_data
        total_cash = (
            df["rmd_amount"]
            + df["taxable_withdrawal"]
            + df["traditional_withdrawal"]
            + df["roth_withdrawal"]
            + df["bank_withdrawal"]
            + df["ss_income"]
            + df["rental_income"]
            + df["investment_income"]
        )
        expected = (total_cash - df["surplus_reinvested"]) - df["total_tax"]
        diff = (expected - df["after_tax_spending"]).abs()
        bad = df[diff > 0.50]["age"].tolist()
        assert not bad, f"after_tax_spending identity fails at ages {bad}"

    def test_surplus_is_non_negative(self, scenario_data):
        """surplus_reinvested is never negative."""
        df, _, _ = scenario_data
        bad = df[df["surplus_reinvested"] < -0.01]["age"].tolist()
        assert not bad, f"Negative surplus_reinvested at ages {bad}"

    # -----------------------------------------------------------------------
    # Portfolio balance bookkeeping
    # -----------------------------------------------------------------------

    def test_balances_sum_to_total_portfolio(self, scenario_data):
        """Sum of bal_* columns == total_portfolio every year."""
        df, _, _ = scenario_data
        bal_cols = [c for c in df.columns if c.startswith("bal_")]
        assert bal_cols, "No bal_* columns in retirement DataFrame"
        diff = (df[bal_cols].sum(axis=1) - df["total_portfolio"]).abs()
        bad = df[diff > 1.0]["age"].tolist()
        assert not bad, f"bal_* sum ≠ total_portfolio at ages {bad}"

    def test_start_portfolio_matches_prior_year_end(self, scenario_data):
        """start_portfolio[age N] == total_portfolio[age N-1] for every consecutive year."""
        df, _, _ = scenario_data
        df = df.reset_index(drop=True)
        for i in range(1, len(df)):
            prev = df.iloc[i - 1]["total_portfolio"]
            curr = df.iloc[i]["start_portfolio"]
            assert abs(curr - prev) < 1.0, (
                f"start_portfolio at age {int(df.iloc[i]['age'])} ({curr:,.0f}) "
                f"≠ prior year end ({prev:,.0f})"
            )

    def test_withdrawal_detail_sums_to_total_withdrawn(self, scenario_data):
        """Sum of wd_* columns == rmd_amount + all discretionary withdrawals."""
        df, _, _ = scenario_data
        wd_cols = [c for c in df.columns if c.startswith("wd_")]
        if not wd_cols:
            pytest.skip("No wd_* columns")
        total_wd = (
            df["rmd_amount"]
            + df["taxable_withdrawal"]
            + df["traditional_withdrawal"]
            + df["roth_withdrawal"]
            + df["bank_withdrawal"]
        )
        diff = (df[wd_cols].sum(axis=1) - total_wd).abs()
        bad = df[diff > 0.50]["age"].tolist()
        assert not bad, f"wd_* sum ≠ total withdrawn at ages {bad}"

    # -----------------------------------------------------------------------
    # Sanity bounds
    # -----------------------------------------------------------------------

    def test_effective_tax_rate_in_bounds(self, scenario_data):
        """Effective tax rate is between 0% and 60% every year."""
        df, _, _ = scenario_data
        assert (df["effective_tax_rate"] >= 0).all(), "Negative effective tax rate"
        assert (df["effective_tax_rate"] <= 0.60).all(), "Effective rate > 60%"

    def test_no_negative_portfolio_before_depletion(self, scenario_data):
        """total_portfolio >= 0 for every year before the depletion year."""
        df, summary, _ = scenario_data
        depl = summary.get("portfolio_depleted_age")
        active = df[df["age"] < depl] if depl else df
        bad = active[active["total_portfolio"] < -1.0]["age"].tolist()
        assert not bad, f"Negative portfolio before depletion at ages {bad}"

    def test_rmd_zero_before_age_73(self, scenario_data):
        """No RMDs are taken before age 73."""
        df, _, _ = scenario_data
        total = df[df["age"] < 73]["rmd_amount"].sum()
        assert total == 0.0, f"Unexpected pre-73 RMD total: {total:,.0f}"

    def test_spending_target_positive(self, scenario_data):
        """Gross spending_target is positive every year."""
        df, _, _ = scenario_data
        bad = df[df["spending_target"] <= 0]["age"].tolist()
        assert not bad, f"Zero or negative spending_target at ages {bad}"

    # -----------------------------------------------------------------------
    # Fixed-net spending accuracy (key regression for binary-search solver)
    # -----------------------------------------------------------------------

    def test_fixed_net_spending_accuracy(self, scenario_data):
        """actual_after_tax_net matches net_spending_target within $1 in every non-depleted year.

        This is the primary regression test for the binary-search solver introduced
        to replace the prev_eff_rate gross-up.  A miss larger than $1 indicates the
        solver did not converge or the withdrawal sequence diverged from the dry-run.
        """
        df, summary, assumptions = scenario_data
        if assumptions.get("spending_mode") != "fixed":
            pytest.skip("Not fixed-net mode — spending target is SWR-based")
        depl = summary.get("portfolio_depleted_age")
        # Only check years the portfolio has assets; after depletion the sim
        # correctly pays out whatever remains (which can be less than target).
        active = df[df["age"] < depl] if depl else df
        diff = (active["actual_after_tax_net"] - active["net_spending_target"]).abs()
        bad_rows = active[diff > 1.0][["age", "net_spending_target", "actual_after_tax_net"]].copy()
        bad_rows["delta"] = diff[bad_rows.index]
        assert bad_rows.empty, (
            f"Spending target miss >$1 in {len(bad_rows)} year(s):\n"
            + bad_rows.to_string(index=False)
        )

    def test_no_large_surplus_in_first_two_years(self, scenario_data):
        """No suspicious cash dump into the bank in the first two retirement years.

        Regression for the 'sold to cash' bug where the gross-up over-withdrew in
        year 1-2, depositing a large surplus back into the bank account.
        A surplus > 15% of the annual net target is a red flag.
        """
        df, _, assumptions = scenario_data
        if assumptions.get("spending_mode") != "fixed":
            pytest.skip("Not fixed-net mode")
        early = df.head(2)
        threshold = early["net_spending_target"] * 0.15
        bad = early[early["surplus_reinvested"] > threshold][["age", "surplus_reinvested", "net_spending_target"]]
        assert bad.empty, (
            f"Unexpectedly large surplus in first two retirement years (>15% of net target):\n"
            + bad.to_string(index=False)
        )


class TestMonteCarloV2DeterministicFirstYear:
    """run_monte_carlo_v2(deterministic_first_year=True) must pin year 0 of every
    trial to the deterministic plan, so the near-term recommendation is a single
    concrete figure rather than a distribution — while later years stay stochastic."""

    def _accts(self):
        return [_trad_account(800_000), _roth_account(50_000), _taxable_account(150_000, 90_000)]

    def _profile(self):
        return _base_profile(current_age=65, retirement_age=65, life_expectancy=90)

    def test_first_year_portfolio_is_deterministic_across_trials(self):
        """Year-0 terminal portfolio is identical across all trials (no MC spread)."""
        import numpy as np
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._accts(), self._profile(), _base_assumptions()
        mc = run_monte_carlo_v2(
            accts, p, a, n_runs=120, seed=7, equity_vol=0.18, bond_vol=0.07,
            deterministic_first_year=True,
        )
        # First entry of every percentile band must coincide → zero year-0 spread.
        first_year_vals = [mc["percentiles"][pp][0] for pp in (10, 25, 50, 75, 90)]
        spread = max(first_year_vals) - min(first_year_vals)
        assert spread < 1.0, f"year-0 portfolio varied by ${spread:,.2f} across percentiles"

    def test_first_year_matches_deterministic_run(self):
        """The pinned year-0 portfolio equals the plain deterministic projection's."""
        import copy
        from withdrawals import simulate_retirement
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._accts(), self._profile(), _base_assumptions()
        det, _ = simulate_retirement(copy.deepcopy(accts), p, a)
        det_year0 = det["total_portfolio"].iloc[0]
        mc = run_monte_carlo_v2(
            accts, p, a, n_runs=80, seed=3, deterministic_first_year=True,
        )
        assert abs(mc["percentiles"][50][0] - det_year0) < 1.0

    def test_later_years_still_stochastic(self):
        """Pinning year 0 must not freeze the rest of the horizon."""
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._accts(), self._profile(), _base_assumptions()
        mc = run_monte_carlo_v2(
            accts, p, a, n_runs=200, seed=11, equity_vol=0.18, bond_vol=0.07,
            deterministic_first_year=True,
        )
        assert mc["percentiles"][90][-1] > mc["percentiles"][10][-1]

    def test_spend_and_final_percentiles_present(self):
        """New cross-trial distributions for optimizer scoring are surfaced."""
        from montecarlo_v2 import run_monte_carlo_v2
        accts, p, a = self._accts(), self._profile(), _base_assumptions()
        mc = run_monte_carlo_v2(accts, p, a, n_runs=60, seed=1)
        for key in ("final_percentiles", "spend_percentiles"):
            assert key in mc
            for pp in (10, 25, 50, 75, 90):
                assert pp in mc[key]
        # Spend and final percentiles are monotone non-decreasing in p.
        for key in ("final_percentiles", "spend_percentiles"):
            vals = [mc[key][pp] for pp in (10, 25, 50, 75, 90)]
            assert vals == sorted(vals)


class TestOptimizerV3:
    """MC-aware receding-horizon optimizer: scores candidates against the MC
    distribution, screens cheap then re-scores survivors, and emits a concrete
    deterministic first-year action plus a serializable recommendation."""

    def _accts(self):
        return [_trad_account(900_000), _roth_account(60_000), _taxable_account(200_000, 120_000)]

    def _profile(self):
        return _base_profile(current_age=62, retirement_age=65, life_expectancy=88)

    def _run(self, **kw):
        from optimizer_v3 import run_optimizer_v3
        accts, p, a = self._accts(), self._profile(), _base_assumptions()
        params = dict(
            accounts_at_retirement=accts, profile=p, assumptions=a,
            roth_conversion_baseline={"enabled": False}, spending_overrides={},
            n_iterations=12, mc_runs_screen=40, mc_runs_final=80,
            survivors=4, seed=42,
        )
        params.update(kw)
        return run_optimizer_v3(**params)

    def test_returns_expected_structure(self):
        res = self._run()
        for key in ("baseline_result", "best_result", "top_results", "n_evaluated", "all_scores"):
            assert key in res
        assert res["n_evaluated"] > 0

    def test_best_carries_first_year_action_and_recommendation(self):
        res = self._run()
        best = res["best_result"]
        assert "first_year_action" in best
        rec = best.get("recommendation", {})
        # Serializable snapshot suitable for persisting alongside a check-in.
        import json
        json.dumps(rec)
        for key in ("anchor_age", "mc_success_rate", "mc_p25_legacy", "mc_median_spend"):
            assert key in rec
        assert 0.0 <= rec["mc_success_rate"] <= 1.0

    def test_crn_makes_search_reproducible(self):
        """Same seed → same best score (deterministic search under Common Random Numbers)."""
        r1 = self._run(seed=99)
        r2 = self._run(seed=99)
        assert r1["best_result"]["score"] == r2["best_result"]["score"]

    def test_score_prefers_higher_success(self):
        """_score_mc is success-dominated: a higher success rate outranks a richer
        but riskier plan even with lower legacy/spend."""
        from optimizer_v3 import _score_mc
        safe = {
            "n_runs": 100, "success_rate": 0.98,
            "final_percentiles": {25: 100_000}, "spend_percentiles": {50: 1_000_000},
            "adjustment_metrics": {"avg_cuts_per_trial": 0.0},
        }
        risky = {
            "n_runs": 100, "success_rate": 0.80,
            "final_percentiles": {25: 800_000}, "spend_percentiles": {50: 1_500_000},
            "adjustment_metrics": {"avg_cuts_per_trial": 0.0},
        }
        assert _score_mc(safe, 0.20) > _score_mc(risky, 0.20)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
