import json
from agents.judge import JudgeAgent

pool = [
  {"hs_code": "41032000", "description": "Of reptiles", "legal_notes": "Note 1: This Chapter does not cover (a) parings..."},
  {"hs_code": "05119990", "description": "Other", "legal_notes": ""}
]

judge = JudgeAgent()
res = judge.evaluate_candidates("da cá sấu thô", pool, {"material": "crocodile skin"})
print(res)
