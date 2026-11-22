from __future__ import annotations

from typing import Any

from app.models.database import DatabaseClient
from app.pipeline import QueryPipeline
from eval.metrics import answer_correctness, refusal_accuracy, retrieval_recall


class EvalRunner:
    """Runs every eval question through the pipeline and records one eval run.

    Each result points to the answer it scored. If the judge fails on a question, that
    result is recorded without a score and with the error, and the run goes on.
    """

    def __init__(
        self,
        db: DatabaseClient,
        pipeline: QueryPipeline,
        judge_model: str,
        notes: str | None = None,
        anthropic_api_key: str | None = None,
    ):
        self.db = db
        self.pipeline = pipeline
        self.judge_model = judge_model
        self.notes = notes
        self.anthropic_api_key = anthropic_api_key

    async def run(self) -> dict[str, Any]:
        results = [await self._evaluate(q) for q in self.db.get_eval_questions()]
        run_id = self.db.record_eval_run({
            "indexing_settings_key": self.pipeline.indexing_settings_key,
            "answer_settings_key": self.pipeline.answer_settings_key,
            "judge_model": self.judge_model,
            "notes": self.notes,
            "results": results,
        })
        return {"run_id": run_id, "results": results}

    async def _evaluate(self, question: dict[str, Any]) -> dict[str, Any]:
        answer = await self.pipeline.run(question["question"])
        required = [s["source_key"] for s in question.get("sources") or []]
        result: dict[str, Any] = {
            "question_key": question["key"],
            "answer_id": answer["answer_id"],
            "refusal_correct": refusal_accuracy(question["question_type"], answer["answer"]),
            "retrieval_recall": retrieval_recall(required, answer.get("retrieved_chunks", []))
            if required else None,
            "answer_correctness": None,
            "judge_error": None,
            "facts": [],
        }
        facts = question.get("facts") or []
        if facts and question["question_type"] == "answerable" and self.anthropic_api_key:
            try:
                judged = await answer_correctness(
                    question=question["question"],
                    generated_answer=answer["answer"],
                    expected_answer=question.get("expected_answer") or "",
                    facts=[f["text"] for f in facts],
                    anthropic_api_key=self.anthropic_api_key,
                    model=self.judge_model,
                )
                if len(judged["details"]) != len(facts):
                    raise RuntimeError(f"expected {len(facts)} verdicts, got {len(judged['details'])}")
            except Exception as e:  # noqa: BLE001 - recorded on the result; the run goes on
                result["judge_error"] = f"{type(e).__name__}: {e}"
            else:
                result["answer_correctness"] = judged["score"]
                result["facts"] = [
                    {"position": f["position"], "present": d["present"], "reason": d.get("reason")}
                    for f, d in zip(facts, judged["details"])
                ]
        return result
