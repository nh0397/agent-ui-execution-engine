"""Private local conversation snapshots, separate from publishable run evidence."""
import json
import os
import re
import sqlite3
import time
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from fastapi import HTTPException, Request

class Message(BaseModel):
    model_config=ConfigDict(extra="forbid")
    role: Literal["you","agent"]
    text: str=Field(max_length=12000)
    matches: list[str] | None=None

class Snapshot(BaseModel):
    model_config=ConfigDict(extra="forbid")
    revision: int=Field(default=0,ge=0)
    messages: list[Message]=Field(default_factory=list,max_length=1000)
    selected_id: str | None=Field(default=None,max_length=100)
    values: dict[str,str]=Field(default_factory=dict)
    initial_request: str=Field(default="",max_length=2000)
    run_id: str | None=Field(default=None,max_length=100)

def install(app, session, storage):
    path=storage/'conversations.sqlite3'
    def db():
        connection=sqlite3.connect(path,timeout=10)
        connection.execute("CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, owner TEXT, revision INTEGER, updated REAL, data TEXT)")
        return connection
    def clean(data):
        text=json.dumps(data)
        key=os.getenv('GROQ_API_KEY','')
        if key: text=text.replace(key,'[REDACTED]')
        return re.sub(r'gsk_[A-Za-z0-9]{20,}','[REDACTED]',text)
    @app.get('/api/conversations')
    def listing(request:Request):
        owner=session(request)['profile']['id']
        with db() as connection:
            rows=connection.execute('SELECT id,revision,updated,data FROM conversations WHERE owner=? ORDER BY updated DESC LIMIT 100',(owner,)).fetchall()
        return [{'id':id,'revision':rev,'updated':updated,'title':next((m['text'][:70] for m in json.loads(data)['messages'] if m['role']=='you'),'New conversation')} for id,rev,updated,data in rows]
    @app.get('/api/conversations/{id}')
    def load(id:UUID,request:Request):
        owner=session(request)['profile']['id']
        with db() as connection:
            row=connection.execute('SELECT revision,data FROM conversations WHERE id=? AND owner=?',(str(id),owner)).fetchone()
        if not row: raise HTTPException(404,'Conversation not found')
        return {**json.loads(row[1]),'id':str(id),'revision':row[0]}
    @app.put('/api/conversations/{id}')
    def save(id:UUID,body:Snapshot,request:Request):
        owner=session(request)['profile']['id']
        payload=clean(body.model_dump(exclude={'revision'}))
        if len(payload)>250000: raise HTTPException(413,'Conversation is too large. Start a new conversation.')
        with db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row=connection.execute('SELECT owner,revision FROM conversations WHERE id=?',(str(id),)).fetchone()
            if row and row[0]!=owner: raise HTTPException(404,'Conversation not found')
            if (row[1] if row else 0)!=body.revision: raise HTTPException(409,'Conversation changed in another window. Reload it before continuing.')
            revision=body.revision+1
            connection.execute('INSERT OR REPLACE INTO conversations VALUES(?,?,?,?,?)',(str(id),owner,revision,time.time(),payload))
        return {'revision':revision}
