import React, { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiOutlined,
  AuditOutlined,
  CheckCircleOutlined,
  CloudServerOutlined,
  CodeOutlined,
  DatabaseOutlined,
  DeploymentUnitOutlined,
  DownloadOutlined,
  ExclamationCircleOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  HomeOutlined,
  MessageOutlined,
  PlusOutlined,
  ReloadOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
  StopOutlined,
  TeamOutlined,
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
  Tag,
  Timeline,
  Tooltip,
  Typography,
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
import {
  AGENT_EDGES,
  AGENT_ROLES,
  NODE_LABELS,
  collaborationState,
  nativeCollaborationState,
} from './agentNetwork.js'
import { loadNativeNetwork } from './graphql.js'
import { flowStatusFromEvent, toConversationItem } from './conversationEvents.js'
import {
  buildFlowWebSocketUrl,
  EventCursor,
  ledgerEntryToSocketEvent,
  unresolvedApprovalPayloads,
} from './transport.js'

const { Header, Sider, Content } = Layout
const { Text, Title } = Typography

const ModelUsagePage = lazy(() => import('./pages/ModelUsagePage.jsx').then((module) => ({
  default: module.ModelUsagePage,
})))
const McpManagementPage = lazy(() => import('./pages/McpManagementPage.jsx').then((module) => ({
  default: module.McpManagementPage,
})))
const PromptManagementPage = lazy(() => import('./pages/PromptManagementPage.jsx').then((module) => ({
  default: module.PromptManagementPage,
})))

const navigationItems = [
  { key: 'workbench', icon: <TeamOutlined />, label: '协作工作台' },
  { key: 'audit', icon: <AuditOutlined />, label: '审计回放' },
  { key: 'prompts', icon: <FileTextOutlined />, label: 'Prompt 目录' },
  { key: 'mcp', icon: <DeploymentUnitOutlined />, label: 'MCP 与工具' },
  { key: 'models', icon: <ApiOutlined />, label: '模型与用量' },
  { key: 'entry', icon: <HomeOutlined />, label: '视觉入口' },
]

const roleIcons = {
  orchestrator: <TeamOutlined />,
  planner: <FileSearchOutlined />,
  executor: <CodeOutlined />,
  reviewer: <SafetyCertificateOutlined />,
  reporter: <DatabaseOutlined />,
}

const networkPositions = {
  orchestrator: { x: 50, y: 13 },
  planner: { x: 22, y: 42 },
  executor: { x: 78, y: 42 },
  reviewer: { x: 70, y: 78 },
  reporter: { x: 30, y: 78 },
}

function networkPosition(index, total) {
  if (total > 5) {
    const columns = 3
    const rows = Math.ceil(total / columns)
    const column = index % columns
    const row = Math.floor(index / columns)
    return {
      x: ((column + 0.5) / columns) * 100,
      y: ((row + 0.5) / rows) * 100,
    }
  }
  const role = AGENT_ROLES[index]?.id
  if (role && networkPositions[role]) return networkPositions[role]
  const angle = -Math.PI / 2 + (index / Math.max(total, 1)) * Math.PI * 2
  return { x: 50 + Math.cos(angle) * 37, y: 50 + Math.sin(angle) * 37 }
}

function roleIcon(role) {
  return roleIcons[role] || <RobotOutlined />
}

const statusLabels = {
  created: ['default', '待运行'],
  running: ['processing', '运行中'],
  waiting: ['warning', '待审批'],
  finished: ['success', '已完成'],
  failed: ['error', '失败'],
}

const connectionLabels = {
  idle: ['default', '未连接'],
  connecting: ['processing', '连接中'],
  connected: ['success', '实时连接'],
  disconnected: ['warning', '重连中'],
  error: ['error', '连接异常'],
}

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

function compactId(value) {
  if (!value) return '-'
  return value.length > 14 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value
}

function StatusTag({ status }) {
  const [color, label] = statusLabels[status] || ['default', status || '未知']
  return <Tag color={color}>{label}</Tag>
}

function ConnectionTag({ status }) {
  const [color, label] = connectionLabels[status] || connectionLabels.idle
  return <Tag color={color}>{label}</Tag>
}

function agentStatusLabel(status) {
  return {
    idle: '待命',
    active: '处理中',
    completed: '已参与',
    waiting: '等待确认',
    failed: '异常',
  }[status] || status
}

function NetworkEdge({ from, to, activeRole, positions }) {
  const start = positions[from] || networkPositions[from] || { x: 50, y: 50 }
  const end = positions[to] || networkPositions[to] || { x: 50, y: 50 }
  const dx = end.x - start.x
  const dy = end.y - start.y
  const length = Math.sqrt(dx * dx + dy * dy)
  const angle = Math.atan2(dy, dx) * (180 / Math.PI)
  const active = activeRole === from || activeRole === to
  return (
    <span
      className={`network-edge ${active ? 'is-active' : ''}`}
      style={{
        left: `${start.x}%`,
        top: `${start.y}%`,
        width: `${length}%`,
        transform: `rotate(${angle}deg)`,
      }}
      aria-hidden="true"
    />
  )
}

function AgentNetwork({ state }) {
  const positions = Object.fromEntries(
    state.roles.map((role, index) => [role.id, networkPosition(index, state.roles.length)]),
  )
  const edges = state.edges || AGENT_EDGES.map(([from, to]) => ({ from, to }))
  return (
    <div className="agent-network" aria-label="智能体协作网络">
      {edges.map(({ from, to, id }) => (
        <NetworkEdge
          key={id || `${from}-${to}`}
          from={from}
          to={to}
          activeRole={state.activeRole}
          positions={positions}
        />
      ))}
      {state.roles.map((role) => {
        const position = positions[role.id]
        return (
          <Tooltip key={role.id} title={role.description} placement="top">
            <div
              className={`agent-node is-${role.status}`}
              style={{ left: `${position.x}%`, top: `${position.y}%` }}
            >
              <span className="agent-node__icon">{roleIcon(role.id)}</span>
              <span className="agent-node__name">{role.shortName}</span>
              <span className="agent-node__status">{agentStatusLabel(role.status)}</span>
            </div>
          </Tooltip>
        )
      })}
    </div>
  )
}

function WorkbenchPage() {
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const [modal, contextHolder] = Modal.useModal()
  const [flows, setFlows] = useState([])
  const [activeFlow, setActiveFlow] = useState(null)
  const [nativeNetwork, setNativeNetwork] = useState(null)
  const [events, setEvents] = useState([])
  const [ledgerEntries, setLedgerEntries] = useState([])
  const [draft, setDraft] = useState('')
  const [connectionStatus, setConnectionStatus] = useState('idle')
  const [isSending, setIsSending] = useState(false)
  const [lastStage, setLastStage] = useState('等待任务')

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

  const sendApproval = useCallback((approvalId, approved) => {
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
  }, [queueOrSend])

  const appendEvent = useCallback((event, fallbackRunId) => {
    if (!eventCursorRef.current.accept(event, fallbackRunId)) return false
    setEvents((current) => [...current, event].slice(-300))
    const ledgerEntry = event.payload?.entry || event.payload?.ledger_entry
    if (ledgerEntry) setLedgerEntries((current) => [...current, ledgerEntry].slice(-1000))
    if (event.type === 'server.status') {
      setLastStage(NODE_LABELS[event.payload?.node] || event.payload?.message || '正在执行')
    }
    if (event.type === 'server.interrupt') setLastStage('等待人工审批')
    if (event.type === 'server.done') setLastStage('运行已完成')
    return true
  }, [])

  const refreshFlows = useCallback(async () => {
    const data = await listFlows()
    setFlows(data)
    return data
  }, [])

  const updateLocalFlowStatus = useCallback((flowId, status) => {
    if (!flowId || !status) return
    setFlows((current) => current.map((flow) => (
      flow.id === flowId ? { ...flow, status } : flow
    )))
    setActiveFlow((current) => (
      current?.id === flowId ? { ...current, status } : current
    ))
  }, [])

  useEffect(() => {
    refreshFlows()
      .then((items) => {
        setActiveFlow((current) => current || items[0] || null)
      })
      .catch((error) => message.error(`流程列表加载失败：${error.message}`))
  }, [message, refreshFlows])

  useEffect(() => {
    if (!activeFlow?.id) {
      setNativeNetwork(null)
      return undefined
    }
    let disposed = false
    const refreshNativeNetwork = () => {
      loadNativeNetwork(activeFlow.id)
        .then((data) => {
          if (!disposed) setNativeNetwork(data)
        })
        .catch(() => {
          if (!disposed) setNativeNetwork(null)
        })
    }
    refreshNativeNetwork()
    const timer = window.setInterval(refreshNativeNetwork, 2000)
    return () => {
      disposed = true
      window.clearInterval(timer)
    }
  }, [activeFlow?.id])

  const openApprovalModal = useCallback((event) => {
    const approvalId = event.payload?.approval_id
    if (!approvalId || handledApprovalIdsRef.current.has(approvalId)) return
    handledApprovalIdsRef.current.add(approvalId)
    modal.confirm({
      title: event.payload?.title || '需要人工审批',
      icon: <ExclamationCircleOutlined />,
      content: (
        <div className="approval-content">
          <Text>{event.payload?.message || '后端请求操作员确认后继续执行。'}</Text>
          <Text type="secondary">审批编号：{approvalId}</Text>
        </div>
      ),
      okText: '批准并继续',
      cancelText: '拒绝',
      onOk: () => sendApproval(approvalId, true),
      onCancel: () => sendApproval(approvalId, false),
    })
  }, [modal, sendApproval])

  const handleSocketEvent = useCallback((event, fallbackRunId, { openApprovals = true } = {}) => {
    if (!appendEvent(event, fallbackRunId)) return
    if (event.type === 'server.connected') setConnectionStatus('connected')
    updateLocalFlowStatus(event.flow_id || fallbackRunId, flowStatusFromEvent(event))
    const ledgerEntry = event.payload?.entry || event.payload?.ledger_entry
    if (openApprovals && event.type === 'server.interrupt') {
      openApprovalModal(event)
    } else if (openApprovals && ledgerEntry?.event_type?.startsWith('interrupt.')) {
      openApprovalModal({ ...event, payload: ledgerEntry.payload })
    }
    if (event.type === 'server.error') {
      message.error(event.payload?.message || '后端返回运行错误')
    }
  }, [appendEvent, openApprovalModal, updateLocalFlowStatus])

  useEffect(() => {
    if (!activeFlow?.id) return undefined
    const flowId = activeFlow.id
    let disposed = false
    let reconnectTimer = null
    let heartbeatTimer = null
    let reconnectAttempt = 0

    activeFlowIdRef.current = flowId
    eventCursorRef.current.resetRun(flowId)
    setEvents([])
    setLedgerEntries([])
    setConnectionStatus('connecting')
    setLastStage('正在恢复运行上下文')
    handledApprovalIdsRef.current = new Set()

    const replayMissingLedgerEntries = async () => {
      const entries = await listLedgerEntries(flowId, {
        afterSequence: eventCursorRef.current.afterSequence(flowId),
      })
      if (disposed) return
      entries.forEach((entry) => {
        handleSocketEvent(ledgerEntryToSocketEvent(entry), flowId, { openApprovals: false })
      })
      unresolvedApprovalPayloads(entries).forEach((payload) => {
        openApprovalModal({ type: 'server.interrupt', flow_id: flowId, payload })
      })
      if (entries.length === 0) setLastStage('等待任务')
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
        if (heartbeatTimer) window.clearInterval(heartbeatTimer)
        heartbeatTimer = window.setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({
              type: 'client.ping',
              flow_id: flowId,
              request_id: makeRequestId(),
              payload: {},
            }))
          }
        }, 30000)
        const queued = pendingMessagesRef.current
        pendingMessagesRef.current = queued.filter((item) => item.flow_id !== flowId)
        queued.filter((item) => item.flow_id === flowId)
          .forEach((item) => socket.send(JSON.stringify(item)))
        replayMissingLedgerEntries().catch((error) => {
          message.error(`断线事件补齐失败：${error.message}`)
        })
      })

      socket.addEventListener('message', (raw) => {
        try {
          handleSocketEvent(JSON.parse(raw.data), flowId)
        } catch {
          message.error('无法解析后端实时事件')
        }
      })

      socket.addEventListener('close', () => {
        if (disposed || socketRef.current !== socket) return
        if (heartbeatTimer) window.clearInterval(heartbeatTimer)
        setConnectionStatus('disconnected')
        reconnectTimer = window.setTimeout(connect, Math.min(1000 * 2 ** reconnectAttempt, 10000))
        reconnectAttempt += 1
      })

      socket.addEventListener('error', () => {
        if (!disposed && socketRef.current === socket) setConnectionStatus('error')
      })
    }

    connect()
    return () => {
      disposed = true
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
      if (heartbeatTimer) window.clearInterval(heartbeatTimer)
      if (activeFlowIdRef.current === flowId) activeFlowIdRef.current = null
      const socket = socketRef.current
      if (socket) {
        socketRef.current = null
        socket.close()
      }
    }
  }, [activeFlow?.id, handleSocketEvent, openApprovalModal])

  async function handleCreateFlow() {
    try {
      const flow = await createFlow({ title: '新建安全分析流程' })
      setFlows((current) => [flow, ...current.filter((item) => item.id !== flow.id)])
      setActiveFlow(flow)
      setLastStage('等待任务')
    } catch (error) {
      message.error(`创建流程失败：${error.message}`)
    }
  }

  async function handleSend() {
    const content = draft.trim()
    if (!content || isSending) return
    setIsSending(true)
    try {
      let flow = activeFlow
      if (!flow) {
        flow = await createFlow({ title: content.slice(0, 48), initial_input: content })
        setFlows((current) => [flow, ...current.filter((item) => item.id !== flow.id)])
        setActiveFlow(flow)
      }
      appendEvent({
        type: 'client.user_message',
        flow_id: flow.id,
        request_id: makeRequestId(),
        timestamp: new Date().toISOString(),
        payload: { content },
      })
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

  const conversationItems = useMemo(() => events.map((event, index) => {
    const item = toConversationItem(event)
    return item ? {
      ...item,
      key: event.request_id || `${event.type}-${index}`,
      timestamp: event.timestamp,
    } : null
  }).filter(Boolean), [events])

  const networkState = useMemo(
    () => nativeCollaborationState(nativeNetwork) || collaborationState(events),
    [events, nativeNetwork],
  )
  const completedRoleCount = networkState.roles.filter((role) => role.completedCount > 0).length

  return (
    <div className="workbench-grid">
      {contextHolder}
      <aside className="session-panel app-panel">
        <div className="panel-heading">
          <div>
            <Text className="panel-kicker">RUNS</Text>
            <Title level={4}>任务流程</Title>
          </div>
          <Tooltip title="刷新流程">
            <Button type="text" icon={<ReloadOutlined />} aria-label="刷新流程" onClick={refreshFlows} />
          </Tooltip>
        </div>
        <Button type="primary" icon={<PlusOutlined />} block onClick={handleCreateFlow}>
          新建流程
        </Button>
        <div className="session-list">
          {flows.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无流程" />
          ) : flows.map((flow) => (
            <button
              className={`session-item ${activeFlow?.id === flow.id ? 'is-active' : ''}`}
              key={flow.id}
              type="button"
              onClick={() => setActiveFlow(flow)}
            >
              <span className="session-item__body">
                <strong>{flow.title}</strong>
                <small>{compactId(flow.id)}</small>
              </span>
              <StatusTag status={flow.status} />
            </button>
          ))}
        </div>
      </aside>

      <section className="conversation-panel app-panel">
        <div className="panel-heading conversation-heading">
          <div className="flow-heading-copy">
            <Text className="panel-kicker">ACTIVE FLOW</Text>
            <Title level={4}>{activeFlow?.title || '选择或创建流程'}</Title>
          </div>
          <Space size={6} wrap>
            <ConnectionTag status={connectionStatus} />
            {activeFlow ? <StatusTag status={activeFlow.status} /> : null}
            {activeFlow?.id ? (
              <Tooltip title="打开审计回放">
                <Button
                  type="text"
                  icon={<AuditOutlined />}
                  aria-label="打开审计回放"
                  onClick={() => navigate(`/audit/${activeFlow.id}`)}
                />
              </Tooltip>
            ) : null}
          </Space>
        </div>

        <div className="collaboration-strip">
          {networkState.roles.map((role, index) => (
            <React.Fragment key={role.id}>
              {index > 0 ? <span className="strip-arrow">›</span> : null}
              <span className={`strip-role is-${role.status}`}>
                {roleIcon(role.id)}
                {role.shortName}
              </span>
            </React.Fragment>
          ))}
        </div>

        <div className="message-viewport">
          {conversationItems.length === 0 ? (
            <div className="empty-workbench">
              <RobotOutlined />
              <Title level={4}>提交一个授权范围内的安全任务</Title>
              <Text type="secondary">运行进度、角色协作与证据事件会在此实时显示。</Text>
            </div>
          ) : (
            <div className="event-stream">
              {conversationItems.map((item) => (
                <article className={`event-card is-${item.kind}`} key={item.key}>
                  <div className="event-card__meta">
                    <span>{item.label}</span>
                    <Text type="secondary">{formatTime(item.timestamp)}</Text>
                  </div>
                  <div className="event-card__body">{item.body}</div>
                  {item.report?.limitations?.length ? (
                    <div className="event-card__limitations">
                      <strong>限制</strong>
                      <ul>
                        {item.report.limitations.map((limitation) => (
                          <li key={limitation}>{limitation}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          )}
        </div>

        <div className="composer">
          <Input.TextArea
            autoSize={{ minRows: 2, maxRows: 6 }}
            placeholder="描述安全分析目标、授权范围、约束和期望输出"
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
          <Tooltip title="发送任务">
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={isSending}
              onClick={handleSend}
              aria-label="发送任务"
            />
          </Tooltip>
        </div>
      </section>

      <aside className="inspector-panel app-panel">
        <div className="panel-heading">
          <div>
            <Text className="panel-kicker">COLLABORATION</Text>
            <Title level={4}>智能体网络</Title>
          </div>
          <TeamOutlined className="heading-icon" />
        </div>
        <AgentNetwork state={networkState} />
        <div className="runtime-summary">
          <div className="summary-metric">
            <span>当前节点</span>
            <strong>{NODE_LABELS[networkState.latestNode] || lastStage}</strong>
          </div>
          <div className="summary-metric-grid">
            <div><span>参与角色</span><strong>{completedRoleCount} / {networkState.roles.length}</strong></div>
            <div><span>账本事件</span><strong>{ledgerEntries.length}</strong></div>
          </div>
        </div>
        <div className="role-list">
          {networkState.roles.map((role) => (
            <div className={`role-row is-${role.status}`} key={role.id}>
              <span className="role-row__icon">{roleIcon(role.id)}</span>
              <span className="role-row__copy">
                <strong>{role.name}</strong>
                <small>{role.description}</small>
              </span>
              <span className="role-row__status">{agentStatusLabel(role.status)}</span>
            </div>
          ))}
        </div>
        <div className="runtime-footer">
          <CloudServerOutlined />
          <span title={activeFlow?.id}>{compactId(activeFlow?.id)}</span>
        </div>
      </aside>
    </div>
  )
}

function ledgerColor(eventType = '') {
  if (eventType.startsWith('interrupt.')) return 'orange'
  if (eventType.startsWith('input.')) return 'blue'
  if (eventType.startsWith('flow.')) return 'green'
  if (eventType.includes('failed') || eventType.includes('error')) return 'red'
  return 'gray'
}

function AuditPage() {
  const { message } = AntApp.useApp()
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

  const auditJsonl = useMemo(
    () => entries.map((entry) => JSON.stringify(entry)).join('\n') + (entries.length ? '\n' : ''),
    [entries],
  )
  const auditDownloadUrl = `data:application/x-ndjson;charset=utf-8,${encodeURIComponent(auditJsonl || '\n')}`

  const timelineItems = entries.map((entry) => ({
    color: ledgerColor(entry.event_type),
    children: (
      <button
        className={`timeline-entry ${selectedEntry?.seq === entry.seq ? 'is-active' : ''}`}
        type="button"
        onClick={() => setSelectedEntry(entry)}
      >
        <span className="timeline-entry__title">#{entry.seq} {entry.event_type}</span>
        <span className="timeline-entry__meta">{entry.actor} · {formatTime(entry.created_at)}</span>
      </button>
    ),
  }))

  return (
    <div className="audit-page">
      <div className="page-toolbar">
        <div>
          <Text className="panel-kicker">LEDGER PROJECTION</Text>
          <Title level={3}>审计回放</Title>
        </div>
        <Space className="page-toolbar-actions" wrap>
          <Select
            className="flow-select"
            placeholder="选择流程"
            value={selectedFlowId || undefined}
            options={flows.map((flow) => ({ value: flow.id, label: flow.title }))}
            onChange={handleSelectFlow}
            aria-label="选择审计流程"
          />
          <Input.Search
            className="flow-id-search"
            placeholder="输入 Flow ID"
            value={manualFlowId}
            onChange={(event) => setManualFlowId(event.target.value)}
            onSearch={() => manualFlowId.trim() && handleSelectFlow(manualFlowId.trim())}
            enterButton="加载"
          />
          <Tooltip title="刷新账本">
            <Button icon={<ReloadOutlined />} onClick={() => loadLedger(selectedFlowId)} aria-label="刷新账本" />
          </Tooltip>
          <Tooltip title="导出 JSONL">
            <Button
              icon={<DownloadOutlined />}
              href={auditDownloadUrl}
              download={`${selectedFlowId || 'secmind'}-audit-log.jsonl`}
              disabled={entries.length === 0}
              aria-label="导出 JSONL"
            />
          </Tooltip>
        </Space>
      </div>

      <div className="audit-status-band">
        {verifyResult?.valid ? (
          <Tag icon={<CheckCircleOutlined />} color="success">哈希链有效</Tag>
        ) : (
          <Tag icon={<StopOutlined />} color={verifyResult ? 'error' : 'default'}>等待校验</Tag>
        )}
        <Text type="secondary">{entries.length} 条记录 · {anchors.length} 个锚点</Text>
        <Text type="secondary">账本按序号回放，接收时间不参与排序</Text>
      </div>

      <div className="audit-grid">
        <section className="timeline-panel app-panel">
          <div className="panel-heading">
            <div>
              <Text className="panel-kicker">EVENTS</Text>
              <Title level={4}>事件时间线</Title>
            </div>
          </div>
          <div className="timeline-scroll">
            {loading ? <Spin /> : timelineItems.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无账本数据" />
            ) : <Timeline items={timelineItems} />}
          </div>
        </section>

        <aside className="detail-panel app-panel">
          <div className="panel-heading">
            <div>
              <Text className="panel-kicker">EVENT DETAIL</Text>
              <Title level={4}>事件详情</Title>
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
              { key: 'hash', label: '哈希', children: compactId(selectedEntry?.hash) },
              { key: 'prev', label: '前序哈希', children: compactId(selectedEntry?.prev_hash) },
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
    : location.pathname.startsWith('/prompts')
      ? 'prompts'
      : location.pathname.startsWith('/mcp')
        ? 'mcp'
        : location.pathname.startsWith('/models') ? 'models' : 'workbench'

  useEffect(() => {
    getInfo().then(setBackendInfo).catch(() => setBackendInfo(null))
  }, [])

  const pageTitle = {
    audit: ['审计回放', <AuditOutlined key="audit" />],
    prompts: ['Prompt 目录', <FileTextOutlined key="prompts" />],
    mcp: ['MCP 与工具', <DeploymentUnitOutlined key="mcp" />],
    models: ['模型与用量', <ApiOutlined key="models" />],
    workbench: ['智能体协作工作台', <TeamOutlined key="workbench" />],
  }[selectedKey]

  return (
    <Layout className="feature-shell">
      <Sider width={190} breakpoint="lg" collapsedWidth={60} className="app-sider">
        <div className="product-mark">
          <SafetyCertificateOutlined />
          <span>SECMIND</span>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={navigationItems}
          onClick={({ key }) => {
            if (key === 'entry') window.location.assign('/')
            else navigate(`/${key}`)
          }}
        />
        <div className="sider-version">AGENT RUNTIME</div>
      </Sider>
      <Layout>
        <Header className="app-header">
          <div className="header-title">{pageTitle[1]}<span>{pageTitle[0]}</span></div>
          <Space size={8}>
            <Text className="api-endpoint" type="secondary">{API_BASE_URL}</Text>
            <Tag color={backendInfo ? 'success' : 'warning'}>
              {backendInfo ? '后端在线' : '后端未确认'}
            </Tag>
            {backendInfo ? (
              <Tag color={backendInfo.extensions?.llmProvider?.configured ? 'processing' : 'default'}>
                {backendInfo.extensions?.llmProvider?.name || 'LLM 未配置'}
              </Tag>
            ) : null}
          </Space>
        </Header>
        <Content className="app-content">
          <Suspense fallback={<div className="center-state"><Spin /></div>}>
            <Routes>
              <Route path="/workbench" element={<WorkbenchPage />} />
              <Route path="/audit" element={<AuditPage />} />
              <Route path="/audit/:flowId" element={<AuditPage />} />
              <Route path="/prompts" element={<PromptManagementPage />} />
              <Route path="/mcp" element={<McpManagementPage />} />
              <Route path="/models" element={<ModelUsagePage />} />
              <Route path="*" element={<Navigate to="/workbench" replace />} />
            </Routes>
          </Suspense>
        </Content>
      </Layout>
    </Layout>
  )
}

export function FeatureApp() {
  return <AntApp><AppLayout /></AntApp>
}
