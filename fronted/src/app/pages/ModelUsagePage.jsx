import React, { useCallback, useEffect, useState } from 'react'
import {
  ApiOutlined,
  ExperimentOutlined,
  KeyOutlined,
  MessageOutlined,
  ReloadOutlined,
  SaveOutlined,
  WalletOutlined,
} from '@ant-design/icons'
import {
  App,
  Button,
  Empty,
  Form,
  Input,
  Progress,
  Select,
  Space,
  Spin,
  Segmented,
  Tag,
  Typography,
} from 'antd'
import {
  getModelConfig,
  getModelUsage,
  testModelConfig,
  updateModelConfig,
} from '../api.js'
import {
  getModelProviderPreset,
  modelProviderOptions,
} from '../modelProviders.js'

const { Text, Title } = Typography
const DEFAULT_CONFIG = {
  provider: 'qwen',
  model: 'qwen-plus',
  baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  apiKey: '',
}

const formatNumber = (value) => new Intl.NumberFormat('en-US').format(Number(value) || 0)

const formatTime = (value) => {
  if (!value) return '暂无记录'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function UsageProgress({ value, total }) {
  const percent = total > 0 ? Math.round((value / total) * 100) : 0
  return (
    <Progress
      percent={percent}
      showInfo={false}
      strokeColor="#63d7ff"
      trailColor="#2b3136"
      size="small"
    />
  )
}

function ModelUsageList({ items, total }) {
  if (!items.length) return null
  return (
    <div className="usage-entry-list">
      {items.map((item) => (
        <article className="usage-entry" key={`${item.provider}:${item.model}`}>
          <div className="usage-entry-heading">
            <span className="usage-entry-icon"><ApiOutlined /></span>
            <div className="usage-entry-title">
              <strong>{item.model}</strong>
              <Text type="secondary">{item.provider} · {formatNumber(item.request_count)} 次请求</Text>
            </div>
            <div className="usage-entry-total">
              <strong>{formatNumber(item.total_tokens)}</strong>
              <Text type="secondary">{total ? `${Math.round((item.total_tokens / total) * 100)}%` : '0%'}</Text>
            </div>
          </div>
          <UsageProgress value={item.total_tokens} total={total} />
          <div className="usage-entry-meta">
            <span>输入 {formatNumber(item.prompt_tokens)}</span>
            <span>输出 {formatNumber(item.completion_tokens)}</span>
            <span>{formatTime(item.last_request_at)}</span>
          </div>
        </article>
      ))}
    </div>
  )
}

function ConversationUsageList({ items, total }) {
  if (!items.length) return null
  return (
    <div className="usage-entry-list">
      {items.map((item) => (
        <article className="usage-entry" key={item.flow_id}>
          <div className="usage-entry-heading">
            <span className="usage-entry-icon"><MessageOutlined /></span>
            <div className="usage-entry-title">
              <strong>{item.title || `Flow ${item.flow_id.slice(0, 8)}`}</strong>
              <Text type="secondary">
                {item.models?.join(' · ') || '未知模型'} · {formatNumber(item.request_count)} 次请求
              </Text>
            </div>
            <div className="usage-entry-total">
              <strong>{formatNumber(item.total_tokens)}</strong>
              <Text type="secondary">{total ? `${Math.round((item.total_tokens / total) * 100)}%` : '0%'}</Text>
            </div>
          </div>
          <UsageProgress value={item.total_tokens} total={total} />
          <div className="usage-entry-meta">
            <span className="usage-entry-id">{item.flow_id}</span>
            <span>输入 {formatNumber(item.prompt_tokens)}</span>
            <span>{formatTime(item.last_request_at)}</span>
          </div>
        </article>
      ))}
    </div>
  )
}

function toApiPayload(values) {
  const payload = {
    provider: values.provider,
    model: values.model.trim(),
    base_url: values.baseUrl.trim().replace(/\/$/, ''),
  }
  if (values.apiKey?.trim()) {
    payload.api_key = values.apiKey.trim()
  }
  return payload
}

export function ModelUsagePage() {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [config, setConfig] = useState(null)
  const [usage, setUsage] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [period, setPeriod] = useState('month')
  const [usageView, setUsageView] = useState('model')

  const handleProviderChange = (provider) => {
    const preset = getModelProviderPreset(provider)
    if (!preset) return
    form.setFieldsValue({
      provider,
      model: preset.model,
      baseUrl: preset.baseUrl,
    })
  }

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [nextConfig, nextUsage] = await Promise.all([
        getModelConfig(),
        getModelUsage(period),
      ])
      setConfig(nextConfig)
      setUsage(nextUsage)
      form.setFieldsValue({
        provider: nextConfig.provider === 'null' ? 'qwen' : nextConfig.provider,
        model: nextConfig.model,
        baseUrl: nextConfig.base_url,
        apiKey: '',
      })
    } catch (error) {
      message.error(`读取模型配置失败：${error.message}`)
    } finally {
      setLoading(false)
    }
  }, [form, message, period])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleTest = async () => {
    const values = await form.validateFields()
    setTesting(true)
    try {
      const result = await testModelConfig(toApiPayload(values))
      message.success(`连接成功，耗时 ${result.latency_ms} ms`)
    } catch (error) {
      message.error(error.message)
    } finally {
      setTesting(false)
    }
  }

  const handleSave = async (values) => {
    setSaving(true)
    try {
      const nextConfig = await updateModelConfig({
        ...toApiPayload(values),
        test_connection: true,
      })
      setConfig(nextConfig)
      form.setFieldValue('apiKey', '')
      message.success('模型连接已验证，运行时 Provider 已更新')
      setUsage(await getModelUsage(period))
    } catch (error) {
      message.error(error.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="model-usage-page">
      <header className="model-page-heading">
        <div>
          <Text className="panel-kicker">MODEL RUNTIME</Text>
          <Title level={3}>模型选择与额度消耗</Title>
        </div>
        <Tag color={config?.configured ? 'success' : 'default'}>
          {config?.configured ? '后端已同步' : '尚未配置'}
        </Tag>
      </header>

      <Spin spinning={loading}>
        <div className="model-usage-grid">
          <section className="app-panel model-config-panel" aria-labelledby="model-config-title">
            <div className="panel-heading">
              <div>
                <Text className="panel-kicker">MODEL CONFIGURATION</Text>
                <Title level={4} id="model-config-title">运行时模型</Title>
              </div>
              <ApiOutlined className="heading-icon model-heading-icon" />
            </div>

            <Form
              form={form}
              layout="vertical"
              initialValues={DEFAULT_CONFIG}
              requiredMark={false}
              onFinish={handleSave}
              className="model-config-form"
            >
              <Form.Item name="provider" label="Provider" rules={[{ required: true }]}>
                <Select
                  showSearch
                  optionFilterProp="label"
                  options={modelProviderOptions()}
                  onChange={handleProviderChange}
                />
              </Form.Item>

              <Form.Item
                name="model"
                label="模型名称"
                rules={[{ required: true, whitespace: true, message: '请输入模型名称' }]}
              >
                <Input prefix={<ApiOutlined />} placeholder="qwen-plus" autoComplete="off" />
              </Form.Item>

              <Form.Item
                name="baseUrl"
                label="Base URL"
                rules={[
                  { required: true, whitespace: true, message: '请输入 Base URL' },
                  { type: 'url', message: '请输入有效的 URL' },
                ]}
              >
                <Input prefix={<ApiOutlined />} placeholder={DEFAULT_CONFIG.baseUrl} autoComplete="url" />
              </Form.Item>

              <Form.Item name="apiKey" label="API Key">
                <Input.Password
                  prefix={<KeyOutlined />}
                  placeholder={config?.api_key_configured ? '已配置，留空则继续使用' : '请输入模型 API Key'}
                  autoComplete="new-password"
                />
              </Form.Item>

              <div className="model-form-footer">
                <Text type="secondary">
                  密钥仅提交到后端内存，不回传，也不会写入 localStorage。
                </Text>
                <Space wrap>
                  <Button icon={<ReloadOutlined />} onClick={loadData}>重新加载</Button>
                  <Button icon={<ExperimentOutlined />} loading={testing} onClick={handleTest}>
                    测试连接
                  </Button>
                  <Button type="primary" htmlType="submit" loading={saving} icon={<SaveOutlined />}>
                    验证并应用
                  </Button>
                </Space>
              </div>
            </Form>
          </section>

          <section className="app-panel quota-panel" aria-labelledby="quota-title">
            <div className="panel-heading">
              <div>
                <Text className="panel-kicker">USAGE QUOTA</Text>
                <Title level={4} id="quota-title">模型用量</Title>
              </div>
              <Segmented
                size="small"
                value={period}
                options={[
                  { label: '日', value: 'day' },
                  { label: '月', value: 'month' },
                  { label: '总', value: 'total' },
                ]}
                onChange={setPeriod}
              />
            </div>
            <div className="usage-content">
              <div className="usage-total">
                <Text className="usage-total-label">TOTAL TOKENS</Text>
                <strong>{formatNumber(usage?.total_tokens)}</strong>
                <Text type="secondary">
                  {formatNumber(usage?.request_count)} 次请求 · 费用待单价配置
                </Text>
              </div>
              <Segmented
                block
                value={usageView}
                options={[
                  { label: '模型消耗', value: 'model' },
                  { label: '对话消耗', value: 'conversation' },
                ]}
                onChange={setUsageView}
              />
              {usageView === 'model' ? (
                <ModelUsageList items={usage?.by_model || []} total={usage?.total_tokens || 0} />
              ) : (
                <ConversationUsageList
                  items={usage?.by_conversation || []}
                  total={usage?.total_tokens || 0}
                />
              )}
              {!usage?.total_tokens && !loading ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="当前时间范围暂无用量"
                />
              ) : null}
              <div className="usage-model-list">
                <WalletOutlined className="usage-inline-icon" />
                <Text type="secondary">
                  数据来自运行账本中的 `llm.response.usage` 字段，费用需要配置模型单价。
                </Text>
              </div>
            </div>
          </section>
        </div>
      </Spin>
    </div>
  )
}
