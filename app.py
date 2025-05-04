import json
import os
import boto3
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import case
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import joinedload
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime
import re, time

# 載入本地 .env 環境變數# 確保永遠讀到正確的 .env
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)

# Flask-Login 配置
app.secret_key = "your_secret_key"  # 用于加密会话
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "index"  # 未登入時會重定向到 login 頁面

# 設定 AWS S3
S3_BUCKET = "ntusc-files"
S3_REGION = "ap-southeast-1"  # 修改為你的 AWS 區域
S3_KEY = os.getenv("AWS_ACCESS_KEY_ID")
S3_SECRET = os.getenv("AWS_SECRET_ACCESS_KEY")

s3 = boto3.client(
    "s3",
    aws_access_key_id=S3_KEY,
    aws_secret_access_key=S3_SECRET,
    region_name=S3_REGION,
)
# 設定 SQLAlchemy 資料庫連線
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "default-secret")

db = SQLAlchemy(app)

# 假设文章存储在字典中
articles = {}
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# 用戶帳號與密碼表
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)

    # 一個用戶可以擁有多條通知和紀錄
    notifications = db.relationship("Notification", backref="user", lazy=True)
    records = db.relationship("Record", backref="user", lazy=True)
    regulations = db.relationship("Regulation", backref="user", lazy=True)

    def __repr__(self):
        return f"<User {self.username}>"


# 通知資料表
class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    session = db.Column(db.Integer, nullable=False)
    datestart = db.Column(db.DateTime, nullable=False)
    dateend = db.Column(db.DateTime, nullable=False)
    place = db.Column(db.String(100), nullable=True)
    person = db.Column(db.String(100), nullable=True)
    shorthand = db.Column(db.String(255), nullable=True)
    upload_type = db.Column(db.String(100), nullable=True)
    meeting_transcript = db.Column(db.String(300), nullable=True)
    video = db.Column(db.String(300), nullable=True)
    chairman = db.Column(db.String(100), nullable=True)
    recorder = db.Column(db.String(100), nullable=True)
    attendance = db.Column(JSONB, nullable=True)  # 不允許為NULL
    present = db.Column(JSONB, nullable=True)  # 不允許為NULL
    is_visible = db.Column(db.Boolean, default=True, nullable=False)

    # 外鍵連接到用戶
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    # 外鍵連接到多個排程
    schedules = db.relationship(
        "Schedule", backref="notification", cascade="all, delete-orphan", lazy=True
    )

    def __repr__(self):
        return f"<Notification {self.title}>"


