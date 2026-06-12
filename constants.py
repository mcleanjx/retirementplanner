# 2026 tax constants — brackets made permanent via One Big Beautiful Bill

# Standard deductions
STANDARD_DEDUCTION = {
    "single": 16100,
    "married_filing_jointly": 32200,
}

# Ordinary income brackets: list of (threshold, rate) — threshold is taxable income above standard deduction
# Each tuple = upper bound of bracket (None = no limit), marginal rate
ORDINARY_BRACKETS = {
    "single": [
        (12400,  0.10),
        (50400,  0.12),
        (105700, 0.22),
        (201775, 0.24),
        (256225, 0.32),
        (640600, 0.35),
        (None,   0.37),
    ],
    "married_filing_jointly": [
        (24800,  0.10),
        (100800, 0.12),
        (211400, 0.22),
        (403550, 0.24),
        (512450, 0.32),
        (768700, 0.35),
        (None,   0.37),
    ],
}

# LTCG brackets: (upper bound of taxable income, rate) — None = no limit
LTCG_BRACKETS = {
    "single": [
        (49450,  0.00),
        (545500, 0.15),
        (None,   0.20),
    ],
    "married_filing_jointly": [
        (98900,  0.00),
        (613700, 0.15),
        (None,   0.20),
    ],
}

# Net Investment Income Tax
NIIT_RATE = 0.038
NIIT_THRESHOLD = {
    "single": 200000,
    "married_filing_jointly": 250000,
}

# IRMAA 2026 — monthly surcharges per person (Part B + Part D)
# (magi_upper_mfj, magi_upper_single, monthly_part_b_surcharge, monthly_part_d_surcharge)
# First tier = base (no surcharge); subsequent tiers add to the base premium of $202.90
IRMAA_TIERS = [
    # (MFJ upper, Single upper, Part B surcharge/mo, Part D surcharge/mo)
    (218000,  109000,  0.00,   0.00),
    (274000,  137000,  81.20,  14.50),
    (342000,  171000, 203.70,  37.60),
    (410000,  205000, 325.20,  60.60),
    (750000,  500000, 406.90,  83.70),
    (None,    None,   487.00,  91.00),
]
MEDICARE_PART_B_BASE_MONTHLY = 202.90  # per person

# RMD uniform lifetime table: age -> distribution period divisor
RMD_TABLE = {
    72: 27.4, 73: 26.5, 74: 25.5, 75: 24.6, 76: 23.7, 77: 22.9,
    78: 22.0, 79: 21.1, 80: 20.2, 81: 19.4, 82: 18.5, 83: 17.7,
    84: 16.8, 85: 16.0, 86: 15.2, 87: 14.4, 88: 13.7, 89: 12.9,
    90: 12.2, 91: 11.5, 92: 10.8, 93: 10.1, 94:  9.5, 95:  8.9,
    96:  8.4, 97:  7.8, 98:  7.3, 99:  6.8, 100: 6.4,
}
RMD_START_AGE = 73

# Social Security combined income thresholds for taxability
SS_TAXABILITY = {
    "single":                {"tier1": 25000, "tier2": 34000},
    "married_filing_jointly": {"tier1": 32000, "tier2": 44000},
}

# IRS contribution limits 2026 (approximate — stretch goal enforcement)
CONTRIBUTION_LIMITS = {
    "401k": 23500,
    "401k_catchup_50": 7500,   # age 50-59 and 64+
    "401k_catchup_60": 11250,  # age 60-63 (SECURE 2.0 super catch-up)
    "ira": 7000,
    "ira_catchup": 1000,       # age 50+
    "hsa_single": 4300,
    "hsa_family": 8550,
}

# ---------------------------------------------------------------------------
# California state income tax — 2026
# Source: CA FTB / EDD withholding schedules
# Key differences from federal:
#   - Capital gains taxed as ordinary income (no preferential rate)
#   - Social Security benefits NOT taxed
#   - Much lower standard deduction
#   - 13.3% top rate = 12.3% + 1% Mental Health Services Tax (income > $1M single / $1,354,550 MFJ)
# ---------------------------------------------------------------------------

CA_STANDARD_DEDUCTION = {
    "single": 5706,
    "married_filing_jointly": 11412,
}

# Brackets: (upper bound of CA taxable income, marginal rate); None = no upper limit
CA_ORDINARY_BRACKETS = {
    "single": [
        (10756,   0.010),
        (25499,   0.020),
        (40245,   0.040),
        (55866,   0.060),
        (70606,   0.080),
        (360659,  0.093),
        (432787,  0.103),
        (721314,  0.113),
        (1000000, 0.123),
        (None,    0.133),  # 12.3% + 1% MHST
    ],
    "married_filing_jointly": [
        (21512,   0.010),
        (50998,   0.020),
        (80490,   0.040),
        (111732,  0.060),
        (141212,  0.080),
        (721318,  0.093),
        (865574,  0.103),
        (1000000, 0.113),
        (1354550, 0.123),
        (None,    0.133),  # 12.3% + 1% MHST
    ],
}

# ---------------------------------------------------------------------------
# Montana state income tax — 2026
# Source: MT DOR HB337 (effective January 1, 2026)
# Key differences from federal:
#   - Long-term capital gains taxed at preferential rates (3.0% / 4.1%), with
#     bracket thresholds matching the ordinary-income ranges
#   - Social Security taxable at same rate as federal (not excluded)
#   - Standard deduction mirrors federal (MT adopted federal standard deduction)
# ---------------------------------------------------------------------------

MT_STANDARD_DEDUCTION = {
    "single": 16100,             # mirrors federal STANDARD_DEDUCTION
    "married_filing_jointly": 32200,
}

# Brackets: (upper bound of MT taxable income, marginal rate); None = no upper limit
MT_ORDINARY_BRACKETS = {
    "single": [
        (47500, 0.047),
        (None,  0.0565),
    ],
    "married_filing_jointly": [
        (95000, 0.047),
        (None,  0.0565),
    ],
}

# Net long-term capital gains rates (HB337, 2026). Thresholds match the ordinary
# ranges; the rate is determined by where LTCG stacks on top of ordinary income.
MT_LTCG_BRACKETS = {
    "single": [
        (47500, 0.030),
        (None,  0.041),
    ],
    "married_filing_jointly": [
        (95000, 0.030),
        (None,  0.041),
    ],
}

# Bracket ceiling for each named bracket (taxable income, above standard deduction)
BRACKET_CEILINGS = {
    "single": {
        0.10: 12400,
        0.12: 50400,
        0.22: 105700,
        0.24: 201775,
    },
    "married_filing_jointly": {
        0.10: 24800,
        0.12: 100800,
        0.22: 211400,
        0.24: 403550,
    },
}
