from __future__ import annotations

from typing import Any

from app.models.database import DatabaseClient
from app.pipeline import QueryPipeline
from eval.metrics import answer_correctness, refusal_accuracy, retrieval_recall


class EvalRunner:
    def __init__(
        self,
        db: DatabaseClient,
        pipeline: QueryPipeline,
        config_snapshot: dict[str, Any],
        notes: str | None = None,
        anthropic_api_key: str | None = None,
    ):
        self.db = db
        self.pipeline = pipeline
        self.config_snapshot = config_snapshot
        self.notes = notes
        self.anthropic_api_key = anthropic_api_key

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
            scores["retrieval_recall"] = retrieval_recall(
                required_docs, pipeline_result.get("retrieved_chunks", [])
            )
        else:
            scores["retrieval_recall"] = None

        # Answer correctness (only for answerable questions with required facts)
        required_facts = question.get("required_facts", [])
        if required_facts and question["question_type"] == "answerable" and self.anthropic_api_key:
            correctness = await answer_correctness(
                question=question["question"],
                generated_answer=pipeline_result["answer"],
                expected_answer=question.get("expected_answer", ""),
                required_facts=required_facts,
                anthropic_api_key=self.anthropic_api_key,
            )
            scores["answer_correctness"] = correctness["score"]
            scores["fact_details"] = correctness["details"]
        else:
            scores["answer_correctness"] = None
            scores["fact_details"] = None

        return scores

    def _aggregate(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        refusal_scores = [r["refusal_correct"] for r in results if r["refusal_correct"] is not None]
        refusal_rate = sum(refusal_scores) / len(refusal_scores) if refusal_scores else 0.0

        recall_scores = [r["retrieval_recall"] for r in results if r["retrieval_recall"] is not None]
        avg_recall = sum(recall_scores) / len(recall_scores) if recall_scores else 0.0

        correctness_scores = [
            r["answer_correctness"] for r in results if r["answer_correctness"] is not None
        ]
        avg_correctness = (
            sum(correctness_scores) / len(correctness_scores) if correctness_scores else 0.0
        )

        return {
            "total_questions": len(results),
            "refusal_accuracy": refusal_rate,
            "retrieval_recall": avg_recall,
            "answer_correctness": avg_correctness,
        }