# 紀錄資料表
class Record(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    session = db.Column(db.Integer, nullable=False)
    datestart = db.Column(db.DateTime, nullable=False)
    dateend = db.Column(db.DateTime, nullable=False)
    place = db.Column(db.String(100), nullable=True)
    person = db.Column(db.String(100), nullable=True)
    shorthand = db.Column(db.String(255), nullable=True)
    upload_type = db.Column(db.String(100), nullable=True)
    meeting_transcript = db.Column(db.String(300), nullable=True)
    video = db.Column(db.String(300), nullable=True)
    chairman = db.Column(db.String(100), nullable=True)
    recorder = db.Column(db.String(100), nullable=True)
    attendance = db.Column(JSONB, nullable=True)  # 不允許為NULL
    present = db.Column(JSONB, nullable=True)
    is_visible = db.Column(db.Boolean, default=True, nullable=False)

    # 外鍵連接到用戶
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    # 外鍵連接到多個排程
    schedules = db.relationship(
        "Schedule", backref="record", cascade="all, delete-orphan", lazy=True
    )

    def __repr__(self):
        return f"<Record {self.title}>"


# Schedule 表格
class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    notification_id = db.Column(
        db.Integer, db.ForeignKey("notification.id", ondelete="CASCADE"), nullable=True
    )
    record_id = db.Column(
        db.Integer, db.ForeignKey("record.id", ondelete="CASCADE"), nullable=True
    )
    # 與 Detail 關聯
    details = db.relationship(
        "Detail", backref="schedule", cascade="all, delete-orphan", lazy="joined"
    )

    def __repr__(self):
        return f"<Schedule {self.title}>"


detail_file = db.Table(
    "detail_file",
    db.Column(
        "detail_id",
        db.Integer,
        db.ForeignKey("detail.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "file_id",
        db.Integer,
        db.ForeignKey("file.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Detail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=True)
    schedule_id = db.Column(
        db.Integer, db.ForeignKey("schedule.id", ondelete="CASCADE"), nullable=False
    )

    files = db.relationship("File", secondary=detail_file, backref="details")

    def __repr__(self):
        return f"<Detail {self.id}>"


class File(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    original_filename = db.Column(db.String(255), nullable=False)
    filename_with_timestamp = db.Column(db.String(255), nullable=False)

    def __repr__(self):
        return f"<File {self.original_filename}>"


# 規章主表
class Regulation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(255))
    description = db.Column(db.Text)
    is_visible = db.Column(db.Boolean, default=True)

    # 關聯章節與修訂紀錄
    chapters = db.relationship(
        "Chapter", backref="regulation", lazy=True, cascade="all, delete-orphan"
    )
    revisions = db.relationship(
        "Revision", backref="regulation", lazy=True, cascade="all, delete-orphan"
    )
    # 外鍵連接到用戶
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )

    def __repr__(self):
        return f"<Regulation {self.title}>"


# 修訂紀錄
class Revision(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    regulation_id = db.Column(
        db.Integer, db.ForeignKey("regulation.id"), nullable=False
    )
    modified_at = db.Column(db.Date, nullable=False)
    note = db.Column(db.Text)

    def __repr__(self):
        return f"<Revision {self.modified_at} - {self.note[:20]}>"


# 章
class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    regulation_id = db.Column(
        db.Integer, db.ForeignKey("regulation.id"), nullable=False
    )
    number = db.Column(db.Integer)  # 第幾章
    title = db.Column(db.String(255))

    articles = db.relationship(
        "Article", backref="chapter", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Chapter 第{self.number}章 - {self.title}>"


class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey("chapter.id"), nullable=False)

    title = db.Column(db.String(255), nullable=False)  # 條標題，如「第四條之一」
    sort_index = db.Column(
        db.Float, nullable=False
    )  # 用於排序：可為 1.0、2.0、2.5、3.0

    paragraphs = db.relationship(
        "Paragraph", backref="article", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Article {self.title}>"


# 項
class Paragraph(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False)
    number = db.Column(db.Integer)  # 第幾項
    content = db.Column(db.Text)

    clauses = db.relationship(
        "Clause", backref="paragraph", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Paragraph 第{self.number}項>"


# 款
class Clause(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    paragraph_id = db.Column(db.Integer, db.ForeignKey("paragraph.id"), nullable=False)
    number = db.Column(db.Integer)  # 第幾款
    content = db.Column(db.Text)

    def __repr__(self):
        return f"<Clause 第{self.number}款>"


# 創建資料庫表格
# with app.app_context():
#     db.create_all()


# 刪除整個資料表（包括資料與結構）
def drop_table(YourModel):
    with app.app_context():
        try:
            YourModel.__table__.drop(db.engine)
            print("資料表已成功刪除。")
        except Exception as e:
            print("刪除失敗：", e)


# drop_table(File)
# drop_table(Detail)


# 創建測試資料的函數
def create_test_user():
    with app.app_context():
        # 設定測試用戶名和密碼
        username = "123"
        password = "123"  # 密碼可以是任意的

        # 檢查使用者是否已經存在
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            print(f"User '{username}' already exists.")
            return
        # 密碼加密
        hashed_password = password

        # 創建新的使用者
        new_user = User(username=username, password=hashed_password)

        # 將新的使用者物件加入資料庫
        db.session.add(new_user)
        db.session.commit()
        print(f"User '{username}' created successfully.")


# 呼叫創建測試用戶的函數
# create_test_user()

# 中文數字對應字典
chinese_numbers = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
    "十三": 13,
    "十四": 14,
    "十五": 15,
    "十六": 16,
    "十七": 17,
    "十八": 18,
    "十九": 19,
    "二十": 20,
    "二十一": 21,
    "二十二": 22,
    "二十三": 23,
    "二十四": 24,
    "二十五": 25,
    "二十六": 26,
    "二十七": 27,
    "二十八": 28,
    "二十九": 29,
    "三十": 30,
}


# 函數：將 "第xx屆" 轉換為數字
def chinese_to_number(chinese_str):
    # 使用正則表達式匹配 "第xx屆" 格式的字串
    match = re.match(r"第([一二三四五六七八九十]+)屆", chinese_str)
    if match:
        chinese_number = match.group(1)  # 提取數字部分
        return chinese_numbers.get(
            chinese_number, -1
        )  # 返回對應的數字，如果找不到則返回 None
    return -1


# 函数：将数字转换为 "第xx屆" 形式的中文
def number_to_chinese(num):
    # 先检查数字是否在字典中
    for chinese_str, number in chinese_numbers.items():
        if num == number:
            return f"第{chinese_str}屆"
    return f"第{num}屆"  # 如果没有找到，则返回默认格式


def custom_secure_filename(filename):
    # 保留中文、英文、數字、底線、括號、點、減號
    filename = re.sub(r"[^\w\u4e00-\u9fa5().-]", "_", filename)
    return filename


def generate_unique_filename(original_filename):
    base, ext = original_filename.rsplit(".", 1)
    base = custom_secure_filename(base)
    ext = custom_secure_filename(ext)
    safe_name = f"{base}.{ext}"

    # 檢查資料庫中是否存在
    existing = File.query.filter_by(original_filename=safe_name).first()
    if existing:
        timestamp = int(time.time())
        safe_name = f"{base}_{timestamp}.{ext}"

    return safe_name


def convert_to_dict(data):
    result = {}
    for item in data:
        role = item["role"]
        members = item["members"]
        result[role] = members
    return result


def getAllMeetTitleFromDB(Table, only_visible: bool = False):
    query = db.session.query(Table)

    if only_visible:
        query = query.filter(Table.is_visible == True)

    tables = query.order_by(Table.session.desc(), Table.datestart.desc()).all()
    result = []
    seen_sessions = set()
    session_list = []

    for table in tables:
        session_str = table.session
        if session_str not in seen_sessions:
            seen_sessions.add(session_str)
            session_list.append(session_str)

        result.append(
            {
                "id": table.id,
                "title": table.title,
                "session": session_str,
                "is_visible": table.is_visible,
            }
        )

    return result, session_list


def serialize_schedule(schedule):
    return {
        "id": schedule.id,
        "title": schedule.title,
        "details": [serialize_detail(detail) for detail in schedule.details],
    }


def serialize_detail(detail):
    file_url_base = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/"
    return {
        "id": detail.id,
        "content": detail.content,
        "file_name": [f.original_filename for f in detail.files],
        "file_urls": [file_url_base + f.filename_with_timestamp for f in detail.files],
    }


def getMeetContentFromDB(Table, id, is_record):
    table = db.session.query(Table).get(id)
    if not table:
        return []

    result = []
    table_data = {
        "id": table.id,
        "title": table.title,
        "session": table.session,
        "place": table.place,
        "datestart": table.datestart,
        "dateend": table.dateend,
        "person": table.person,
        "shorthand": table.shorthand,
        "attendance": table.attendance,
        "present": table.present,
        "is_visible": table.is_visible,
        "upload_type": table.upload_type,
        "chairman": table.chairman,
        "recorder": table.recorder,
        "meeting_transcript": (
            f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{table.video}"
            if table.meeting_transcript
            else table.meeting_transcript
        ),
    }
    if table.upload_type == "file":
        if table.video:
            table_data["video"] = (
                f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{table.video}"
            )
        else:
            table_data["video"] = table.video
    elif table.upload_type == "link":
        table_data["video"] = table.video

    # 預先載入每個 schedule 的 details 和每個 detail 的 files
    filter_kwargs = (
        {"record_id": table.id} if is_record else {"notification_id": table.id}
    )
    schedules = (
        Schedule.query.filter_by(**filter_kwargs)
        .options(joinedload(Schedule.details).joinedload(Detail.files))
        .all()
    )

    table_data["schedules"] = [serialize_schedule(sched) for sched in schedules]
    result.append(table_data)
    return result


def parse_json_field(request, field_name):
    try:
        return json.loads(request.form.get(field_name, "{}"))
    except json.JSONDecodeError:
        print(f"JSON decode error for field: {field_name}")
        return {}


def getDataFromFrontend(request):
    is_visible = request.form.get("is_visible")
    data = {
        "title": request.form.get("title"),
        "session": request.form.get("session"),
        "datestart": datetime.fromisoformat(request.form.get("datestart")),
        "dateend": datetime.fromisoformat(request.form.get("dateend")),
        "place": request.form.get("place"),
        "person": request.form.get("person"),
        "shorthand": request.form.get("shorthand"),
        "chairman": request.form.get("chairman"),
        "recorder": request.form.get("recorder"),
        "is_visible": True if is_visible == "true" else False,
        "present": parse_json_field(request, "present"),
        "attendance": parse_json_field(request, "attendance"),
        "upload_type": request.form.get("uploadType"),
        "meeting_transcript": "",
        "video": "",
    }

    if data["upload_type"] == "link":
        video_link = request.form.get("videoLink")
        data["video"] = video_link
    # else:
    #     video_file = request.files.get('videoFile')
    uploaded_files_info = {}
    # 上傳檔案
    for key in request.files:
        if key.startswith("newfile-"):
            file = request.files[key]
            original = file.filename
            safe = generate_unique_filename(original)
            try:
                s3.upload_fileobj(
                    file, S3_BUCKET, safe, ExtraArgs={"ACL": "public-read"}
                )
                uploaded_files_info[original] = {
                    "original": original,
                    "safe": safe,
                }
            except Exception as e:
                print(e, "  上傳失敗")
        elif key.startswith("MeetingTranscript"):
            file = request.files[key]
            try:
                s3.upload_fileobj(
                    file, S3_BUCKET, file.filename, ExtraArgs={"ACL": "public-read"}
                )
                data["meeting_transcript"] = file.filename
            except Exception as e:
                print(e, "  上傳失敗")
        elif key.startswith("videoFile"):
            file = request.files[key]
            try:
                s3.upload_fileobj(
                    file, S3_BUCKET, file.filename, ExtraArgs={"ACL": "public-read"}
                )
                data["video"] = file.filename
            except Exception as e:
                print(e, "  上傳失敗")
            print(f"影音檔案 {key}: {file.filename}")

    deleted_files = []
    content = parse_json_field(request, "content")
    # 填入 file_urls
    for schedule in content:
        for detail in schedule["details"]:
            if detail.get("deleted_files"):  # 假設使用 deleted_files 儲存被刪除的檔案
                deleted_files += detail.get("deleted_files")
            detail["file_urls"] = []
            # 處理舊檔案
            file_dict_urls = [
                {"original": file["name"], "safe": file["url"]}
                for file in detail.get("file_dict", [])
            ]
            # 來自本次上傳的新檔案
            new_file_urls = [
                uploaded_files_info[fname]
                for fname in detail.get("fileName", [])
                if fname in uploaded_files_info
            ]
            detail["file_urls"] = file_dict_urls + new_file_urls
    data["content"] = content
    return data, deleted_files


def addSchedule(content, id, is_record):
    st_time = time.time()
    for schedule in content:
        # 動態決定欄位
        schedule_kwargs = {
            "title": schedule["title"],
            "notification_id": None if is_record else id,
            "record_id": id if is_record else None,
        }
        schedule_obj = Schedule(**schedule_kwargs)
        db.session.add(schedule_obj)
        db.session.flush()

        for detail in schedule["details"]:
            detail_obj = Detail(
                content=detail["content"],
                schedule_id=schedule_obj.id,
            )
            db.session.add(detail_obj)
            db.session.flush()

            for file_item in detail.get("file_urls", []):
                # 檢查是否已有此檔案
                file_obj = File.query.filter_by(
                    filename_with_timestamp=file_item["safe"]
                ).first()

                if not file_obj:
                    file_obj = File(
                        original_filename=file_item["original"],
                        filename_with_timestamp=file_item["safe"],
                    )
                    db.session.add(file_obj)
                    db.session.flush()

                db.session.execute(
                    detail_file.insert().values(
                        detail_id=detail_obj.id, file_id=file_obj.id
                    )
                )
    db.session.commit()
    print(
        "更新/新增議程 id = ",
        id,
        " 是否為紀錄:",
        is_record,
        " 花費時間:",
        time.time() - st_time,
    )


def delete_file_if_unused(file, deleted_files_set):
    """
    如果檔案只被一個 detail 使用，且在刪除清單中，就從 S3 與資料庫中刪除。
    """
    if len(file.details) == 1 and file.filename_with_timestamp in deleted_files_set:
        try:
            s3_time = time.time()
            s3.delete_object(Bucket=S3_BUCKET, Key=file.filename_with_timestamp)
            print("s3", file.filename_with_timestamp, time.time() - s3_time)
        except Exception as e:
            print("刪除 S3 失敗：", e)
        db.session.delete(file)


def deletSchedule(id, deleted_files, is_record):
    st_time = time.time()
    schedule_filter = (
        Schedule.record_id == id if is_record else Schedule.notification_id == id
    )
    old_schedules = Schedule.query.filter(schedule_filter).all()
    if not old_schedules:
        print("刪議程,此id=", id, "沒有議程 紀錄:", is_record)
        return
    for sched in old_schedules:
        dele_time = time.time()
        if deleted_files:
            for detail in sched.details:
                for file in detail.files:
                    delete_file_if_unused(file, deleted_files)
            print("全部刪檔案", time.time() - dele_time)
        db.session.delete(sched)
    db.session.commit()
    print("刪議程,id=", id, " 紀錄:", is_record, " 花費時間:", time.time() - st_time)


def getAllRegulationTitleFromDB(Table, only_visible: bool = False):
    category_ordering = {
        "憲制性法規篇": 1,
        "綜合法規篇": 2,
        "行政部門篇": 3,
        "立法部門篇": 4,
        "司法部門篇": 5,
        "附錄篇": 6,
    }

    category_order = case(
        *[(Table.category == name, order) for name, order in category_ordering.items()],
        else_=100,
    )

    query = db.session.query(Table)
    if only_visible:
        query = query.filter(Table.is_visible == True)

    regulations = query.order_by(category_order, Table.id.asc()).all()

    result = [
        {
            "id": r.id,
            "title": r.title,
            "category": r.category,
            "is_visible": r.is_visible,
        }
        for r in regulations
    ]

    return result, list(category_ordering.keys())


def getRegulationContentFromDB(reg_id):
    regulation = (
        db.session.query(Regulation)
        .options(
            joinedload(Regulation.chapters)
            .joinedload(Chapter.articles)
            .joinedload(Article.paragraphs)
            .joinedload(Paragraph.clauses),
            joinedload(Regulation.revisions),
        )
        .filter(Regulation.id == reg_id)
        .first()
    )

    if not regulation:
        return None

    return {
        "id": regulation.id,
        "title": regulation.title,
        "category": regulation.category,
        "is_visible": regulation.is_visible,
        "description": regulation.description,
        "chapters": [
            {
                "id": chapter.id,
                "number": chapter.number,
                "title": chapter.title,
                "articles": [
                    {
                        "id": article.id,
                        # "number": article.number,
                        "title": article.title,
                        "sort_index": article.sort_index,
                        "paragraphs": [
                            {
                                "id": para.id,
                                "number": para.number,
                                "content": para.content,
                                "clauses": [
                                    {
                                        "id": clause.id,
                                        "number": clause.number,
                                        "content": clause.content,
                                    }
                                    for clause in para.clauses
                                ],
                            }
                            for para in article.paragraphs
                        ],
                    }
                    for article in sorted(
                        chapter.articles, key=lambda x: float(x.sort_index)
                    )  # 排序
                ],
            }
            for chapter in regulation.chapters
        ],
        "revisions": [
            {
                "id": revision.id,
                "modified_at": revision.modified_at,  # datetime to str
                "note": revision.note,
            }
            for revision in regulation.revisions
        ],
    }


def getRegulationFromFrontend(request):
    is_visible = request.form.get("is_visible")
    data = {
        "title": request.form.get("title"),
        "category": request.form.get("category"),
        "description": request.form.get("description"),
        "is_visible": True if is_visible == "true" else False,
    }
    data["content"] = parse_json_field(request, "content")
    data["revision"] = parse_json_field(request, "revision")
    return data


def deletChapter(id):
    st_time = time.time()
    regulation = (
        Regulation.query.options(
            joinedload(Regulation.chapters)
            .joinedload(Chapter.articles)
            .joinedload(Article.paragraphs)
            .joinedload(Paragraph.clauses),
            joinedload(Regulation.revisions),
        )
        .filter_by(id=id)
        .first()
    )
    if not regulation:
        raise ValueError(f"Regulation id {id} not found.")
    # 刪掉所有章節底下的資料
    for chapter in regulation.chapters:
        for article in chapter.articles:
            for paragraph in article.paragraphs:
                for clause in paragraph.clauses:
                    db.session.delete(clause)
                db.session.delete(paragraph)
            db.session.delete(article)
        db.session.delete(chapter)

    # 刪掉修訂紀錄
    for revision in regulation.revisions:
        db.session.delete(revision)

    db.session.commit()
    print("刪章節,id=", id, " 花費時間:", time.time() - st_time)


def addChapter(content, revision, regulation_id):
    st_time = time.time()
    # 新增章節
    for chapter_data in content:
        chapter = Chapter(
            regulation_id=regulation_id,
            title=chapter_data["title"],
            number=chapter_data["number"],
        )
        db.session.add(chapter)
        db.session.flush()  # 把 chapter.id 生出來給後面用

        for article_data in chapter_data.get("articles", []):
            article = Article(
                chapter_id=chapter.id,
                title=article_data["title"],
                sort_index=article_data["sort_index"],
            )
            db.session.add(article)
            db.session.flush()

            for paragraph_data in article_data.get("paragraphs", []):
                paragraph = Paragraph(
                    article_id=article.id,
                    number=paragraph_data["number"],
                    content=paragraph_data["content"],
                )
                db.session.add(paragraph)
                db.session.flush()

                for clause_data in paragraph_data.get("clauses", []):
                    clause = Clause(
                        paragraph_id=paragraph.id,
                        number=clause_data["number"],
                        content=clause_data["content"],
                    )
                    db.session.add(clause)

    # 新增修訂紀錄
    for rev in revision:
        rev_obj = Revision(
            regulation_id=regulation_id,
            modified_at=datetime.strptime(rev["date"], "%Y-%m-%d").date(),
            note=rev["note"],
        )
        db.session.add(rev_obj)

    db.session.commit()
    print("新增章節,id=", id, " 花費時間:", time.time() - st_time)


# 設定如何載入使用者
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.route("/")
def index():
    logout_user()
    session.clear()
    return render_template("index.html")  # 登录页面


# 登录页面
@app.route("/login", methods=["POST"])
def login():
    if request.method == "POST":
        # session.pop("logged_in", None)  # 访问 login 页面时自动登出
        data = request.get_json()
        username = data.get("username")
        password = data.get("password")
        # 假設這裡直接從資料庫查詢使用者
        user = User.query.filter_by(username=username).first()
        if user and user.password == password:  # 驗證密碼
            login_user(user)  # 登入使用者
            print("帳密正確")
            return jsonify({"success": True}), 200  # 登入後重定向到 admin 頁面
        else:
            print("帳密錯誤")
            return (
                jsonify({"success": False, "message": "Invalid credentials"}),
                401,
            )  # 錯誤的帳號或密碼
    return render_template("index.html")


# 登出路由
@app.route("/logout", methods=["GET"])
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("index"))


@app.route("/notifi")
def admin_notifi_page():
    print(current_user.is_authenticated)
    return render_template("admin_notifi.html", editable=current_user.is_authenticated)


@app.route("/minutes")
def admin_minutes_page():
    return render_template("admin_minutes.html", editable=current_user.is_authenticated)


@app.route("/regulations")
def admin_regulations_page():
    return render_template(
        "admin_regulations.html", editable=current_user.is_authenticated
    )


@app.route("/notifi/data")
# @login_required  # 需要用戶登入才能訪問
def admin_notifi_data():
    try:
        # 根據是否登入決定是否顯示所有與是否可編輯
        is_authenticated = current_user.is_authenticated
        result, session_list = getAllMeetTitleFromDB(
            Notification, only_visible=not is_authenticated
        )
        return (
            jsonify(
                {
                    "notifications": result,
                    "session_list": session_list,
                    "editable": is_authenticated,
                }
            ),
            200,
        )
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/minutes/data")
# @login_required  # 需要用戶登入才能訪問
def admin_record_data():
    try:
        # 根據是否登入決定是否顯示所有與是否可編輯
        is_authenticated = current_user.is_authenticated
        result, session_list = getAllMeetTitleFromDB(
            Record, only_visible=not is_authenticated
        )
        return (
            jsonify(
                {
                    "records": result,
                    "session_list": session_list,
                    "editable": is_authenticated,
                }
            ),
            200,
        )
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/regulations/data")
# @login_required  # 需要用戶登入才能訪問
def admin_regulations_data():
    try:
        is_authenticated = current_user.is_authenticated
        result, category_list = getAllRegulationTitleFromDB(
            Regulation, only_visible=not is_authenticated
        )
        return (
            jsonify(
                {
                    "regulations": result,
                    "category_list": category_list,
                    "editable": is_authenticated,
                }
            ),
            200,
        )
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/notifi/data/<int:id>", methods=["GET"])
# @login_required  # 需要用戶登入才能訪問
def admin_notifi_getdetail(id):
    try:
        result = getMeetContentFromDB(Notification, id, 0)
        if result:
            return jsonify({"notifications": result}), 200
        return jsonify({"error": "找不到此通知"}), 404
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/minutes/data/<int:id>", methods=["GET"])
# @login_required  # 需要用戶登入才能訪問
def admin_record_getdetail(id):
    try:
        result = getMeetContentFromDB(Record, id, 1)
        if result:
            return jsonify({"records": result}), 200
        return jsonify({"error": "找不到此通知"}), 500
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/regulations/data/<int:id>", methods=["GET"])
# @login_required  # 需要用戶登入才能訪問
def admin_regulations_getdetail(id):
    try:
        result = getRegulationContentFromDB(id)
        if result:
            return jsonify({"regulations": result}), 200
        return jsonify({"error": "找不到此通知"}), 404
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/notifi/upload", methods=["POST"])
@login_required  # 需要用戶登入才能訪問
def upload_notifi():
    try:
        not_time = time.time()
        data, deleted_files = getDataFromFrontend(request)

        record = None
        noti_id = request.form.get("id")
        is_new = noti_id == "-1"

        # 建立或取得 Notification
        if is_new:
            print("新增通知")
            notification = Notification(user_id=current_user.id)
            db.session.add(notification)
        else:
            print(f"修改通知 id = {noti_id}")
            notification = Notification.query.get(noti_id)
            if not notification:
                return {"error": "找不到通知資料"}, 404
        # 通用欄位
        print(data["chairman"], data["recorder"])

        for field in [
            "title",
            "session",
            "datestart",
            "dateend",
            "place",
            "person",
            "shorthand",
            "present",
            "attendance",
            "is_visible",
            "meeting_transcript",
            "upload_type",
            "chairman",
            "recorder",
            "video",
        ]:
            setattr(notification, field, data[field])
        db.session.flush()
        if not is_new:
            deletSchedule(notification.id, deleted_files, is_record=False)
        addSchedule(data["content"], notification.id, is_record=False)

        db.session.commit()
        print("完成", time.time() - not_time)

        return admin_notifi_data()
    except Exception as e:
        db.session.rollback()
        print(str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/minutes/upload", methods=["POST"])
@login_required  # 需要用戶登入才能訪問
def upload_record():
    try:
        record_time = time.time()
        data, deleted_files = getDataFromFrontend(request)
        record_id = request.form.get("id")

        is_new = record_id == "-1"
        if is_new:
            print("新增紀錄")
            record = Record(
                user_id=current_user.id,
                is_modify=True,
            )
            db.session.add(record)
        else:
            print(f"修改紀錄 id = {record_id}")
            record = Record.query.get(record_id)
            if not record:
                return {"error": "找不到紀錄資料"}, 404
            record.is_modify = True
        # 通用欄位填入
        print(data["chairman"], data["recorder"])
        for field in [
            "title",
            "session",
            "datestart",
            "dateend",
            "place",
            "person",
            "shorthand",
            "present",
            "attendance",
            "is_visible",
            "meeting_transcript",
            "upload_type",
            "chairman",
            "recorder",
            "video",
        ]:

            setattr(record, field, data[field])
        db.session.flush()

        if not is_new:
            deletSchedule(record.id, deleted_files, is_record=True)

        addSchedule(data["content"], record.id, is_record=True)
        db.session.commit()
        print("完成", time.time() - record_time)

        return admin_record_data()
    except Exception as e:
        db.session.rollback()
        print(str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/regulations/upload", methods=["POST"])
@login_required  # 需要用戶登入才能訪問
def upload_regulation():
    try:
        record_time = time.time()
        data = getRegulationFromFrontend(request)
        regulation_id = request.form.get("id")

        is_new = regulation_id == "-1"
        print("current_user.id", current_user.id)
        if is_new:
            print("新增規章")
            regulation = Regulation(
                user_id=current_user.id,
            )
            db.session.add(regulation)
        else:
            print(f"修改規章 id = {regulation_id}")
            regulation = Regulation.query.get(regulation_id)
            if not regulation:
                return {"error": "找不到紀錄資料"}, 404
        # 通用欄位填入
        for field in [
            "title",
            "category",
            "description",
            "is_visible",
        ]:
            setattr(regulation, field, data[field])
        db.session.flush()

        if not is_new:
            deletChapter(regulation.id)
        addChapter(data["content"], data["revision"], regulation.id)
        db.session.commit()
        print("完成", time.time() - record_time)

        return admin_regulations_data()
    except Exception as e:
        db.session.rollback()
        print(str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/notifi/delete", methods=["POST"])
@login_required  # 需要用戶登入才能訪問
def delete_notifi():
    try:
        notifi_id = request.form.get("id")
        if notifi_id:
            notification = Notification.query.get(notifi_id)
            if notification:
                db.session.delete(notification)
                db.session.commit()
                return admin_notifi_data()
            else:
                return jsonify({"error": "找不到通知資料"}), 404
        else:
            return jsonify({"error": "缺少通知 ID"}), 400
    except Exception as e:
        db.session.rollback()
        print(str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/minutes/delete", methods=["POST"])
@login_required  # 需要用戶登入才能訪問
def delete_record():
    try:
        record_id = request.form.get("id")
        if record_id:
            record = Record.query.get(record_id)
            if record:
                db.session.delete(record)
                db.session.commit()
                return admin_record_data()
            else:
                return jsonify({"error": "找不到紀錄資料"}), 404
        else:
            return jsonify({"error": "缺少紀錄 ID"}), 400
    except Exception as e:
        db.session.rollback()
        print(str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/regulations/delete", methods=["POST"])
@login_required  # 需要用戶登入才能訪問
def delete_regulation():
    try:
        regulation_id = request.form.get("id")
        if regulation_id:
            regulation = Regulation.query.get(regulation_id)
            if regulation:
                db.session.delete(regulation)
                db.session.commit()
                return admin_regulations_data()
            else:
                return jsonify({"error": "找不到規章資料"}), 404
        else:
            return jsonify({"error": "缺少規章 ID"}), 400
    except Exception as e:
        db.session.rollback()
        print(str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/viewer/notifi")
def viewer_notifi_page():
    return render_template("viewer_notifi.html")


@app.route("/viewer/minutes")
def viewer_minutes_page():
    return render_template("viewer_minutes.html")


@app.route("/viewer/regulations")
def viewer_regulations_page():
    return render_template("viewer_regulations.html")


@app.route("/viewer/notifi/data")
def viewer_notifi_data():
    try:
        result, session_list = getAllMeetTitleFromDB(Notification, only_visible=True)
        return jsonify({"notifications": result, "session_list": session_list}), 200
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/viewer/minutes/data")
def viewer_record_data():
    try:
        result, session_list = getAllMeetTitleFromDB(Record, only_visible=True)
        return jsonify({"records": result, "session_list": session_list}), 200
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/viewer/regulations/data")
def viewer_regulations_data():
    try:
        result, category_list = getAllRegulationTitleFromDB(
            Regulation, only_visible=True
        )
        return (
            jsonify({"regulations": result, "category_list": category_list}),
            200,
        )
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/viewer/notifi/data/<int:id>", methods=["GET"])
def viewer_notifi_getdetail(id):
    try:
        result = getMeetContentFromDB(Notification, id, 0)
        if result:
            return jsonify({"notifications": result}), 200
        return jsonify({"error": "找不到此通知"}), 404
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/viewer/minutes/data/<int:id>", methods=["GET"])
def viewer_record_getdetail(id):
    try:
        result = getMeetContentFromDB(Record, id, 1)
        if result:
            return jsonify({"records": result}), 200
        return jsonify({"error": "找不到此通知"}), 500
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/viewer/regulations/data/<int:id>", methods=["GET"])
def viewer_regulations_getdetail(id):
    try:
        result = getRegulationContentFromDB(id)
        if result:
            return jsonify({"regulations": result}), 200
        return jsonify({"error": "找不到此通知"}), 404
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # app.run(debug=True)
    # app.run(host="0.0.0.0", port="8012", debug=True)
    debug_mode = os.getenv("FLASK_ENV") != "production"
    app.run(debug=debug_mode, port=8012)  # 預設啟動在 localhost:5000
