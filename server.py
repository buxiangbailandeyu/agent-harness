from fastapi import FastAPI
from pydantic import BaseModel

from agent import ask

app = FastAPI()

class ChatIn(BaseModel):
    message:str
    session_id:str="default"

@app.post("/chat")
def chat(data:ChatIn):
    answer = ask(data.message, data.session_id)
    return {"session_id":data.session_id,"answer":answer}