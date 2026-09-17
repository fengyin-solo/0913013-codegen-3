from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_active_user, check_project_permission

router = APIRouter(prefix="/projects", tags=["Projects"])

VALID_ROLES = ("viewer", "editor", "owner")
ROLE_HIERARCHY = {"viewer": 1, "editor": 2, "owner": 3}


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------

def _get_project(db: Session, project_id: int) -> Optional[models.Project]:
    return db.query(models.Project).filter(models.Project.id == project_id).first()


def _user_role_in_project(db: Session, user: models.User, project_id: int) -> Optional[str]:
    """返回用户在项目中的有效角色；admin/创建者视为 owner；非成员返回 None。"""
    if user.is_admin:
        return "owner"
    project = _get_project(db, project_id)
    if not project:
        return None
    if project.created_by == user.id:
        return "owner"
    membership = db.query(models.ProjectMember).filter(
        models.ProjectMember.project_id == project_id,
        models.ProjectMember.user_id == user.id,
    ).first()
    return membership.role if membership else None


def _has_role(db: Session, user: models.User, project_id: int, required_role: str) -> bool:
    role = _user_role_in_project(db, user, project_id)
    if role is None:
        return False
    return ROLE_HIERARCHY.get(role, 1) >= ROLE_HIERARCHY.get(required_role, 1)


def _validate_target_project(
    db: Session, user: models.User, target_project_id: int, exclude_ids: Optional[List[int]] = None
) -> Optional[dict]:
    """
    校验数据转移的目标项目。
    返回 None 表示通过；否则返回 {"code": ..., "message": ...}。
    """
    target = _get_project(db, target_project_id)
    if not target:
        return {
            "code": "target_unavailable",
            "message": f"目标项目（ID: {target_project_id}）不存在或已被删除，服务端拒绝转移",
        }
    if not _has_role(db, user, target_project_id, "editor"):
        return {
            "code": "target_unavailable",
            "message": f"目标项目「{target.name}」不可用：您没有该项目的编辑权限，无法把数据转移到该项目",
        }
    if exclude_ids and target_project_id in exclude_ids:
        return {
            "code": "target_is_source",
            "message": "目标项目不能同时是被转移的源项目，数据体无法转移到项目自身",
        }
    return None


def _load_target_name_set(db: Session, target_project_id: int) -> set:
    """目标项目当前全部数据体名称（小写比较），用于快速预检同名冲突。"""
    return {
        (name or "").strip().lower()
        for (name,) in db.query(models.SeismicData.name)
        .filter(models.SeismicData.project_id == target_project_id)
        .all()
    }


def _move_one_seismic(
    db: Session,
    seismic: models.SeismicData,
    target_project_id: int,
    target_name_conflicts: set,
) -> dict:
    """
    转移单个数据体，独立提交。成功/失败都不会影响其它数据体。
    返回条目结果 dict（可直接传入 BatchTransferItem）。
    每次移动前以数据库当前状态为准重新检查同名，避免并发/集合状态漂移。
    target_name_conflicts 仅作为输出：记录本批已经在目标项目占用的名称。
    """
    base = {"seismic_data_id": seismic.id, "name": seismic.name, "project_id": seismic.project_id}

    # 幂等：重试时它可能已经在目标项目下
    if seismic.project_id == target_project_id:
        target_name_conflicts.add((seismic.name or "").strip().lower())
        return {**base, "status": "already_at_target", "reason": None, "reason_code": None}

    # 以数据库当前状态为准重新查重（同批前一个条目移动后也会立即反映出来）
    target_duplicate = (
        db.query(models.SeismicData.id)
        .filter(
            models.SeismicData.project_id == target_project_id,
            models.SeismicData.name == seismic.name,
            models.SeismicData.id != seismic.id,
        )
        .first()
    )
    if target_duplicate is not None:
        return {
            **base,
            "status": "failed",
            "reason_code": "name_conflict",
            "reason": f"目标项目下已存在同名数据体「{seismic.name}」，请先在目标项目中重命名后再重试",
        }

    try:
        original_project_id = seismic.project_id
        seismic.project_id = target_project_id
        db.commit()
        target_name_conflicts.add((seismic.name or "").strip().lower())
        return {
            **base,
            "status": "moved",
            "reason": None,
            "reason_code": None,
            "project_id": original_project_id,
        }
    except Exception as exc:  # noqa: BLE001 - 单条失败要向调用方明确返回原因
        db.rollback()
        return {
            **base,
            "status": "failed",
            "reason_code": "server_error",
            "reason": f"服务端处理失败：{exc}",
        }


