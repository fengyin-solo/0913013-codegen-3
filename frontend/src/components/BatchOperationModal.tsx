import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Modal, Form, Select, Button, List, Tag, Space, Typography, Alert, Progress } from 'antd';
import { CheckCircleFilled, CloseCircleFilled, LoadingOutlined, MinusCircleFilled } from '@ant-design/icons';
import { projectsAPI, parseApiError } from '../services/api';
import { BatchItemStatus, Project, User } from '../types';

const { Text } = Typography;

interface BatchOperationModalProps {
  open: boolean;
  action: 'assign_collaborator' | 'transfer_seismic_data';
  projects: Project[];
  allProjects: Project[];
  users: User[];
  loadingUsers: boolean;
  onClose: () => void;
  onCompleted: () => void;
}

interface ExecutionItem {
  project_id: number;
  project_name: string;
  status: BatchItemStatus;
  message: string;
  error_code?: string | null;
}

const ROLE_OPTIONS = [
  { value: 'viewer', label: '查看者（仅查看）' },
  { value: 'editor', label: '编辑者（可上传与编辑）' },
  { value: 'owner', label: '所有者（完整管理权限）' },
];

const BatchOperationModal: React.FC<BatchOperationModalProps> = ({
  open,
  action,
  projects,
  allProjects,
  users,
  loadingUsers,
  onClose,
  onCompleted,
}) => {
  const [form] = Form.useForm();
  const [phase, setPhase] = useState<'setup' | 'executing' | 'done'>('setup');
  const [items, setItems] = useState<ExecutionItem[]>([]);
  const [cancelled, setCancelled] = useState(false);
  const cancelRef = useRef(false);

  const selectedProjects = projects;
  const currentUserId = JSON.parse(localStorage.getItem('user') || 'null')?.id as number | undefined;

  useEffect(() => {
    if (open) {
      setPhase('setup');
      setCancelled(false);
      cancelRef.current = false;
      form.resetFields();
    }
  }, [open, form]);

  const successCount = items.filter((i) => i.status === 'success').length;
  const failedCount = items.filter((i) => i.status === 'failed').length;
  const pendingCount = items.filter((i) => i.status === 'pending' || i.status === 'processing').length;
  const percent = items.length
    ? Math.round((items.filter((i) => i.status === 'success' || i.status === 'failed').length / items.length) * 100)
    : 0;

  const title =
    action === 'assign_collaborator'
      ? `批量分配协作成员（已选 ${selectedProjects.length} 个项目）`
      : `批量转移数据体（已选 ${selectedProjects.length} 个项目）`;

  const targetProjectOptions = useMemo(
    () =>
      allProjects
        .filter((p) => !selectedProjects.some((sp) => sp.id === p.id))
        .map((p) => ({ value: p.id, label: p.name })),
    [allProjects, selectedProjects],
  );

  const patchItem = (projectId: number, patch: Partial<ExecutionItem>) => {
    setItems((prev) => prev.map((it) => (it.project_id === projectId ? { ...it, ...patch } : it)));
  };

  const runOne = async (item: ExecutionItem) => {
    const values = form.getFieldsValue();
    try {
      if (action === 'assign_collaborator') {
        await projectsAPI.assignCollaborator(item.project_id, {
          user_id: values.user_id,
          role: values.role || 'editor',
        });
        return { success: true, message: `已将成员加入项目「${item.project_name}」` };
      }
      const res = await projectsAPI.transferSeismicData(item.project_id, values.target_project_id);
      return { success: true, message: res.data.message };
    } catch (error: any) {
      const parsed = parseApiError(error);
      return {
        success: false,
        message: parsed.message,
        error_code: parsed.errorCode,
      };
    }
  };

  const handleSetupOk = async () => {
    const values = await form.validateFields();
    cancelRef.current = false;
    setCancelled(false);

    if (action === 'transfer_seismic_data'
      && selectedProjects.some((p) => p.id === values.target_project_id)) {
      Modal.warning({
        title: '目标项目选择无效',
        content: '目标项目不能与勾选的源项目相同，请选择其他项目作为转移目标。',
      });
      return;
    }

    setItems(
      selectedProjects.map((p) => ({
        project_id: p.id,
        project_name: p.name,
        status: 'pending' as BatchItemStatus,
        message: '',
      })),
    );
    await startExecutionWith(values, selectedProjects);
  };

  const startExecutionWith = async (values: any, projectQueue: Project[]) => {
    setPhase('executing');

    for (const p of projectQueue) {
      if (cancelRef.current) {
        setItems((prev) =>
          prev.map((it) =>
            it.status === 'pending' || it.status === 'processing'
              ? { ...it, status: 'cancelled', message: '已取消，未执行（之前已处理的项目不会回退）' }
              : it,
          ),
        );
        break;
      }

      patchItem(p.id, { status: 'processing' });
      try {
        let message: string;
        if (action === 'assign_collaborator') {
          await projectsAPI.assignCollaborator(p.id, {
            user_id: values.user_id,
            role: values.role || 'editor',
          });
          message = `已将成员加入项目「${p.name}」`;
        } else {
          const res = await projectsAPI.transferSeismicData(p.id, values.target_project_id);
          message = res.data.message;
        }
        patchItem(p.id, { status: 'success', message, error_code: null });
      } catch (error: any) {
        const parsed = parseApiError(error);
        patchItem(p.id, {
          status: 'failed',
          message: parsed.message,
          error_code: parsed.errorCode,
        });
      }
    }

    setPhase('done');
    onCompleted();
  };

  const handleCancelExecution = () => {
    cancelRef.current = true;
    setCancelled(true);
  };

  const retryOne = async (projectId: number) => {
    patchItem(projectId, { status: 'processing', message: '', error_code: null });
    const item = items.find((it) => it.project_id === projectId)!;
    const result = await runOne(item);
    patchItem(projectId, {
      status: result.success ? 'success' : 'failed',
      message: result.message,
      error_code: result.error_code ?? null,
    });
    onCompleted();
  };

  const retryAllFailed = async () => {
    const failedIds = items.filter((it) => it.status === 'failed').map((it) => it.project_id);
    cancelRef.current = false;
    setCancelled(false);
    setPhase('executing');
    for (const id of failedIds) {
      patchItem(id, { status: 'processing', message: '', error_code: null });
      const item = items.find((it) => it.project_id === id)!;
      const result = await runOne(item);
      patchItem(id, {
        status: result.success ? 'success' : 'failed',
        message: result.message,
        error_code: result.error_code ?? null,
      });
    }
    setPhase('done');
    onCompleted();
  };

  const handleClose = () => {
    if (phase === 'executing') {
      Modal.confirm({
        title: '批量处理尚未完成',
        content: '取消并关闭后，已经处理成功的项目不会回退，剩余未处理的项目将被跳过。确定关闭吗？',
        okText: '取消执行并关闭',
        cancelText: '继续等待',
        onOk: () => {
          handleCancelExecution();
          onClose();
        },
      });
      return;
    }
    onClose();
  };

  const statusIcon = (status: BatchItemStatus) => {
    switch (status) {
      case 'success':
        return <CheckCircleFilled style={{ color: '#52c41a' }} />;
      case 'failed':
        return <CloseCircleFilled style={{ color: '#ff4d4f' }} />;
      case 'processing':
        return <LoadingOutlined style={{ color: '#1677ff' }} />;
      case 'cancelled':
        return <MinusCircleFilled style={{ color: '#8c8c8c' }} />;
      default:
        return <MinusCircleFilled style={{ color: '#d9d9d9' }} />;
    }
  };

  return (
    <Modal
      title={title}
      open={open}
      onCancel={handleClose}
      width={680}
      maskClosable={false}
      footer={
        phase === 'setup'
          ? [
              <Button key="cancel" onClick={onClose}>
                取消
              </Button>,
              <Button key="submit" type="primary" onClick={handleSetupOk}>
                开始批量处理
              </Button>,
            ]
          : [
              phase === 'executing' ? (
                <Button key="stop" danger onClick={handleCancelExecution}>
                  停止后续处理（已处理的不回退）
                </Button>
              ) : (
                <Space key="done">
                  {failedCount > 0 && (
                    <Button onClick={retryAllFailed}>重试全部失败项（{failedCount}）</Button>
                  )}
                  <Button type="primary" onClick={onClose}>
                    完成
                  </Button>
                </Space>
              ),
            ]
      }
    >
      {phase === 'setup' && (
        <Form form={form} layout="vertical" initialValues={{ role: 'editor' }}>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message={`将对勾选的 ${selectedProjects.length} 个项目逐条独立执行，已成功的项目不会因为后续失败或中途取消而回退。`}
          />
          {action === 'assign_collaborator' ? (
            <>
              <Form.Item
                name="user_id"
                label="协作成员"
                rules={[{ required: true, message: '请选择要分配的成员' }]}
              >
                <Select
                  placeholder="选择成员"
                  loading={loadingUsers}
                  showSearch
                  optionFilterProp="label"
                  options={users
                    .filter((u) => u.id !== currentUserId)
                    .map((u) => ({
                      value: u.id,
                      label: `${u.full_name || u.username}（${u.username}）`,
                    }))}
                />
              </Form.Item>
              <Form.Item name="role" label="角色" rules={[{ required: true }]}>
                <Select options={ROLE_OPTIONS} />
              </Form.Item>
              <Text type="secondary">
                若成员已经在某个项目中，该项目会返回失败并说明原因，不影响其他项目，可在结果中单独重试。
              </Text>
            </>
          ) : (
            <>
              <Form.Item
                name="target_project_id"
                label="目标项目"
                rules={[{ required: true, message: '请选择数据体要转入的目标项目' }]}
              >
                <Select
                  placeholder="选择目标项目"
                  showSearch
                  optionFilterProp="label"
                  options={targetProjectOptions}
                />
              </Form.Item>
              <Text type="secondary">
                数据体（含切片与标注的归属）会转移到目标项目；井数据仍保留在原项目。目标项目需要有编辑权限，
                且目标项目下不能存在同名数据体，否则该条会失败并列出冲突名称，重命名后可单独重试。
              </Text>
            </>
          )}
        </Form>
      )}

      {phase !== 'setup' && (
        <>
          <Space style={{ marginBottom: 12 }}>
            <Tag color="green">成功 {successCount}</Tag>
            <Tag color="red">失败 {failedCount}</Tag>
            {cancelled && <Tag color="default">已取消</Tag>}
            {!cancelled && pendingCount > 0 && <Tag color="blue">待处理/处理中 {pendingCount}</Tag>}
          </Space>
          <Progress percent={percent} size="small" status={failedCount > 0 && percent === 100 ? 'exception' : 'active'} />
          <List
            size="small"
            style={{ marginTop: 12, maxHeight: 360, overflow: 'auto' }}
            bordered
            dataSource={items}
            renderItem={(item) => (
              <List.Item>
                <Space align="start" style={{ width: '100%' }}>
                  {statusIcon(item.status)}
                  <div style={{ flex: 1 }}>
                    <div>
                      <strong>{item.project_name}</strong>
                      <Text type="secondary" style={{ marginLeft: 8 }}>
                        #{item.project_id}
                      </Text>
                    </div>
                    {item.message && (
                      <div style={{ marginTop: 2 }}>
                        <Text type={item.status === 'failed' ? 'danger' : 'secondary'} style={{ fontSize: 12 }}>
                          {item.message}
                        </Text>
                      </div>
                    )}
                  </div>
                  {item.status === 'failed' && (
                    <Button size="small" type="link" onClick={() => retryOne(item.project_id)}>
                      重试此条
                    </Button>
                  )}
                </Space>
              </List.Item>
            )}
          />
        </>
      )}
    </Modal>
  );
};

export default BatchOperationModal;
