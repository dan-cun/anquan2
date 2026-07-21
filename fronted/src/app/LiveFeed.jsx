import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiOutlined,
  AuditOutlined,
  BulbOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CodeOutlined,
  DatabaseOutlined,
  DownOutlined,
  ExclamationCircleOutlined,
  FileSearchOutlined,
  LoadingOutlined,
  MessageOutlined,
  RightOutlined,
  RobotOutlined,
  SearchOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import { Button, Empty, Input, Select, Switch, Tag, Tooltip, Typography } from 'antd'

import {
  filterLiveFeed,
  LIVE_FEED_STATUS_OPTIONS,
  liveFeedCategoryOptions,
  projectLiveFeed,
} from './liveFeed.js'

const { Text } = Typography

const categoryIcons = {
  agent: <RobotOutlined />,
  tool: <ToolOutlined />,
  mcp: <ApiOutlined />,
  decision: <BulbOutlined />,
  verification: <AuditOutlined />,
  approval: <MessageOutlined />,
  llm: <CodeOutlined />,
  model: <CodeOutlined />,
  plan: <FileSearchOutlined />,
  evidence: <DatabaseOutlined />,
  finding: <ExclamationCircleOutlined />,
}

const statusMeta = {
  running: { label: '执行中', color: 'processing', icon: <LoadingOutlined spin /> },
  success: { label: '已完成', color: 'success', icon: <CheckCircleOutlined /> },
  waiting: { label: '等待中', color: 'warning', icon: <ClockCircleOutlined /> },
  error: { label: '异常', color: 'error', icon: <ExclamationCircleOutlined /> },
  neutral: { label: '信息', color: 'default', icon: null },
}

function formatTime(value) {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(parsed)
}

function hasContent(value) {
  if (value === undefined || value === null || value === '') return false
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value).length > 0
  return true
}

