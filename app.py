import os
import sqlite3
import json
import time
from functools import wraps
from flask import Flask, request, jsonify, g, render_template, session
from flask_cors import CORS

# 配置
DATABASE = os.path.join(os.getcwd(), "database.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "changeme_secret")
TEACHER_PASSWORD = os.environ.get("TEACHER_PASSWORD", "changeme")

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = SECRET_KEY
CORS(app, supports_credentials=True)

# --- 数据库 ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    c = db.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        score INTEGER,
        volunteers TEXT,
        admitted TEXT,
        last_updated INTEGER
    )
    """)
    db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db: db.close()

with app.app_context():
    init_db()

# --- 权限 ---
def require_teacher(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if session.get("is_teacher"): return f(*a, **kw)
        data = request.get_json(silent=True) or {}
        if data.get("teacher_password") == TEACHER_PASSWORD:
            session["is_teacher"] = True
            return f(*a, **kw)
        return jsonify({"error":"teacher authentication required"}), 401
    return wrapper

# --- 页面 ---
@app.route("/")
def student_page():
    return render_template("student.html")

@app.route("/teacher")
def teacher_page():
    return render_template("teacher.html")

# --- 学生提交 ---
@app.route("/api/submit", methods=["POST"])
def submit():
    data = request.get_json() or {}
    name = data.get("name","").strip()
    score = data.get("score")
    vols = data.get("volunteers", [])
    if not name or not isinstance(vols, list):
        return jsonify({"error":"invalid data"}), 400

    db = get_db()
    c = db.cursor()
    now = int(time.time())
    c.execute("SELECT id FROM students WHERE name=?", (name,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE students SET score=?, volunteers=?, admitted=NULL, last_updated=? WHERE id=?",
                  (score, json.dumps(vols,ensure_ascii=False), now, row["id"]))
    else:
        c.execute("INSERT INTO students (name,score,volunteers,last_updated) VALUES (?,?,?,?)",
                  (name, score, json.dumps(vols,ensure_ascii=False), now))
    db.commit()
    return jsonify({"ok":True})

# 获取单个学生
@app.route("/api/student")
def get_student():
    name = request.args.get("name","").strip()
    db = get_db()
    c = db.cursor()
    c.execute("SELECT * FROM students WHERE name=?", (name,))
    r = c.fetchone()
    if not r: return jsonify({"found":False})
    return jsonify({
        "found":True,
        "name":r["name"],
        "score":r["score"],
        "volunteers":json.loads(r["volunteers"]),
        "admitted":r["admitted"]
    })

# 老师端：获取所有学生
@app.route("/api/students")
@require_teacher
def all_students():
    db = get_db()
    c = db.cursor()
    c.execute("SELECT * FROM students ORDER BY score DESC, last_updated ASC")
    rows = c.fetchall()
    data = []
    for r in rows:
        data.append({
            "name": r["name"],
            "score": r["score"],
            "volunteers": json.loads(r["volunteers"]),
            "admitted": r["admitted"]
        })
    return jsonify({"students": data})

# 老师：清空数据
@app.route("/api/reset", methods=["POST"])
@require_teacher
def reset_all():
    db = get_db()
    db.execute("DELETE FROM students")
    db.commit()
    return jsonify({"ok":True})

# 老师：分配逻辑（每排2人）
@app.route("/api/assign", methods=["POST"])
@require_teacher
def assign():
    db = get_db()
    c = db.cursor()
    c.execute("SELECT * FROM students ORDER BY score DESC, last_updated ASC")
    rows = c.fetchall()
    students = [{"id":r["id"], "name":r["name"], "score":r["score"], "volunteers":json.loads(r["volunteers"])} for r in rows]

    # 每排容量 2
    seat_quota = {}
    for s in students:
        for v in s["volunteers"]:
            seat_quota.setdefault(v, 2)

    log = []
    for s in students:
        admitted = None
        for v in s["volunteers"]:
            if seat_quota.get(v,0) > 0:
                admitted = v
                seat_quota[v] -= 1
                log.append({"student":s["name"],"score":s["score"],"volunteer":v,"result":"分配成功"})
                break
        c.execute("UPDATE students SET admitted=? WHERE id=?", (admitted, s["id"]))
    db.commit()

    c.execute("SELECT name,score,admitted FROM students ORDER BY score DESC")
    results = [{"name":r["name"],"score":r["score"],"admitted":r["admitted"]} for r in c.fetchall()]
    return jsonify({"ok":True, "process":log, "results":results})

# 分配结果（公开）
@app.route("/api/results")
def results():
    db = get_db()
    c = db.cursor()
    c.execute("SELECT name,score,admitted FROM students ORDER BY score DESC")
    r = c.fetchall()
    return jsonify({"results":[{"name":x["name"],"score":x["score"],"admitted":x["admitted"]} for x in r]})

# 老师登录
@app.route("/api/teacher_login", methods=["POST"])
def teacher_login():
    pw = (request.get_json() or {}).get("password")
    if pw == TEACHER_PASSWORD:
        session["is_teacher"] = True
        return jsonify({"ok":True})
    return jsonify({"error":"wrong password"}),401

@app.route("/api/logout", methods=["POST"])
def logout():
    session.pop("is_teacher",None)
    return jsonify({"ok":True})

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)), debug=True)
