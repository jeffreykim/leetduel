from src.submit import Problem
from src.crud import get_problem
from src.database import SessionLocal
from src.dataclass import ProblemData

def get_specific_problem(difficulty: list[bool], problem_id: int) -> ProblemData:
    db = SessionLocal()

    try:
        problem = get_problem(db, difficulty, problem_id)
        if not problem:
            raise ValueError
        return problem.asdata()
    
    finally:
        db.close()


def test_any_order():
    p = get_specific_problem([True, True, True], 1)
    problem = Problem(100, p)

    code = """
def twoSum(nums: list[int], target: int) -> list[int]:
    hashmap = {}
    for i in range(len(nums)):
        complement = target - nums[i]
        if complement in hashmap:
            return [i, hashmap[complement]]
        hashmap[nums[i]] = i
    # Return an empty list if no solution is found
    return []
"""

    r = problem.submit_code(code)

    print(r)
    assert "status" in r
    assert r["status"] == "Accepted"


def test_combination_sum():
    p = get_specific_problem([True, True, True], 21)
    problem = Problem(100, p)

    code = """
def combinationSum(candidates: list[int], target: int) -> list[list[int]]:
    dp = [[] for _ in range(target+1)]
    for c in candidates:                                  # O(N): for each candidate
        for i in range(c, target+1):                      # O(M): for each possible value <= target
            if i == c: dp[i].append([c])
            for comb in dp[i-c]: dp[i].append(comb + [c]) # O(M) worst: for each combination
    return dp[-1]
"""
    r = problem.submit_code(code)

    print(r)
    assert r.accepted
    print("all tests passed")

test_combination_sum()