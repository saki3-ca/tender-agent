"""
Deterministic scoring and priority engine for ACNABIN opportunities.
Implements the exact scoring algorithm, breakdown tracking, and priority banding from Section 17.
"""

from typing import Any, Dict, Tuple
from app.utils.config import config


class ScoringEngine:
    """Calculates integer scores (0-100) and assigns priority bands deterministically."""

    def __init__(self):
        self.scoring_config = config.scoring
        self.base_scores = self.scoring_config["category_base_scores"]
        self.modifiers = self.scoring_config["modifiers"]

    def compute_score(
        self,
        category: str,
        record_type: str,
        organization_type: str,
        is_target_bank: bool,
        fit_type: str,
        source_tier: int,
        confidence: str,
        is_aqr_or_diagnostic: bool = False
    ) -> Tuple[int, str, Dict[str, int], str]:
        """
        Calculates score, priority band, breakdown dict, and human-readable reasoning summary.
        Returns: (score, priority, score_breakdown, reasoning_summary)
        """
        breakdown: Dict[str, int] = {}
        reasoning_parts = []

        # 1. Base score by category
        base = self.base_scores.get(category, 25)
        breakdown["category_base"] = base
        reasoning_parts.append(f"Category {category} base: {base}")

        # 2. Opportunity modifier (+15)
        if record_type == "OPPORTUNITY":
            opp_mod = self.modifiers.get("is_opportunity_yes", 15)
            breakdown["is_opportunity"] = opp_mod
            reasoning_parts.append(f"Genuine procurement notice (+{opp_mod})")
        else:
            breakdown["is_opportunity"] = 0

        # 3. Financial institution / regulator (+10)
        is_fi = is_target_bank or any(t in str(organization_type).lower() for t in ["bank", "nbfi", "regulator", "insurer"])
        if is_fi:
            fi_mod = self.modifiers.get("is_financial_institution_or_regulator", 10)
            breakdown["financial_institution_bonus"] = fi_mod
            reasoning_parts.append(f"Target financial institution/regulator (+{fi_mod})")
        else:
            breakdown["financial_institution_bonus"] = 0

        # 4. Fit Type modifier
        fit_mods = self.modifiers.get("fit_type", {})
        fit_mod = fit_mods.get(fit_type, 0)
        breakdown["fit_type_mod"] = fit_mod
        if fit_mod > 0:
            reasoning_parts.append(f"Fit {fit_type} (+{fit_mod})")

        # 5. Source Tier modifier (+5 for Tier 1/2)
        if source_tier in (1, 2):
            tier_mod = self.modifiers.get("source_tier_1_or_2", 5)
            breakdown["source_tier_bonus"] = tier_mod
            reasoning_parts.append(f"Verified Tier {source_tier} source (+{tier_mod})")
        else:
            breakdown["source_tier_bonus"] = 0

        # 6. Confidence Penalty
        conf_penalties = self.modifiers.get("confidence_penalty", {})
        conf_pen = conf_penalties.get(confidence.upper(), 0)
        breakdown["confidence_penalty"] = conf_pen
        if conf_pen < 0:
            reasoning_parts.append(f"Confidence {confidence} penalty ({conf_pen})")

        # 7. AQR / Major Banking Diagnostic (+10)
        if is_aqr_or_diagnostic:
            aqr_mod = self.modifiers.get("aqr_or_banking_diagnostic_bonus", 10)
            breakdown["aqr_diagnostic_bonus"] = aqr_mod
            reasoning_parts.append(f"Asset Quality Review / Banking Diagnostic (+{aqr_mod})")
        else:
            breakdown["aqr_diagnostic_bonus"] = 0

        # Total and Clamp 0-100
        raw_score = sum(breakdown.values())
        score = max(0, min(100, raw_score))
        breakdown["total_clamped"] = score

        # Priority Banding
        if score >= 85:
            priority = "VERY HIGH"
        elif score >= 70:
            priority = "HIGH"
        elif score >= 55:
            priority = "MEDIUM"
        elif score >= 40:
            priority = "LOW"
        else:
            priority = "IGNORE"

        reasoning_summary = "; ".join(reasoning_parts) + f". Final Score: {score} -> Priority: {priority}"
        return score, priority, breakdown, reasoning_summary
