import json
from fastapi import FastAPI
from pydantic import BaseModel

from fastapi.responses import FileResponse, StreamingResponse
from agent import ask, ask_stream

app = FastAPI()

class ChatIn(BaseModel):
    message:str
    session_id:str="default"

@app.post("/chat")
def chat(data:ChatIn):
    answer = ask(data.message, data.session_id)
    return {"session_id":data.session_id,"answer":answer}

@app.post("/chat/stream")
def chat_stream(data:ChatIn):
    """SSE 流式接口：边生成边把 token 推给前端"""
    def gen():
        for token in ask_stream(data.message, data.session_id):
            yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/")
def home():
    return FileResponse("index.html")
