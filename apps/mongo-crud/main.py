"""
mongo-crud: MongoDB CRUD 데모 앱 (Python / FastAPI)
- 백그라운드 워커: 주기적으로 문서 삽입 → 조회 → 랜덤 삭제 반복
- Valkey pub/sub: CRUD 이벤트 PUBLISH (채널: crud-events)
- 미션 모드: 환경변수 MISSION 으로 트러블슈팅 시나리오 주입

연결 정보 (환경변수)
  MONGO_URI   : mongodb://user:pass@host:27017/demo?authSource=admin
  VALKEY_HOST : valkey-production.middleware.svc.cluster.local
  VALKEY_PORT : 6379
  VALKEY_PASSWORD : (선택) auth.enabled 시 필수
  MISSION     : "" | wrong-creds | oom | conn-exhaust
"""

import asyncio
import json
import os
import random
import string
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
import uvicorn
from bson import ObjectId
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/demo")
VALKEY_HOST = os.getenv("VALKEY_HOST", "localhost")
VALKEY_PORT = int(os.getenv("VALKEY_PORT", "6379"))
VALKEY_PASSWORD = os.getenv("VALKEY_PASSWORD", "")
MISSION = os.getenv("MISSION", "")
WORKER_INTERVAL = int(os.getenv("WORKER_INTERVAL", "5"))  # 초

# MISSION: wrong-creds → 잘못된 MongoDB URI 사용 (CrashLoopBackOff 유발)
if MISSION == "wrong-creds":
    MONGO_URI = "mongodb://baduser:badpass@mongodb-cluster-rs0-0.mongodb-cluster-rs0.mongodb.svc.cluster.local:27017/demo?authSource=admin"

# MISSION: conn-exhaust → maxPoolSize=1 로 커넥션 부족 유발
POOL_SIZE = 1 if MISSION == "conn-exhaust" else 10

app = FastAPI(title="mongo-crud", version="1.0.1", lifespan=lifespan)

# ---------------------------------------------------------------------------
# MongoDB 클라이언트
# ---------------------------------------------------------------------------
mongo_client: AsyncIOMotorClient = None
db = None


def get_valkey():
    return redis.Redis(
        host=VALKEY_HOST,
        port=VALKEY_PORT,
        password=VALKEY_PASSWORD or None,
        decode_responses=True,
    )


def publish_event(action: str, payload: dict):
    try:
        r = get_valkey()
        event = json.dumps({
            "source": "mongo-crud",
            "action": action,
            "payload": payload,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        r.publish("crud-events", event)
    except Exception as e:
        print(f"[WARN] Valkey publish failed: {e}")


# ---------------------------------------------------------------------------
# 모델
# ---------------------------------------------------------------------------
class ItemCreate(BaseModel):
    name: str
    value: str = ""


def serialize(doc) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


# ---------------------------------------------------------------------------
# 라이프사이클 (FastAPI lifespan)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global mongo_client, db
    mongo_client = AsyncIOMotorClient(
        MONGO_URI,
        maxPoolSize=POOL_SIZE,
        serverSelectionTimeoutMS=5000,
    )
    db = mongo_client.get_default_database() if "/" in MONGO_URI.rsplit("@", 1)[-1] else mongo_client["demo"]
    await mongo_client.server_info()
    print(f"[INFO] MongoDB connected. MISSION={MISSION!r}")
    asyncio.create_task(background_worker())
    yield
    if mongo_client:
        mongo_client.close()


# ---------------------------------------------------------------------------
# 백그라운드 워커
# ---------------------------------------------------------------------------
async def background_worker():
    """주기적으로 삽입 → 조회 → 랜덤 삭제 반복"""
    while True:
        try:
            # MISSION: oom → 큰 문자열 반복 생성
            if MISSION == "oom":
                _ = ["x" * 10_000_000 for _ in range(100)]

            name = "item-" + "".join(random.choices(string.ascii_lowercase, k=6))
            result = await db.items.insert_one({"name": name, "value": str(time.time())})
            publish_event("insert", {"id": str(result.inserted_id), "name": name})

            items = await db.items.find().to_list(length=50)
            if items:
                target = random.choice(items)
                await db.items.delete_one({"_id": target["_id"]})
                publish_event("delete", {"id": str(target["_id"]), "name": target.get("name")})

            count = await db.items.count_documents({})
            print(f"[worker] insert+delete done. total={count}")
        except Exception as e:
            print(f"[ERROR] worker: {e}")
        await asyncio.sleep(WORKER_INTERVAL)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "mission": MISSION}


@app.get("/items")
async def list_items(limit: int = 20):
    items = await db.items.find().sort("_id", -1).limit(limit).to_list(length=limit)
    return [serialize(i) for i in items]


@app.post("/items", status_code=201)
async def create_item(body: ItemCreate):
    result = await db.items.insert_one(body.model_dump())
    publish_event("insert", {"id": str(result.inserted_id), "name": body.name})
    return {"id": str(result.inserted_id)}


@app.delete("/items/{item_id}")
async def delete_item(item_id: str):
    result = await db.items.delete_one({"_id": ObjectId(item_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="not found")
    publish_event("delete", {"id": item_id})
    return {"deleted": item_id}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