function renderValue(value) {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

function DetailBlock({ label, value, tone = '' }) {
  if (!hasContent(value)) return null
  return (
    <section className={`feed-detail-block ${tone ? `is-${tone}` : ''}`}>
      <span className="feed-detail-block__label">{label}</span>
      <pre>{renderValue(value)}</pre>
    </section>
  )
}

function DecisionBlock({ decision }) {
  if (!decision) return null
  const rationale = decision.rationale_summary || decision.rationaleSummary
  return (
    <section className="feed-decision">
      <div className="feed-decision__heading">
        <BulbOutlined />
        <strong>公开决策依据</strong>
        {decision.confidence !== undefined ? (
          <span>置信度 {Math.round(Number(decision.confidence) * 100)}%</span>
        ) : null}
      </div>
      {decision.goal ? <p><span>目标</span>{decision.goal}</p> : null}
      {decision.decision ? <p><span>选择</span>{decision.decision}</p> : null}
      {rationale ? <p><span>原因</span>{rationale}</p> : null}
      {decision.expected_outcome || decision.expectedOutcome ? (
        <p><span>预期</span>{decision.expected_outcome || decision.expectedOutcome}</p>
      ) : null}
      {decision.risk_summary || decision.riskSummary ? (
        <p><span>风险</span>{decision.risk_summary || decision.riskSummary}</p>
      ) : null}
      {decision.actual_outcome || decision.actualOutcome ? (
        <p><span>结果</span>{decision.actual_outcome || decision.actualOutcome}</p>
      ) : null}
      {hasContent(decision.alternatives) ? (
        <DetailBlock label="备选方案" value={decision.alternatives} />
      ) : null}
    </section>
  )
}

function FeedRow({ row, expanded, selected, onExpand, onSelect }) {
  const meta = statusMeta[row.status] || statusMeta.neutral
  const sequence = row.ledgerSequence || row.sequence
  return (
    <article
      className={`live-feed-row is-${row.status} ${selected ? 'is-selected' : ''}`}
      data-event-id={row.id}
    >
      <div className="live-feed-row__head">
        <button
          className="live-feed-row__select"
          type="button"
          onClick={() => (onSelect ? onSelect(row) : onExpand(row.id))}
          aria-label={`选择事件 ${sequence} ${row.eventType}`}
        >
          <span className={`live-feed-row__icon is-${row.category}`}>
            {categoryIcons[row.category] || <AuditOutlined />}
          </span>
          <span className="live-feed-row__copy">
            <span className="live-feed-row__title">
              <strong>{row.title}</strong>
              <code>{row.eventType}</code>
            </span>
            <span className="live-feed-row__summary">{row.summary}</span>
          </span>
        </button>
        <div className="live-feed-row__actions">
          <Tag color={meta.color} icon={meta.icon}>{meta.label}</Tag>
          <Tooltip title={expanded ? '收起详情' : '展开详情'}>
            <Button
              type="text"
              size="small"
              icon={expanded ? <DownOutlined /> : <RightOutlined />}
              onClick={() => onExpand(row.id)}
              aria-label={expanded ? `收起事件 ${sequence}` : `展开事件 ${sequence}`}
            />
          </Tooltip>
        </div>
      </div>

      <div className="live-feed-row__meta">
        <span>#{sequence}</span>
        {row.runtimeSequence && row.runtimeSequence !== sequence ? (
          <span>Runtime #{row.runtimeSequence}</span>
        ) : null}
        <span>{row.actor}</span>
        <span>{formatTime(row.timestamp)}</span>
        {row.toolId ? <span className="feed-meta-id">Tool {row.toolId}</span> : null}
        {row.agentId ? <span className="feed-meta-id">Agent {row.agentId}</span> : null}
        {row.verificationVerdict ? (
          <Tag className="feed-verdict" color={row.verificationVerdict === 'confirmed' ? 'success' : row.verificationVerdict === 'rejected' ? 'error' : 'warning'}>
            {row.verificationVerdict}
          </Tag>
        ) : null}
      </div>

      {expanded ? (
        <div className="live-feed-row__details">
          <DecisionBlock decision={row.decision} />
          <div className="feed-detail-grid">
            <DetailBlock label="参数" value={row.parameters} />
            <DetailBlock label="结果" value={row.result} />
            <DetailBlock label="错误" value={row.error} tone="error" />
            <DetailBlock label="事件上下文" value={{
              schemaVersion: row.schemaVersion,
              visibility: row.visibility,
              correlationId: row.correlationId,
              decisionId: row.decisionId,
            }} />
          </div>
          <DetailBlock label="原始 Payload" value={row.payload} />
        </div>
      ) : null}
    </article>
  )
}

export function LiveFeed({
  entries = [],
  selectedEventId = null,
  onSelect,
  emptyText = '暂无运行事件',
  className = '',
}) {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('all')
  const [status, setStatus] = useState('all')
  const [expandedIds, setExpandedIds] = useState(() => new Set())
  const [autoFollow, setAutoFollow] = useState(true)
  const scrollRef = useRef(null)
  const rows = useMemo(() => projectLiveFeed(entries), [entries])
  const filteredRows = useMemo(
    () => filterLiveFeed(rows, { query, category, status }),
    [category, query, rows, status],
  )
  const categoryOptions = useMemo(() => liveFeedCategoryOptions(rows), [rows])

  useEffect(() => {
    if (!autoFollow || !scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [autoFollow, filteredRows.length])

  function toggleExpanded(id) {
    setExpandedIds((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <section className={`live-feed ${className}`} aria-label="实时步骤流">
      <div className="live-feed-toolbar">
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索事件、Agent 或工具"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="搜索实时步骤"
        />
        <Select
          value={category}
          options={categoryOptions}
          onChange={setCategory}
          aria-label="筛选事件类别"
        />
        <Select
          value={status}
          options={LIVE_FEED_STATUS_OPTIONS}
          onChange={setStatus}
          aria-label="筛选事件状态"
        />
        <label className="live-feed-follow">
          <Switch size="small" checked={autoFollow} onChange={setAutoFollow} />
          <span>自动跟随</span>
        </label>
        <Text type="secondary" className="live-feed-count">
          {filteredRows.length} / {rows.length}
        </Text>
      </div>

      <div className="live-feed-scroll" ref={scrollRef}>
        {filteredRows.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={rows.length ? '没有匹配的事件' : emptyText} />
        ) : (
          <div className="live-feed-list">
            {filteredRows.map((row) => (
              <FeedRow
                key={row.id}
                row={row}
                expanded={expandedIds.has(row.id)}
                selected={selectedEventId === row.id}
                onExpand={toggleExpanded}
                onSelect={onSelect}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
