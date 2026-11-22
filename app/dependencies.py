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


def build_dependencies():
    settings = get_settings()

    db = DatabaseClient()

    embedder = Embedder(
        api_key=settings.cohere_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )

    llm = LLMClient(api_key=settings.anthropic_api_key, model=settings.llm_model)

    known_providers = db.get_known_scopes()
    query_parser = QueryParser(known_providers=known_providers)

    vector_search = VectorSearch(db=db, embedder=embedder, top_k=settings.retrieval_top_k)
    reranker = CohereReranker(api_key=settings.cohere_api_key, top_n=settings.rerank_top_n)
    formatter = ResponseFormatter()
    logger = QueryLogger(db=db)

    pipeline = QueryPipeline(
        query_parser=query_parser,
        vector_search=vector_search,
        reranker=reranker,
        llm=llm,
        formatter=formatter,
        logger=logger,
    )

    return {
        "db": db,
        "pipeline": pipeline,
        "settings": settings,
    }
