import React, { useEffect, useState } from 'react';
import {
  Card,
  Table,
  Button,
  Space,
  Modal,
  Form,
  Input,
  Popconfirm,
  message,
  Tag,
  Typography,
  Upload,
  Progress,
  Empty,
  Alert,
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  EyeOutlined,
  UploadOutlined,
  DatabaseOutlined,
  TeamOutlined,
  SwapOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import {
  fetchProjects,
  createProject,
  updateProject,
  deleteProject,
} from '../store/slices/projectSlice';
import { fetchSeismicData, uploadSeismicData, setCurrentSeismic } from '../store/slices/seismicSlice';
import { RootState, AppDispatch } from '../store';
import { Project, SeismicData, User } from '../types';
import { authAPI } from '../services/api';
import BatchOperationModal from '../components/BatchOperationModal';

const { Title, Text } = Typography;

type BatchAction = 'assign_collaborator' | 'transfer_seismic_data';

const Projects: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingProject, setEditingProject] = useState<Project | null>(null);
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [batchAction, setBatchAction] = useState<BatchAction | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [form] = Form.useForm();
  const [uploadForm] = Form.useForm();
  const navigate = useNavigate();
  const dispatch = useDispatch<AppDispatch>();

  const { projects, loading } = useSelector((state: RootState) => state.projects);
  const { seismicList, uploadProgress } = useSelector((state: RootState) => state.seismic);

  useEffect(() => {
    dispatch(fetchProjects());
  }, [dispatch]);

  const selectedProjects = projects.filter((p) => selectedRowKeys.includes(p.id));

  const loadUsers = async () => {
    setLoadingUsers(true);
    try {
      const res = await authAPI.listUsers();
      setUsers(res.data);
    } catch {
      message.error('获取成员列表失败，请稍后重试');
    } finally {
      setLoadingUsers(false);
    }
  };

  const openBatchAction = (action: BatchAction) => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先勾选要处理的项目');
      return;
    }
    if (action === 'assign_collaborator' && users.length === 0) {
      loadUsers();
    }
    setBatchAction(action);
  };

  const closeBatchModal = () => {
    setBatchAction(null);
    // 关闭即结束本次批量上下文，清空勾选
    setSelectedRowKeys([]);
  };

  const handleBatchCompleted = () => {
    // 归属可能已变化（成员关系、数据体归属），重新拉取项目列表；
    // 若数据管理弹窗开着，同步刷新当前项目的数据体列表
    dispatch(fetchProjects());
    if (selectedProject) {
      dispatch(fetchSeismicData(selectedProject.id));
    }
  };
  const handleCreate = () => {
    setEditingProject(null);
    form.resetFields();
    setIsModalOpen(true);
  };

  const handleEdit = (project: Project) => {
    setEditingProject(project);
    form.setFieldsValue(project);
    setIsModalOpen(true);
  };

  const handleDelete = async (id: number) => {
    const result = await dispatch(deleteProject(id));
    if (deleteProject.fulfilled.match(result)) {
      message.success('项目删除成功');
    }
  };

  const handleSubmit = async (values: any) => {
    if (editingProject) {
      await dispatch(updateProject({ id: editingProject.id, data: values }));
      message.success('项目更新成功');
    } else {
      await dispatch(createProject(values));
      message.success('项目创建成功');
    }
    setIsModalOpen(false);
  };

  const handleOpenViewer = (seismic: SeismicData) => {
    dispatch(setCurrentSeismic(seismic));
    navigate(`/viewer/${seismic.id}`);
  };

  const handleUpload = (project: Project) => {
    setSelectedProject(project);
    uploadForm.resetFields();
    setIsUploadModalOpen(true);
    dispatch(fetchSeismicData(project.id));
  };

  const handleUploadSubmit = async (values: any) => {
    if (!selectedProject) return;

    const file = values.file?.file;
    if (!file) {
      message.error('请选择要上传的文件');
      return;
    }

    const result = await dispatch(
      uploadSeismicData({
        projectId: selectedProject.id,
        name: values.name,
        description: values.description || '',
        file: file.originFileObj,
      })
    );

    if (uploadSeismicData.fulfilled.match(result)) {
      message.success('地震数据上传成功');
      setIsUploadModalOpen(false);
      dispatch(fetchSeismicData(selectedProject.id));
    }
  };

  const projectColumns = [
    {
      title: '项目名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string) => <strong>{text}</strong>,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => new Date(date).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_: any, record: Project) => (
        <Space>
          <Button
            type="primary"
            size="small"
            icon={<DatabaseOutlined />}
            onClick={() => handleUpload(record)}
          >
            数据管理
          </Button>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定要删除这个项目吗？"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const seismicColumns = [
    {
      title: '数据名称',
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: '文件大小',
      dataIndex: 'file_size',
      key: 'file_size',
      render: (size: number) => (size ? `${(size / 1024 / 1024).toFixed(2)} MB` : '-'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const colorMap: Record<string, string> = {
          ready: 'green',
          processing: 'blue',
          uploading: 'orange',
          error: 'red',
        };
        const textMap: Record<string, string> = {
          ready: '就绪',
          processing: '处理中',
          uploading: '上传中',
          error: '错误',
        };
        return <Tag color={colorMap[status] || 'default'}>{textMap[status] || status}</Tag>;
      },
    },
    {
      title: '数据维度',
      key: 'dimensions',
      render: (_: any, record: SeismicData) => (
        <span>
          {record.num_inlines} × {record.num_crosslines} × {record.num_depths}
        </span>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_: any, record: SeismicData) => (
        <Space>
          {record.status === 'ready' && (
            <Button
              type="primary"
              size="small"
              icon={<EyeOutlined />}
              onClick={() => handleOpenViewer(record)}
            >
              查看
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 24 }}>
        <Title level={2} style={{ margin: 0 }}>
          项目管理
        </Title>
        <Text type="secondary">管理地震数据项目和数据集</Text>
      </div>

      <Card
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
            新建项目
          </Button>
        }
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="勾选项目后可批量处理"
          description={
            <Space wrap>
          <Button
            icon={<TeamOutlined />}
            disabled={selectedRowKeys.length === 0}
            onClick={() => openBatchAction('assign_collaborator')}
          >
            批量分配协作成员
          </Button>
          <Button
            icon={<SwapOutlined />}
            disabled={selectedRowKeys.length === 0}
            onClick={() => openBatchAction('transfer_seismic_data')}
          >
            批量转移数据体
          </Button>
          {selectedRowKeys.length > 0 && (
            <Text type="secondary">已选 {selectedRowKeys.length} 个项目（逐条独立执行，失败可单独重试）</Text>
          )}
            </Space>
          }
        />
        <Table
          columns={projectColumns}
          dataSource={projects}
          rowKey="id"
          loading={loading}
          rowSelection={{
            selectedRowKeys,
            onChange: setSelectedRowKeys,
            preserveSelectedRowKeys: false,
          }}
          pagination={{ pageSize: 10 }}
        />
      </Card>

      {batchAction && (
        <BatchOperationModal
          key={batchAction}
          open={!!batchAction}
          action={batchAction}
          projects={selectedProjects}
          allProjects={projects}
          users={users}
          loadingUsers={loadingUsers}
          onClose={closeBatchModal}
          onCompleted={handleBatchCompleted}
        />
      )}

      <Modal
        title={editingProject ? '编辑项目' : '新建项目'}
        open={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        footer={null}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            name="name"
            label="项目名称"
            rules={[{ required: true, message: '请输入项目名称' }]}
          >
            <Input placeholder="请输入项目名称" />
          </Form.Item>
          <Form.Item name="description" label="项目描述">
            <Input.TextArea rows={4} placeholder="请输入项目描述" />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                保存
              </Button>
              <Button onClick={() => setIsModalOpen(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`地震数据管理 - ${selectedProject?.name}`}
        open={isUploadModalOpen}
        onCancel={() => setIsUploadModalOpen(false)}
        width={800}
        footer={null}
      >
        <Card
          title="上传地震数据"
          size="small"
          style={{ marginBottom: 16 }}
        >
          <Form form={uploadForm} layout="vertical" onFinish={handleUploadSubmit}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Form.Item
                name="name"
                label="数据名称"
                rules={[{ required: true, message: '请输入数据名称' }]}
              >
                <Input placeholder="请输入数据名称" />
              </Form.Item>
              <Form.Item name="description" label="描述">
                <Input.TextArea rows={2} placeholder="请输入描述" />
              </Form.Item>
              <Form.Item
                name="file"
                label="SEG-Y文件"
                rules={[{ required: true, message: '请选择文件' }]}
              >
                <Upload
                  maxCount={1}
                  beforeUpload={() => false}
                  accept=".sgy,.segy"
                  showUploadList={true}
                >
                  <Button icon={<UploadOutlined />}>选择SEG-Y文件</Button>
                </Upload>
              </Form.Item>
              {uploadProgress > 0 && uploadProgress < 100 && (
                <Progress percent={uploadProgress} />
              )}
              <Form.Item>
                <Button type="primary" htmlType="submit" loading={loading}>
                  上传
                </Button>
              </Form.Item>
            </Space>
          </Form>
        </Card>

        <Card title="地震数据列表" size="small">
          {seismicList.length === 0 ? (
            <Empty description="暂无地震数据" />
          ) : (
            <Table
              columns={seismicColumns}
              dataSource={seismicList}
              rowKey="id"
              size="small"
              pagination={{ pageSize: 5 }}
            />
          )}
        </Card>
      </Modal>
    </div>
  );
};

export default Projects;
