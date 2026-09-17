export interface User {
  id: number;
  username: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_admin: boolean;
  created_at: string;
}

export interface Project {
  id: number;
  name: string;
  description: string | null;
  created_by: number;
  created_at: string;
  updated_at: string | null;
}

export interface ProjectMember {
  id: number;
  project_id: number;
  user_id: number;
  role: string;
  user?: User;
  created_at: string;
}

export type BatchItemStatus = 'pending' | 'processing' | 'success' | 'failed' | 'cancelled';

export interface BatchItemResult {
  project_id: number;
  project_name?: string | null;
  success: boolean;
  message: string;
  error_code?: string | null;
  /** 前端逐条执行时的本地状态（服务端不返回） */
  status?: BatchItemStatus;
}

export interface BatchActionResponse {
  action: string;
  total: number;
  succeeded: number;
  failed: number;
  results: BatchItemResult[];
}

export interface BackendErrorDetail {
  error_code?: string;
  message?: string;
}

export type BatchActionType = 'assign_collaborator' | 'transfer_seismic_data';

export interface SeismicDataDimensions {
  inline_start: number;
  inline_end: number;
  inline_step: number;
  crossline_start: number;
  crossline_end: number;
  crossline_step: number;
  depth_start: number;
  depth_end: number;
  depth_step: number;
  num_inlines: number;
  num_crosslines: number;
  num_depths: number;
}

export interface SeismicDataStats {
  min_value: number;
  max_value: number;
  mean_value: number;
  std_value: number;
}

export interface SeismicData {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  file_type: string;
  file_size: number | null;
  status: string;
  upload_progress: number;
  created_by: number;
  created_at: string;
  dimensions?: SeismicDataDimensions;
  statistics?: SeismicDataStats;
  inline_start?: number;
  inline_end?: number;
  inline_step?: number;
  crossline_start?: number;
  crossline_end?: number;
  crossline_step?: number;
  depth_start?: number;
  depth_end?: number;
  depth_step?: number;
  num_inlines?: number;
  num_crosslines?: number;
  num_depths?: number;
  min_value?: number;
  max_value?: number;
  mean_value?: number;
  std_value?: number;
}

export interface Annotation {
  id: number;
  seismic_data_id: number;
  owner_id: number;
  name: string | null;
  annotation_type: string;
  geometry: any;
  properties: any;
  created_at: string;
  updated_at: string | null;
}

export interface Well {
  id: number;
  project_id: number;
  name: string;
  uwi: string | null;
  x: number | null;
  y: number | null;
  kb_elevation: number | null;
  total_depth: number | null;
  created_at: string;
}

export interface Point3D {
  x: number;
  y: number;
  z: number;
}

export interface MeasurementResult {
  measurement_type: string;
  value: number;
  unit: string;
  points: Point3D[];
}

export interface SliceConfig {
  type: 'inline' | 'crossline' | 'depth';
  index: number;
  visible: boolean;
  opacity: number;
  colormap: string;
  minValue: number | null;
  maxValue: number | null;
}

export interface VolumeRenderingConfig {
  enabled: boolean;
  quality: number;
  sampleRate: number;
  opacity: number;
}

export interface ViewState {
  cameraPosition: [number, number, number];
  cameraTarget: [number, number, number];
}
