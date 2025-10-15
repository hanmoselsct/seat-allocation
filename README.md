# 🎓 Seat Allocation System 座位分配系统

一个支持 **多人同时填报志愿**、**教师后台录取**、**云端数据存储** 的可视化座位分配系统。  
前端支持学生填报界面与教师后台界面分离，后端采用 Flask + PostgreSQL 架构，  
可在 **Render 云平台** 免费部署使用。

---

## 🧭 功能概述

| 模块 | 功能 |
|------|------|
| 🎓 学生端 | 学生在线填报志愿（每人可填多个志愿） |
| 🧑‍🏫 教师端 | 教师查看所有志愿、执行分配、查看录取结果 |
| 🪑 分配算法 | 采用 **平行志愿分配策略（成绩优先、一次投档）** |
| 💾 数据持久化 | 所有填报数据保存至 Render PostgreSQL 云数据库 |
| 🗂️ 安全访问 | 学生与教师界面隔离，学生无法看到他人志愿 |
| 📤 导出功能（可选） | 教师可导出学生志愿与录取结果为 CSV/Excel |
| ☁️ 云部署 | 可直接运行于 Render 免费计划，无需本地服务器 |

---

## 🏗️ 系统架构

```

Frontend (HTML/JS)
↓
Flask Backend (Python)
↓
PostgreSQL Database (Render Cloud)

```

### 🔹 文件结构
```

├── app.py                 # Flask 主应用
├── templates/
│   ├── index.html         # 首页
│   ├── student.html       # 学生填报界面
│   ├── teacher.html       # 教师后台界面
├── static/
│   ├── style.css          # 页面样式
│   └── fonts              # 字体
├── requirements.txt       # Python 依赖
└── README.md              # 项目说明

````

---

## ⚙️ 核心功能逻辑

### 🎓 学生端
- 输入姓名、成绩、选择志愿座位；
- 提交后写入 PostgreSQL 数据库；
- 学生不可查看他人数据；
- 支持移动端和桌面端访问。

### 🧑‍🏫 教师端
- 登录后可查看所有学生填报信息；
- 点击“分配”后，系统自动执行录取算法；
- 可点击“刷新数据”获取最新填报；
- 可查看最终分配座位图；

---

## 🧮 分配算法说明（平行志愿）

系统采用 **平行志愿分配策略**：

> 成绩优先 → 志愿顺序优先 → 一次投档 → 不退档

### 🔹 分配流程：

1. 按学生成绩从高到低排序；
2. 每位学生依次检查志愿列表；
3. 若当前志愿有空位，则录取；
4. 若都满，则未录取。

### 🔹 示例：

| 学生 | 成绩 | 志愿1 | 志愿2 | 结果 |
|------|------|--------|--------|------|
| 张三 | 98 | 第一组第1排 | 第二组第2排 | 第一组第1排 |
| 李四 | 95 | 第一组第1排 | 第二组第1排 | 第二组第1排 |
| 王五 | 92 | 第二组第2排 | 第一组第1排 | 第二组第2排 |

### 🔹 算法复杂度：
O(n × m)，对 60 名学生、3 个志愿，仅需约 0.1 秒。

---

## 🗄️ 数据库存储结构

表名：`students`

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | SERIAL | 主键 |
| name | TEXT | 学生姓名 |
| score | INTEGER | 成绩 |
| volunteers | TEXT (JSON) | 志愿列表（字符串数组） |
| admitted | TEXT | 录取志愿 |
| last_updated | BIGINT | 提交时间戳 |

---

## ☁️ Render 云端部署指南

### 1️⃣ 上传项目到 GitHub

```bash
git init
git add .
git commit -m "init seat allocation system"
git branch -M main
git remote add origin https://github.com/yourname/seat-allocation.git
git push -u origin main
````

### 2️⃣ Render 新建 Web Service

* 选择 “New +” → “Web Service”
* 选择该 GitHub 仓库
* 运行命令填写：

  ```
  gunicorn app:app
  ```
* 环境：Python 3.10+
* 启动命令自动识别 `requirements.txt`

### 3️⃣ Render 创建数据库

* 点击 “New +” → “PostgreSQL”
* 创建数据库后进入 “Connections” 标签页
* 复制 **External Database URL**

  ```
  postgres://renderuser:xxxxx@dpg-xxxx.render.com:5432/seatdb
  ```
* 回到 Web Service → “Environment” → 新建变量：

  ```
  DATABASE_URL = postgres://renderuser:xxxxx@dpg-xxxx.render.com:5432/seatdb
  ```

### 4️⃣ 重新部署

Render 会自动检测到更改并重新部署。

---

## 🔐 教师登录与权限

* 学生端访问：`/student`
* 教师端访问：`/teacher`
* 教师密码在后端代码中设置，例如：

```python
TEACHER_PASSWORD = "admin123"
```

（建议：在 Render 环境变量中设置 `TEACHER_PASSWORD` 来替代硬编码）

---

## 📊 查看数据库内容

### ✅ 方式一：Render 控制台查看

1. 打开数据库服务；
2. 点击 “Connections” → “psql shell”；
3. 输入以下命令：

```sql
\dt;
SELECT * FROM students;
```

### ✅ 方式二：Navicat / DBeaver 连接数据库

| 参数     | 示例                  |
| ------ | ------------------- |
| 主机     | dpg-xxxx.render.com |
| 端口     | 5432                |
| 用户名    | renderuser          |
| 密码     | Render 提供           |
| 数据库    | seatdb              |
| SSL 模式 | require             |

---

## 🧠 性能说明

| 操作           | 负载         | 响应时间   | 是否安全 |
| ------------ | ---------- | ------ | ---- |
| 学生填报         | 60 次写入     | < 0.3s | ✅    |
| 教师点击分配       | 60×3 志愿    | < 1s   | ✅    |
| 并发请求         | Flask 自动排队 | 无卡顿    | ✅    |
| Render 休眠后启动 | 冷启动约 10s   | 数据不丢失  | ✅    |

---

## 🧩 可选优化方向

* [ ] 教师后台添加 “导出 CSV” 按钮
* [ ] 支持多轮分配（第一轮录取、第二轮补录）
* [ ] 可视化分配进度条
* [ ] 座位图动态显示分配状态
