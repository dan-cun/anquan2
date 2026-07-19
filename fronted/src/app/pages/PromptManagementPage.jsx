import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CheckCircleOutlined,
  FileTextOutlined,
  ImportOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  App as AntApp,
  Button,
  Descriptions,
  Empty,
  Input,
  Modal,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'

import {
  createPromptVersion,
  enablePromptVersion,
  importPromptWorkbook,
  listPrompts,
} from '../features/prompts/api.js'
import {
  activePromptVersion,
  promptCatalogSummary,
  promptStatusColor,
} from '../features/prompts/model.js'

const { Text, Title } = Typography

export function PromptManagementPage() {
  const { message } = AntApp.useApp()
  const [prompts, setPrompts] = useState([])
  const [selectedKey, setSelectedKey] = useState('')
  const [loading, setLoading] = useState(true)
  const [editorOpen, setEditorOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listPrompts()
      setPrompts(data)
      setSelectedKey((current) => (
        data.some((prompt) => prompt.promptKey === current) ? current : data[0]?.promptKey || ''
      ))
    } catch (error) {
      message.error(`Prompt 目录加载失败：${error.message}`)
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    refresh()
  }, [refresh])

  const selected = prompts.find((prompt) => prompt.promptKey === selectedKey) || null
  const activeVersion = activePromptVersion(selected)
  const summary = useMemo(() => promptCatalogSummary(prompts), [prompts])

  async function handleImport() {
    setLoading(true)
    try {
      await importPromptWorkbook()
      message.success('完成版 Prompt 工作簿已重新导入并激活')
      await refresh()
    } catch (error) {
      message.error(`工作簿导入失败：${error.message}`)
      setLoading(false)
    }
  }

  async function handleCreateVersion() {
    if (!selected || !draft.trim()) return
    setSaving(true)
    try {
      await createPromptVersion(selected.promptKey, draft.trim())
      message.success('新版本已创建为草稿')
      setEditorOpen(false)
      await refresh()
    } catch (error) {
      message.error(`创建版本失败：${error.message}`)
    } finally {
      setSaving(false)
    }
  }

  async function handleActivate(versionId) {
    try {
      await enablePromptVersion(selected.promptKey, versionId)
      message.success('Prompt 版本已激活')
      await refresh()
    } catch (error) {
      message.error(`激活失败：${error.message}`)
    }
  }

  const promptColumns = [
    { title: 'Prompt', dataIndex: 'promptKey', ellipsis: true },
    { title: '模块', dataIndex: 'name', ellipsis: true },
    { title: '角色', dataIndex: 'messageRole', width: 92 },
    {
      title: '活动版本',
      width: 96,
      render: (_, prompt) => {
        const version = activePromptVersion(prompt)
        return version ? <Tag color="success">v{version.version}</Tag> : <Tag>无</Tag>
      },
    },
  ]

  const versionColumns = [
    { title: '版本', dataIndex: 'version', width: 72, render: (value) => `v${value}` },
    {
      title: '状态',
      dataIndex: 'status',
      width: 96,
      render: (status) => <Tag color={promptStatusColor(status)}>{status}</Tag>,
    },
    { title: '来源', dataIndex: 'source', ellipsis: true },
    { title: '校验值', dataIndex: 'checksum', ellipsis: true, width: 150 },
    {
      title: '操作',
      width: 76,
      render: (_, version) => version.status === 'ACTIVE' ? null : (
        <Tooltip title="激活版本">
          <Button
            type="text"
            icon={<CheckCircleOutlined />}
            aria-label={`激活 v${version.version}`}
            onClick={() => handleActivate(version.versionId)}
          />
        </Tooltip>
      ),
    },
  ]

  return (
    <div className="management-page prompt-page">
      <div className="page-toolbar">
        <div>
          <Text className="panel-kicker">VERSIONED REGISTRY</Text>
          <Title level={3}>Prompt 目录</Title>
        </div>
        <Space wrap>
          <Tooltip title="重新导入完成版工作簿">
            <Button icon={<ImportOutlined />} onClick={handleImport}>导入工作簿</Button>
          </Tooltip>
          <Tooltip title="刷新目录">
            <Button icon={<ReloadOutlined />} aria-label="刷新 Prompt" onClick={refresh} />
          </Tooltip>
        </Space>
      </div>

      <div className="summary-band">
        <div><span>Prompt</span><strong>{summary.total}</strong></div>
        <div><span>活动版本</span><strong>{summary.active}</strong></div>
        <div><span>Agent Prompt</span><strong>{summary.agent}</strong></div>
        <div><span>工作簿来源</span><strong>{summary.workbook}</strong></div>
      </div>

      <div className="management-grid">
        <section className="catalog-panel app-panel">
          <div className="panel-heading">
            <div><Text className="panel-kicker">CATALOG</Text><Title level={4}>模板列表</Title></div>
            <FileTextOutlined className="heading-icon" />
          </div>
          <div className="management-table-scroll">
            <Table
              rowKey="promptKey"
              size="small"
              loading={loading}
              columns={promptColumns}
              dataSource={prompts}
              pagination={false}
              onRow={(prompt) => ({ onClick: () => setSelectedKey(prompt.promptKey) })}
              rowClassName={(prompt) => prompt.promptKey === selectedKey ? 'is-selected' : ''}
            />
          </div>
        </section>

        <section className="prompt-detail app-panel">
          <div className="panel-heading">
            <div><Text className="panel-kicker">ACTIVE TEMPLATE</Text><Title level={4}>{selected?.name || 'Prompt 详情'}</Title></div>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              disabled={!selected}
              onClick={() => {
                setDraft(activeVersion?.content || '')
                setEditorOpen(true)
              }}
            >
              新建版本
            </Button>
          </div>
          {loading ? <div className="center-state"><Spin /></div> : !selected ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无 Prompt" />
          ) : (
            <div className="prompt-detail-scroll">
              <Descriptions
                size="small"
                column={2}
                items={[
                  { key: 'key', label: 'Prompt 键', children: selected.promptKey },
                  { key: 'role', label: '消息角色', children: selected.messageRole },
                  { key: 'agent', label: 'Agent', children: selected.agentRole || '-' },
                  { key: 'source', label: '源文件', children: selected.sourcePath || '-' },
                  { key: 'variables', label: '变量', span: 2, children: selected.variables.join(', ') || '-' },
                ]}
              />
              <div className="template-preview">
                <Text type="secondary">活动内容</Text>
                <Input.TextArea readOnly value={activeVersion?.content || ''} autoSize={{ minRows: 9, maxRows: 18 }} />
              </div>
              <Table
                rowKey="versionId"
                size="small"
                columns={versionColumns}
                dataSource={[...(selected.versions || [])].reverse()}
                pagination={false}
              />
            </div>
          )}
        </section>
      </div>

      <Modal
        title={`新建版本 · ${selected?.promptKey || ''}`}
        open={editorOpen}
        width="min(900px, 92vw)"
        okText="创建草稿"
        cancelText="取消"
        confirmLoading={saving}
        onOk={handleCreateVersion}
        onCancel={() => setEditorOpen(false)}
      >
        <Input.TextArea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          autoSize={{ minRows: 16, maxRows: 24 }}
          aria-label="Prompt 内容"
        />
      </Modal>
    </div>
  )
}
