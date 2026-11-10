# くうちゅう えしりとり

## 起動
    pip install -r requirements.txt
    python server.py          # http://localhost:8000

## 遊び方
1. ホストが http://localhost:8000 を開き「へやを つくる」。
2. ロビーに出るURL（例 /?room=1234）をコピーして友だちに送る。
3. 友だちはそのURLを開くだけで部屋に入れる（番号入力でも入れる）。

## 注意
- カメラ(getUserMedia)は **HTTPS か localhost** でしか使えない。
  別のパソコンから遊ぶときは、cloudflared / ngrok などでHTTPSのURLを作る。
    cloudflared tunnel --url http://localhost:8000
- 手の認識のライブラリとモデルはCDNから読む（インターネット接続が必要）。
- カメラ映像はブラウザの中だけで処理。サーバーには線の座標と答えだけが届く。保存はしない。
- 手がなくてもマウスで描ける（動作確認用）。
# air-shiritori