def _transfer_project_data(
    db: Session,
    user: models.User,
    project_id: int,
    target_project_id: int,
    target_name_conflicts: set,
) -> dict:
    """转移单个源项目下的全部数据体，返回 BatchTransferResult 兼容 dict。"""
    project = _get_project(db, project_id)
    if not project:
        return {
            "action": "transfer_data",
            "project_id": project_id,
            "project_name": None,
            "success": False,
            "status": "failed",
            "reason_code": "project_not_found",
            "reason": "该项目在提交前已被其他成员删除，无法转移其数据体",
            "items": [],
            "moved_count": 0,
            "failed_count": 0,
        }

    if not _has_role(db, user, project_id, "editor"):
        return {
            "action": "transfer_data",
            "project_id": project_id,
            "project_name": project.name,
            "success": False,
            "status": "failed",
            "reason_code": "permission_denied",
            "reason": f"您对源项目「{project.name}」没有编辑权限，不能转移其数据体",
            "items": [],
            "moved_count": 0,
            "failed_count": 0,
        }

    seismic_list = (
        db.query(models.SeismicData)
        .filter(models.SeismicData.project_id == project_id)
        .order_by(models.SeismicData.id)
        .all()
    )
    if not seismic_list:
        return {
            "action": "transfer_data",
            "project_id": project_id,
            "project_name": project.name,
            "success": True,
            "status": "no_data",
            "reason": None,
            "reason_code": None,
            "items": [],
            "moved_count": 0,
            "failed_count": 0,
        }

    items = []
    for seismic in seismic_list:
        items.append(_move_one_seismic(db, seismic, target_project_id, target_name_conflicts))

    moved = [i for i in items if i["status"] == "moved"]
    already = [i for i in items if i["status"] == "already_at_target"]
    failed = [i for i in items if i["status"] == "failed"]

    if failed and not moved:
        status_value = "failed"
        success = False
        reason = f"{len(failed)} 个数据体转移失败"
        reason_code = failed[0]["reason_code"]
    elif failed:
        status_value = "partial_transfer"
        success = False
        reason = f"{len(failed)} 个数据体转移失败（已成功转移 {len(moved)} 个，不会回退），可对失败项单独重试"
        reason_code = "partial_transfer"
    else:
        status_value = "transferred"
        success = True
        reason = None
        reason_code = None

    return {
        "action": "transfer_data",
        "project_id": project_id,
        "project_name": project.name,
        "success": success,
        "status": status_value,
        "reason": reason,
        "reason_code": reason_code,
        "items": items,
        "moved_count": len(moved) + len(already),
        "failed_count": len(failed),
    }


# ---------------------------------------------------------------------------
# 项目 CRUD（保持原有单条流程不变）
# ---------------------------------------------------------------------------

