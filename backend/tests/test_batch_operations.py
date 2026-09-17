"""批量处理接口的集成测试（使用 SQLite 内存库，不依赖 postgres/redis/minio）。"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_batch.db"

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.database import get_db
from app.auth import get_password_hash
from app.routers import auth as auth_router
from app.routers import projects as projects_router
from app import models


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def _make_app(db):
    app = FastAPI()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(auth_router.router, prefix="/api/v1")
    app.include_router(projects_router.router, prefix="/api/v1")
    return app


@pytest.fixture()
def client(db):
    return TestClient(_make_app(db))


@pytest.fixture()
def seeded(db):
    admin = models.User(username="admin", email="a@x.com",
                        hashed_password=get_password_hash("x"), is_admin=True)
    owner = models.User(username="owner", email="o@x.com",
                        hashed_password=get_password_hash("x"))
    other = models.User(username="other", email="r@x.com",
                        hashed_password=get_password_hash("x"))
    member = models.User(username="member", email="m@x.com",
                         hashed_password=get_password_hash("x"), is_active=True)
    inactive = models.User(username="ghost", email="g@x.com",
                           hashed_password=get_password_hash("x"), is_active=False)
    db.add_all([admin, owner, other, member, inactive])
    db.commit()
    for u in (admin, owner, other, member, inactive):
        db.refresh(u)

    projects = {}
    for key, name, creator in [
        ("p1", "项目一", owner.id),
        ("p2", "项目二", owner.id),
        ("p3", "别人的项目", other.id),
    ]:
        p = models.Project(name=name, created_by=creator)
        db.add(p)
        db.commit()
        db.refresh(p)
        db.add(models.ProjectMember(project_id=p.id, user_id=creator, role="owner"))
        db.commit()
        projects[key] = p

    # p1 下两个数据体，p2 下一个，其中一个名字将来会和目标项目冲突
    d1 = models.SeismicData(project_id=projects["p1"].id, name="数据A", status="ready")
    d2 = models.SeismicData(project_id=projects["p1"].id, name="数据B", status="ready")
    d3 = models.SeismicData(project_id=projects["p2"].id, name="重复体", status="ready")
    dt = models.SeismicData(project_id=projects["p3"].id, name="重复体", status="ready")
    db.add_all([d1, d2, d3, dt])
    db.commit()

    return {
        "admin": admin, "owner": owner, "other": other,
        "member": member, "inactive": inactive,
        "projects": projects,
        "data": {"d1": d1, "d2": d2, "d3": d3, "dt": dt},
    }


def _token(client, user):
    resp = client.post("/api/v1/auth/login",
                       data={"username": user.username, "password": "x"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 批量分配成员
# ---------------------------------------------------------------------------

def test_assign_members_partial_success_and_retry(client, db, seeded):
    token = _token(client, seeded["owner"])
    p1, p2, p3 = seeded["projects"]["p1"], seeded["projects"]["p2"], seeded["projects"]["p3"]

    resp = client.post("/api/v1/projects/batch/assign-members",
                       headers=_auth(token),
                       json={"project_ids": [p1.id, p2.id, p3.id],
                             "user_id": seeded["member"].id, "role": "editor"})
    assert resp.status_code == 200
    results = {r["project_id"]: r for r in resp.json()}

    assert results[p1.id]["success"] is True
    assert results[p1.id]["status"] == "added"
    assert results[p2.id]["status"] == "added"
    # 不是 p3 所有者 → 失败但不影响前两条
    assert results[p3.id]["success"] is False
    assert results[p3.id]["reason_code"] == "permission_denied"

    # 已成功的不回退；失败的换 admin 单独重试成功
    admin_token = _token(client, seeded["admin"])
    resp2 = client.post("/api/v1/projects/batch/assign-members",
                        headers=_auth(admin_token),
                        json={"project_ids": [p3.id],
                              "user_id": seeded["member"].id, "role": "editor"})
    assert resp2.json()[0]["status"] == "added"

    # 再次执行：已是成员 → already_member（幂等）
    resp3 = client.post("/api/v1/projects/batch/assign-members",
                        headers=_auth(token),
                        json={"project_ids": [p1.id],
                              "user_id": seeded["member"].id, "role": "editor"})
    assert resp3.json()[0]["status"] == "already_member"
    assert resp3.json()[0]["success"] is True


def test_assign_members_missing_project_explained(client, db, seeded):
    token = _token(client, seeded["owner"])
    p1 = seeded["projects"]["p1"]
    ghost_id = p1.id + 9999

    resp = client.post("/api/v1/projects/batch/assign-members",
                       headers=_auth(token),
                       json={"project_ids": [p1.id, ghost_id],
                             "user_id": seeded["member"].id, "role": "viewer"})
    results = {r["project_id"]: r for r in resp.json()}
    assert results[p1.id]["success"] is True
    failed = results[ghost_id]
    assert failed["success"] is False
    assert failed["reason_code"] == "project_not_found"
    assert "已被其他成员删除" in failed["reason"]


def test_assign_members_user_not_found_404(client, db, seeded):
    token = _token(client, seeded["owner"])
    resp = client.post("/api/v1/projects/batch/assign-members",
                       headers=_auth(token),
                       json={"project_ids": [seeded["projects"]["p1"].id],
                             "user_id": 99999, "role": "viewer"})
    assert resp.status_code == 404


def test_preflight_user_inactive(client, db, seeded):
    token = _token(client, seeded["owner"])
    resp = client.post("/api/v1/projects/batch/preflight",
                       headers=_auth(token),
                       json={"action": "assign_members",
                             "project_ids": [seeded["projects"]["p1"].id],
                             "user_id": seeded["inactive"].id, "role": "viewer"})
    body = resp.json()
    assert body["proceed"] is False
    assert any(b["code"] == "user_inactive" for b in body["blockers"])


# ---------------------------------------------------------------------------
# 批量转移数据体
# ---------------------------------------------------------------------------

def test_transfer_data_success_changes_all_entries(client, db, seeded):
    # admin 可把 owner 项目的数据转到 other 的项目下
    token = _token(client, seeded["admin"])
    p1, p3 = seeded["projects"]["p1"], seeded["projects"]["p3"]
    d1, d2 = seeded["data"]["d1"], seeded["data"]["d2"]

    resp = client.post("/api/v1/projects/batch/transfer-data",
                       headers=_auth(token),
                       json={"project_ids": [p1.id], "target_project_id": p3.id})
    assert resp.status_code == 200
    r = resp.json()[0]
    assert r["success"] is True
    assert r["status"] == "transferred"
    assert r["moved_count"] == 2

    db.expire_all()
    assert db.get(models.SeismicData, d1.id).project_id == p3.id
    assert db.get(models.SeismicData, d2.id).project_id == p3.id


def test_transfer_target_unavailable_rejected(client, db, seeded):
    token = _token(client, seeded["owner"])
    p1 = seeded["projects"]["p1"]
    # 目标不存在
    resp = client.post("/api/v1/projects/batch/transfer-data",
                       headers=_auth(token),
                       json={"project_ids": [p1.id], "target_project_id": 99999})
    assert resp.status_code == 409
    assert "目标项目" in resp.json()["detail"]

    # 目标存在但无权限
    resp = client.post("/api/v1/projects/batch/transfer-data",
                       headers=_auth(token),
                       json={"project_ids": [p1.id],
                             "target_project_id": seeded["projects"]["p3"].id})
    # owner 是 p1 的 owner，但 p3 是 other 的项目 → 无编辑权限
    assert resp.status_code == 409
    assert "不可用" in resp.json()["detail"]

    # 目标 == 源
    resp2 = client.post("/api/v1/projects/batch/transfer-data",
                        headers=_auth(token),
                        json={"project_ids": [p1.id], "target_project_id": p1.id})
    assert resp2.status_code == 409

    # 被拒绝后源数据归属不变
    db.expire_all()
    assert db.get(models.SeismicData, seeded["data"]["d1"].id).project_id == p1.id


def test_transfer_name_conflict_partial_and_item_retry(client, db, seeded):
    # 1) p2 下「重复体」先转到 p1 → 让 p1 同时拥有 数据A/数据B/重复体
    # 2) 新建目标项目 T 并放入一个持久的「重复体」作为同名源
    # 3) 批量 [p3, p1] → T：p3 整项目失败；p1 部分成功（A/B 成功、重复体冲突，不回退）
    token = _token(client, seeded["admin"])  # admin 对所有项目有权限
    p1, p2, p3 = (seeded["projects"]["p1"], seeded["projects"]["p2"],
                  seeded["projects"]["p3"])

    ok = client.post("/api/v1/projects/batch/transfer-data",
                     headers=_auth(token),
                     json={"project_ids": [p2.id], "target_project_id": p1.id})
    assert ok.json()[0]["status"] == "transferred"

    target = models.Project(name="目标项目", created_by=seeded["admin"].id)
    db.add(target)
    db.commit()
    db.refresh(target)
    db.add(models.ProjectMember(project_id=target.id, user_id=seeded["admin"].id, role="owner"))
    db.add(models.SeismicData(project_id=target.id, name="重复体", status="ready"))
    db.commit()

    resp = client.post("/api/v1/projects/batch/transfer-data",
                       headers=_auth(token),
                       json={"project_ids": [p3.id, p1.id],
                             "target_project_id": target.id})
    results = {r["project_id"]: r for r in resp.json()}

    # p3: 只有「重复体」，与目标项目现有同名 → 项目级失败
    p3r = results[p3.id]
    assert p3r["success"] is False
    item = p3r["items"][0]
    assert item["status"] == "failed"
    assert item["reason_code"] == "name_conflict"
    assert "同名数据体" in item["reason"]

    # p1: 数据A/数据B 成功，「重复体」失败 → 部分成功，不回退
    p1r = results[p1.id]
    assert p1r["status"] == "partial_transfer"
    assert p1r["moved_count"] == 2
    assert p1r["failed_count"] == 1
    failed_item = next(i for i in p1r["items"] if i["status"] == "failed")
    assert failed_item["reason_code"] == "name_conflict"

    # 已成功的两条归属已在目标项目，未因后续失败回退
    db.expire_all()
    assert db.get(models.SeismicData, seeded["data"]["d1"].id).project_id == target.id
    assert db.get(models.SeismicData, seeded["data"]["d2"].id).project_id == target.id

    # 目标端改名后，失败项可单独重试成功
    blocker = db.query(models.SeismicData).filter_by(
        name="重复体", project_id=target.id
    ).first()
    blocker.name = "重复体_重命名"
    db.commit()

    retry = client.post("/api/v1/projects/batch/retry-transfer",
                        headers=_auth(token),
                        json={"target_project_id": target.id,
                              "seismic_data_ids": [item["seismic_data_id"]]})
    assert retry.json()[0]["status"] == "moved"

    # p1 的同名体此时仍与目标项目中刚移过去的「重复体」冲突 → 明确失败
    retry_conflict = client.post(
        "/api/v1/projects/batch/retry-transfer", headers=_auth(token),
        json={"target_project_id": target.id,
              "seismic_data_ids": [failed_item["seismic_data_id"]]})
    rc = retry_conflict.json()[0]
    assert rc["status"] == "failed" and rc["reason_code"] == "name_conflict"

    # 目标端再次改名后重试 → 成功
    db.query(models.SeismicData).filter_by(
        name="重复体", project_id=target.id
    ).first().name = "重复体_来自p3"
    db.commit()
    retry2b = client.post("/api/v1/projects/batch/retry-transfer",
                          headers=_auth(token),
                          json={"target_project_id": target.id,
                                "seismic_data_ids": [failed_item["seismic_data_id"]]})
    assert retry2b.json()[0]["status"] == "moved"

    # 再重试一次 → already_at_target，幂等（p3 的同名体现在叫「重复体_来自p3」）
    retry2 = client.post("/api/v1/projects/batch/retry-transfer",
                         headers=_auth(token),
                         json={"target_project_id": target.id,
                               "seismic_data_ids": [failed_item["seismic_data_id"]]})
    assert retry2.json()[0]["status"] == "already_at_target"


def test_transfer_source_project_deleted_midway(client, db, seeded):
    """勾选项在提交前被别人删掉：该条失败并明确说明，其它条不受影响。"""
    token = _token(client, seeded["owner"])
    p1, p2 = seeded["projects"]["p1"], seeded["projects"]["p2"]
    ghost_id = 88888

    # 预先在 preflight 看到缺失提示
    pre = client.post("/api/v1/projects/batch/preflight",
                      headers=_auth(token),
                      json={"action": "transfer_data",
                            "project_ids": [p1.id, p2.id, ghost_id],
                            "target_project_id": None})
    # 没给目标 → 也会有 target blocker，同时包含 projects_missing
    codes = {b["code"] for b in pre.json()["blockers"]}
    assert "projects_missing" in codes

    # admin 直接执行带一个不存在的源 id（目标用 admin 可访问的 p2，实际 p1→p2）
    admin_token = _token(client, seeded["admin"])
    resp = client.post("/api/v1/projects/batch/transfer-data",
                       headers=_auth(admin_token),
                       json={"project_ids": [p1.id, ghost_id],
                             "target_project_id": p2.id})
    results = {r["project_id"]: r for r in resp.json()}
    assert results[p1.id]["success"] is True
    assert results[ghost_id]["success"] is False
    assert results[ghost_id]["reason_code"] == "project_not_found"
    assert "已被其他成员删除" in results[ghost_id]["reason"]


def test_transfer_no_rollback_after_partial(client, db, seeded):
    """同一批里后面的源项目已被删除，前面已转移成功的数据体不能回退。"""
    token = _token(client, seeded["admin"])
    p1, p2 = seeded["projects"]["p1"], seeded["projects"]["p2"]
    d1, d2 = seeded["data"]["d1"], seeded["data"]["d2"]

    resp = client.post("/api/v1/projects/batch/transfer-data",
                       headers=_auth(token),
                       json={"project_ids": [p1.id, 77777],
                             "target_project_id": p2.id})
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(models.SeismicData, d1.id).project_id == p2.id
    assert db.get(models.SeismicData, d2.id).project_id == p2.id


def test_users_list_for_picker(client, db, seeded):
    token = _token(client, seeded["owner"])
    resp = client.get("/api/v1/auth/users", headers=_auth(token))
    assert resp.status_code == 200
    usernames = {u["username"] for u in resp.json()}
    assert "member" in usernames
    assert "ghost" not in usernames  # 停用用户不参与分配


def test_original_crud_flow_unchanged(client, db, seeded):
    token = _token(client, seeded["owner"])
    # 单条创建
    r = client.post("/api/v1/projects", headers=_auth(token),
                    json={"name": "新项目", "description": "d"})
    assert r.status_code == 200
    pid = r.json()["id"]
    # 编辑
    r = client.put(f"/api/v1/projects/{pid}", headers=_auth(token),
                   json={"name": "新项目2"})
    assert r.json()["name"] == "新项目2"
    # 成员添加（单条）
    r = client.post(f"/api/v1/projects/{pid}/members", headers=_auth(token),
                    json={"user_id": seeded["member"].id, "role": "viewer"})
    assert r.status_code == 200
    # 重复添加保持原有 400
    r = client.post(f"/api/v1/projects/{pid}/members", headers=_auth(token),
                    json={"user_id": seeded["member"].id, "role": "viewer"})
    assert r.status_code == 400
    # 删除
    r = client.delete(f"/api/v1/projects/{pid}", headers=_auth(token))
    assert r.status_code == 200
