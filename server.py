"""空中えしりとり - サーバー (FastAPI + WebSocket)
部屋・参加者・順番・時間・答え・判定をすべてここで管理する。
カメラ映像は一切受け取らない。受け取るのは「線(座標)」と「答え」だけ。保存もしない。
"""
import asyncio, json, os, random, string, time, uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse

BASE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI()

COLORS = ["#e63946", "#1d78d6", "#2faa5a", "#8e44ad", "#ff8c1a", "#00a8a8"]
SHAPES = ["circle", "square", "triangle", "star", "heart", "diamond"]
DRAW_SEC, ANS_SEC, MAX_PLAYERS = 30, 15, 4
TOPICS = "あいうえおかきくけこさしすせそたちつてとなにはひふへほまみむめもやゆよらりるれろわ"
SMALL = {"ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "ぁ": "あ", "ぃ": "い", "ぅ": "う", "ぇ": "え", "ぉ": "お", "ゎ": "わ", "っ": "つ"}

rooms: dict = {}


def clean(s) -> str:
    """答えはひらがなと「ー」だけ、12文字まで。"""
    return "".join(c for c in str(s) if "\u3041" <= c <= "\u3096" or c == "ー")[:12]


def norm(c: str) -> str:
    return SMALL.get(c, c)


def last_char(word: str) -> str:
    w = word.rstrip("ー") or word
    return norm(w[-1]) if w else ""


def new_code() -> str:
    while True:
        c = "".join(random.choices(string.digits, k=4))
        if c not in rooms:
            return c


class Player:
    def __init__(self, ws):
        self.id = uuid.uuid4().hex[:6]
        self.ws = ws
        self.name = ""
        self.shape = "circle"
        self.color = ""


class Room:
    def __init__(self, code):
        self.code, self.players, self.host = code, {}, None
        self.rounds, self.task = 2, None
        self.reset()

    def reset(self):
        self.phase, self.seq, self.turn, self.turns = "lobby", [], 0, []
        self.strokes, self.draft, self.topic, self.deadline = [], "", "", 0
        self.cancel()

    def cancel(self):
        if self.task:
            self.task.cancel()
            self.task = None

    def set_timer(self, secs):
        self.cancel()
        self.deadline = time.time() + secs
        self.task = asyncio.create_task(self._timer(self.phase, self.turn, secs))

    async def _timer(self, phase, turn, secs):
        await asyncio.sleep(secs)
        if self.phase == phase and self.turn == turn:
            if phase == "draw":
                await to_answer(self)
            else:
                await finish_answer(self)

    def pub(self):
        res = self.phase == "result"
        active = self.phase in ("prepare", "draw", "answer")
        return dict(
            code=self.code, phase=self.phase, host=self.host, rounds=self.rounds,
            players=[dict(id=p.id, name=p.name, shape=p.shape, color=p.color) for p in self.players.values()],
            turn=self.turn, total=len(self.seq), topic=self.topic,
            drawer=self.seq[self.turn] if active else None,
            next=self.seq[self.turn + 1] if active and self.turn + 1 < len(self.seq) else None,
            left=max(0, round(self.deadline - time.time(), 1)) if self.phase in ("draw", "answer") else 0,
            turns=[dict(pid=t["pid"], strokes=t["strokes"], len=len(t["ans"]),
                        ans=t["ans"] if res else None, ok=t["ok"] if res else None) for t in self.turns],
            strokes=self.strokes if self.phase == "draw" else [],
        )

    async def send_all(self, msg, skip=None):
        data = json.dumps(msg, ensure_ascii=False)
        for p in list(self.players.values()):
            if p.id != skip:
                try:
                    await p.ws.send_text(data)
                except Exception:
                    pass

    async def broadcast(self):
        await self.send_all(dict(t="state", s=self.pub()))


async def to_answer(room: Room):
    room.phase, room.draft = "answer", ""
    room.set_timer(ANS_SEC)
    await room.broadcast()


async def finish_answer(room: Room):
    pid = room.seq[room.turn]
    room.turns.append(dict(pid=pid, strokes=room.strokes, ans=clean(room.draft), ok=False))
    room.strokes, room.draft = [], ""
    room.turn += 1
    if room.turn >= len(room.seq):
        room.cancel()
        room.phase = "result"
        prev = room.topic
        for t in room.turns:  # しりとり判定
            t["ok"] = bool(t["ans"]) and norm(t["ans"][0]) == prev
            prev = last_char(t["ans"]) if t["ans"] else ""
    else:
        room.phase = "prepare"
        room.cancel()
    await room.broadcast()


async def handle(room: Room, p: Player, m: dict):
    t = m.get("t")
    drawer = room.seq[room.turn] if room.phase in ("prepare", "draw", "answer") and room.seq else None
    if t == "char" and room.phase == "lobby":
        color = m.get("color")
        others = [q for q in room.players.values() if q is not p and q.color]
        used = {q.color for q in others}
        if color not in COLORS or color in used or m.get("shape") not in SHAPES or m.get("shape") in {q.shape for q in others}:
            return await p.ws.send_text(json.dumps(dict(t="err", m="その いろは つかえないよ", stay=True)))
        p.name, p.shape, p.color = str(m.get("name", "")).strip()[:6] or "ななし", m["shape"], color
        await room.broadcast()
    elif t == "start" and p.id == room.host and room.phase == "lobby":
        ps = list(room.players.values())
        if len(ps) >= 2 and all(q.color for q in ps):
            room.rounds = m.get("rounds") if m.get("rounds") in (2, 3, 4) else 2
            room.seq = [q.id for q in ps] * room.rounds
            room.topic = random.choice(TOPICS)
            room.turn, room.turns, room.phase = 0, [], "prepare"
            await room.broadcast()
    elif t == "begin" and room.phase == "prepare" and p.id == drawer:
        room.phase, room.strokes = "draw", []
        room.set_timer(DRAW_SEC)
        await room.broadcast()
    elif t == "stroke" and room.phase == "draw" and p.id == drawer:
        s = m.get("strokes")
        if isinstance(s, list):
            room.strokes = s[:300]
            await room.send_all(dict(t="live", strokes=room.strokes), skip=p.id)
    elif t == "done" and room.phase == "draw" and p.id == drawer:
        await to_answer(room)
    elif t == "draft" and room.phase == "answer" and p.id == drawer:
        room.draft = clean(m.get("text", ""))
    elif t == "answer" and room.phase == "answer" and p.id == drawer:
        room.draft = clean(m.get("text", ""))
        await finish_answer(room)
    elif t == "again" and room.phase == "result" and p.id == room.host:
        room.reset()
        await room.broadcast()


async def leave(room: Room, p: Player):
    room.players.pop(p.id, None)
    if not room.players:
        room.cancel()
        rooms.pop(room.code, None)
        return
    if room.host == p.id:
        room.host = next(iter(room.players))
    if room.phase != "lobby":  # 途中で抜けたらロビーに戻る
        room.reset()
    await room.broadcast()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    room, p = None, None
    try:
        while True:
            m = json.loads(await ws.receive_text())
            if room is None:
                if m.get("t") != "join":
                    continue
                if m.get("create"):
                    room = Room(new_code())
                    rooms[room.code] = room
                else:
                    r = rooms.get(str(m.get("room", "")))
                    if not r:
                        await ws.send_text(json.dumps(dict(t="err", m="その へやは みつからないよ")))
                        continue
                    if r.phase != "lobby" or len(r.players) >= MAX_PLAYERS:
                        await ws.send_text(json.dumps(dict(t="err", m="この へやには はいれないよ")))
                        continue
                    room = r
                p = Player(ws)
                room.players[p.id] = p
                if room.host is None:
                    room.host = p.id
                await ws.send_text(json.dumps(dict(t="hello", you=p.id, colors=COLORS)))
                await room.broadcast()
            else:
                await handle(room, p, m)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # 想定外の入力でサーバーが止まらないようにする
        print("ws error:", e)
    finally:
        if room and p:
            await leave(room, p)


@app.get("/")
async def index():
    for path in (os.path.join(BASE, "static", "index.html"), os.path.join(BASE, "index.html")):
        if os.path.exists(path):
            return FileResponse(path)
    return HTMLResponse("index.html が見つかりません", status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

    ##fvaeearvker;vkae;orkvo;aekrv;oake;vroaek;