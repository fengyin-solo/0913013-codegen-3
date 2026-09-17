from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text, JSON, LargeBinary
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100))
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    projects = relationship("ProjectMember", back_populates="user")
    annotations = relationship("Annotation", back_populates="owner")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    members = relationship("ProjectMember", back_populates="project", passive_deletes=True)
    seismic_data = relationship("SeismicData", back_populates="project", passive_deletes=True)
    wells = relationship("Well", back_populates="project", passive_deletes=True)


class ProjectMember(Base):
    __tablename__ = "project_members"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), default="viewer")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", back_populates="members")
    user = relationship("User", back_populates="projects")


class SeismicData(Base):
    __tablename__ = "seismic_data"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    file_type = Column(String(20), default="segy")
    file_path = Column(String(500))
    storage_type = Column(String(20), default="minio")
    file_size = Column(Float)

    inline_start = Column(Integer)
    inline_end = Column(Integer)
    inline_step = Column(Integer)
    crossline_start = Column(Integer)
    crossline_end = Column(Integer)
    crossline_step = Column(Integer)
    depth_start = Column(Float)
    depth_end = Column(Float)
    depth_step = Column(Float)

    num_inlines = Column(Integer)
    num_crosslines = Column(Integer)
    num_depths = Column(Integer)

    min_value = Column(Float)
    max_value = Column(Float)
    mean_value = Column(Float)
    std_value = Column(Float)

    status = Column(String(20), default="uploading")
    upload_progress = Column(Float, default=0.0)
    error_message = Column(Text)

    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    project = relationship("Project", back_populates="seismic_data")
    annotations = relationship("Annotation", back_populates="seismic_data", passive_deletes=True)
    slices = relationship("SeismicSlice", back_populates="seismic_data", passive_deletes=True)


class SeismicSlice(Base):
    __tablename__ = "seismic_slices"

    id = Column(Integer, primary_key=True, index=True)
    seismic_data_id = Column(Integer, ForeignKey("seismic_data.id", ondelete="CASCADE"), nullable=False)
    slice_type = Column(String(20), nullable=False)
    slice_index = Column(Integer, nullable=False)
    data_path = Column(String(500))
    thumbnail_path = Column(String(500))
    width = Column(Integer)
    height = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    seismic_data = relationship("SeismicData", back_populates="slices")


class Well(Base):
    __tablename__ = "wells"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    uwi = Column(String(50))
    x = Column(Float)
    y = Column(Float)
    kb_elevation = Column(Float)
    total_depth = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", back_populates="wells")
    well_logs = relationship("WellLog", back_populates="well", passive_deletes=True)


class WellLog(Base):
    __tablename__ = "well_logs"

    id = Column(Integer, primary_key=True, index=True)
    well_id = Column(Integer, ForeignKey("wells.id", ondelete="CASCADE"), nullable=False)
    log_name = Column(String(50), nullable=False)
    log_type = Column(String(50))
    unit = Column(String(20))
    depth_start = Column(Float)
    depth_end = Column(Float)
    depth_step = Column(Float)
    data_path = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    well = relationship("Well", back_populates="well_logs")


class Annotation(Base):
    __tablename__ = "annotations"

    id = Column(Integer, primary_key=True, index=True)
    seismic_data_id = Column(Integer, ForeignKey("seismic_data.id", ondelete="CASCADE"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200))
    annotation_type = Column(String(50), nullable=False)
    geometry = Column(JSON)
    properties = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    seismic_data = relationship("SeismicData", back_populates="annotations")
    owner = relationship("User", back_populates="annotations")


class DataProcessingTask(Base):
    __tablename__ = "processing_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_type = Column(String(50), nullable=False)
    seismic_data_id = Column(Integer, ForeignKey("seismic_data.id", ondelete="SET NULL"))
    status = Column(String(20), default="pending")
    progress = Column(Float, default=0.0)
    parameters = Column(JSON)
    result_path = Column(String(500))
    error_message = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
