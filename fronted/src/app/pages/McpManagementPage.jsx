import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CloudServerOutlined,
  DeleteOutlined,
  PlusOutlined,
  ReloadOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import {
  App as AntApp,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'

import {
  loadMcpCatalog,
  refreshMcpCapabilities,
  registerMcpServer,
  removeMcpServer,
  updateMcpServer,
} from '../features/mcp/api.js'
import {
  mcpCatalogSummary,
  mcpStatusColor,
  normalizeMcpServerInput,
} from '../features/mcp/model.js'

const { Text, Title } = Typography

export function McpManagementPage() {
  const { message } = AntApp.useApp()
  const [form] = Form.useForm()
  const transport = Form.useWatch('transport', form)
  const [servers, setServers] = useState([])
  const [tools, setTools] = useState([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await loadMcpCatalog()
      setServers(data.mcpServers)
      setTools(data.tools)
    } catch (error) {
      message.error(`MCP 目录加载失败：${error.message}`)
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    refresh()
  }, [refresh])

  const summary = useMemo(() => mcpCatalogSummary(servers, tools), [servers, tools])

  async function handleRegister() {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await registerMcpServer(normalizeMcpServerInput(values))
      message.success('MCP Server 已注册')
      setModalOpen(false)
      form.resetFields()
      await refresh()
    } catch (error) {
      message.error(`注册失败：${error.message}`)
    } finally {
      setSaving(false)
    }
  }

  async function handleRefreshServer(serverId = null) {
    try {
      await refreshMcpCapabilities(serverId)
      message.success(serverId ? '能力目录已刷新' : '全部 MCP 能力已刷新')
      await refresh()
    } catch (error) {
      message.error(`刷新失败：${error.message}`)
    }
  }

  async function handleToggle(server, enabled) {
    try {
      await updateMcpServer(server.serverId, { enabled })
      await refresh()
    } catch (error) {
      message.error(`更新失败：${error.message}`)
    }
  }

  async function handleRemove(serverId) {
    try {
      await removeMcpServer(serverId)
      message.success('MCP Server 已移除')
      await refresh()
    } catch (error) {
      message.error(`移除失败：${error.message}`)
    }
  }

  const serverColumns = [
    { title: 'Server', dataIndex: 'name', ellipsis: true },
    { title: '传输', dataIndex: 'transport', width: 130 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (status) => <Tag color={mcpStatusColor(status)}>{status}</Tag>,
    },
    { title: '能力', width: 70, render: (_, server) => server.capabilities.length },
    {
      title: '启用',
      width: 66,
      render: (_, server) => (
        <Switch size="small" checked={server.enabled} onChange={(value) => handleToggle(server, value)} />
      ),
    },
    {
      title: '操作',
      width: 90,
      render: (_, server) => (
        <Space size={2}>
          <Tooltip title="刷新能力">
            <Button type="text" icon={<ReloadOutlined />} onClick={() => handleRefreshServer(server.serverId)} />
          </Tooltip>
          <Popconfirm title="移除这个 MCP Server？" onConfirm={() => handleRemove(server.serverId)}>
            <Tooltip title="移除">
              <Button type="text" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const toolColumns = [
    { title: '工具', dataIndex: 'name', ellipsis: true },
    { title: 'Tool ID', dataIndex: 'toolId', ellipsis: true },
    { title: '来源', dataIndex: 'origin', width: 90, render: (origin) => <Tag>{origin}</Tag> },
    { title: 'Server', dataIndex: 'serverId', width: 130, render: (value) => value || 'native' },
    { title: '说明', dataIndex: 'description', ellipsis: true },
  ]

  return (
    <div className="management-page mcp-page">
      <div className="page-toolbar">
        <div>
          <Text className="panel-kicker">UNIFIED TOOL GATEWAY</Text>
          <Title level={3}>MCP 与工具</Title>
        </div>
        <Space wrap>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              form.setFieldsValue({ transport: 'STDIO', enabled: true })
              setModalOpen(true)
            }}
          >
            注册 Server
          </Button>
          <Tooltip title="刷新全部能力">
            <Button icon={<ReloadOutlined />} aria-label="刷新全部 MCP" onClick={() => handleRefreshServer()} />
          </Tooltip>
        </Space>
      </div>

      <div className="summary-band">
        <div><span>Server</span><strong>{summary.servers}</strong></div>
        <div><span>已连接</span><strong>{summary.connected}</strong></div>
        <div><span>能力</span><strong>{summary.capabilities}</strong></div>
        <div><span>统一工具</span><strong>{summary.tools}</strong></div>
      </div>

      <div className="management-stack">
        <section className="app-panel">
          <div className="panel-heading">
            <div><Text className="panel-kicker">SERVERS</Text><Title level={4}>连接目录</Title></div>
            <CloudServerOutlined className="heading-icon" />
          </div>
          <Table
            rowKey="serverId"
            size="small"
            loading={loading}
            columns={serverColumns}
            dataSource={servers}
            pagination={false}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未配置 MCP Server" /> }}
          />
        </section>

        <section className="app-panel">
          <div className="panel-heading">
            <div><Text className="panel-kicker">TOOLS</Text><Title level={4}>统一工具目录</Title></div>
            <ToolOutlined className="heading-icon" />
          </div>
          <Table
            rowKey="toolId"
            size="small"
            loading={loading}
            columns={toolColumns}
            dataSource={tools}
            pagination={false}
          />
        </section>
      </div>

      <Modal
        title="注册 MCP Server"
        open={modalOpen}
        okText="注册"
        cancelText="取消"
        confirmLoading={saving}
        onOk={handleRegister}
        onCancel={() => setModalOpen(false)}
      >
        <Form form={form} layout="vertical" initialValues={{ transport: 'STDIO', enabled: true }}>
          <Form.Item name="serverId" label="Server ID" rules={[{ required: true }]}>
            <Input placeholder="local-security-tools" />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="Local Security Tools" />
          </Form.Item>
          <Form.Item name="transport" label="传输方式" rules={[{ required: true }]}>
            <Select options={[
              { value: 'STDIO', label: 'stdio' },
              { value: 'STREAMABLE_HTTP', label: 'Streamable HTTP' },
              { value: 'SSE', label: 'SSE' },
            ]} />
          </Form.Item>
          {transport === 'STDIO' ? (
            <>
              <Form.Item name="command" label="命令" rules={[{ required: true }]}>
                <Input placeholder="python" />
              </Form.Item>
              <Form.Item name="args" label="参数">
                <Input placeholder="-m my_mcp_server" />
              </Form.Item>
              <Form.Item name="cwd" label="工作目录"><Input /></Form.Item>
            </>
          ) : (
            <Form.Item name="url" label="URL" rules={[{ required: true, type: 'url' }]}>
              <Input placeholder="http://127.0.0.1:9000/mcp" />
            </Form.Item>
          )}
          <Form.Item name="enabled" label="立即连接" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
