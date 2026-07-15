import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiOutlined,
  AuditOutlined,
  CheckCircleOutlined,
  CloudServerOutlined,
  DownloadOutlined,
  ExclamationCircleOutlined,
  MessageOutlined,
  PlusOutlined,
  ReloadOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
  StopOutlined,
} from '@ant-design/icons'
import {
  App as AntApp,
  Button,
  Descriptions,
  Empty,
  Input,
  Layout,
  Menu,
  Modal,
  Select,
  Space,
  Spin,
  Steps,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd'
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  API_BASE_URL,
  WS_BASE_URL,
  createFlow,
  getInfo,
  listFlows,
  listLedgerAnchors,
  listLedgerEntries,
  verifyLedger,
} from './api.js'
import { ControlStarfield } from './ControlStarfield.jsx'
import { ModelUsagePage } from './pages/ModelUsagePage.jsx'
import {
  buildFlowWebSocketUrl,
  EventCursor,
  ledgerEntryToSocketEvent,
  unresolvedApprovalPayloads,
} from './transport.js'

const { Header, Sider, Content } = Layout
const { Text, Title } = Typography

const navigationItems = [
  { key: 'workbench', icon: <MessageOutlined />, label: '对话工作台' },
  { key: 'audit', icon: <AuditOutlined />, label: '审计回放' },
  { key: 'models', icon: <ApiOutlined />, label: '模型与额度' },
  { key: 'entry', icon: <RobotOutlined />, label: '视觉入口' },
]

const flowStepItems = [
  { title: '等待输入', description: 'CREATED' },
  { title: '执行中', description: 'RUNNING' },
  { title: '等待确认', description: 'WAITING' },
  { title: '完成', description: 'FINISHED' },
]

function makeRequestId() {
  return window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
}

function formatTime(value) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value))
}

function eventTitle(type) {
  const labels = {
    'client.user_message': '用户输入',
    'server.connected': '连接建立',
    'server.status': '运行状态',
    'server.ledger_entry': '账本记录',
    'server.interrupt': '人工确认',
    'server.done': '流程完成',
    'server.error': '运行错误',
    'server.pong': '心跳响应',
  }
  return labels[type] || type
}

function ledgerColor(eventType) {
  if (eventType.startsWith('interrupt.')) return 'orange'
  if (eventType.startsWith('input.')) return 'blue'
  if (eventType.startsWith('flow.')) return 'green'
  if (eventType.includes('error')) return 'red'
  return 'gray'
}

function statusTag(status) {
  const map = {
    created: ['default', 'CREATED'],
    running: ['processing', 'RUNNING'],
    waiting: ['warning', 'WAITING'],
    finished: ['success', 'FINISHED'],
    failed: ['error', 'FAILED'],
  }
  const [color, label] = map[status] || ['default', status || 'UNKNOWN']
  return <Tag color={color}>{label}</Tag>
}

function connectionTag(status) {
  const map = {
    idle: ['default', '未连接'],
    connecting: ['processing', '连接中'],
    connected: ['success', '已连接'],
    disconnected: ['warning', '已断开'],
    error: ['error', '连接异常'],
  }
  const [color, label] = map[status] || map.idle
  return <Tag color={color}>{label}</Tag>
}

