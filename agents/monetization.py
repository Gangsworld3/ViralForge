from __future__ import annotations

from dataclasses import asdict
from typing import Any

from agents.base import BaseAgent, PipelineState
from monetization.monetization import MonetizationEngine


class MonetizationAgent(BaseAgent):
    name = "monetize"

    def __init__(self, config, router, memory, healer, logger=None):
        super().__init__(config, router, memory, healer, logger=logger)
        self.engine = MonetizationEngine(config, memory, logger=logger)

    def run(self, state: PipelineState) -> dict[str, Any]:
        def _execute() -> dict[str, Any]:
            products = self.engine.discover_products(state.topic)
            plan = self.engine.generate_plan(state.topic, state.analytics, state.script, products=products)
            funnel = self.engine.funnel.build(state.topic, products, plan.disclosure)
            state.monetization = {
                "eligible": plan.eligible,
                "revenue_streams": plan.revenue_streams,
                "affiliate_copy": plan.affiliate_copy,
                "sponsorship_email": plan.sponsorship_email,
                "disclosure": plan.disclosure,
                "products": products,
                "funnel": asdict(funnel),
            }
            self.memory.save_memory("monetization", plan.affiliate_copy, state.monetization)
            return {
                "status": "ok",
                "summary": f"Monetization plan prepared ({'eligible' if plan.eligible else 'warming up'})",
                "plan": state.monetization,
                "products": products,
                "funnel": asdict(funnel),
            }

        return self.healer.safe_execute(self.name, _execute, retries=1)
