import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CheckOutlined,
  CompressOutlined,
  FileAddOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  App as AntApp,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd'

import {
  compressContext,
  createTodo,
  listSkills,
  loadRunState,
  loadSkill,
  recordNote,
  registerSkill,
  updateTodo,
} from '../features/longTerm/api.js'

const { Text, Title } = Typography

export function LongTermStatePage() {
  const { message } = AntApp.useApp()
  const [skills, setSkills] = useState([])
  const [state, setState] = useState({ skillLoads: [], todos: [], notes: [], contextSnapshots: [] })
  const [runId, setRunId] = useState('')
  const [flowId, setFlowId] = useState('')
  const [skillOpen, setSkillOpen] = useState(false)
  const [todoOpen, setTodoOpen] = useState(false)
  const [noteOpen, setNoteOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [skillForm] = Form.useForm()
  const [todoForm] = Form.useForm()
  const [noteForm] = Form.useForm()

  const refreshSkills = useCallback(async () => {
    try { setSkills(await listSkills()) } catch (error) { message.error(`Skill 加载失败：${error.message}`) }
  }, [message])

  const refreshState = useCallback(async () => {
    if (!runId.trim()) return
    setBusy(true)
    try { setState(await loadRunState(runId.trim())) } catch (error) { message.error(`运行状态加载失败：${error.message}`) }
    finally { setBusy(false) }
  }, [message, runId])

  useEffect(() => { refreshSkills() }, [refreshSkills])

  const activeTodos = useMemo(
    () => state.todos.filter((item) => !['COMPLETED', 'CANCELLED'].includes(item.status)).length,
    [state.todos],
  )

  async function submitSkill() {
    const values = await skillForm.validateFields()
    setBusy(true)
    try {
      await registerSkill({ ...values, tags: values.tags ? values.tags.split(',').map((x) => x.trim()).filter(Boolean) : [] })
      setSkillOpen(false); skillForm.resetFields(); await refreshSkills(); message.success('Skill 已登记')
    } catch (error) { message.error(`登记失败：${error.message}`) } finally { setBusy(false) }
  }

  async function attachSkill(skillId) {
    if (!runId || !flowId) return message.warning('请先填写 Run ID 和 Flow ID')
    await loadSkill({ skillId, runId, flowId, reason: '操作员按需加载' })
    await refreshState(); message.success('Skill 已加载到运行上下文')
  }

  async function submitTodo() {
    const values = await todoForm.validateFields()
    await createTodo({ runId, flowId, ...values })
    setTodoOpen(false); todoForm.resetFields(); await refreshState()
  }

  async function submitNote() {
    const values = await noteForm.validateFields()
    await recordNote({ runId, flowId, ...values, evidenceIds: values.evidenceIds ? values.evidenceIds.split(',').map((x) => x.trim()).filter(Boolean) : [] })
    setNoteOpen(false); noteForm.resetFields(); await refreshState()
  }

  const skillColumns = [
    { title: 'Skill', dataIndex: 'name', render: (value, row) => <><strong>{value}</strong><br /><Text type="secondary">{row.skillId} · v{row.version}</Text></> },
    { title: '说明', dataIndex: 'description', ellipsis: true },
    { title: '标签', dataIndex: 'tags', render: (tags) => tags.map((tag) => <Tag key={tag}>{tag}</Tag>) },
    { title: '', width: 52, render: (_, row) => <Tooltip title="加载到当前运行"><Button type="text" icon={<PlusOutlined />} onClick={() => attachSkill(row.skillId)} /></Tooltip> },
  ]
  const todoColumns = [
    { title: '任务', dataIndex: 'title' },
    { title: '状态', dataIndex: 'status', width: 110, render: (value) => <Tag>{value}</Tag> },
    { title: '优先级', dataIndex: 'priority', width: 90 },
    { title: '证据', dataIndex: 'evidenceIds', render: (value) => value.join(', ') || '-' },
    { title: '', width: 52, render: (_, row) => row.status === 'COMPLETED' ? null : <Tooltip title="完成"><Button type="text" icon={<CheckOutlined />} onClick={async () => { await updateTodo(row.todoId, { status: 'COMPLETED' }); await refreshState() }} /></Tooltip> },
  ]
  const noteColumns = [
    { title: '类型', dataIndex: 'kind', width: 110, render: (value) => <Tag>{value}</Tag> },
    { title: '内容', dataIndex: 'content' },
    { title: 'Evidence', dataIndex: 'evidenceIds', render: (value) => value.join(', ') || '-' },
  ]
  const snapshotColumns = [
    { title: '序号范围', render: (_, row) => `${row.sourceFromSequence} → ${row.sourceToSequence}` },
    { title: 'Token 估算', render: (_, row) => `${row.estimatedTokensBefore} → ${row.estimatedTokensAfter}` },
    { title: '摘要', dataIndex: 'narrativeSummary' },
    { title: '时间', dataIndex: 'createdAt', width: 180, render: (value) => new Date(value).toLocaleString('zh-CN') },
  ]

  return <div className="management-page long-term-page">
    <div className="page-toolbar">
      <div><Text className="panel-kicker">DURABLE AGENT STATE</Text><Title level={3}>长期任务状态</Title></div>
      <Space wrap><Input placeholder="Run ID" value={runId} onChange={(e) => setRunId(e.target.value)} /><Input placeholder="Flow ID" value={flowId} onChange={(e) => setFlowId(e.target.value)} /><Tooltip title="读取运行状态"><Button icon={<ReloadOutlined />} loading={busy} onClick={refreshState} /></Tooltip></Space>
    </div>
    <div className="summary-band"><div><span>Skill</span><strong>{skills.length}</strong></div><div><span>已加载</span><strong>{state.skillLoads.filter((x) => !x.unloadedAt).length}</strong></div><div><span>活动 Todo</span><strong>{activeTodos}</strong></div><div><span>上下文快照</span><strong>{state.contextSnapshots.length}</strong></div></div>
    <section className="app-panel long-term-panel">
      <Tabs items={[
        { key: 'skills', label: 'Skill', children: <><div className="inline-actions"><Button type="primary" icon={<PlusOutlined />} onClick={() => setSkillOpen(true)}>登记 Skill</Button></div><Table rowKey="skillId" size="small" columns={skillColumns} dataSource={skills} pagination={false} locale={{ emptyText: <Empty description="暂无 Skill，可随时登记" /> }} /></> },
        { key: 'todos', label: 'Todo', children: <><div className="inline-actions"><Button icon={<PlusOutlined />} disabled={!runId || !flowId} onClick={() => setTodoOpen(true)}>新建 Todo</Button></div><Table rowKey="todoId" size="small" columns={todoColumns} dataSource={state.todos} pagination={false} /></> },
        { key: 'notes', label: 'Notes', children: <><div className="inline-actions"><Button icon={<FileAddOutlined />} disabled={!runId || !flowId} onClick={() => setNoteOpen(true)}>记录 Note</Button></div><Table rowKey="noteId" size="small" columns={noteColumns} dataSource={state.notes} pagination={false} /></> },
        { key: 'context', label: '上下文压缩', children: <><div className="inline-actions"><Button icon={<CompressOutlined />} disabled={!runId || !flowId} onClick={async () => { await compressContext(runId, flowId); await refreshState() }}>生成快照</Button></div><Table rowKey="snapshotId" size="small" columns={snapshotColumns} dataSource={state.contextSnapshots} pagination={false} /></> },
      ]} />
    </section>
    <Modal title="登记 Skill" open={skillOpen} onOk={submitSkill} confirmLoading={busy} onCancel={() => setSkillOpen(false)}><Form form={skillForm} layout="vertical"><Form.Item name="skillId" label="Skill ID" rules={[{ required: true }]}><Input placeholder="web.audit" /></Form.Item><Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="description" label="说明"><Input /></Form.Item><Form.Item name="version" label="版本" initialValue="1.0"><Input /></Form.Item><Form.Item name="tags" label="标签"><Input placeholder="web, audit" /></Form.Item><Form.Item name="content" label="Skill 内容" rules={[{ required: true }]}><Input.TextArea autoSize={{ minRows: 8, maxRows: 16 }} /></Form.Item></Form></Modal>
    <Modal title="新建 Todo" open={todoOpen} onOk={submitTodo} onCancel={() => setTodoOpen(false)}><Form form={todoForm} layout="vertical"><Form.Item name="title" label="任务" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="description" label="说明"><Input.TextArea /></Form.Item><Form.Item name="priority" label="优先级" initialValue="NORMAL"><Select options={['LOW', 'NORMAL', 'HIGH', 'CRITICAL'].map((value) => ({ value, label: value }))} /></Form.Item></Form></Modal>
    <Modal title="记录 Note" open={noteOpen} onOk={submitNote} onCancel={() => setNoteOpen(false)}><Form form={noteForm} layout="vertical"><Form.Item name="kind" label="类型" initialValue="FACT"><Select options={['FACT', 'HYPOTHESIS', 'CONSTRAINT', 'DECISION', 'OBSERVATION', 'ERROR'].map((value) => ({ value, label: value }))} /></Form.Item><Form.Item name="content" label="内容" rules={[{ required: true }]}><Input.TextArea autoSize={{ minRows: 4, maxRows: 10 }} /></Form.Item><Form.Item name="evidenceIds" label="Evidence ID"><Input placeholder="逗号分隔" /></Form.Item></Form></Modal>
  </div>
}
