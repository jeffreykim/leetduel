from sqlalchemy.orm import Session
from .models import Problem
from typing import List
import random


def get_problem(db: Session, difficulties: list[bool], problem_id: int | None = None) -> Problem | None:
    if problem_id is not None:
        return db.query(Problem).filter(Problem.problem_id == problem_id).first()
    enabled_difficulties: List[str] = []
    if difficulties[0]:
        enabled_difficulties.append("Easy")
    if difficulties[1]:
        enabled_difficulties.append("Medium")
    if difficulties[2]:
        enabled_difficulties.append("Hard")
    problems = db.query(Problem).filter(Problem.problem_difficulty.in_(enabled_difficulties)).all()
    if not problems:
        return None
    return random.choice(problems)


def get_count(db: Session):
    return db.query(Problem).count()


def create_problem(db: Session, title: str, description: str, difficulty: str, test_cases: list, function_signature: str, any_order: bool):
    db_problem = Problem(problem_name=title, problem_description=description, problem_difficulty=difficulty, test_cases=test_cases, function_signature=function_signature, any_order=any_order, reports=0)  
    db.add(db_problem)
    db.commit()
    db.refresh(db_problem)
    return db_problem


def check_problem_exists(db: Session, title: str) -> bool:
    return db.query(Problem).filter(Problem.problem_name == title).first() is not None

def check_problem_reports(db: Session, title: str) -> int:
    reports = db.query(Problem.reports).filter(Problem.problem_name == title).scalar()
    return reports if reports is not None else 0

def increment_reports(db: Session, title: str) -> None:
    reports = db.query(Problem.reports).filter(Problem.problem_name == title).scalar()
    if reports is not None:
        db.query(Problem).filter(Problem.problem_name == title).update({"reports": reports + 1})
        db.commit()

def remove_reported_problems(db: Session) -> int:
    count = db.query(Problem).filter(Problem.reports >= 1).count()
    db.query(Problem).filter(Problem.reports >= 1).delete(synchronize_session=False)
    db.commit()
    return count