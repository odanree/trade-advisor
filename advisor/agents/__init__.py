"""LLM-driven agents: analysts, bull/bear debate, and synthesizer."""

from advisor.agents.debate import DebateResult, run_debate
from advisor.agents.synthesizer import SynthesizerOutput, synthesize

__all__ = ["DebateResult", "SynthesizerOutput", "run_debate", "synthesize"]
