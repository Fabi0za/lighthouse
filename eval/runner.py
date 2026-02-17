from __future__ import annotations

from typing import Any

from app.models.database import DatabaseClient
from app.pipeline import QueryPipeline
from eval.metrics import refusal_accuracy, retrieval_recall


class EvalRunner:
    def __init__(
        self,
        db: DatabaseClient,
        pipeline: QueryPipeline,
        config_snapshot: dict[str, Any],
        notes: str | None = None,
    ):
        self.db = db
        self.pipeline = pipeline
        self.config_snapshot = config_snapshot
        self.notes = notes

    async def run(self) -> dict[str, Any]:
        questions = self.db.get_eval_questions()
        results = []

        for q in questions:
            result = await self._evaluate_question(q)
            results.append(result)

        aggregate = self._aggregate(results)

        run_data = {
            "config_snapshot": self.config_snapshot,
            "results": results,
            "aggregate_scores": aggregate,
            "notes": self.notes,
        }
        self.db.insert_eval_run(run_data)

        return {"aggregate_scores": aggregate, "results": results}

    async def _evaluate_question(self, question: dict[str, Any]) -> dict[str, Any]:
        pipeline_result = await self.pipeline.run(question["question"])

        scores: dict[str, Any] = {
            "question_id": question["id"],
            "question": question["question"],
            "question_type": question["question_type"],
            "answer": pipeline_result["answer"],
        }

        # Refusal accuracy
        scores["refusal_correct"] = refusal_accuracy(
            question["question_type"], pipeline_result["answer"]
        )

        # Retrieval recall (only for answerable questions with required docs)
        required_docs = question.get("required_source_docs", [])
        if required_docs:
            scores["retrieval_recall"] = None
        else:
            scores["retrieval_recall"] = None

        return scores

    def _aggregate(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        refusal_scores = [r["refusal_correct"] for r in results if r["refusal_correct"] is not None]
        refusal_rate = sum(refusal_scores) / len(refusal_scores) if refusal_scores else 0.0

        return {
            "total_questions": len(results),
            "refusal_accuracy": refusal_rate,
        }