function WorkbenchPage() {
  const navigate = useNavigate()
  const [modal, contextHolder] = Modal.useModal()
  const [flows, setFlows] = useState([])
  const [activeFlow, setActiveFlow] = useState(null)
  const [events, setEvents] = useState([])
  const [ledgerEntries, setLedgerEntries] = useState([])
  const [draft, setDraft] = useState('')
  const [connectionStatus, setConnectionStatus] = useState('idle')
  const [isSending, setIsSending] = useState(false)
  const [lastStage, setLastStage] = useState('等待输入')

  const socketRef = useRef(null)
  const pendingMessagesRef = useRef([])
  const eventCursorRef = useRef(new EventCursor())
  const activeFlowIdRef = useRef(null)
  const handledApprovalIdsRef = useRef(new Set())

  const queueOrSend = useCallback((envelope) => {
    const socket = socketRef.current
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(envelope))
      return
    }
    pendingMessagesRef.current.push(envelope)
  }, [])

  const sendApproval = useCallback(
    (approvalId, approved) => {
      queueOrSend({
        type: 'client.approval_response',
        flow_id: activeFlowIdRef.current,
        request_id: makeRequestId(),
        payload: {
          approval_id: approvalId,
          approved,
          reason: approved ? 'operator approved in workbench' : 'operator denied in workbench',
        },
      })
    },
    [queueOrSend],
  )

  const appendEvent = useCallback((event, fallbackRunId) => {
    if (!eventCursorRef.current.accept(event, fallbackRunId)) return false
    setEvents((current) => [...current, event].slice(-200))
    const ledgerEntry = event.payload?.entry || event.payload?.ledger_entry
    if (ledgerEntry) {
      setLedgerEntries((current) => [...current, ledgerEntry])
    }
    if (event.type === 'server.status') {
      setLastStage(event.payload?.message || event.payload?.stage || '执行中')
    }
    if (event.type === 'server.done') {
      setLastStage('流程完成')
    }
    return true
  }, [])

  const refreshFlows = useCallback(async () => {
    const data = await listFlows()
    setFlows(data)
    return data
  }, [])

  useEffect(() => {
    refreshFlows().catch((error) => message.error(`流程列表加载失败：${error.message}`))
  }, [refreshFlows])

  const openApprovalModal = useCallback(
    (event) => {
      const approvalId = event.payload?.approval_id
      if (!approvalId || handledApprovalIdsRef.current.has(approvalId)) return
      handledApprovalIdsRef.current.add(approvalId)

      modal.confirm({
        title: event.payload?.title || '需要人工确认',
        icon: <ExclamationCircleOutlined />,
        content: (
          <div className="approval-content">
            <Text>{event.payload?.message || '后端请求人工审批后继续执行。'}</Text>
            <Text type="secondary">审批编号：{approvalId}</Text>
          </div>
        ),
        okText: '批准继续',
        cancelText: '拒绝',
        onOk: () => sendApproval(approvalId, true),
        onCancel: () => sendApproval(approvalId, false),
      })
    },
    [modal, sendApproval],
  )

  const handleSocketEvent = useCallback(
    (event, fallbackRunId, { openApprovals = true } = {}) => {
      if (!appendEvent(event, fallbackRunId)) return
      if (event.type === 'server.connected') setConnectionStatus('connected')
      const ledgerEntry = event.payload?.entry || event.payload?.ledger_entry
      if (openApprovals && event.type === 'server.interrupt') {
        openApprovalModal(event)
      } else if (openApprovals && ledgerEntry?.event_type?.startsWith('interrupt.')) {
        openApprovalModal({ ...event, payload: ledgerEntry.payload })
      }
      if (event.type === 'server.error') message.error(event.payload?.message || '后端返回错误')
    },
    [appendEvent, openApprovalModal],
  )

  useEffect(() => {
    if (!activeFlow?.id) return undefined

    const flowId = activeFlow.id
    let disposed = false
    let reconnectTimer = null
    let reconnectAttempt = 0

    activeFlowIdRef.current = flowId
    eventCursorRef.current.resetRun(flowId)
    setEvents([])
    setLedgerEntries([])
    setConnectionStatus('connecting')
    handledApprovalIdsRef.current = new Set()

    const replayMissingLedgerEntries = async () => {
      const afterSequence = eventCursorRef.current.afterSequence(flowId)
      const entries = await listLedgerEntries(flowId, { afterSequence })
      if (disposed) return
      entries.forEach((entry) => {
        handleSocketEvent(ledgerEntryToSocketEvent(entry), flowId, { openApprovals: false })
      })

      unresolvedApprovalPayloads(entries).forEach((payload) => {
        openApprovalModal({
          type: 'server.interrupt',
          flow_id: flowId,
          payload,
        })
      })
    }

    const connect = () => {
      if (disposed) return
      setConnectionStatus('connecting')
      const afterSequence = eventCursorRef.current.afterSequence(flowId)
      const socket = new WebSocket(buildFlowWebSocketUrl(WS_BASE_URL, flowId, afterSequence))
      socketRef.current = socket

      socket.addEventListener('open', () => {
        if (disposed || socketRef.current !== socket) return
        reconnectAttempt = 0
        setConnectionStatus('connected')

        const queued = pendingMessagesRef.current
        pendingMessagesRef.current = queued.filter((item) => item.flow_id !== flowId)
        queued
          .filter((item) => item.flow_id === flowId)
          .forEach((item) => socket.send(JSON.stringify(item)))

        replayMissingLedgerEntries().catch((error) => {
          message.error(`断线事件补齐失败：${error.message}`)
        })
      })

      socket.addEventListener('message', (raw) => {
        try {
          handleSocketEvent(JSON.parse(raw.data), flowId)
        } catch {
          message.error('无法解析后端流式事件')
        }
      })

      socket.addEventListener('close', () => {
        if (disposed || socketRef.current !== socket) return
        setConnectionStatus('disconnected')
        const delay = Math.min(1000 * 2 ** reconnectAttempt, 10000)
        reconnectAttempt += 1
        reconnectTimer = window.setTimeout(connect, delay)
      })

      socket.addEventListener('error', () => {
        if (!disposed && socketRef.current === socket) setConnectionStatus('error')
      })
    }

    connect()

    return () => {
      disposed = true
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
      if (activeFlowIdRef.current === flowId) activeFlowIdRef.current = null
      const socket = socketRef.current
      if (socket) {
        socketRef.current = null
        socket.close()
      }
    }
  }, [activeFlow?.id, handleSocketEvent, openApprovalModal])

  async function handleCreateFlow() {
    const flow = await createFlow({ title: '新建安全分析流程' })
    setFlows((current) => [flow, ...current.filter((item) => item.id !== flow.id)])
    setActiveFlow(flow)
    setLastStage('等待输入')
  }

  async function handleSend() {
    const content = draft.trim()
    if (!content || isSending) return
    setIsSending(true)

    try {
      let flow = activeFlow
      if (!flow) {
        flow = await createFlow({
          title: content.slice(0, 48),
          initial_input: content,
        })
        setFlows((current) => [flow, ...current.filter((item) => item.id !== flow.id)])
        setActiveFlow(flow)
      }

      const localEvent = {
        type: 'client.user_message',
        flow_id: flow.id,
        request_id: makeRequestId(),
        timestamp: new Date().toISOString(),
        payload: { content },
      }
      appendEvent(localEvent)
      setDraft('')
      setLastStage('提交任务')
      queueOrSend({
        type: 'client.user_message',
        flow_id: flow.id,
        request_id: makeRequestId(),
        payload: {
          content,
          metadata: {
            source: 'fronted.workbench',
            submitted_at: new Date().toISOString(),
          },
        },
      })
    } catch (error) {
      message.error(`发送失败：${error.message}`)
    } finally {
      setIsSending(false)
    }
  }

  const currentStep = useMemo(() => {
    if (!activeFlow) return 0
    if (activeFlow.status === 'waiting') return 2
    if (activeFlow.status === 'finished') return 3
    if (events.some((event) => event.type === 'server.interrupt')) return 2
    if (events.some((event) => event.type === 'server.done')) return 3
    if (events.some((event) => event.type === 'server.status')) return 1
    return 0
  }, [activeFlow, events])

  return (
    <div className="workbench-grid">
      {contextHolder}
      <aside className="session-panel app-panel">
        <div className="panel-heading">
          <div>
            <Text className="panel-kicker">Flows</Text>
            <Title level={4}>会话列表</Title>
          </div>
          <Button type="text" icon={<ReloadOutlined />} aria-label="刷新流程" onClick={refreshFlows} />
        </div>
        <Button type="primary" icon={<PlusOutlined />} block onClick={handleCreateFlow}>
          新建流程
        </Button>
        <div className="session-list">
          {flows.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无流程" />
          ) : (
            flows.map((flow) => (
              <button
                className={`session-item ${activeFlow?.id === flow.id ? 'is-active' : ''}`}
                key={flow.id}
                type="button"
                onClick={() => setActiveFlow(flow)}
              >
                <span>{flow.title}</span>
                {statusTag(flow.status)}
              </button>
            ))
          )}
        </div>
      </aside>

      <section className="conversation-panel app-panel">
        <div className="panel-heading conversation-heading">
          <div>
            <Text className="panel-kicker">Current Flow</Text>
            <Title level={4}>{activeFlow?.title || '未选择流程'}</Title>
          </div>
          <Space>
            {connectionTag(connectionStatus)}
            {activeFlow?.id ? (
              <Button size="small" onClick={() => navigate(`/audit/${activeFlow.id}`)}>
                查看审计
              </Button>
            ) : null}
          </Space>
        </div>
        <div className="message-viewport">
          {events.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="输入任务后开始接收后端流式输出" />
          ) : (
            <div className="event-stream">
              {events.map((event) => (
                <div
                  className={`event-card ${event.type === 'client.user_message' ? 'is-user' : ''}`}
                  key={event.request_id}
                >
                  <div className="event-card__meta">
                    <Tag>{eventTitle(event.type)}</Tag>
                    <Text type="secondary">{formatTime(event.timestamp)}</Text>
                  </div>
                  <div className="event-card__body">
                    {event.payload?.content ||
                      event.payload?.message ||
                      event.payload?.result ||
                      event.payload?.stage ||
                      event.payload?.entry?.event_type ||
                      JSON.stringify(event.payload)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="composer">
          <Input.TextArea
            autoSize={{ minRows: 2, maxRows: 6 }}
            placeholder="输入安全分析任务；包含 confirm、approval 或 人工确认 可触发审批弹窗"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onPressEnter={(event) => {
              if (!event.shiftKey) {
                event.preventDefault()
                handleSend()
              }
            }}
            aria-label="任务内容"
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={isSending}
            onClick={handleSend}
            aria-label="发送任务"
          />
        </div>
      </section>

      <aside className="inspector-panel app-panel">
        <div className="panel-heading">
          <div>
            <Text className="panel-kicker">Runtime</Text>
            <Title level={4}>执行检查器</Title>
          </div>
          <CloudServerOutlined className="heading-icon" />
        </div>
        <Steps orientation="vertical" size="small" current={currentStep} items={flowStepItems} />
        <Descriptions
          className="status-descriptions"
          size="small"
          column={1}
          items={[
            { key: 'socket', label: 'WebSocket', children: connectionTag(connectionStatus) },
            { key: 'stage', label: '当前阶段', children: lastStage },
            { key: 'ledger', label: '账本事件', children: ledgerEntries.length },
            {
              key: 'flow',
              label: 'Flow ID',
              children: activeFlow?.id || '-',
            },
          ]}
        />
      </aside>
    </div>
  )
}

function AuditPage() {
  const { flowId } = useParams()
  const navigate = useNavigate()
  const [flows, setFlows] = useState([])
  const [selectedFlowId, setSelectedFlowId] = useState(flowId || '')
  const [entries, setEntries] = useState([])
  const [anchors, setAnchors] = useState([])
  const [verifyResult, setVerifyResult] = useState(null)
  const [selectedEntry, setSelectedEntry] = useState(null)
  const [manualFlowId, setManualFlowId] = useState(flowId || '')
  const [loading, setLoading] = useState(false)

  const loadFlows = useCallback(async () => {
    const data = await listFlows()
    setFlows(data)
    if (!selectedFlowId && data[0]?.id) {
      setSelectedFlowId(data[0].id)
      setManualFlowId(data[0].id)
      navigate(`/audit/${data[0].id}`, { replace: true })
    }
  }, [navigate, selectedFlowId])

  useEffect(() => {
    loadFlows().catch((error) => message.error(`流程列表加载失败：${error.message}`))
  }, [loadFlows])

  useEffect(() => {
    if (flowId) {
      setSelectedFlowId(flowId)
      setManualFlowId(flowId)
    }
  }, [flowId])

  const loadLedger = useCallback(async (id) => {
    if (!id) return
    setLoading(true)
    try {
      const [entryData, verifyData, anchorData] = await Promise.all([
        listLedgerEntries(id),
        verifyLedger(id),
        listLedgerAnchors(id),
      ])
      setEntries(entryData)
      setVerifyResult(verifyData)
      setAnchors(anchorData)
      setSelectedEntry(entryData[0] || null)
    } catch (error) {
      message.error(`账本加载失败：${error.message}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadLedger(selectedFlowId)
  }, [loadLedger, selectedFlowId])

  function handleSelectFlow(id) {
    setSelectedFlowId(id)
    setManualFlowId(id)
    navigate(`/audit/${id}`)
  }

  function handleManualLoad() {
    const id = manualFlowId.trim()
    if (!id) return
    handleSelectFlow(id)
  }

  const auditJsonl = useMemo(
    () => entries.map((entry) => JSON.stringify(entry)).join('\n') + (entries.length ? '\n' : ''),
    [entries],
  )
  const auditDownloadUrl = `data:application/x-ndjson;charset=utf-8,${encodeURIComponent(
    auditJsonl || '\n',
  )}`

  const timelineItems = entries.map((entry) => ({
    color: ledgerColor(entry.event_type),
    children: (
      <button
        className={`timeline-entry ${selectedEntry?.seq === entry.seq ? 'is-active' : ''}`}
        type="button"
        onClick={() => setSelectedEntry(entry)}
      >
        <span className="timeline-entry__title">
          #{entry.seq} {entry.event_type}
        </span>
        <span className="timeline-entry__meta">
          {entry.actor} · {formatTime(entry.created_at)}
        </span>
      </button>
    ),
  }))

  return (
    <div className="audit-page">
      <div className="page-toolbar">
        <div>
          <Text className="panel-kicker">Ledger Projection</Text>
          <Title level={3}>审计回放</Title>
        </div>
        <Button
          className="export-log-button"
          icon={<DownloadOutlined />}
          href={auditDownloadUrl}
          download={`${selectedFlowId || 'secmind'}-audit-log.jsonl`}
          disabled={entries.length === 0}
        >
          导出 JSONL
        </Button>
        <Space className="page-toolbar-actions" wrap>
          <Select
            className="flow-select"
            placeholder="选择流程"
            value={selectedFlowId || undefined}
            options={flows.map((flow) => ({
              value: flow.id,
              label: flow.title,
            }))}
            onChange={handleSelectFlow}
            aria-label="选择审计流程"
          />
          <Input.Search
            className="flow-id-search"
            placeholder="输入 flow_id"
            value={manualFlowId}
            onChange={(event) => setManualFlowId(event.target.value)}
            onSearch={handleManualLoad}
            enterButton="加载"
          />
          <Button icon={<ReloadOutlined />} onClick={() => loadLedger(selectedFlowId)}>
            刷新
          </Button>
          {verifyResult?.valid ? (
            <Tag icon={<CheckCircleOutlined />} color="success">
              哈希链有效
            </Tag>
          ) : (
            <Tag icon={<StopOutlined />} color={verifyResult ? 'error' : 'default'}>
              等待校验
            </Tag>
          )}
        </Space>
      </div>

      <div className="audit-grid">
        <section className="timeline-panel app-panel">
          <div className="panel-heading">
            <div>
              <Text className="panel-kicker">Events</Text>
              <Title level={4}>垂直时间轴</Title>
            </div>
            <Space>
              <Text type="secondary">{entries.length} 条记录</Text>
              <Text type="secondary">{anchors.length} 个锚点</Text>
            </Space>
          </div>
          <div className="timeline-scroll">
            {loading ? (
              <Spin />
            ) : timelineItems.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无账本数据" />
            ) : (
              <Timeline mode="left" items={timelineItems} />
            )}
          </div>
        </section>

        <aside className="detail-panel app-panel">
          <div className="panel-heading">
            <div>
              <Text className="panel-kicker">Detail</Text>
              <Title level={4}>步骤详情</Title>
            </div>
          </div>
          <Descriptions
            size="small"
            column={1}
            items={[
              { key: 'seq', label: '序号', children: selectedEntry?.seq || '-' },
              { key: 'type', label: '事件', children: selectedEntry?.event_type || '-' },
              { key: 'actor', label: '执行者', children: selectedEntry?.actor || '-' },
              { key: 'time', label: '时间', children: selectedEntry?.created_at || '-' },
              { key: 'hash', label: '哈希', children: selectedEntry?.hash || '-' },
              { key: 'prev', label: '前序哈希', children: selectedEntry?.prev_hash || '-' },
            ]}
          />
          <div className="payload-block">
            <Text type="secondary">Payload</Text>
            <pre>{JSON.stringify(selectedEntry?.payload || {}, null, 2)}</pre>
          </div>
          <div className="payload-block">
            <Text type="secondary">校验结果</Text>
            <pre>{JSON.stringify(verifyResult || {}, null, 2)}</pre>
          </div>
        </aside>
      </div>
    </div>
  )
}

function AppLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const [backendInfo, setBackendInfo] = useState(null)
  const selectedKey = location.pathname.startsWith('/audit')
    ? 'audit'
    : location.pathname.startsWith('/models')
      ? 'models'
      : 'workbench'

  useEffect(() => {
    getInfo()
      .then(setBackendInfo)
      .catch(() => setBackendInfo(null))
  }, [])

  const handleNavigation = ({ key }) => {
    if (key === 'entry') {
      window.location.assign('/')
      return
    }
    navigate(`/${key}`)
  }

  return (
    <Layout className="feature-shell">
      <ControlStarfield />
      <Sider width={208} breakpoint="lg" collapsedWidth={64} className="app-sider">
        <div className="product-mark">
          <SafetyCertificateOutlined />
          <span>SecMind</span>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={navigationItems}
          onClick={handleNavigation}
        />
      </Sider>
      <Layout>
        <Header className="app-header">
          <div className="header-title">
            {selectedKey === 'audit' ? (
              <AuditOutlined />
            ) : selectedKey === 'models' ? (
              <ApiOutlined />
            ) : (
              <MessageOutlined />
            )}
            <span>
              {selectedKey === 'audit'
                ? '审计回放'
                : selectedKey === 'models'
                  ? '模型选择与额度消耗'
                  : '对话工作台'}
            </span>
          </div>
          <Space>
            <Text type="secondary">{API_BASE_URL}</Text>
            {backendInfo ? (
              <Tag color={backendInfo.extensions?.llmProvider?.configured ? 'success' : 'default'}>
                {backendInfo.extensions?.llmProvider?.name || 'llm'}
              </Tag>
            ) : (
              <Tag color="warning">后端未确认</Tag>
            )}
          </Space>
        </Header>
        <Content className="app-content">
          <Routes>
            <Route path="/workbench" element={<WorkbenchPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/audit/:flowId" element={<AuditPage />} />
            <Route path="/models" element={<ModelUsagePage />} />
            <Route path="*" element={<Navigate to="/workbench" replace />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}

export function FeatureApp() {
  return (
    <AntApp>
      <AppLayout />
    </AntApp>
  )
}
