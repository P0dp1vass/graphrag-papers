import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from neo4j import GraphDatabase
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from qa import ask

URI = "bolt://localhost:7687"
AUTH = ("neo4j", os.environ.get("NEO4J_PASSWORD", ""))
MODEL = "all-MiniLM-L6-v2"

class AskRequest(BaseModel):
    question: str

class AskResponse(BaseModel):
    question: str
    answer: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.driver = GraphDatabase.driver(URI, auth=AUTH)
    app.state.driver.verify_connectivity()
    app.state.model = SentenceTransformer(MODEL)
    yield
    app.state.driver.close()

app = FastAPI(title="GraphRAG", lifespan=lifespan)

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

@app.post("/ask", response_model=AskResponse)
def ask_endpoint(req: AskRequest) -> AskResponse:
    answer = ask(req.question, app.state.driver, app.state.model)
    return AskResponse(question=req.question, answer=answer)
