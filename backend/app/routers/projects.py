from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_active_user, check_project_permission

router = APIRouter(prefix="/projects", tags=["Projects"])

ROLE_HIERARCHY = {"viewer": 1, "editor": 2, "owner": 3}


class ItemError(Exception):
    """批量流程中单条项目的可预期错误，携带错误码与 HTTP 状态码。"""

    def __init__(self, error_code: str, message: str, http_status: int = 400):
        self.error_code = error_code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


def _user_role_level(user: models.User, project: models.Project, db: Session) -> Optional[int]:
    """返回用户在项目上的角色等级，非成员返回 None。创建者与管理员视同 owner。"""
    if user.is_admin or project.created_by == user.id:
        return ROLE_HIERARCHY["owner"]

    membership = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project.id,
            models.ProjectMember.user_id == user.id,
        )
        .first()
    )
    if not membership:
        return None
    return ROLE_HIERARCHY.get(membership.role, ROLE_HIERARCHY["viewer"])


def _get_project(project_id: int, db: Session) -> models.Project:
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise ItemError("not_found", "项目不存在，可能已被其他用户删除", status.HTTP_404_NOT_FOUND)
    return project


def _require_role(project: models.Project, user: models.User, db: Session, required_role: str):
    level = _user_role_level(user, project, db)
    if level is None:
        raise ItemError("forbidden", "你没有该项目的访问权限", status.HTTP_403_FORBIDDEN)
    if level < ROLE_HIERARCHY[required_role]:
        role_text = {"owner": "所有者(owner)", "editor": "编辑者(editor)", "viewer": "查看者(viewer)"}
        raise ItemError(
            "forbidden",
            f"权限不足，该操作需要{role_text[required_role]}权限",
            status.HTTP_403_FORBIDDEN,
        )


def assign_collaborator_item(
    db: Session,
    user: models.User,
    project_id: int,
    collaborator_user_id: int,
    role: str,
) -> str:
    """把单个项目交给指定成员协作，成功时独立提交。"""
    if role not in ROLE_HIERARCHY:
        raise ItemError("invalid_role", f"不支持的角色：{role}")

    project = _get_project(project_id, db)
    _require_role(project, user, db, "owner")

    collaborator = db.query(models.User).filter(models.User.id == collaborator_user_id).first()
    if not collaborator or not collaborator.is_active:
        raise ItemError("user_not_found", "协作成员不存在或已被停用", status.HTTP_404_NOT_FOUND)

    existing = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == collaborator_user_id,
        )
        .first()
    )
    if existing:
        if existing.role == role:
            raise ItemError(
                "already_member",
                f"成员「{collaborator.username}」已经是该项目的{_role_text(role)}，无需重复添加",
                status.HTTP_409_CONFLICT,
            )
        raise ItemError(
            "already_member",
            f"成员「{collaborator.username}」已是项目成员（当前角色：{_role_text(existing.role)}），"
            "请在成员管理中调整角色",
            status.HTTP_409_CONFLICT,
        )

    db.add(
        models.ProjectMember(
            project_id=project_id,
            user_id=collaborator_user_id,
            role=role,
        )
    )
    db.commit()
    return f"已将成员「{collaborator.username}」以{_role_text(role)}身份加入项目「{project.name}」"


def transfer_seismic_data_item(
    db: Session,
    user: models.User,
    source_project_id: int,
    target_project_id: int,
) -> str:
    """把单个项目下的全部地震数据体转移到目标项目，成功时独立提交。"""
    source = _get_project(source_project_id, db)
    _require_role(source, user, db, "editor")

    if source_project_id == target_project_id:
        raise ItemError("invalid_target", "目标项目与当前项目相同，无需转移")

    target = db.query(models.Project).filter(models.Project.id == target_project_id).first()
    if not target:
        raise ItemError(
            "target_not_found",
            "目标项目不存在，可能已被其他用户删除",
            status.HTTP_404_NOT_FOUND,
        )

    target_level = _user_role_level(user, target, db)
    if target_level is None or target_level < ROLE_HIERARCHY["editor"]:
        # 服务端判定目标项目不可用（无权限/不可写入）
        raise ItemError(
            "target_unavailable",
            "目标项目不可用：你没有目标项目的编辑权限，无法向其转入数据体",
        )

    bodies = (
        db.query(models.SeismicData)
        .filter(models.SeismicData.project_id == source_project_id)
        .all()
    )
    if not bodies:
        return f"项目「{source.name}」下没有数据体，无需转移"

    target_names = {
        name
        for (name,) in db.query(models.SeismicData.name)
        .filter(models.SeismicData.project_id == target_project_id)
        .all()
    }
    duplicated = sorted({b.name for b in bodies if b.name in target_names})
    if duplicated:
        preview = "、".join(f"「{name}」" for name in duplicated[:5])
        more = "等" if len(duplicated) > 5 else ""
        raise ItemError(
            "duplicate_name",
            f"目标项目「{target.name}」中已存在同名数据体{preview}{more}，"
            "请先在源项目或目标项目中重命名后再转移",
            status.HTTP_409_CONFLICT,
        )

    for body in bodies:
        body.project_id = target_project_id
    db.commit()
    return f"已将项目「{source.name}」的 {len(bodies)} 个数据体转移到项目「{target.name}」"


def _role_text(role: str) -> str:
    return {"owner": "所有者", "editor": "编辑者", "viewer": "查看者"}.get(role, role)