@router.get("", response_model=List[schemas.Project])
async def list_projects(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    if current_user.is_admin:
        projects = db.query(models.Project).all()
    else:
        owned = db.query(models.Project).filter(models.Project.created_by == current_user.id)
        member = db.query(models.Project).join(models.ProjectMember).filter(
            models.ProjectMember.user_id == current_user.id
        )
        projects = list(set(owned.all() + member.all()))

    return projects


@router.post("", response_model=schemas.Project)
async def create_project(
    project_in: schemas.ProjectCreate,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    project = models.Project(
        name=project_in.name,
        description=project_in.description,
        created_by=current_user.id
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    membership = models.ProjectMember(
        project_id=project.id,
        user_id=current_user.id,
        role="owner"
    )
    db.add(membership)
    db.commit()

    return project


# ---------------------------------------------------------------------------
# 批量处理接口（必须定义在 /{project_id} 之前，避免路径被吞掉）
# ---------------------------------------------------------------------------

@router.post("/batch/preflight", response_model=schemas.BatchPreflightResponse)
async def batch_preflight(
    payload: schemas.BatchPreflightRequest,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """提交前统一校验：全局性问题（如目标项目不可用）直接拦截，不允许开始执行。"""
    blockers: List[dict] = []
    project_ids = list(dict.fromkeys(payload.project_ids))  # 去重保序

    if payload.action == "assign_members":
        if payload.user_id is None:
            blockers.append({"code": "missing_user", "message": "未指定要分配的成员"})
        else:
            target_user = db.query(models.User).filter(models.User.id == payload.user_id).first()
            if not target_user:
                blockers.append({
                    "code": "user_not_found",
                    "message": f"目标成员（ID: {payload.user_id}）不存在，无法分配",
                })
            elif not target_user.is_active:
                blockers.append({
                    "code": "user_inactive",
                    "message": f"成员「{target_user.username}」已被停用，无法分配",
                })
        if payload.role not in (None, "") and payload.role not in VALID_ROLES:
            blockers.append({
                "code": "invalid_role",
                "message": f"角色无效：{payload.role}（仅支持 viewer / editor / owner）",
            })

    elif payload.action == "transfer_data":
        if payload.target_project_id is None:
            blockers.append({"code": "missing_target", "message": "未指定目标项目"})
        else:
            target_error = _validate_target_project(
                db, current_user, payload.target_project_id, exclude_ids=project_ids
            )
            if target_error:
                blockers.append(target_error)

    missing_ids = [
        pid for pid in project_ids if _get_project(db, pid) is None
    ]
    if missing_ids:
        blockers.append({
            "code": "projects_missing",
            "message": f"以下项目在提交前已被其他成员删除：{', '.join(map(str, missing_ids))}，请刷新列表后重新勾选",
        })

    return {
        "action": payload.action,
        "proceed": len(blockers) == 0,
        "blockers": blockers,
        "item_count": len(project_ids),
    }


@router.post("/batch/assign-members", response_model=List[schemas.BatchAssignResult])
async def batch_assign_members(
    payload: schemas.BatchAssignMembersRequest,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    批量把同一位成员加入多个项目。
    每个项目独立提交：单条失败不影响其它项目，也不会回退已成功的项目。
    """
    if payload.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role: {payload.role}. Must be one of {VALID_ROLES}",
        )

    target_user = db.query(models.User).filter(models.User.id == payload.user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target user {payload.user_id} not found",
        )
    if not target_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User {target_user.username} is inactive",
        )

    results: List[dict] = []
    for project_id in dict.fromkeys(payload.project_ids):
        project = _get_project(db, project_id)
        if not project:
            results.append({
                "action": "assign_members",
                "project_id": project_id,
                "project_name": None,
                "success": False,
                "status": "failed",
                "reason_code": "project_not_found",
                "reason": "该项目在提交前已被其他成员删除，请刷新列表",
                "member_id": None,
            })
            continue

        if not _has_role(db, current_user, project_id, "owner"):
            results.append({
                "action": "assign_members",
                "project_id": project_id,
                "project_name": project.name,
                "success": False,
                "status": "failed",
                "reason_code": "permission_denied",
                "reason": f"您不是项目「{project.name}」的所有者，无权为其添加成员",
                "member_id": None,
            })
            continue

        existing = db.query(models.ProjectMember).filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == payload.user_id,
        ).first()

        try:
            if existing:
                if existing.role == payload.role:
                    results.append({
                        "action": "assign_members",
                        "project_id": project_id,
                        "project_name": project.name,
                        "success": True,
                        "status": "already_member",
                        "reason": f"成员已是该项目的{payload.role}，无需重复添加",
                        "reason_code": None,
                        "member_id": existing.id,
                    })
                else:
                    existing.role = payload.role
                    db.commit()
                    db.refresh(existing)
                    results.append({
                        "action": "assign_members",
                        "project_id": project_id,
                        "project_name": project.name,
                        "success": True,
                        "status": "role_updated",
                        "reason": f"成员已在项目中，角色已更新为{payload.role}",
                        "reason_code": None,
                        "member_id": existing.id,
                    })
            else:
                member = models.ProjectMember(
                    project_id=project_id,
                    user_id=payload.user_id,
                    role=payload.role,
                )
                db.add(member)
                db.commit()
                db.refresh(member)
                results.append({
                    "action": "assign_members",
                    "project_id": project_id,
                    "project_name": project.name,
                    "success": True,
                    "status": "added",
                    "reason": None,
                    "reason_code": None,
                    "member_id": member.id,
                })
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            results.append({
                "action": "assign_members",
                "project_id": project_id,
                "project_name": project.name,
                "success": False,
                "status": "failed",
                "reason_code": "server_error",
                "reason": f"服务端处理失败：{exc}",
                "member_id": None,
            })

    return results


@router.post("/batch/transfer-data", response_model=List[schemas.BatchTransferResult])
async def batch_transfer_data(
    payload: schemas.BatchTransferDataRequest,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    批量把多个项目下的数据体转移到另一个项目下。
    目标项目不可用（不存在/无权限/等于源项目）直接整体拒绝；
    各项目、各数据体逐条独立提交，中途单条失败不回退已成功项。
    """
    target_error = _validate_target_project(
        db, current_user, payload.target_project_id, exclude_ids=payload.project_ids
    )
    if target_error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=target_error["message"])

    # 目标项目现有数据体名称集合，用于同名冲突预检（最终以数据库唯一约束为准）
    existing_names = _load_target_name_set(db, payload.target_project_id)

    results: List[dict] = []
    for project_id in dict.fromkeys(payload.project_ids):
        results.append(
            _transfer_project_data(
                db, current_user, project_id, payload.target_project_id, existing_names
            )
        )

    return results


@router.post("/batch/retry-transfer", response_model=List[schemas.BatchTransferItem])
async def batch_retry_transfer(
    payload: schemas.BatchRetryTransferRequest,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """对批量转移中失败的单个/多个数据体进行重试（幂等）。"""
    target_error = _validate_target_project(db, current_user, payload.target_project_id)
    if target_error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=target_error["message"])

    existing_names = _load_target_name_set(db, payload.target_project_id)

    items: List[dict] = []
    for seismic_id in dict.fromkeys(payload.seismic_data_ids):
        seismic = (
            db.query(models.SeismicData)
            .filter(models.SeismicData.id == seismic_id)
            .first()
        )
        if not seismic:
            items.append({
                "seismic_data_id": seismic_id,
                "name": "",
                "project_id": -1,
                "status": "failed",
                "reason_code": "not_found",
                "reason": "该数据体已被删除，无法重试转移",
            })
            continue

        if not _has_role(db, current_user, seismic.project_id, "editor"):
            items.append({
                "seismic_data_id": seismic_id,
                "name": seismic.name,
                "project_id": seismic.project_id,
                "status": "failed",
                "reason_code": "permission_denied",
                "reason": "您对该数据体当前所属项目没有编辑权限，不能转移",
            })
            continue

        items.append(_move_one_seismic(db, seismic, payload.target_project_id, existing_names))

    return items


@router.get("/{project_id}", response_model=schemas.Project)
async def get_project(
    project_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    check_project_permission(current_user, project_id, "viewer", db)

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return project


@router.put("/{project_id}", response_model=schemas.Project)
async def update_project(
    project_id: int,
    project_in: schemas.ProjectUpdate,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    check_project_permission(current_user, project_id, "editor", db)

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project_in.name:
        project.name = project_in.name
    if project_in.description is not None:
        project.description = project_in.description

    db.commit()
    db.refresh(project)

    return project


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    check_project_permission(current_user, project_id, "owner", db)

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    db.delete(project)
    db.commit()

    return {"message": "Project deleted successfully"}


@router.get("/{project_id}/members", response_model=List[schemas.ProjectMember])
async def list_project_members(
    project_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    check_project_permission(current_user, project_id, "viewer", db)

    members = db.query(models.ProjectMember).filter(
        models.ProjectMember.project_id == project_id
    ).all()

    return members


@router.post("/{project_id}/members", response_model=schemas.ProjectMember)
async def add_project_member(
    project_id: int,
    member_in: schemas.ProjectMemberCreate,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    check_project_permission(current_user, project_id, "owner", db)

    existing = db.query(models.ProjectMember).filter(
        models.ProjectMember.project_id == project_id,
        models.ProjectMember.user_id == member_in.user_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this project"
        )

    user = db.query(models.User).filter(models.User.id == member_in.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    member = models.ProjectMember(
        project_id=project_id,
        user_id=member_in.user_id,
        role=member_in.role
    )
    db.add(member)
    db.commit()
    db.refresh(member)

    return member


@router.put("/{project_id}/members/{member_id}", response_model=schemas.ProjectMember)
async def update_project_member(
    project_id: int,
    member_id: int,
    member_in: schemas.ProjectMemberUpdate,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    check_project_permission(current_user, project_id, "owner", db)

    member = db.query(models.ProjectMember).filter(
        models.ProjectMember.id == member_id,
        models.ProjectMember.project_id == project_id
    ).first()

    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if member_in.role:
        member.role = member_in.role

    db.commit()
    db.refresh(member)

    return member


@router.delete("/{project_id}/members/{member_id}")
async def remove_project_member(
    project_id: int,
    member_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    check_project_permission(current_user, project_id, "owner", db)

    member = db.query(models.ProjectMember).filter(
        models.ProjectMember.id == member_id,
        models.ProjectMember.project_id == project_id
    ).first()

    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    db.delete(member)
    db.commit()

    return {"message": "Member removed successfully"}
