import os
import sqlite3
from datetime import datetime
from typing import Dict, Any, List

from flask import Flask, render_template, jsonify, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "forum.db")

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)


# ---------- БД форума ----------


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id INTEGER NOT NULL,
            author TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
        )
        """
    )

    conn.commit()
    conn.close()


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


init_db()


# ---------- Веб-страница ----------


@app.route("/")
def index():
    return render_template("index.html")


# ---------- API форума ----------


@app.get("/api/forum/threads")
def api_list_threads():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.id,
               t.title,
               t.author,
               t.created_at,
               COUNT(p.id) AS posts_count,
               MAX(p.created_at) AS last_post_at
        FROM threads t
        LEFT JOIN posts p ON p.thread_id = t.id
        GROUP BY t.id, t.title, t.author, t.created_at
        ORDER BY COALESCE(last_post_at, t.created_at) DESC
        """
    )
    rows = cur.fetchall()
    conn.close()

    threads: List[Dict[str, Any]] = []
    for r in rows:
        threads.append(
            {
                "id": r["id"],
                "title": r["title"],
                "author": r["author"],
                "created_at": r["created_at"],
                "posts_count": r["posts_count"],
                "last_post_at": r["last_post_at"],
            }
        )
    return jsonify(threads)


@app.post("/api/forum/threads")
def api_create_thread():
    data = request.get_json(force=True) or {}
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()
    author = (data.get("author") or "").strip() or "Anon"

    if not title or not body:
        return jsonify({"error": "title and body required"}), 400

    conn = get_conn()
    cur = conn.cursor()
    created = now_iso()

    # создаём тему
    cur.execute(
        "INSERT INTO threads (title, author, created_at) VALUES (?, ?, ?)",
        (title, author, created),
    )
    thread_id = cur.lastrowid

    # первый пост в теме
    cur.execute(
        "INSERT INTO posts (thread_id, author, body, created_at) VALUES (?, ?, ?, ?)",
        (thread_id, author, body, created),
    )
    conn.commit()

    # достаём полную тему
    cur.execute(
        "SELECT id, title, author, created_at FROM threads WHERE id=?",
        (thread_id,),
    )
    trow = cur.fetchone()

    cur.execute(
        "SELECT id, author, body, created_at FROM posts WHERE thread_id=? ORDER BY created_at ASC",
        (thread_id,),
    )
    prows = cur.fetchall()
    conn.close()

    thread = {
        "id": trow["id"],
        "title": trow["title"],
        "author": trow["author"],
        "created_at": trow["created_at"],
        "posts": [
            {
                "id": p["id"],
                "author": p["author"],
                "body": p["body"],
                "created_at": p["created_at"],
            }
            for p in prows
        ],
    }
    return jsonify(thread), 201


@app.get("/api/forum/threads/<int:thread_id>")
def api_get_thread(thread_id: int):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, title, author, created_at FROM threads WHERE id=?",
        (thread_id,),
    )
    trow = cur.fetchone()
    if not trow:
        conn.close()
        return jsonify({"error": "thread not found"}), 404

    cur.execute(
        "SELECT id, author, body, created_at FROM posts WHERE thread_id=? ORDER BY created_at ASC",
        (thread_id,),
    )
    prows = cur.fetchall()
    conn.close()

    thread = {
        "id": trow["id"],
        "title": trow["title"],
        "author": trow["author"],
        "created_at": trow["created_at"],
        "posts": [
            {
                "id": p["id"],
                "author": p["author"],
                "body": p["body"],
                "created_at": p["created_at"],
            }
            for p in prows
        ],
    }
    return jsonify(thread)


@app.post("/api/forum/threads/<int:thread_id>/posts")
def api_add_post(thread_id: int):
    data = request.get_json(force=True) or {}
    body = (data.get("body") or "").strip()
    author = (data.get("author") or "").strip() or "Anon"

    if not body:
        return jsonify({"error": "body required"}), 400

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM threads WHERE id=?", (thread_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify({"error": "thread not found"}), 404

    created = now_iso()
    cur.execute(
        "INSERT INTO posts (thread_id, author, body, created_at) VALUES (?, ?, ?, ?)",
        (thread_id, author, body, created),
    )
    post_id = cur.lastrowid
    conn.commit()
    conn.close()

    post = {
        "id": post_id,
        "author": author,
        "body": body,
        "created_at": created,
    }
    return jsonify(post), 201


# Небольшой health-чек, пригодится на хостинге
@app.get("/health")
def health():
    return "ok"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