def _item_result(project_id: int, project_name: Optional[str], error: ItemError) -> schemas.BatchItemResult:
    return schemas.BatchItemResult(
        project_id=project_id,
        project_name=project_name,
        success=False,
        message=error.message,
        error_code=error.error_code,
    )


def _project_name_map(db: Session, project_ids: List[int]) -> dict:
    rows = (
        db.query(models.Project.id, models.Project.name)
        .filter(models.Project.id.in_(project_ids))
        .all()
    )
    return {row[0]: row[1] for row in rows}


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


@router.post("/batch/assign-collaborator", response_model=schemas.BatchActionResponse)
async def batch_assign_collaborator(
    batch_in: schemas.BatchAssignCollaborator,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """批量把多个项目交给同一位成员协作。逐条独立提交，中途失败或请求取消不会回退已完成项。"""
    if not batch_in.project_ids:
        raise HTTPException(status_code=400, detail="project_ids 不能为空")
    if batch_in.role not in ROLE_HIERARCHY:
        raise HTTPException(status_code=400, detail=f"不支持的角色：{batch_in.role}")

    collaborator = (
        db.query(models.User).filter(models.User.id == batch_in.user_id).first()
    )
    if not collaborator or not collaborator.is_active:
        raise HTTPException(status_code=404, detail="协作成员不存在或已被停用")

    project_ids = list(dict.fromkeys(batch_in.project_ids))
    name_map = _project_name_map(db, project_ids)
    results: List[schemas.BatchItemResult] = []

    for project_id in project_ids:
        project_name = name_map.get(project_id)
        try:
            message = assign_collaborator_item(
                db, current_user, project_id, batch_in.user_id, batch_in.role
            )
            results.append(
                schemas.BatchItemResult(
                    project_id=project_id, project_name=project_name, success=True, message=message
                )
            )
        except ItemError as exc:
            db.rollback()
            results.append(_item_result(project_id, project_name, exc))
        except Exception as exc:  # noqa: BLE001 - 单条异常隔离，不影响其余项目
            db.rollback()
            results.append(
                _item_result(
                    project_id,
                    project_name,
                    ItemError("internal_error", f"服务器内部错误：{exc}", 500),
                )
            )

    succeeded = sum(1 for r in results if r.success)
    return schemas.BatchActionResponse(
        action="assign_collaborator",
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
    )


@router.post("/batch/transfer-seismic-data", response_model=schemas.BatchActionResponse)
async def batch_transfer_seismic_data(
    batch_in: schemas.BatchTransferSeismicData,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """批量把多个项目的数据体转移到同一目标项目。逐条独立提交，中途失败或请求取消不会回退已完成项。"""
    if not batch_in.project_ids:
        raise HTTPException(status_code=400, detail="project_ids 不能为空")

    target = (
        db.query(models.Project).filter(models.Project.id == batch_in.target_project_id).first()
    )
    if not target:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "target_not_found", "message": "目标项目不存在，可能已被其他用户删除"},
        )
    target_level = _user_role_level(current_user, target, db)
    if target_level is None or target_level < ROLE_HIERARCHY["editor"]:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "target_unavailable",
                "message": "目标项目不可用：你没有目标项目的编辑权限，无法向其转入数据体",
            },
        )

    project_ids = list(dict.fromkeys(batch_in.project_ids))
    name_map = _project_name_map(db, project_ids + [target.id])
    results: List[schemas.BatchItemResult] = []

    for project_id in project_ids:
        project_name = name_map.get(project_id)
        try:
            message = transfer_seismic_data_item(
                db, current_user, project_id, batch_in.target_project_id
            )
            results.append(
                schemas.BatchItemResult(
                    project_id=project_id, project_name=project_name, success=True, message=message
                )
            )
        except ItemError as exc:
            db.rollback()
            results.append(_item_result(project_id, project_name, exc))
        except Exception as exc:  # noqa: BLE001 - 单条异常隔离，不影响其余项目
            db.rollback()
            results.append(
                _item_result(
                    project_id,
                    project_name,
                    ItemError("internal_error", f"服务器内部错误：{exc}", 500),
                )
            )

    succeeded = sum(1 for r in results if r.success)
    return schemas.BatchActionResponse(
        action="transfer_seismic_data",
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
    )


@router.post("/{project_id}/collaborator", response_model=schemas.ProjectMember)
async def add_single_project_collaborator(
    project_id: int,
    collaborator_in: schemas.ProjectCollaboratorAssign,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """单条分配协作成员，供批量执行中的逐条调用与失败重试使用。"""
    try:
        assign_collaborator_item(
            db, current_user, project_id, collaborator_in.user_id, collaborator_in.role
        )
    except ItemError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={"error_code": exc.error_code, "message": exc.message},
        )

    member = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == collaborator_in.user_id,
        )
        .first()
    )
    return member


@router.post("/{project_id}/seismic-transfer")
async def transfer_single_project_seismic_data(
    project_id: int,
    transfer_in: schemas.SeismicDataTransfer,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """单条转移数据体，供批量执行中的逐条调用与失败重试使用。"""
    try:
        message = transfer_seismic_data_item(
            db, current_user, project_id, transfer_in.target_project_id
        )
    except ItemError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={"error_code": exc.error_code, "message": exc.message},
        )

    return {"message": message}


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
