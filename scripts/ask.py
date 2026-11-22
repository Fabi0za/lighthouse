"""Ask one question through the full pipeline and print the answer.

Usage:
    python scripts/ask.py "<question>"

The answer is logged with the versions it saw, like any other answer.
"""
import asyncio
import sys

from app.dependencies import build_dependencies


async def main():
    if len(sys.argv) < 2:
        print('Usage: python scripts/ask.py "<question>"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    pipeline = build_dependencies()["pipeline"]

    print(f"\nQuestion: {question}\n")
    result = await pipeline.run(question)

    print(f"Answer: {result['answer']}\n")
    print(f"Confidence: {result['confidence']}")
    print("Sources:")
    for s in result["sources"]:
        print(f"  - {s['document_title']}, {s['section']}, Page {s['page']}")
    print(f"\nLog ID: {result['log_id']}")

    await pipeline.vector_search.embedder.close()
    await pipeline.llm.close()


if __name__ == "__main__":
    asyncio.run(main())
