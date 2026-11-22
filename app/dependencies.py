from app.config import get_settings
from app.generation.formatter import ResponseFormatter
from app.generation.llm import LLMClient
from app.ingestion.embedder import Embedder
from app.answers.logger import AnswerLogger
from app.models.database import DatabaseClient
from app.pipeline import QueryPipeline
from app.retrieval.query_parser import QueryParser
from app.retrieval.reranker import CohereReranker
from app.retrieval.search import VectorSearch
from app.settings_rows import answer_settings_row, indexing_settings_row


def build_dependencies():
    settings = get_settings()

    db = DatabaseClient()

    embedder = Embedder(
        api_key=settings.cohere_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        rate_limit_wait_seconds=settings.embed_rate_limit_wait_seconds,
        rate_limit_retries=settings.embed_rate_limit_retries,
    )

    llm = LLMClient(api_key=settings.anthropic_api_key, model=settings.llm_model)

    query_parser = QueryParser(known_scopes=db.get_known_scopes())

    vector_search = VectorSearch(db=db, embedder=embedder, top_k=settings.retrieval_top_k)
    reranker = CohereReranker(api_key=settings.cohere_api_key, top_n=settings.rerank_top_n,
                              model=settings.rerank_model)
    indexing_settings, answer_settings = indexing_settings_row(settings), answer_settings_row(settings)
    stored = [k for k in db.current_indexing_settings_keys() if k != indexing_settings["key"]]
    if stored:
        raise RuntimeError(
            f"current versions were loaded with indexing settings {', '.join(stored)}, but the "
            f"configuration gives {indexing_settings['key']}: queries would be embedded differently "
            "from the stored chunks. Restore the settings, or reload into a fresh store."
        )
    db.save_indexing_settings(indexing_settings)
    db.save_answer_settings(answer_settings)
    formatter = ResponseFormatter()
    logger = AnswerLogger(db=db)

    pipeline = QueryPipeline(
        query_parser=query_parser,
        vector_search=vector_search,
        reranker=reranker,
        llm=llm,
        formatter=formatter,
        logger=logger,
        indexing_settings_key=indexing_settings["key"],
        answer_settings_key=answer_settings["key"],
    )

    return {
        "db": db,
        "pipeline": pipeline,
        "settings": settings,
    }
