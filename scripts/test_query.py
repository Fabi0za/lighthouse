"""Quick script to test querying the RAG system."""
import asyncio
import json
import sys

from app.config import get_settings
from app.generation.formatter import ResponseFormatter
from app.generation.llm import LLMClient
from app.ingestion.embedder import Embedder
from app.logging.query_logger import QueryLogger
from app.models.database import DatabaseClient
from app.pipeline import QueryPipeline
from app.retrieval.query_parser import QueryParser
from app.retrieval.reranker import CohereReranker
from app.retrieval.search import VectorSearch


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_query.py <question>")
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    settings = get_settings()

    db = DatabaseClient()
    embedder = Embedder(
        api_key=settings.cohere_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )

    llm = LLMClient(api_key=settings.anthropic_api_key, model=settings.llm_model)

    known_providers = db.get_known_scopes()
    print(f"Known providers: {known_providers}")

    pipeline = QueryPipeline(
        query_parser=QueryParser(known_providers=known_providers),
        vector_search=VectorSearch(db=db, embedder=embedder, top_k=settings.retrieval_top_k),
        reranker=CohereReranker(api_key=settings.cohere_api_key, top_n=settings.rerank_top_n),
        llm=llm,
        formatter=ResponseFormatter(),
        logger=QueryLogger(db=db),
    )

    print(f"\nQuestion: {question}\n")
    result = await pipeline.run(question)

    print(f"Answer: {result['answer']}\n")
    print(f"Confidence: {result['confidence']}")
    print(f"Sources:")
    for s in result["sources"]:
        print(f"  - {s['document_title']}, {s['section']}, Page {s['page']}")
    print(f"\nLog ID: {result['log_id']}")

    await embedder.close()
    await llm.close()


if __name__ == "__main__":
    asyncio.run(main())
