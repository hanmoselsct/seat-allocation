import os
import sqlite3
import json
import time
from functools import wraps
from flask import Flask, request, jsonify, g, render_template, session
from flask_cors import CORS

# 配置
DATABASE = os.path.join(os.getcwd(), "database.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "change_this_secret")
TEACHER_PASSWORD = os.environ.get("TEACHER_PASSWORD", "changeme")

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = SECRET_KEY
CORS(app, supports_credentials=True)

# --- 数据库工具 ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        score INTEGER NOT NULL,
        volunteers TEXT NOT NULL, -- JSON array
        admitted TEXT,            -- admitted seat name or NULL
        last_updated INTEGER
    )
    """)
    db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# 初始化数据库
with app.app_context():
    init_db()

# --- 辅助装饰器（仅老师可调的 API） ---
def require_teacher(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        # 简单 session 验证
        if session.get("is_teacher"):
            return f(*args, **kwargs)
        # 也接受一次性密码方式（方便调试）
        data = request.get_json(silent=True) or {}
        if data.get("teacher_password") == TEACHER_PASSWORD:
            session["is_teacher"] = True
            return f(*args, **kwargs)
        return jsonify({"error":"teacher authentication required"}), 401
    return wrapped

# -------------------------
# 前端页面路由
# -------------------------
@app.route("/")
def student_page():
    return render_template("student.html")

@app.route("/teacher")
def teacher_page():
    return render_template("teacher.html")

# -------------------------
# API：学生提交志愿
# -------------------------
@app.route("/api/submit", methods=["POST"])
def api_submit():
    payload = request.get_json()
    if not payload:
        return jsonify({"error":"invalid payload"}), 400

    name = (payload.get("name") or "").strip()
    try:
        score = int(payload.get("score", -1))
    except:
        score = -1
    volunteers = payload.get("volunteers") or []

    if not name:
        return jsonify({"error":"name required"}), 400
    if score < 0:
        return jsonify({"error":"score invalid"}), 400
    if not isinstance(volunteers, list) or len(volunteers) == 0:
        return jsonify({"error":"volunteers list required"}), 400

    db = get_db()
    cursor = db.cursor()
    timestamp = int(time.time())
    # 若已存在同名学生，更新；否则插入新记录
    cursor.execute("SELECT id FROM students WHERE name = ?", (name,))
    row = cursor.fetchone()
    if row:
        cursor.execute(
            "UPDATE students SET score=?, volunteers=?, last_updated=?, admitted=NULL WHERE id=?",
            (score, json.dumps(volunteers, ensure_ascii=False), timestamp, row["id"])
        )
    else:
        cursor.execute(
            "INSERT INTO students (name, score, volunteers, last_updated) VALUES (?,?,?,?)",
            (name, score, json.dumps(volunteers, ensure_ascii=False), timestamp)
        )
    db.commit()
    return jsonify({"ok":True})

# 获取某个学生的提交（通过 name 查询）
@app.route("/api/student", methods=["GET"])
def api_get_student():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error":"name parameter required"}), 400
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM students WHERE name = ?", (name,))
    row = cursor.fetchone()
    if not row:
        return jsonify({"found":False})
    return jsonify({
        "found": True,
        "id": row["id"],
        "name": row["name"],
        "score": row["score"],
        "volunteers": json.loads(row["volunteers"]),
        "admitted": row["admitted"]
    })

# 获取所有学生（老师用）
@app.route("/api/students", methods=["GET"])
@require_teacher
def api_get_all_students():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM students ORDER BY score DESC, last_updated ASC")
    rows = cursor.fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "name": r["name"],
            "score": r["score"],
            "volunteers": json.loads(r["volunteers"]),
            "admitted": r["admitted"]
        })
    return jsonify({"students": out})

# 清空所有数据（老师）
@app.route("/api/reset", methods=["POST"])
@require_teacher
def api_reset():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM students")
    db.commit()
    return jsonify({"ok":True})

# 分配算法（老师触发）
# 规则：按成绩从高到低；按志愿顺序尝试分配；每个座位配额为1（和你原逻辑一致）
@app.route("/api/assign", methods=["POST"])
@require_teacher
def api_assign():
    # 1）读取所有学生
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM students ORDER BY score DESC, last_updated ASC")
    rows = cursor.fetchall()
    students = []
    for r in rows:
        students.append({
            "id": r["id"],
            "name": r["name"],
            "score": r["score"],
            "volunteers": json.loads(r["volunteers"])
        })

    # 2）初始化每个座位名额为1
    # 收集所有可能座位
    seat_quota = {}
    for r in rows:
        vols = json.loads(r["volunteers"])
        for v in vols:
            seat_quota.setdefault(v, 1)

    # 3）分配过程
    process_log = []
    for s in students:
        admitted = None
        for vol in s["volunteers"]:
            # 如果该座位还有名额
            if seat_quota.get(vol, 1) > 0:
                admitted = vol
                seat_quota[vol] = seat_quota.get(vol, 1) - 1
                process_log.append({
                    "student": s["name"],
                    "score": s["score"],
                    "volunteer": vol,
                    "result": "分配成功"
                })
                break
        # 更新学生 admit 字段
        cursor.execute("UPDATE students SET admitted = ? WHERE id = ?", (admitted, s["id"]))
    db.commit()

    # 4）返回结果概览
    cursor.execute("SELECT name, admitted FROM students ORDER BY score DESC")
    rows2 = cursor.fetchall()
    results = [{"name": r["name"], "admitted": r["admitted"]} for r in rows2]
    return jsonify({"ok":True, "process": process_log, "results": results})

# 获取分配结果（任何人都可看）
@app.route("/api/results", methods=["GET"])
def api_results():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT name, score, admitted FROM students ORDER BY score DESC")
    rows = cursor.fetchall()
    out = [{"name": r["name"], "score": r["score"], "admitted": r["admitted"]} for r in rows]
    return jsonify({"results": out})

# 教师登录（前端可 POST 密码来建立 session）
@app.route("/api/teacher_login", methods=["POST"])
def api_teacher_login():
    data = request.get_json() or {}
    pw = data.get("password", "")
    if pw == TEACHER_PASSWORD:
        session["is_teacher"] = True
        return jsonify({"ok":True})
    return jsonify({"error":"wrong password"}), 401

# 退出登录
@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.pop("is_teacher", None)
    return jsonify({"ok":True})

if __name__ == "__main__":
    # 仅用于本地调试；Render 会使用 gunicorn 启动
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
